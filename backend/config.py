import os
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # Telegram
    TELEGRAM_API_ID: str = ""
    TELEGRAM_API_HASH: str = ""
    TELEGRAM_SESSION_STRING: str = ""
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_CHAT_ID: str = ""

    # Binance
    BINANCE_API_KEY: str = ""
    BINANCE_SECRET: str = ""
    BINANCE_TESTNET: bool = True

    # 🧠 AI (UPDATED FOR DYNAMIC LLMs)
    LLM_PROVIDER: str = "anthropic"           # e.g., 'anthropic', 'openai', 'gemini'
    LLM_MODEL_NAME: str = "claude-3-5-haiku-20241022"
    LLM_API_KEY: str = ""                     # The master key for the chosen provider
    AI_MOCK_MODE: bool = True                 # True = no API calls, uses simulated scores

    # Risk defaults
    MAX_RISK_PER_TRADE_PCT: float = 1.0
    DAILY_DRAWDOWN_LIMIT_PCT: float = 5.0
    MAX_CONCURRENT_TRADES: int = 3
    APPROVAL_TIMEOUT_SECONDS: int = 300
    MAX_LEVERAGE: int = 10
    SLIPPAGE_THRESHOLD_PCT: float = 0.5
    SL_COOLDOWN_HOURS: int = 2

    # App
    SECRET_KEY: str = "changeme-use-a-real-secret-in-production"
    PAPER_MODE: bool = True

    # System overrides
    admin_chat_id: str = ""
    use_mock_ai: bool = True
    use_paper_trading: bool = True

    class Config:
        env_file = ".env"
        extra = "ignore" # Tells the bouncer to relax if you add more stuff later!

settings = Settings()