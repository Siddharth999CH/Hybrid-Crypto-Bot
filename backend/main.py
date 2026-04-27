import asyncio
import json
import csv
import io
from datetime import datetime, timezone
from typing import Optional, List
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from telethon import TelegramClient
from telethon.sessions import StringSession
from sqlalchemy import select, desc, func
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database import (
    init_db, get_db, AsyncSessionLocal,
    Signal, Trade, User, DailyPnL,
    SignalStatus, TradeStatus,
    TelegramSource, ApiSource, MarketContext
)
from state import bot_state
from pipeline import run_pipeline
from scraper import start_signal_source
from executor import execute_trade, get_current_price
from api_worker import run_api_worker_loop


# ─────────────────────────────────────────
# STARTUP / SHUTDOWN
# ─────────────────────────────────────────
signal_queue: asyncio.Queue = asyncio.Queue()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # #region agent log
    bot_state.debug_log(
        run_id="initial",
        hypothesis_id="H1",
        location="backend/main.py:lifespan",
        message="lifespan start",
        data={},
    )
    # #endregion
    await init_db()
    bot_state.log("🚀 SignalBot backend initialized.")
    if bot_state.ai_mock_mode:
        bot_state.is_active = True
        bot_state.log("🧪 Testing mode: bot auto-activated.")
    
    # Start pipeline, scraper, and data worker as background tasks
    asyncio.create_task(run_pipeline(signal_queue))
    
    db_factory = AsyncSessionLocal
    asyncio.create_task(start_signal_source(signal_queue, db_factory))

    asyncio.create_task(run_api_worker_loop())
    # #region agent log
    bot_state.debug_log(
        run_id="initial",
        hypothesis_id="H1",
        location="backend/main.py:lifespan",
        message="background tasks started",
        data={"tasks": ["pipeline", "signal_source", "api_worker"]},
    )
    # #endregion
    
    # Try to get portfolio balance
    try:
        from executor import get_exchange
        exchange = get_exchange()
        bal = exchange.fetch_balance()
        bot_state.portfolio_balance = float(bal['total'].get('USDT', 10000))
        bot_state.log(f"💰 Portfolio balance: ${bot_state.portfolio_balance:,.2f} USDT")
    except:
        # #region agent log
        bot_state.debug_log(
            run_id="initial",
            hypothesis_id="H1",
            location="backend/main.py:lifespan",
            message="balance fetch failed",
            data={},
        )
        # #endregion
        bot_state.log("⚠️ Could not fetch balance — using default $10,000.", level="warning")

    yield
    bot_state.log("👋 SignalBot shutting down.")


app = FastAPI(title="SignalBot API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─────────────────────────────────────────
# PYDANTIC SCHEMAS
# ─────────────────────────────────────────
class ToggleResponse(BaseModel):
    is_active: bool

class ApprovalAction(BaseModel):
    signal_id: int
    action: str            # "approve" | "reject"
    trade_id: Optional[int] = None
    position_size_usdt: Optional[float] = None
    tp_split: Optional[List[float]] = None

class SourceCreate(BaseModel):
    name: str
    username: str
    trust_weight: float = 0.5
    api_key: Optional[str] = None

class SourceUpdate(BaseModel):
    trust_weight: Optional[float] = None
    is_active: Optional[bool] = None

class SettingsUpdate(BaseModel):
    max_risk_pct: Optional[float] = None
    daily_drawdown_limit: Optional[float] = None
    max_concurrent_trades: Optional[int] = None
    approval_timeout: Optional[int] = None
    max_leverage: Optional[int] = None
    slippage_threshold: Optional[float] = None
    paper_mode: Optional[bool] = None
    ai_mock_mode: Optional[bool] = None
    trailing_sl: Optional[bool] = None
    signal_notifications: Optional[bool] = None
    
    trading_style: Optional[str] = None  # NEW: "scalp" or "swing"
    
    llm_provider: Optional[str] = None
    llm_model_name: Optional[str] = None
    llm_api_key: Optional[str] = None

class TelegramConnect(BaseModel):
    api_id: str
    api_hash: str
    phone: str

class TelegramVerify(BaseModel):
    phone: str
    code: str
    password: Optional[str] = None


_telegram_login_clients: dict[str, TelegramClient] = {}


# ─────────────────────────────────────────
# WEBSOCKET
# ─────────────────────────────────────────
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    bot_state.ws_clients.append(websocket)
    try:
        await websocket.send_text(json.dumps({
            "type": "init",
            "data": get_full_status()
        }))
        while True:
            await websocket.receive_text() 
    except WebSocketDisconnect:
        if websocket in bot_state.ws_clients:
            bot_state.ws_clients.remove(websocket)


# ─────────────────────────────────────────
# STATUS & CONTROL
# ─────────────────────────────────────────
def get_full_status():
    return {
        "is_active": bot_state.is_active,
        "paper_mode": bot_state.paper_mode,
        "kill_switch_active": bot_state.kill_switch_active,
        "kill_switch_reason": bot_state.kill_switch_reason,
        "daily_pnl": bot_state.daily_pnl,
        "open_trades_count": bot_state.open_trades_count,
        "portfolio_balance": bot_state.portfolio_balance,
        "pending_approvals_count": len(bot_state.pending_approvals),
        "activity_logs": bot_state.activity_logs[:20],
        "settings": {
            "max_risk_pct": bot_state.max_risk_pct,
            "daily_drawdown_limit": bot_state.daily_drawdown_limit,
            "max_concurrent_trades": bot_state.max_concurrent_trades,
            "approval_timeout": bot_state.approval_timeout,
            "max_leverage": bot_state.max_leverage,
            "slippage_threshold": bot_state.slippage_threshold,
            "ai_mock_mode": bot_state.ai_mock_mode,
            "trailing_sl": bot_state.trailing_sl,
            "signal_notifications": bot_state.signal_notifications,
            "trading_style": bot_state.trading_style,
        }
    }

@app.get("/api/status")
async def get_status():
    return get_full_status()

@app.post("/api/toggle")
async def toggle_bot():
    if bot_state.kill_switch_active:
        raise HTTPException(400, "Kill switch is active.")
    bot_state.is_active = not bot_state.is_active
    state_str = "🟢 ACTIVE" if bot_state.is_active else "🔴 PAUSED"
    bot_state.log(f"System {state_str}")
    await bot_state.broadcast("status_changed", {"is_active": bot_state.is_active})
    return {"is_active": bot_state.is_active}

@app.post("/api/resume")
async def resume_bot():
    bot_state.kill_switch_active = False
    bot_state.kill_switch_reason = ""
    bot_state.is_active = True
    bot_state.log("✅ Bot resumed manually.")
    await bot_state.broadcast("status_changed", {"is_active": True, "kill_switch": False})
    return {"message": "Bot resumed."}

@app.post("/api/state/clear-active-coins")
async def clear_active_coins():
    cleared = list(bot_state.active_trades_coins)
    bot_state.active_trades_coins.clear()
    bot_state.log(f"🧹 Cleared active coins lock: {cleared}")
    return {"message": "Active coins cleared.", "cleared": cleared}

# ─────────────────────────────────────────
# APPROVALS
# ─────────────────────────────────────────
@app.get("/api/approvals")
async def get_pending_approvals():
    # #region agent log
    bot_state.debug_log(
        run_id="initial",
        hypothesis_id="H3",
        location="backend/main.py:get_pending_approvals",
        message="pending approvals requested",
        data={"count": len(bot_state.pending_approvals)},
    )
    # #endregion
    approvals = []
    for sid, payload in bot_state.pending_approvals.items():
        row = dict(payload)
        row.setdefault("signal_id", sid)
        approvals.append(row)
    return approvals

@app.post("/api/approvals/action")
async def handle_approval(action: ApprovalAction, db: AsyncSession = Depends(get_db)):
    signal_id = action.signal_id
    # #region agent log
    bot_state.debug_log(
        run_id="initial",
        hypothesis_id="H3",
        location="backend/main.py:handle_approval",
        message="approval action received",
        data={"signal_id": signal_id, "action": action.action, "trade_id": action.trade_id},
    )
    # #endregion

    if signal_id not in bot_state.pending_approvals:
        # #region agent log
        bot_state.debug_log(
            run_id="initial",
            hypothesis_id="H3",
            location="backend/main.py:handle_approval",
            message="approval missing in pending map",
            data={"signal_id": signal_id, "pending_keys": list(bot_state.pending_approvals.keys())[:20]},
        )
        # #endregion
        raise HTTPException(404, "Approval not found.")

    approval_data = bot_state.pending_approvals.pop(signal_id)

    trade = None
    if action.trade_id:
        trade = await db.get(Trade, action.trade_id)
    
    if action.action == "approve" and not trade:
        trade = Trade(
            signal_id=signal_id,
            coin=approval_data['coin'],
            direction=approval_data['direction'],
            position_size_usdt=action.position_size_usdt or approval_data.get("position_size_usdt", 0.0),
            leverage=int(approval_data.get("leverage", bot_state.max_leverage)),
            confidence=float(approval_data.get("confidence", 0.0)),
            channel=approval_data.get("channel", "aggregated"),
            market_type=approval_data.get("market_type", "futures"),
            tp1=approval_data.get("tp1"),
            stop_loss=approval_data.get("stop_loss"),
        )
        db.add(trade)
        await db.flush()

    if action.action == "reject":
        if trade:
            trade.status = TradeStatus.REJECTED
            await db.commit()
        bot_state.log(f"❌ Trade rejected: {approval_data['coin']} {approval_data['direction']}")
        await bot_state.broadcast("trade_rejected", {"trade_id": action.trade_id, "coin": approval_data['coin']})
        return {"message": "Trade rejected."}

    if action.action == "approve":
        if action.position_size_usdt is not None and trade:
            trade.position_size_usdt = action.position_size_usdt

        success = await execute_trade(trade, approval_data)
        if trade: await db.commit()

        if success:
            bot_state.active_trades_coins.add(approval_data['coin'])
            return {"message": "Trade executed.", "trade_id": getattr(trade, 'id', None)}
        else:
            return {"message": "Execution failed.", "trade_id": getattr(trade, 'id', None)}

    raise HTTPException(400, "Invalid action.")


# ─────────────────────────────────────────
# SETTINGS
# ─────────────────────────────────────────
@app.get("/api/settings")
async def get_settings():
    return {
        "max_risk_pct": bot_state.max_risk_pct,
        "daily_drawdown_limit": bot_state.daily_drawdown_limit,
        "max_concurrent_trades": bot_state.max_concurrent_trades,
        "approval_timeout": bot_state.approval_timeout,
        "max_leverage": bot_state.max_leverage,
        "slippage_threshold": bot_state.slippage_threshold,
        "paper_mode": bot_state.paper_mode,
        "ai_mock_mode": bot_state.ai_mock_mode,
        "trailing_sl": bot_state.trailing_sl,
        "signal_notifications": bot_state.signal_notifications,
        "trading_style": bot_state.trading_style,
        "binance_connected": bool(settings.BINANCE_API_KEY),
        "telegram_connected": bool(settings.TELEGRAM_SESSION_STRING),
        "llm_provider": settings.LLM_PROVIDER,
        "llm_model_name": settings.LLM_MODEL_NAME,
        "llm_api_key": settings.LLM_API_KEY,
    }

@app.post("/api/settings")
async def update_settings(update: SettingsUpdate):
    # #region agent log
    bot_state.debug_log(
        run_id="initial",
        hypothesis_id="H5",
        location="backend/main.py:update_settings",
        message="settings update called",
        data={
            "paper_mode": update.paper_mode,
            "ai_mock_mode": update.ai_mock_mode,
            "trading_style": update.trading_style,
            "llm_provider": update.llm_provider,
            "llm_model_name": update.llm_model_name,
        },
    )
    # #endregion
    if update.max_risk_pct is not None: bot_state.max_risk_pct = update.max_risk_pct
    if update.daily_drawdown_limit is not None: bot_state.daily_drawdown_limit = update.daily_drawdown_limit
    if update.max_concurrent_trades is not None: bot_state.max_concurrent_trades = update.max_concurrent_trades
    if update.approval_timeout is not None: bot_state.approval_timeout = update.approval_timeout
    if update.max_leverage is not None: bot_state.max_leverage = update.max_leverage
    if update.slippage_threshold is not None: bot_state.slippage_threshold = update.slippage_threshold
    
    if update.paper_mode is not None:
        bot_state.paper_mode = update.paper_mode
        mode = "📝 Paper" if update.paper_mode else "⚡ Live"
        bot_state.log(f"Trading mode switched to {mode}")
        
    if update.ai_mock_mode is not None: bot_state.ai_mock_mode = update.ai_mock_mode
    if update.trailing_sl is not None: bot_state.trailing_sl = update.trailing_sl
    if update.signal_notifications is not None: bot_state.signal_notifications = update.signal_notifications
    
    # --- DYNAMIC RADAR MODE UPDATE ---
    if update.trading_style is not None:
        bot_state.trading_style = update.trading_style
        bot_state.log(f"⚙️ Trading Style switched to: {update.trading_style.upper()}")
    
    if update.llm_provider is not None: settings.LLM_PROVIDER = update.llm_provider
    if update.llm_model_name is not None: settings.LLM_MODEL_NAME = update.llm_model_name
    if update.llm_api_key is not None: settings.LLM_API_KEY = update.llm_api_key

    await bot_state.broadcast("settings_updated", get_settings_dict())
    return {"message": "Settings updated."}


@app.post("/api/telegram/connect")
async def telegram_connect(req: TelegramConnect):
    client = TelegramClient(StringSession(""), int(req.api_id), req.api_hash)
    await client.connect()
    await client.send_code_request(req.phone)
    _telegram_login_clients[req.phone] = client
    return {"message": "OTP sent."}


@app.post("/api/telegram/verify")
async def telegram_verify(req: TelegramVerify):
    client = _telegram_login_clients.get(req.phone)
    if not client:
        raise HTTPException(400, "No pending Telegram login. Send OTP first.")
    try:
        await client.sign_in(phone=req.phone, code=req.code)
    except Exception as e:
        text = str(e).lower()
        if "password" in text or "2fa" in text:
            if not req.password:
                raise HTTPException(400, "2FA password required.")
            await client.sign_in(password=req.password)
        else:
            raise
    session_string = client.session.save()
    await client.disconnect()
    _telegram_login_clients.pop(req.phone, None)
    return {"session_string": session_string}

def get_settings_dict():
    return {
        "paper_mode": bot_state.paper_mode,
        "ai_mock_mode": bot_state.ai_mock_mode,
        "trading_style": bot_state.trading_style,
    }

@app.get("/api/signals")
async def get_signals(limit: int = 50, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Signal).order_by(desc(Signal.id)).limit(limit))
    return result.scalars().all()

@app.get("/api/trades")
async def get_trades(
    limit: int = 50,
    status: Optional[str] = None,
    is_paper: Optional[bool] = None,
    db: AsyncSession = Depends(get_db),
):
    query = select(Trade)
    if status:
        query = query.where(Trade.status == status.upper())
    if is_paper is not None:
        query = query.where(Trade.is_paper == is_paper)

    result = await db.execute(query.order_by(desc(Trade.id)).limit(limit))
    return result.scalars().all()

@app.get("/api/trades/stats")
async def get_trade_stats(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Trade))
    trades = result.scalars().all()

    closed_statuses = {"TP_HIT", "SL_HIT"}
    closed_trades = [t for t in trades if t.status in closed_statuses]
    winning_trades = [t for t in closed_trades if (t.pnl_usdt or 0) > 0]

    total_pnl = sum((t.pnl_usdt or 0.0) for t in trades)
    wins = len(winning_trades)
    total_closed = len(closed_trades)
    win_rate = round((wins / total_closed) * 100, 2) if total_closed else 0.0

    pnl_by_day = {}
    for trade in closed_trades:
        ts = trade.closed_at or trade.created_at
        if not ts:
            continue
        day_key = ts.strftime("%a")
        pnl_by_day[day_key] = round(pnl_by_day.get(day_key, 0.0) + (trade.pnl_usdt or 0.0), 2)

    channel_totals = {}
    for trade in closed_trades:
        if not trade.channel:
            continue
        channel_totals[trade.channel] = channel_totals.get(trade.channel, 0.0) + (trade.pnl_usdt or 0.0)
    best_channel = max(channel_totals, key=channel_totals.get) if channel_totals else None

    return {
        "daily_pnl": pnl_by_day,
        "open_trades": bot_state.open_trades_count,
        "portfolio_balance": bot_state.portfolio_balance,
        "total_pnl": round(total_pnl, 2),
        "wins": wins,
        "total_trades": total_closed,
        "win_rate": win_rate,
        "best_channel": best_channel,
    }
# ─────────────────────────────────────────
# DATA INGESTION (CHANNELS)
# ─────────────────────────────────────────
@app.get("/api/channels")
async def get_channels(db: AsyncSession = Depends(get_db)):
    telegram_result = await db.execute(select(TelegramSource).order_by(desc(TelegramSource.id)))
    api_result = await db.execute(select(ApiSource).order_by(desc(ApiSource.id)))

    channels = []
    for source in telegram_result.scalars().all():
        channels.append({
            "id": source.id,
            "name": source.name,
            "username": source.username,
            "trust_weight": source.trust_weight,
            "is_active": source.is_active,
            "source_type": "telegram",
        })

    for source in api_result.scalars().all():
        channels.append({
            "id": source.id,
            "name": source.name,
            "username": source.endpoint_url,
            "trust_weight": source.trust_weight,
            "is_active": source.is_active,
            "source_type": "api",
        })

    return sorted(channels, key=lambda row: row["id"], reverse=True)

@app.post("/api/channels")
async def add_channel(source: SourceCreate, db: AsyncSession = Depends(get_db)):
    raw_username = source.username.strip()
    is_api_source = raw_username.startswith("http://") or raw_username.startswith("https://")

    if is_api_source:
        new_source = ApiSource(
            name=source.name,
            endpoint_url=raw_username,
            api_key=source.api_key,
            trust_weight=source.trust_weight,
            is_active=True,
        )
    else:
        new_source = TelegramSource(
            name=source.name,
            username=raw_username.replace("@", ""),  # Clean up username
            trust_weight=source.trust_weight,
            is_active=True,
        )
    db.add(new_source)
    await db.commit()
    await db.refresh(new_source)
    return new_source

@app.put("/api/channels/{channel_id}")
async def update_channel(channel_id: int, update: SourceUpdate, db: AsyncSession = Depends(get_db)):
    channel = await db.get(TelegramSource, channel_id)
    source_type = "telegram"
    if not channel:
        channel = await db.get(ApiSource, channel_id)
        source_type = "api"

    if not channel:
        raise HTTPException(404, "Channel not found")
    
    if update.trust_weight is not None:
        channel.trust_weight = update.trust_weight
    if update.is_active is not None:
        channel.is_active = update.is_active
        
    await db.commit()
    return {"message": "Channel updated.", "source_type": source_type}

@app.delete("/api/channels/{channel_id}")
async def delete_channel(
    channel_id: int,
    source_type: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    channel = None
    resolved_source_type = source_type

    if source_type == "api":
        channel = await db.get(ApiSource, channel_id)
    elif source_type == "telegram":
        channel = await db.get(TelegramSource, channel_id)
    else:
        channel = await db.get(TelegramSource, channel_id)
        resolved_source_type = "telegram"
        if not channel:
            channel = await db.get(ApiSource, channel_id)
            resolved_source_type = "api"

    if not channel:
        raise HTTPException(404, "Channel not found")
    
    await db.delete(channel)
    await db.commit()
    return {"message": "Channel deleted.", "source_type": resolved_source_type}


@app.get("/api/trades/export")
async def export_trades_csv(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Trade).order_by(desc(Trade.id)))
    trades = result.scalars().all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "id", "signal_id", "coin", "direction", "entry_price", "tp1", "stop_loss",
        "position_size_usdt", "leverage", "status", "pnl_usdt", "pnl_pct", "is_paper",
        "opened_at", "closed_at", "created_at"
    ])

    for t in trades:
        writer.writerow([
            t.id, t.signal_id, t.coin, t.direction, t.entry_price, t.tp1, t.stop_loss,
            t.position_size_usdt, t.leverage, t.status, t.pnl_usdt, t.pnl_pct, t.is_paper,
            t.opened_at, t.closed_at, t.created_at
        ])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=trades.csv"},
    )
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8001, reload=True)