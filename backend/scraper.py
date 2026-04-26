import asyncio
from typing import Optional
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from config import settings
from state import bot_state

_client: Optional[TelegramClient] = None
_signal_queue: Optional[asyncio.Queue] = None

# Recent message hashes for dedup (last 30 min)
_recent_signals: dict = {}  # coin+direction -> timestamp

def _is_duplicate(coin: str, direction: str) -> bool:
    import time
    key = f"{coin}_{direction}"
    now = time.time()
    for k in list(_recent_signals.keys()):
        if now - _recent_signals[k] > 1800:
            del _recent_signals[k]
    if key in _recent_signals:
        return True
    _recent_signals[key] = now
    return False

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

# ─── Querying the new TelegramSource table instead of old Channel table ───
async def get_active_channels(db) -> list:
    from sqlalchemy import select
    from database import TelegramSource 
    result = await db.execute(select(TelegramSource).where(TelegramSource.is_active == True))
    return result.scalars().all()

async def start_scraper(signal_queue: asyncio.Queue, db_factory):
    global _signal_queue
    _signal_queue = signal_queue

    client = await get_client()
    if not client:
        bot_state.log("⚠️ Scraper not started — no Telegram session.", level="warning")
        return

    # EMPTY BRACKETS = Listen to EVERYTHING (God Mode)
    @client.on(events.NewMessage())
    async def handler(event):
        # 1. IMMEDIATE DIAGNOSTIC (Runs even if bot is paused)
        try:
            chat = await event.get_chat()
            # Handle Private Chats (DMs) vs Groups/Channels
            from telethon.tl.types import User
            if isinstance(chat, User):
                chat_title = f"{chat.first_name or ''} {chat.last_name or ''}".strip()
                chat_username = chat.username or ""
            else:
                chat_title = getattr(chat, 'title', '') or ''
                chat_username = getattr(chat, 'username', '') or ''
                
            print(f"🚨 ABSOLUTE RAW EVENT: Message from [{chat_title}] (@{chat_username})")
        except Exception as e:
            pass

        # 2. STATE CHECK (Halts execution if paused, but AFTER logging)
        if not bot_state.is_active:
            return

        # 3. Check watch list dynamically
        async with db_factory() as db:
            channels = await get_active_channels(db)

        if not channels:
            return 

        matched_channel = None
        matched_trust = 0.5
        
        # SEARCH LOGIC: Check both Title and Username robustly
        for ch in channels:
            ch_watch = (ch.username or "").lower().replace("@", "")
            ch_name = (ch.name or "").lower()
            
            # Match if watch-name is in the sender's username OR the sender's display name
            if (ch_watch and ch_watch in chat_username.lower()) or \
               (ch_name and ch_name in chat_title.lower()):
                matched_channel = ch
                matched_trust = ch.trust_weight
                break

        if not matched_channel:
            print(f"🚫 DEBUG: Ignored message from @{chat_username} (Not in Active Targets)")
            return 

        raw_text = event.text or ""
        if len(raw_text.strip()) < 10:
            return

        source_name = chat_title or chat_username or "Unknown"
        bot_state.log(f"📩 SUCCESS: Signal captured from [{source_name}]!")

        await signal_queue.put({
            "text": raw_text,
            "channel": source_name,
            "channel_username": chat_username,
            "trust": matched_trust
        })

    bot_state.log("🔍 Telegram scraper listening (Dynamic Mode)...")
    await client.run_until_disconnected()

class SignalSimulator:
    SAMPLE_SIGNALS = [
        "🚀 BTC/USDT LONG\nEntry: 67,000\nTP1: 68,500\nSL: 65,800",
        "SHORT ETH now! Target $3,200. Stop at $3,520.",
        "SOL Buy Zone: 140-142\nTake Profit: 155\nStop Loss: 136",
    ]
    SAMPLE_CHANNELS = ["CryptoKings", "AltcoinAlerts"]

    async def run(self, signal_queue: asyncio.Queue):
        import random
        bot_state.log("🤖 Signal simulator active.")
        while True:
            await asyncio.sleep(random.uniform(15, 45))
            if not bot_state.is_active: continue
            text = random.choice(self.SAMPLE_SIGNALS)
            channel = random.choice(self.SAMPLE_CHANNELS)
            await signal_queue.put({"text": text, "channel": channel, "trust": 0.8})

async def start_signal_source(signal_queue: asyncio.Queue, db_factory):
    if settings.TELEGRAM_SESSION_STRING and settings.TELEGRAM_API_ID:
        await start_scraper(signal_queue, db_factory)
    else:
        sim = SignalSimulator()
        await sim.run(signal_queue)