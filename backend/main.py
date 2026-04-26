import asyncio
import json
import csv
import io
from datetime import datetime, date, timedelta
from typing import Optional, List
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
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


# ─────────────────────────────────────────
# STARTUP / SHUTDOWN
# ─────────────────────────────────────────
signal_queue: asyncio.Queue = asyncio.Queue()

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    bot_state.log("🚀 SignalBot backend initialized.")
    
    # Start pipeline and scraper as background tasks
    asyncio.create_task(run_pipeline(signal_queue))
    
    db_factory = AsyncSessionLocal
    asyncio.create_task(start_signal_source(signal_queue, db_factory))
    
    # Try to get portfolio balance
    try:
        from executor import get_exchange
        exchange = get_exchange()
        bal = exchange.fetch_balance()
        bot_state.portfolio_balance = float(bal['total'].get('USDT', 10000))
        bot_state.log(f"💰 Portfolio balance: ${bot_state.portfolio_balance:,.2f} USDT")
    except:
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
    
    # --- DYNAMIC LLM CONFIGURATION ---
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


# ─────────────────────────────────────────
# WEBSOCKET
# ─────────────────────────────────────────
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    bot_state.ws_clients.append(websocket)
    try:
        # Send current state on connect
        await websocket.send_text(json.dumps({
            "type": "init",
            "data": get_full_status()
        }))
        while True:
            await websocket.receive_text()  # keep alive
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
        }
    }

@app.get("/api/status")
async def get_status():
    return get_full_status()

@app.post("/api/toggle")
async def toggle_bot():
    if bot_state.kill_switch_active:
        raise HTTPException(400, "Kill switch is active. Use /api/resume to re-enable.")
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


# ─────────────────────────────────────────
# APPROVALS
# ─────────────────────────────────────────
@app.get("/api/approvals")
async def get_pending_approvals():
    return list(bot_state.pending_approvals.values())

@app.post("/api/approvals/action")
async def handle_approval(action: ApprovalAction, db: AsyncSession = Depends(get_db)):
    signal_id = action.signal_id

    if signal_id not in bot_state.pending_approvals:
        raise HTTPException(404, "Approval not found or already handled.")

    approval_data = bot_state.pending_approvals.pop(signal_id)

    trade = None
    if action.trade_id:
        trade = await db.get(Trade, action.trade_id)
    
    if action.action == "approve" and not trade:
        trade = Trade(coin=approval_data['coin'], direction=approval_data['direction'])

    if action.action == "reject":
        if trade:
            trade.status = TradeStatus.REJECTED
            await db.commit()
        bot_state.log(f"❌ Trade rejected: {approval_data['coin']} {approval_data['direction']}")
        await bot_state.broadcast("trade_rejected", {"trade_id": action.trade_id, "coin": approval_data['coin']})
        return {"message": "Trade rejected."}

    if action.action == "approve":
        if action.position_size_usdt and trade:
            trade.position_size_usdt = action.position_size_usdt

        success = await execute_trade(trade, approval_data)
        if trade: await db.commit()

        if success:
            return {"message": "Trade executed.", "trade_id": getattr(trade, 'id', None)}
        else:
            return {"message": "Trade execution failed — check logs.", "trade_id": getattr(trade, 'id', None)}

    raise HTTPException(400, "Invalid action. Use 'approve' or 'reject'.")


# ─────────────────────────────────────────
# SIGNALS
# ─────────────────────────────────────────
@app.get("/api/signals")
async def get_signals(
    limit: int = 50,
    status: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
):
    q = select(Signal).order_by(desc(Signal.timestamp)).limit(limit)
    if status:
        q = q.where(Signal.status == status)
    result = await db.execute(q)
    sigs = result.scalars().all()
    return [
        {
            "id": s.id, "coin": s.coin, "direction": s.direction,
            "entry_price": s.entry_price, "tp1": s.tp1, "tp2": s.tp2, "tp3": s.tp3,
            "stop_loss": s.stop_loss, "confidence": s.confidence,
            "channel": s.channel, "status": s.status,
            "market_type": s.market_type,
            "timestamp": s.timestamp.isoformat() if s.timestamp else None,
            "raw_text": s.raw_text[:200]
        }
        for s in sigs
    ]


# ─────────────────────────────────────────
# TRADES
# ─────────────────────────────────────────
@app.get("/api/trades")
async def get_trades(
    limit: int = 50,
    is_paper: Optional[bool] = None,
    db: AsyncSession = Depends(get_db)
):
    q = select(Trade).order_by(desc(Trade.created_at)).limit(limit)
    if is_paper is not None:
        q = q.where(Trade.is_paper == is_paper)
    result = await db.execute(q)
    trades = result.scalars().all()
    return [
        {
            "id": t.id, "coin": t.coin, "direction": t.direction,
            "entry_price": t.entry_price, "tp1": t.tp1, "stop_loss": t.stop_loss,
            "position_size_usdt": t.position_size_usdt, "leverage": t.leverage,
            "confidence": t.confidence, "channel": t.channel,
            "status": t.status, "pnl_usdt": t.pnl_usdt, "pnl_pct": t.pnl_pct,
            "is_paper": t.is_paper, "market_type": t.market_type,
            "opened_at": t.opened_at.isoformat() if t.opened_at else None,
            "closed_at": t.closed_at.isoformat() if t.closed_at else None,
        }
        for t in trades
    ]

@app.get("/api/trades/stats")
async def get_trade_stats(
    is_paper: Optional[bool] = None,
    db: AsyncSession = Depends(get_db)
):
    q = select(Trade).where(Trade.status.in_([TradeStatus.TP_HIT, TradeStatus.SL_HIT]))
    if is_paper is not None:
        q = q.where(Trade.is_paper == is_paper)
    result = await db.execute(q)
    closed = result.scalars().all()

    if not closed:
        return {"total_trades": 0, "win_rate": 0, "total_pnl": 0, "avg_rr": 0, "best_channel": None}

    wins = [t for t in closed if t.pnl_usdt and t.pnl_usdt > 0]
    total_pnl = sum(t.pnl_usdt or 0 for t in closed)

    channel_stats: dict = {}
    for t in closed:
        ch = t.channel
        if ch not in channel_stats:
            channel_stats[ch] = {"wins": 0, "total": 0}
        channel_stats[ch]["total"] += 1
        if t.pnl_usdt and t.pnl_usdt > 0:
            channel_stats[ch]["wins"] += 1
    best_ch = max(channel_stats, key=lambda c: channel_stats[c]["wins"] / channel_stats[c]["total"])

    daily: dict = {}
    for t in closed:
        if t.closed_at:
            d = t.closed_at.strftime("%a")
            daily[d] = daily.get(d, 0) + (t.pnl_usdt or 0)

    return {
        "total_trades": len(closed),
        "wins": len(wins),
        "losses": len(closed) - len(wins),
        "win_rate": round(len(wins) / len(closed) * 100, 1),
        "total_pnl": round(total_pnl, 2),
        "avg_pnl": round(total_pnl / len(closed), 2),
        "best_channel": best_ch,
        "daily_pnl": daily,
    }

@app.get("/api/trades/export")
async def export_trades(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Trade).order_by(desc(Trade.created_at)))
    trades = result.scalars().all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID", "Coin", "Direction", "Entry", "TP1", "SL", "Size USDT",
                     "Confidence", "Channel", "Status", "PnL USDT", "PnL %", "Paper", "Opened", "Closed"])
    for t in trades:
        writer.writerow([
            t.id, t.coin, t.direction, t.entry_price, t.tp1, t.stop_loss,
            t.position_size_usdt, t.confidence, t.channel, t.status,
            t.pnl_usdt, t.pnl_pct, t.is_paper,
            t.opened_at, t.closed_at
        ])
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=trades.csv"}
    )


# ─────────────────────────────────────────
# CHANNELS & DATA SOURCES
# ─────────────────────────────────────────
@app.get("/api/channels")
async def get_data_sources(db: AsyncSession = Depends(get_db)):
    tg_result = await db.execute(select(TelegramSource))
    api_result = await db.execute(select(ApiSource))
    
    tg_sources = tg_result.scalars().all()
    api_sources = api_result.scalars().all()
    
    combined = []
    for t in tg_sources:
        combined.append({
            "id": f"tg_{t.id}", 
            "name": t.name, 
            "username": t.username, 
            "trust_weight": t.trust_weight,
            "is_active": t.is_active
        })
    for a in api_sources:
        combined.append({
            "id": f"api_{a.id}", 
            "name": a.name, 
            "username": a.endpoint_url, 
            "trust_weight": a.trust_weight,
            "is_active": a.is_active
        })
        
    return combined

@app.post("/api/channels")
async def add_data_source(source: SourceCreate, db: AsyncSession = Depends(get_db)):
    is_api = source.username.startswith("http")
    
    if is_api:
        new_source = ApiSource(
            name=source.name,
            endpoint_url=source.username,
            api_key=source.api_key,
            trust_weight=source.trust_weight
        )
    else:
        new_source = TelegramSource(
            name=source.name,
            username=source.username.replace("@", ""),
            trust_weight=source.trust_weight
        )
        
    db.add(new_source)
    try:
        await db.commit()
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=400, detail="Source already exists or invalid format.")
        
    bot_state.log(f"📡 Data source mapped: {source.name}")
    return {"status": "success", "type": "api" if is_api else "telegram"}

@app.put("/api/channels/{source_id}")
async def update_data_source(source_id: str, update: SourceUpdate, db: AsyncSession = Depends(get_db)):
    try:
        s_type, s_id_str = source_id.split("_")
        s_id = int(s_id_str)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid source ID format")
    
    source_to_update = await db.get(TelegramSource if s_type == "tg" else ApiSource, s_id)
        
    if not source_to_update:
        raise HTTPException(status_code=404, detail="Source not found")

    if update.trust_weight is not None:
        source_to_update.trust_weight = update.trust_weight
    if update.is_active is not None:
        source_to_update.is_active = update.is_active

    await db.commit()
    return {"message": "Data source updated."}

@app.delete("/api/channels/{source_id}")
async def delete_data_source(source_id: str, db: AsyncSession = Depends(get_db)):
    try:
        s_type, s_id_str = source_id.split("_")
        s_id = int(s_id_str)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid source ID format")
    
    source_to_delete = await db.get(TelegramSource if s_type == "tg" else ApiSource, s_id)
        
    if not source_to_delete:
        raise HTTPException(status_code=404, detail="Source not found")
        
    await db.delete(source_to_delete)
    await db.commit()
    return {"status": "deleted"}


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
        "binance_connected": bool(settings.BINANCE_API_KEY),
        "telegram_connected": bool(settings.TELEGRAM_SESSION_STRING),
        
        # DYNAMIC LLM RETURNS
        "llm_provider": settings.LLM_PROVIDER,
        "llm_model_name": settings.LLM_MODEL_NAME,
        "llm_api_key": settings.LLM_API_KEY,
    }

@app.post("/api/settings")
async def update_settings(update: SettingsUpdate):
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
    
    # DYNAMIC LLM UPDATES
    if update.llm_provider is not None: settings.LLM_PROVIDER = update.llm_provider
    if update.llm_model_name is not None: settings.LLM_MODEL_NAME = update.llm_model_name
    if update.llm_api_key is not None: settings.LLM_API_KEY = update.llm_api_key

    await bot_state.broadcast("settings_updated", get_settings_dict())
    return {"message": "Settings updated."}

def get_settings_dict():
    return {
        "paper_mode": bot_state.paper_mode,
        "ai_mock_mode": bot_state.ai_mock_mode,
    }


# ─────────────────────────────────────────
# TELEGRAM SESSION
# ─────────────────────────────────────────
_telegram_pending: dict = {}  

@app.post("/api/telegram/connect")
async def telegram_connect(data: TelegramConnect):
    try:
        from telethon import TelegramClient
        from telethon.sessions import StringSession
        client = TelegramClient(StringSession(), int(data.api_id), data.api_hash)
        await client.connect()
        await client.send_code_request(data.phone)
        _telegram_pending[data.phone] = {
            "client": client,
            "api_id": data.api_id,
            "api_hash": data.api_hash
        }
        bot_state.log(f"📱 OTP sent to {data.phone}")
        return {"message": "OTP sent."}
    except Exception as e:
        raise HTTPException(400, f"Failed to send OTP: {str(e)}")

@app.post("/api/telegram/verify")
async def telegram_verify(data: TelegramVerify):
    pending = _telegram_pending.get(data.phone)
    if not pending:
        raise HTTPException(400, "No pending connection for this phone.")
    try:
        client = pending["client"]
        await client.sign_in(data.phone, data.code, password=data.password or None)
        session_string = client.session.save()
        await client.disconnect()
        del _telegram_pending[data.phone]
        bot_state.log(f"✅ Telegram account connected: {data.phone}")
        return {
            "session_string": session_string,
            "message": "Connected! Copy this session string to your .env file."
        }
    except Exception as e:
        raise HTTPException(400, f"Verification failed: {str(e)}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8001, reload=True)