import json
import random
import re
from typing import Optional, List
from datetime import datetime, timezone
from sqlalchemy import select
import ccxt.async_support as ccxt 

from config import settings
from state import bot_state
from database import AsyncSessionLocal, MarketContext

# ─────────────────────────────────────────
# GLOBAL INSTANCES (Bug 2 Fix)
# ─────────────────────────────────────────
# Keeps the socket open so Binance doesn't rate-limit or IP ban us.
binance_client = ccxt.binance({'enableRateLimit': True})

# ─────────────────────────────────────────
# 1. MATHEMATICAL & SIZING HELPERS
# ─────────────────────────────────────────
def calculate_trade_parameters(
    current_price: float, 
    direction: str, 
    trading_style: str
) -> dict:
    """Calculates TP and SL based on the current trading style."""
    
    if trading_style == "scalp":
        tp_pct = 0.02  # 2% target
        sl_pct = 0.01  # 1% stop
    elif trading_style == "swing":
        tp_pct = 0.10  # 10% target
        sl_pct = 0.05  # 5% stop
    else:
        # Fallback defaults
        tp_pct = 0.05
        sl_pct = 0.02

    if direction == "LONG":
        tp = current_price * (1 + tp_pct)
        sl = current_price * (1 - sl_pct)
    else: # SHORT
        tp = current_price * (1 - tp_pct)
        sl = current_price * (1 + sl_pct)
        
    return {
        "entry_price": round(current_price, 4),
        "tp1": round(tp, 4),
        "stop_loss": round(sl, 4)
    }

def calculate_position_size(
    entry_price: float,
    stop_loss: float,
    portfolio_balance: float,
    confidence: float,
    leverage: int = 1
) -> float:
    """Calculates position size strictly respecting max risk and confidence."""
    max_risk_usdt = portfolio_balance * (bot_state.max_risk_pct / 100)
    
    # Scale risk linearly by confidence
    confidence_factor = min(max(confidence, 0.0), 1.0)
    adjusted_risk = max_risk_usdt * confidence_factor

    risk_per_unit = abs(entry_price - stop_loss)
    if risk_per_unit == 0:
        return round(adjusted_risk, 2)

    units = adjusted_risk / risk_per_unit
    position_size = units * entry_price * leverage

    # Hard cap at 10% of portfolio to prevent massive exposure
    max_position = portfolio_balance * 0.10
    return round(min(position_size, max_position), 2)


# ─────────────────────────────────────────
# 2. DATA INGESTION HELPERS
# ─────────────────────────────────────────
async def fetch_live_price(coin: str) -> Optional[float]:
    """Fetches the live ticker price from Binance via CCXT."""
    try:
        # Re-using the global binance_client instance
        ticker = await binance_client.fetch_ticker(f"{coin}/USDT")
        return float(ticker['last'])
    except Exception as e:
        bot_state.log(f"⚠️ Failed to fetch live price for {coin}: {e}", level="warning")
        if bot_state.ai_mock_mode:
            # Testing-mode fallback so the full pipeline remains usable offline.
            return 100.0
        return None

async def fetch_dex_context(coin: str) -> str:
    """Pulls the latest quantitative Hyperliquid data from local DB."""
    dex_context = "No live DEX data available for this coin."
    try:
        async with AsyncSessionLocal() as db:
            stmt = select(MarketContext).where(
                MarketContext.coin == coin.upper(),
                MarketContext.data_type == "DEX_Metrics"
            )
            result = await db.execute(stmt)
            db_record = result.scalar_one_or_none()
            
            if db_record and db_record.payload:
                payload = db_record.payload
                funding = payload.get("funding_rate", "N/A")
                oi = payload.get("open_interest", "N/A")
                dex_context = f"Funding Rate: {funding} | Open Interest: ${oi}"
    except Exception as e:
        bot_state.log(f"⚠️ Failed to read MarketContext: {e}", level="warning")
        
    return dex_context


# ─────────────────────────────────────────
# 3. THE GENERATIVE AI ENGINE
# ─────────────────────────────────────────
async def evaluate_sentiment_bias(
    coin: str, 
    messages: List[str], 
    dex_context: str
) -> dict:
    """Uses LLM to evaluate social heat vs DEX reality and output a directional bias."""
    
    if bot_state.ai_mock_mode or not settings.LLM_API_KEY:
        bot_state.log("⚠️ LLM bypassed. Using mock generation.", level="warning")
        return {"bias": random.choice(["LONG", "SHORT"]), "confidence": 0.75, "reason": "Mock mode active."}

    # Compress messages to avoid blowing up context windows
    compressed_messages = " | ".join(messages)[:1500]

    prompt = f"""You are an elite quantitative crypto analyst. Your job is to determine a trading bias (LONG, SHORT, or NEUTRAL) based on recent social sentiment and live market data.

Target Asset: {coin}
Current Trading Style: {bot_state.trading_style.upper()}

--- SOCIAL SENTIMENT INTERCEPTS ---
{compressed_messages}

--- LIVE DEX CONFLUENCE (Hyperliquid) ---
{dex_context}

Analysis Rules:
1. Compare the sentiment against the DEX data. If social is hyper-bullish but Funding Rates are heavily positive (longs paying shorts), that is a bearish divergence.
2. If the data conflicts heavily, output NEUTRAL.
3. If there is a strong alignment between social heat and market structure, assign a high confidence score.

Return ONLY a JSON exactly like this: 
{{"bias": "LONG", "confidence": 0.85, "reason": "Social sentiment indicates a breakout, supported by negative funding rates (shorts squeezed)."}}
"""

    try:
        # Lazy import keeps backend bootable when optional AI deps are missing.
        from litellm import acompletion
        response = await acompletion(
            model=settings.LLM_MODEL_NAME,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=200,
            temperature=0.1,
            api_key=settings.LLM_API_KEY
        )
        
        raw_text = response.choices[0].message.content.strip()
        
        # Bug 3 Fix: Regex parsing to guarantee JSON extraction
        json_match = re.search(r'\{.*\}', raw_text, re.DOTALL)
        if json_match:
            data = json.loads(json_match.group(0))
        else:
            raise ValueError("No valid JSON object found in LLM response.")
            
        bot_state.log(f"🧠 AI Quant [{settings.LLM_MODEL_NAME}]: {coin} {data.get('bias')} - {data.get('reason', '')[:100]}...")
        
        return {
            "bias": data.get("bias", "NEUTRAL").upper(),
            "confidence": float(data.get("confidence", 0.0)),
            "reason": data.get("reason", "No reason provided.")
        }

    except Exception as e:
        bot_state.log(f"⚠️ AI generation error: {str(e)[:50]}", level="warning")
        return {"bias": "NEUTRAL", "confidence": 0.0, "reason": "LLM Failure"}


# ─────────────────────────────────────────
# 4. MAIN ORCHESTRATOR (Handoff from Phase A)
# ─────────────────────────────────────────
async def analyze_sentiment_target(coin: str, raw_messages: List[str], portfolio_balance: float) -> Optional[dict]:
    """
    Full Phase B Pipeline: 
    Takes raw sentiment -> Fetches Data -> Generates Bias -> Calculates Math -> Returns Trade Dict
    """
    bot_state.log(f"🔍 Phase B: Analyzing aggregated sentiment for {coin}...")

    # 1. Fetch Market Reality
    current_price = await fetch_live_price(coin)
    if not current_price:
        bot_state.log(f"❌ Aborting analysis for {coin}: Could not fetch live price.")
        return None

    dex_context = await fetch_dex_context(coin)

    # 2. Get LLM Bias & Confidence
    ai_decision = await evaluate_sentiment_bias(coin, raw_messages, dex_context)
    
    if ai_decision["bias"] == "NEUTRAL" or ai_decision["confidence"] < 0.50:
        bot_state.log(f"⏭️ Skipping {coin}: AI confidence too low or bias neutral.")
        return None

    # 3. Calculate Mathematical Trade Targets based on Trading Style
    params = calculate_trade_parameters(
        current_price=current_price,
        direction=ai_decision["bias"],
        trading_style=bot_state.trading_style
    )

    # 4. Calculate Risk-Adjusted Position Size
    position_size = calculate_position_size(
        entry_price=params["entry_price"],
        stop_loss=params["stop_loss"],
        portfolio_balance=portfolio_balance,
        confidence=ai_decision["confidence"],
        leverage=settings.MAX_LEVERAGE
    )

    # 5. Format payload for bot_state.pending_approvals queue
    trade_payload = {
        "coin": coin,
        "direction": ai_decision["bias"],
        "entry_price": params["entry_price"],
        "tp1": params["tp1"],
        "stop_loss": params["stop_loss"],
        "position_size_usdt": position_size,
        "confidence": ai_decision["confidence"],
        "reason": ai_decision["reason"],
        "trading_style": bot_state.trading_style,
        "market_type": "futures",
        "leverage": settings.MAX_LEVERAGE,
        "timestamp": datetime.now(timezone.utc).isoformat() # Bug 4 Fix: True Timestamp
    }

    bot_state.log(f"🎯 Trade Drafted: {coin} {ai_decision['bias']} at {params['entry_price']} (Size: ${position_size})")
    return trade_payload