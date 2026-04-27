import re
import asyncio
from typing import Optional
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from config import settings
from state import bot_state

_client: Optional[TelegramClient] = None

# Ignore non-asset words that often appear in signal text.
IGNORE_LIST = {
    "USDT", "USDC", "FDUSD", "DAI", "TUSD", "BUSD",
    "LONG", "SHORT", "BUY", "SELL",
    "THE", "AND", "FOR", "WITH", "THIS", "THAT", "FROM",
    "STOP", "LOSS", "ENTRY", "MARKET", "SETUP", "SUPPORT",
    "LEVERAGE", "VIP", "LOOKS", "PRIMED", "BOUNCE", "COIN", "OFF",
}


def extract_candidate_tickers(raw_text: str) -> set[str]:
    """
    Extract likely symbols from free-form messages.
    Accept only stronger symbol patterns to avoid false positives.
    """
    text = (raw_text or "").upper()
    tickers: set[str] = set()

    # High-confidence patterns:
    # - $BTC
    # - BTC/USDT
    # - BTCUSDT
    for match in re.findall(r"\$([A-Z]{2,10})\b", text):
        tickers.add(match)
    for base in re.findall(r"\b([A-Z]{2,10})/USDT\b", text):
        tickers.add(base)
    for base in re.findall(r"\b([A-Z]{2,10})USDT\b", text):
        tickers.add(base)

    # Medium-confidence fallback:
    # standalone short uppercase tokens like BTC, ETH, SOL, PEPE
    for token in re.findall(r"\b[A-Z]{2,5}\b", text):
        if token not in IGNORE_LIST:
            tickers.add(token)

    return tickers


async def radar_flush_loop(signal_queue: asyncio.Queue):
    """Periodically flushes Phase A bucket into Phase B queue."""
    while True:
        interval = 30 if bot_state.trading_style == "scalp" else 120
        await asyncio.sleep(interval)
        if not bot_state.is_active or bot_state.kill_switch_active:
            continue
        if not bot_state.radar_bucket:
            continue

        min_users = 1 if bot_state.ai_mock_mode else 2
        # Require multiple unique users in normal mode; relax in testing mode.
        for coin, bucket in list(bot_state.radar_bucket.items()):
            user_count = len(bucket.get("users", set()))
            if user_count < min_users:
                continue
            await signal_queue.put((coin, {"messages": list(bucket.get("messages", []))}))
            bot_state.log(f"🧺 Flushed {coin} bucket -> pipeline ({user_count} users).")

        bot_state.radar_bucket.clear()

async def get_client() -> Optional[TelegramClient]:
    global _client
    if _client and _client.is_connected():
        return _client
    if not settings.TELEGRAM_SESSION_STRING or not settings.TELEGRAM_API_ID:
        return None
    try:
        _client = TelegramClient(
            StringSession(settings.TELEGRAM_SESSION_STRING),
            int(settings.TELEGRAM_API_ID),
            settings.TELEGRAM_API_HASH
        )
        await _client.start()
        bot_state.log("📡 Telegram scraper connected.")
        return _client
    except Exception as e:
        bot_state.log(f"❌ Telegram connection failed: {str(e)[:60]}", level="danger")
        return None

async def get_active_channels(db) -> list:
    from sqlalchemy import select
    from database import TelegramSource 
    result = await db.execute(select(TelegramSource).where(TelegramSource.is_active == True))
    return result.scalars().all()

async def start_scraper(signal_queue: asyncio.Queue, db_factory):
    # Note: signal_queue remains in the function signature to avoid breaking main.py
    client = await get_client()
    if not client:
        bot_state.log("⚠️ Scraper not started — no Telegram session.", level="warning")
        # #region agent log
        bot_state.debug_log(
            run_id="initial",
            hypothesis_id="H7",
            location="backend/scraper.py:start_scraper",
            message="scraper not started due missing client",
            data={"has_session": bool(settings.TELEGRAM_SESSION_STRING), "has_api_id": bool(settings.TELEGRAM_API_ID)},
        )
        # #endregion
        return

    @client.on(events.NewMessage())
    async def handler(event):
        if not bot_state.is_active or bot_state.kill_switch_active:
            # #region agent log
            bot_state.debug_log(
                run_id="initial",
                hypothesis_id="H7",
                location="backend/scraper.py:handler",
                message="incoming telegram message ignored due bot state",
                data={"is_active": bot_state.is_active, "kill_switch_active": bot_state.kill_switch_active},
            )
            # #endregion
            return

        try:
            chat = await event.get_chat()
            from telethon.tl.types import User
            if isinstance(chat, User):
                chat_username = chat.username or ""
                chat_title = f"{chat.first_name or ''} {chat.last_name or ''}".strip()
            else:
                chat_username = getattr(chat, 'username', '') or ''
                chat_title = getattr(chat, 'title', '') or ''
        except Exception:
            return

        # Check watch list dynamically
        async with db_factory() as db:
            channels = await get_active_channels(db)

        if not channels:
            # #region agent log
            bot_state.debug_log(
                run_id="initial",
                hypothesis_id="H7",
                location="backend/scraper.py:handler",
                message="incoming telegram message ignored due no active channels",
                data={},
            )
            # #endregion
            return

        matched = False
        for ch in channels:
            ch_watch = (ch.username or "").lower().replace("@", "")
            ch_name = (ch.name or "").lower()
            if (ch_watch and ch_watch in chat_username.lower()) or \
               (ch_name and ch_name in chat_title.lower()):
                matched = True
                break

        if not matched:
            # #region agent log
            bot_state.debug_log(
                run_id="initial",
                hypothesis_id="H7",
                location="backend/scraper.py:handler",
                message="incoming telegram message did not match watchlist",
                data={"chat_username": chat_username, "chat_title": chat_title, "active_channels": len(channels)},
            )
            # #endregion
            return 

        raw_text = event.text or ""
        if len(raw_text.strip()) < 5: return

        sender = await event.get_sender()
        user_id = sender.id if sender else 0

        # --- PHASE A: RADAR TALLY LOGIC ---
        found_tickers = extract_candidate_tickers(raw_text)
        
        for coin in found_tickers:
            if coin in IGNORE_LIST:
                continue
            
            if coin not in bot_state.radar_bucket:
                bot_state.radar_bucket[coin] = {"users": set(), "messages": []}
            
            # Sybil Attack Fix: Only count unique users
            if user_id not in bot_state.radar_bucket[coin]["users"]:
                bot_state.radar_bucket[coin]["users"].add(user_id)
                bot_state.radar_bucket[coin]["messages"].append(raw_text)
                # #region agent log
                bot_state.debug_log(
                    run_id="initial",
                    hypothesis_id="H6",
                    location="backend/scraper.py:handler",
                    message="radar bucket updated from telegram",
                    data={
                        "coin": coin,
                        "unique_users": len(bot_state.radar_bucket[coin]["users"]),
                        "messages": len(bot_state.radar_bucket[coin]["messages"]),
                    },
                )
                # #endregion

    bot_state.log("🔍 NLP Radar listening (Sentiment Aggregation Mode)...")
    await client.run_until_disconnected()

class RadarSimulator:
    SAMPLE_MESSAGES = [
        "SOL is looking super bullish right now.",
        "I'm buying more SOL, breakout incoming!",
        "ETH is lagging, moving funds to SOL.",
        "BTC holding 65k nicely.",
        "Anyone looking at WIF here?",
    ]

    async def run(self):
        import random
        bot_state.log("🤖 Radar simulator active (Mocking Telegram Chatter).")
        while True:
            await asyncio.sleep(random.uniform(5, 15))
            if not bot_state.is_active: continue
            
            text = random.choice(self.SAMPLE_MESSAGES)
            user_id = random.randint(1000, 9999) # Fake unique user ID
            
            found_tickers = extract_candidate_tickers(text)
            for coin in found_tickers:
                if coin in IGNORE_LIST: continue
                if coin not in bot_state.radar_bucket:
                    bot_state.radar_bucket[coin] = {"users": set(), "messages": []}
                
                # Dump into bucket just like the real scraper
                bot_state.radar_bucket[coin]["users"].add(user_id)
                bot_state.radar_bucket[coin]["messages"].append(text)
                # #region agent log
                bot_state.debug_log(
                    run_id="initial",
                    hypothesis_id="H6",
                    location="backend/scraper.py:RadarSimulator.run",
                    message="radar bucket updated from simulator",
                    data={
                        "coin": coin,
                        "unique_users": len(bot_state.radar_bucket[coin]["users"]),
                        "messages": len(bot_state.radar_bucket[coin]["messages"]),
                        "bot_active": bot_state.is_active,
                    },
                )
                # #endregion

async def start_signal_source(signal_queue: asyncio.Queue, db_factory):
    asyncio.create_task(radar_flush_loop(signal_queue))
    # #region agent log
    bot_state.debug_log(
        run_id="initial",
        hypothesis_id="H7",
        location="backend/scraper.py:start_signal_source",
        message="signal source branch selected",
        data={"using_telegram": bool(settings.TELEGRAM_SESSION_STRING and settings.TELEGRAM_API_ID)},
    )
    # #endregion
    if settings.TELEGRAM_SESSION_STRING and settings.TELEGRAM_API_ID:
        await start_scraper(signal_queue, db_factory)
    else:
        sim = RadarSimulator()
        await sim.run()