⚡ Hybrid-Crypto-Bot (SignalBot)
A Semi-Autonomous, LLM-Powered Quantitative Crypto Trading Engine

🚧 WORK IN PROGRESS: This project is under active development. Architecture and features are subject to rapid iteration. 🚧

📖 Overview
Hybrid-Crypto-Bot intercepts Telegram trading signals, enriches them with live DEX metrics (Funding Rates, Open Interest), and scores them using an LLM. Trades that pass the AI's confluence engine are pushed to a secure React dashboard for manual execution. No rogue auto-trading—you have the final say.

✨ Key Features
🧠 LLM-Agnostic Engine: Route prompts to OpenAI, Claude, Gemini, or local models like Ollama via litellm.

📊 Live DEX Memory: Cross-references signals against live Hyperliquid whale positioning and funding rates.

📡 Dynamic Telegram Scraper: Intercepts signals via Telethon with database-driven target filtering.

🛡️ Human-in-the-Loop: Bot calculates risk and position sizing, but waits in a UI queue for your approval to execute on Binance.

🛠️ Tech Stack
Backend: Python, FastAPI, SQLAlchemy, CCXT, Telethon, LiteLLM | Frontend: React, Vite | DB: SQLite

