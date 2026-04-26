from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, Text, Enum, JSON
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime
import enum

DATABASE_URL = "sqlite+aiosqlite:///./signalbot.db"

engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
Base = declarative_base()

class TradeDirection(str, enum.Enum):
    LONG = "LONG"
    SHORT = "SHORT"

class TradeStatus(str, enum.Enum):
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    OPEN = "OPEN"
    TP_HIT = "TP_HIT"
    SL_HIT = "SL_HIT"
    EXPIRED = "EXPIRED"
    SKIPPED_SLIPPAGE = "SKIPPED_SLIPPAGE"

class SignalStatus(str, enum.Enum):
    SEEN = "SEEN"
    PARSED = "PARSED"
    REJECTED_AI = "REJECTED_AI"
    REJECTED_INCOMPLETE = "REJECTED_INCOMPLETE"
    REJECTED_DUPLICATE = "REJECTED_DUPLICATE"
    REJECTED_DRAWDOWN = "REJECTED_DRAWDOWN"
    SENT_FOR_APPROVAL = "SENT_FOR_APPROVAL"

class Signal(Base):
    __tablename__ = "signals"
    id = Column(Integer, primary_key=True, index=True)
    coin = Column(String, nullable=False)
    direction = Column(String, nullable=False)
    entry_price = Column(Float, nullable=True)
    entry_low = Column(Float, nullable=True)
    entry_high = Column(Float, nullable=True)
    tp1 = Column(Float, nullable=True)
    tp2 = Column(Float, nullable=True)
    tp3 = Column(Float, nullable=True)
    stop_loss = Column(Float, nullable=True)
    leverage = Column(Integer, nullable=True)
    confidence = Column(Float, nullable=True)
    channel = Column(String, nullable=False)
    raw_text = Column(Text, nullable=False)
    status = Column(String, default=SignalStatus.SEEN)
    market_type = Column(String, default="spot")
    timestamp = Column(DateTime, default=datetime.utcnow)

class Trade(Base):
    __tablename__ = "trades"
    id = Column(Integer, primary_key=True, index=True)
    signal_id = Column(Integer, nullable=True)
    coin = Column(String, nullable=False)
    direction = Column(String, nullable=False)
    entry_price = Column(Float, nullable=True)
    tp1 = Column(Float, nullable=True)
    tp2 = Column(Float, nullable=True)
    tp3 = Column(Float, nullable=True)
    stop_loss = Column(Float, nullable=True)
    position_size_usdt = Column(Float, nullable=False)
    leverage = Column(Integer, default=1)
    confidence = Column(Float, nullable=True)
    channel = Column(String, nullable=False)
    status = Column(String, default=TradeStatus.PENDING_APPROVAL)
    pnl_usdt = Column(Float, nullable=True)
    pnl_pct = Column(Float, nullable=True)
    is_paper = Column(Boolean, default=True)
    market_type = Column(String, default="spot")
    opened_at = Column(DateTime, nullable=True)
    closed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

# ─── NEW ARCHITECTURE: SEPARATED SOURCES & MEMORY ─────────────────────────────

class TelegramSource(Base):
    __tablename__ = "telegram_sources"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    username = Column(String, nullable=False, unique=True, index=True)
    trust_weight = Column(Float, default=0.5)
    is_active = Column(Boolean, default=True)
    total_signals = Column(Integer, default=0)
    winning_signals = Column(Integer, default=0)
    added_at = Column(DateTime, default=datetime.utcnow)

class ApiSource(Base):
    __tablename__ = "api_sources"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    endpoint_url = Column(String, nullable=False, unique=True)
    api_key = Column(String, nullable=True)
    trust_weight = Column(Float, default=0.5)
    is_active = Column(Boolean, default=True)
    added_at = Column(DateTime, default=datetime.utcnow)

class MarketContext(Base):
    __tablename__ = "market_context"
    id = Column(Integer, primary_key=True, index=True)
    coin = Column(String, index=True, nullable=True)  # Nullable because some data (like Macro) isn't coin-specific
    data_type = Column(String, index=True, nullable=False)
    payload = Column(JSON, nullable=False)            # The Schemaless Memory Blob!
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

# ──────────────────────────────────────────────────────────────────────────────

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class DailyPnL(Base):
    __tablename__ = "daily_pnl"
    id = Column(Integer, primary_key=True)
    date = Column(String, nullable=False, unique=True)
    realized_pnl = Column(Float, default=0.0)
    trade_count = Column(Integer, default=0)

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

async def get_db():
    async with AsyncSessionLocal() as session:
        yield session