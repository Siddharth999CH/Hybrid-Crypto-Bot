import asyncio
from datetime import datetime
from typing import Optional
from state import bot_state
from signal_parser import parse_signal, ParsedSignal
from analyzer import analyze_signal
from database import Signal, Trade, TelegramSource, SignalStatus, TradeStatus, AsyncSessionLocal
from sqlalchemy import select
from signal_parser import parse_signal, ParsedSignal, verify_ticker

_approval_timers: dict = {}  # signal_id -> asyncio.Task


async def get_channel_trust(channel_name: str, channel_username: str = "") -> float:
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(TelegramSource).where(
                (TelegramSource.name == channel_name) | (TelegramSource.username == channel_username)
            )
        )
        ch = result.scalar_one_or_none()
        return ch.trust_weight if ch else 0.5


async def save_signal(parsed: ParsedSignal, status: str) -> int:
    async with AsyncSessionLocal() as db:
        sig = Signal(
            coin=parsed.coin or "UNKNOWN",
            direction=parsed.direction,
            entry_price=parsed.entry_price,
            entry_low=parsed.entry_low,
            entry_high=parsed.entry_high,
            tp1=parsed.tp1,
            tp2=parsed.tp2,
            tp3=parsed.tp3,
            stop_loss=parsed.stop_loss,
            leverage=parsed.leverage,
            confidence=parsed.confidence,
            channel=parsed.channel,
            raw_text=parsed.raw_text[:1000],
            status=status,
            market_type=parsed.market_type,
        )
        db.add(sig)
        await db.commit()
        await db.refresh(sig)
        return sig.id


async def create_pending_trade(analyzed: dict, signal_id: int) -> int:
    async with AsyncSessionLocal() as db:
        trade = Trade(
            signal_id=signal_id,
            coin=analyzed['coin'],
            direction=analyzed['direction'],
            entry_price=analyzed.get('entry_price'),
            tp1=analyzed.get('tp1'),
            tp2=analyzed.get('tp2'),
            tp3=analyzed.get('tp3'),
            stop_loss=analyzed.get('stop_loss'),
            position_size_usdt=analyzed.get('position_size_usdt', 100),
            leverage=analyzed.get('leverage') or 1,
            confidence=analyzed.get('confidence'),
            channel=analyzed['channel'],
            status=TradeStatus.PENDING_APPROVAL,
            is_paper=bot_state.paper_mode,
            market_type=analyzed.get('market_type', 'spot'),
        )
        db.add(trade)
        await db.commit()
        await db.refresh(trade)
        return trade.id


async def handle_approval_timeout(signal_id: int, trade_id: int):
    """Auto-reject if no response within timeout window."""
    await asyncio.sleep(bot_state.approval_timeout)
    if signal_id in bot_state.pending_approvals:
        del bot_state.pending_approvals[signal_id]
        async with AsyncSessionLocal() as db:
            trade = await db.get(Trade, trade_id)
            if trade and trade.status == TradeStatus.PENDING_APPROVAL:
                trade.status = TradeStatus.EXPIRED
                await db.commit()
        bot_state.log(f"⏰ Signal #{signal_id} expired (no response in {bot_state.approval_timeout//60}m)")
        await bot_state.broadcast("signal_expired", {"signal_id": signal_id, "trade_id": trade_id})


async def process_signal(raw: dict):
    """Full pipeline: raw message → parsed → analyzed → approval queue."""
    text = raw.get("text", "")
    channel = raw.get("channel", "Unknown")
    trust = raw.get("trust", 0.5)

    if bot_state.signal_notifications:
        bot_state.log(f"📨 Processing signal from [{channel}]")

    # PARSE
    parsed = await parse_signal(text, channel)
    if not parsed or not parsed.coin:
        await save_signal(
            ParsedSignal(raw_text=text, channel=channel),
            SignalStatus.REJECTED_AI
        )
        if bot_state.signal_notifications:
            bot_state.log(f"🛡️ Rejected: no valid signal found in message.")
        return

    # 🛡️ THE TICKER SHIELD (GATES 1 & 2)
    is_valid_ticker = await verify_ticker(parsed.coin)
    if not is_valid_ticker:
        await save_signal(parsed, SignalStatus.REJECTED_AI)
        bot_state.log(f"🛡️ Shield Activated: Blocked phantom ticker [{parsed.coin}]")
        return

    # DRAWDOWN CHECK
    # ... (rest of your code continues normally)

    # DRAWDOWN CHECK
    if bot_state.kill_switch_active:
        await save_signal(parsed, SignalStatus.REJECTED_DRAWDOWN)
        bot_state.log(f"🚨 Rejected [{parsed.coin}]: kill switch active")
        return

    # DUPLICATE CHECK
    from scraper import _is_duplicate
    if _is_duplicate(parsed.coin, parsed.direction):
        await save_signal(parsed, SignalStatus.REJECTED_DUPLICATE)
        bot_state.log(f"♻️ Rejected [{parsed.coin}]: duplicate within 30 min")
        return

    # INCOMPLETE CHECK
    if not parsed.is_complete:
        sig_id = await save_signal(parsed, SignalStatus.REJECTED_INCOMPLETE)
        bot_state.log(f"⚠️ Signal [{parsed.coin}] incomplete — missing SL. Logged.", level="warning")
        await bot_state.broadcast("signal_incomplete", {
            "coin": parsed.coin,
            "channel": channel,
            "raw": text[:200]
        })
        return

    # ANALYZE
    analyzed = await analyze_signal(parsed, trust, bot_state.portfolio_balance)
    confidence = analyzed['confidence']

    # AUTO-REJECT low confidence
    if confidence < 0.5:
        parsed.confidence = confidence
        await save_signal(parsed, SignalStatus.REJECTED_AI)
        bot_state.log(f"📉 Rejected [{parsed.coin}]: confidence too low ({confidence:.2f})")
        await bot_state.broadcast("signal_rejected", {
            "coin": parsed.coin,
            "confidence": confidence,
            "channel": channel
        })
        return

    # SAVE + QUEUE FOR APPROVAL
    parsed.confidence = confidence
    sig_id = await save_signal(parsed, SignalStatus.SENT_FOR_APPROVAL)
    trade_id = await create_pending_trade(analyzed, sig_id)

    approval_payload = {
        **analyzed,
        "signal_id": sig_id,
        "trade_id": trade_id,
        "is_paper": bot_state.paper_mode,
    }
    bot_state.pending_approvals[sig_id] = approval_payload

    confidence_label = "🟢 Strong" if confidence >= 0.75 else "🟡 Low confidence"
    bot_state.log(
        f"🔔 Approval requested: {parsed.coin} {parsed.direction} | "
        f"Conf: {confidence:.2f} {confidence_label} | R:R: {analyzed.get('rr_ratio', 'N/A')}",
        level="info"
    )

    await bot_state.broadcast("approval_requested", approval_payload)

    # Start timeout timer
    timer = asyncio.create_task(handle_approval_timeout(sig_id, trade_id))
    _approval_timers[sig_id] = timer


async def run_pipeline(signal_queue: asyncio.Queue):
    """Continuously drain the signal queue and process each message."""
    bot_state.log("⚙️ Signal pipeline running.")
    while True:
        try:
            raw = await signal_queue.get()
            await process_signal(raw)
        except Exception as e:
            bot_state.log(f"❌ Pipeline error: {str(e)[:80]}", level="danger")
        finally:
            signal_queue.task_done()