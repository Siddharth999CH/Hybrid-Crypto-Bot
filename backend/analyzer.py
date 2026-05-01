import json
import random
import re
from typing import Optional, List
from datetime import datetime, timezone
from sqlalchemy import select
import ccxt.async_support as ccxt_async

from config import settings
from state import bot_state
from database import AsyncSessionLocal, MarketContext

# ─────────────────────────────────────────
# GLOBAL ASYNC CCXT CLIENT
# FIX 5: Stored as a module-level singleton so it can be properly closed
# on shutdown.  Call close_binance_client() in the FastAPI lifespan teardown.
# ─────────────────────────────────────────
_binance_client: Optional[ccxt_async.binance] = None

def _get_binance_client() -> ccxt_async.binance:
    global _binance_client
    if _binance_client is None:
        _binance_client = ccxt_async.binance({'enableRateLimit': True})
    return _binance_client

async def close_binance_client():
    """Call this in FastAPI lifespan shutdown to prevent connection leaks."""
    global _binance_client
    if _binance_client is not None:
        try:
            await _binance_client.close()
        except Exception:
            pass
        _binance_client = None


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
        tp_pct, sl_pct = 0.02, 0.01
    elif trading_style == "swing":
        tp_pct, sl_pct = 0.10, 0.05
    else:
        tp_pct, sl_pct = 0.05, 0.02

    if direction == "LONG":
        tp = current_price * (1 + tp_pct)
        sl = current_price * (1 - sl_pct)
    else:
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
    """Calculates position size respecting max risk and confidence."""
    max_risk_usdt = portfolio_balance * (bot_state.max_risk_pct / 100)
    confidence_factor = min(max(confidence, 0.0), 1.0)
    adjusted_risk = max_risk_usdt * confidence_factor

    risk_per_unit = abs(entry_price - stop_loss)
    if risk_per_unit == 0:
        return round(adjusted_risk, 2)

    units = adjusted_risk / risk_per_unit
    position_size = units * entry_price * leverage
    max_position = portfolio_balance * 0.10
    return round(min(position_size, max_position), 2)


# ─────────────────────────────────────────
# 2. DATA INGESTION HELPERS
# ─────────────────────────────────────────
async def fetch_live_price(coin: str) -> Optional[float]:
    """Fetches the live ticker price from Binance via async ccxt."""
    try:
        client = _get_binance_client()
        ticker = await client.fetch_ticker(f"{coin}/USDT")
        return float(ticker['last'])
    except Exception as e:
        bot_state.log(f"⚠️ Failed to fetch live price for {coin}: {e}", level="warning")
        if bot_state.ai_mock_mode:
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
    """Uses LiteLLM to evaluate social heat vs DEX reality."""

    if bot_state.ai_mock_mode or not settings.LLM_API_KEY:
        bot_state.log("⚠️ LLM bypassed. Using mock generation.", level="warning")
        return {
            "bias": random.choice(["LONG", "SHORT"]),
            "confidence": round(random.uniform(0.60, 0.90), 2),
            "reason": "Mock mode active — simulated bias."
        }

    compressed_messages = " | ".join(messages)[:1500]
    prompt = f"""You are an elite quantitative crypto analyst. Determine a trading bias (LONG, SHORT, or NEUTRAL).

Target Asset: {coin}
Trading Style: {bot_state.trading_style.upper()}

--- SOCIAL SENTIMENT ---
{compressed_messages}

--- LIVE DEX CONFLUENCE ---
{dex_context}

Rules:
1. If social is hyper-bullish but funding rates are heavily positive (longs paying), that is a bearish divergence.
2. Heavy conflict between social and DEX → NEUTRAL.
3. Strong alignment → high confidence.

Return ONLY valid JSON:
{{"bias": "LONG", "confidence": 0.85, "reason": "Brief explanation."}}"""

    try:
        from litellm import acompletion
        response = await acompletion(
            model=settings.LLM_MODEL_NAME,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=200,
            temperature=0.1,
            api_key=settings.LLM_API_KEY
        )
        raw_text = response.choices[0].message.content.strip()
        json_match = re.search(r'\{.*\}', raw_text, re.DOTALL)
        if not json_match:
            raise ValueError("No JSON object in LLM response.")
        data = json.loads(json_match.group(0))
        bot_state.log(
            f"🧠 AI [{settings.LLM_MODEL_NAME}]: {coin} {data.get('bias')} "
            f"({data.get('confidence', 0):.0%}) — {data.get('reason', '')[:80]}"
        )
        return {
            "bias": data.get("bias", "NEUTRAL").upper(),
            "confidence": float(data.get("confidence", 0.0)),
            "reason": data.get("reason", "No reason provided.")
        }
    except Exception as e:
        bot_state.log(f"⚠️ AI generation error: {str(e)[:60]}", level="warning")
        return {"bias": "NEUTRAL", "confidence": 0.0, "reason": "LLM failure."}


# ─────────────────────────────────────────
# 4. MAIN ORCHESTRATOR
# ─────────────────────────────────────────
async def analyze_sentiment_target(
    coin: str,
    raw_messages: List[str],
    portfolio_balance: float
) -> Optional[dict]:
    """
    Full Phase B Pipeline:
    Raw sentiment → Fetch Data → Generate Bias → Calculate Math → Return Trade Dict
    """
    bot_state.log(f"🔍 Phase B: Analyzing aggregated sentiment for {coin}...")

    current_price = await fetch_live_price(coin)
    if not current_price:
        bot_state.log(f"❌ Aborting analysis for {coin}: Could not fetch live price.")
        return None

    dex_context = await fetch_dex_context(coin)
    ai_decision = await evaluate_sentiment_bias(coin, raw_messages, dex_context)

    if ai_decision["bias"] == "NEUTRAL" or ai_decision["confidence"] < 0.50:
        bot_state.log(f"⏭️ Skipping {coin}: AI confidence too low or bias neutral.")
        return None

    params = calculate_trade_parameters(
        current_price=current_price,
        direction=ai_decision["bias"],
        trading_style=bot_state.trading_style
    )

    position_size = calculate_position_size(
        entry_price=params["entry_price"],
        stop_loss=params["stop_loss"],
        portfolio_balance=portfolio_balance,
        confidence=ai_decision["confidence"],
        leverage=settings.MAX_LEVERAGE
    )

    trade_payload = {
        "coin": coin,
        "direction": ai_decision["bias"],
        "entry_price": params["entry_price"],
        "tp1": params["tp1"],
        "stop_loss": params["stop_loss"],
        "position_size_usdt": position_size,
        "confidence": ai_decision["confidence"],
        "reason": ai_decision["reason"],
        "analysis": ai_decision["reason"],      # Alias for Signals.jsx display
        "trading_style": bot_state.trading_style,
        "market_type": "futures",
        "leverage": settings.MAX_LEVERAGE,
        "channel": "aggregated",
        "source_count": len(raw_messages),
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

    bot_state.log(
        f"🎯 Trade Drafted: {coin} {ai_decision['bias']} @ {params['entry_price']} "
        f"(Size: ${position_size}, Conf: {ai_decision['confidence']:.0%})"
    )
    return trade_payload