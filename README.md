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

🚀 Quick Start
1. Backend
Bash
git clone https://github.com/yourusername/Hybrid-Crypto-Bot.git
cd Hybrid-Crypto-Bot/backend
python -m venv bot_env
source bot_env/bin/activate  # Windows: bot_env\Scripts\activate
pip install -r requirements.txt
python main.py
2. Frontend
Bash
cd ../frontend
npm install
npm run dev
3. Configure
Open http://localhost:5173, navigate to Settings, and plug in your LLM Provider, Binance Keys, and Telegram API credentials.

⚠️ Disclaimer
Educational purposes only. Do not risk money you cannot afford to lose. Always run in PAPER_MODE first. Use at your own risk.