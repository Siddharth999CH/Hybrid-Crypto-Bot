import asyncio
from datetime import datetime, date
from typing import List, Dict, Optional, Set
import json
import sys
from config import settings

class BotState:
    """Central shared state for the entire bot system."""

    def __init__(self):
        self.is_active: bool = False
        self.paper_mode: bool = settings.PAPER_MODE
        self.kill_switch_active: bool = False
        self.kill_switch_reason: str = ""

        # Runtime stats
        self.daily_pnl: float = 0.0
        self.daily_pnl_date: str = str(date.today())
        self.open_trades_count: int = 0
        self.portfolio_balance: float = 10000.0  # Updated from exchange on startup

        # Pending approvals: signal_id -> Signal dict
        self.pending_approvals: Dict[int, dict] = {}

        # Cooldowns: coin -> datetime when cooldown expires
        self.sl_cooldowns: Dict[str, datetime] = {}

        # Activity log (newest first)
        self.activity_logs: List[dict] = []

        # WebSocket connections
        self.ws_clients: List = []

        # Settings (runtime-adjustable)
        self.max_risk_pct: float = settings.MAX_RISK_PER_TRADE_PCT
        self.daily_drawdown_limit: float = settings.DAILY_DRAWDOWN_LIMIT_PCT
        self.max_concurrent_trades: int = settings.MAX_CONCURRENT_TRADES
        self.approval_timeout: int = settings.APPROVAL_TIMEOUT_SECONDS
        self.max_leverage: int = settings.MAX_LEVERAGE
        self.slippage_threshold: float = settings.SLIPPAGE_THRESHOLD_PCT
        self.ai_mock_mode: bool = settings.AI_MOCK_MODE
        self.trailing_sl: bool = False
        self.signal_notifications: bool = True

        # ─────────────────────────────────────────
        # PHASE A: SENTIMENT RADAR VARIABLES
        # ─────────────────────────────────────────
        self.trading_style: str = "scalp" 
        self.radar_bucket: Dict[str, dict] = {} 
        self.active_trades_coins: Set[str] = set()
    
    def debug_log(self, run_id: str, hypothesis_id: str, location: str, message: str, data: dict):
        try:
            payload = {
                "sessionId": "e3292d",
                "runId": run_id,
                "hypothesisId": hypothesis_id,
                "location": location,
                "message": message,
                "data": data,
                "timestamp": int(datetime.now().timestamp() * 1000),
            }
            with open("C:/Users/91990/Desktop/Hybrid-Crypto-Bot/debug-e3292d.log", "a", encoding="utf-8") as f:
                f.write(json.dumps(payload, ensure_ascii=True) + "\n")
        except Exception:
            pass

    def log(self, message: str, level: str = "info"):
        timestamp = datetime.now().strftime("%H:%M:%S")
        entry = {"time": timestamp, "message": message, "level": level}
        self.activity_logs.insert(0, entry)
        if len(self.activity_logs) > 50:
            self.activity_logs.pop()
        line = f"[{timestamp}] {message}"
        try:
            print(line)
        except UnicodeEncodeError:
            # Windows cp1252 consoles can choke on emoji; degrade gracefully.
            encoding = (getattr(sys.stdout, "encoding", None) or "utf-8")
            safe_line = line.encode(encoding, errors="replace").decode(encoding, errors="replace")
            print(safe_line)
        # #region agent log
        self.debug_log(
            run_id="initial",
            hypothesis_id="H1",
            location="backend/state.py:log",
            message="bot_state.log emitted",
            data={"level": level, "message": message[:200]},
        )
        # #endregion

    def check_and_reset_daily_pnl(self):
        today = str(date.today())
        if self.daily_pnl_date != today:
            self.daily_pnl = 0.0
            self.daily_pnl_date = today
            if self.kill_switch_active and "drawdown" in self.kill_switch_reason.lower():
                # Auto-reset kill switch on new day
                self.kill_switch_active = False
                self.kill_switch_reason = ""
                self.log("🔄 Kill switch auto-reset for new trading day.")

    def trigger_kill_switch(self, reason: str):
        self.kill_switch_active = True
        self.kill_switch_reason = reason
        self.is_active = False
        self.log(f"🚨 KILL SWITCH TRIGGERED: {reason}", level="danger")

    def can_trade(self, coin: str) -> tuple[bool, str]:
        """Returns (can_trade, reason_if_not)"""
        self.check_and_reset_daily_pnl()
        if self.kill_switch_active:
            # #region agent log
            self.debug_log(
                run_id="initial",
                hypothesis_id="H4",
                location="backend/state.py:can_trade",
                message="can_trade blocked by kill switch",
                data={"coin": coin, "reason": self.kill_switch_reason},
            )
            # #endregion
            return False, f"Kill switch active: {self.kill_switch_reason}"
        if not self.is_active:
            # #region agent log
            self.debug_log(
                run_id="initial",
                hypothesis_id="H4",
                location="backend/state.py:can_trade",
                message="can_trade blocked by paused bot",
                data={"coin": coin, "is_active": self.is_active},
            )
            # #endregion
            return False, "Bot is paused"
        if self.open_trades_count >= self.max_concurrent_trades:
            return False, f"Max concurrent trades ({self.max_concurrent_trades}) reached"
        if coin.upper() in self.sl_cooldowns:
            if datetime.now() < self.sl_cooldowns[coin.upper()]:
                remaining = (self.sl_cooldowns[coin.upper()] - datetime.now()).seconds // 60
                return False, f"{coin} in SL cooldown ({remaining}m remaining)"
        
        # Phase A Check: Prevent opening multiple positions on the same coin
        if coin.upper() in self.active_trades_coins:
             # #region agent log
             self.debug_log(
                 run_id="initial",
                 hypothesis_id="H4",
                 location="backend/state.py:can_trade",
                 message="can_trade blocked by active coin lock",
                 data={"coin": coin},
             )
             # #endregion
             return False, f"Trade already active for {coin}"
             
        # #region agent log
        self.debug_log(
            run_id="initial",
            hypothesis_id="H4",
            location="backend/state.py:can_trade",
            message="can_trade allowed",
            data={"coin": coin, "open_trades_count": self.open_trades_count},
        )
        # #endregion
        return True, ""

    def add_pnl(self, pnl_usdt: float):
        self.check_and_reset_daily_pnl()
        self.daily_pnl += pnl_usdt
        loss_pct = abs(self.daily_pnl) / self.portfolio_balance * 100
        if self.daily_pnl < 0 and loss_pct >= self.daily_drawdown_limit:
            self.trigger_kill_switch(
                f"Daily loss limit reached: -{loss_pct:.1f}% (limit: {self.daily_drawdown_limit}%)"
            )

    async def broadcast(self, event_type: str, data: dict):
        """Push event to all connected WebSocket clients."""
        import json
        message = json.dumps({"type": event_type, "data": data})
        dead = []
        for ws in self.ws_clients:
            try:
                await ws.send_text(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.ws_clients.remove(ws)

# Singleton
bot_state = BotState()