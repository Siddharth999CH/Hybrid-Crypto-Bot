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

    # AI — Primary (Anthropic)
    ANTHROPIC_API_KEY: str = ""
    AI_MOCK_MODE: bool = True

    # FIX 4: LiteLLM generic fields — used by analyzer.py
    # Set LLM_PROVIDER to e.g. "anthropic", "openai", "gemini", "ollama"
    # Set LLM_MODEL_NAME to e.g. "claude-haiku-4-5-20251001", "gpt-4o-mini"
    # Set LLM_API_KEY to the matching provider's key
    LLM_PROVIDER: str = "anthropic"
    LLM_MODEL_NAME: str = "claude-haiku-4-5-20251001"
    LLM_API_KEY: str = ""         # Populated at runtime from Settings UI or .env

    # Risk defaults
    MAX_RISK_PER_TRADE_PCT: float = 1.0
    DAILY_DRAWDOWN_LIMIT_PCT: float = 5.0
    MAX_CONCURRENT_TRADES: int = 3
    APPROVAL_TIMEOUT_SECONDS: int = 300
    MAX_LEVERAGE: int = 10
    SLIPPAGE_THRESHOLD_PCT: float = 0.5
    SL_COOLDOWN_HOURS: int = 2

    # App
    SECRET_KEY: str = "changeme-in-production"
    PAPER_MODE: bool = True

    # Aliases from older .env files — kept for backwards compatibility
    notifier_bot_token: str = ""
    admin_chat_id: str = ""
    claude_api_key: str = ""
    use_mock_ai: bool = True
    use_paper_trading: bool = True
    huggingface_api_key: str = ""

    class Config:
        env_file = ".env"
        extra = "ignore"

settings = Settings()

# If LLM_API_KEY is blank, fall back to ANTHROPIC_API_KEY
# so existing .env files keep working without changes.
if not settings.LLM_API_KEY and settings.ANTHROPIC_API_KEY:
    settings.LLM_API_KEY = settings.ANTHROPIC_API_KEY