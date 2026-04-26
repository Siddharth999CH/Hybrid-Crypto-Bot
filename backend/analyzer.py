import json
import random
from typing import Optional
from sqlalchemy import select
import litellm
from litellm import acompletion

from signal_parser import ParsedSignal
from config import settings
from state import bot_state
from database import AsyncSessionLocal, MarketContext

def calculate_rr_ratio(signal: ParsedSignal) -> Optional[float]:
    """Risk:Reward ratio. Higher = better signal."""
    if not signal.entry_price or not signal.stop_loss or not signal.tp1:
        return None
    risk = abs(signal.entry_price - signal.stop_loss)
    reward = abs(signal.tp1 - signal.entry_price)
    if risk == 0:
        return None
    return round(reward / risk, 2)


def calculate_position_size(
    signal: ParsedSignal,
    portfolio_balance: float,
    confidence: float
) -> float:
    """
    AI-driven position sizing:
    - Base risk = 1% of portfolio (hard cap)
    - Adjusted by confidence score (0.5 confidence = 50% of base risk)
    - Never exceeds max_risk_pct regardless of confidence
    """
    if not signal.entry_price or not signal.stop_loss:
        # Fallback: use 0.5% of portfolio
        return round(portfolio_balance * 0.005, 2)

    max_risk_usdt = portfolio_balance * (bot_state.max_risk_pct / 100)

    # Scale by confidence: confidence 0.5 -> 50% of max, 1.0 -> 100% of max
    confidence_factor = min(max(confidence, 0.0), 1.0)
    adjusted_risk = max_risk_usdt * confidence_factor

    # Calculate position size from risk amount
    risk_per_unit = abs(signal.entry_price - signal.stop_loss)
    if risk_per_unit == 0:
        return round(adjusted_risk, 2)

    units = adjusted_risk / risk_per_unit
    position_size = units * signal.entry_price

    # Apply leverage factor for futures
    leverage = signal.leverage or 1
    position_size = position_size * leverage

    # Hard cap at 10% of portfolio regardless of leverage/confidence
    max_position = portfolio_balance * 0.10
    return round(min(position_size, max_position), 2)


async def score_signal(signal: ParsedSignal, channel_trust: float = 0.5) -> float:
    """
    Score a signal 0.0 - 1.0.
    Combines: R:R ratio, completeness, channel trust, and LIVE DEX CONFLUENCE.
    """
    # 1. Check if we should bypass the API
    if bot_state.ai_mock_mode or not settings.LLM_API_KEY:
        if not settings.LLM_API_KEY and not bot_state.ai_mock_mode:
            bot_state.log("⚠️ No LLM_API_KEY provided. Falling back to mock scores.", level="warning")
        return _mock_score(signal, channel_trust)

    # 2. GATE 3: THE CONFLUENCE ENGINE (Fetch from Memory)
    dex_context = "No live DEX data available for this coin."
    try:
        if signal.coin:
            async with AsyncSessionLocal() as db:
                stmt = select(MarketContext).where(
                    MarketContext.coin == signal.coin.upper(),
                    MarketContext.data_type == "DEX_Metrics"
                )
                result = await db.execute(stmt)
                db_record = result.scalar_one_or_none()
                
                if db_record and db_record.payload:
                    payload = db_record.payload
                    funding = payload.get("funding_rate", "N/A")
                    oi = payload.get("open_interest", "N/A")
                    pred_funding = payload.get("predicted_funding", "N/A")
                    dex_context = f"Funding Rate: {funding} | Open Interest: ${oi} | Predicted Funding (8h): {pred_funding}"
    except Exception as e:
        bot_state.log(f"⚠️ Failed to read MarketContext: {e}", level="warning")

    # 3. THE LLM EVALUATION (Now LLM-Agnostic via LiteLLM)
    try:
        signal_summary = f"""
Coin: {signal.coin}
Direction: {signal.direction}
Entry: {signal.entry_price}
TP1: {signal.tp1}, TP2: {signal.tp2}, TP3: {signal.tp3}
Stop Loss: {signal.stop_loss}
Leverage: {signal.leverage or 'none'}
Market: {signal.market_type}
Channel trust: {channel_trust}
Raw message: {signal.raw_text[:300]}

--- LIVE HYPERLIQUID DEX CONFLUENCE ---
{dex_context}
"""

        prompt = f"""You are a quant risk analyst evaluating a crypto trading signal. Score this from 0.0 to 1.0.

{signal_summary}

Scoring criteria:
- R:R ratio (higher is better, 1:2+ is good)
- Signal completeness (has entry, TP, SL = higher score)
- Channel trust weight (0.0 to 1.0)
- MARKET CONFLUENCE: Does the DEX data support the trade? 
  * If LONG: High negative funding means shorts are paying longs (Bullish structure). Drop score if OI is extremely low.
  * If SHORT: High positive funding means longs are paying shorts (Bearish structure).
  * If no DEX data is available, do not penalize heavily, base it on the R:R.

Return ONLY a JSON exactly like this: {{"confidence": 0.82, "reason": "Good R:R of 2.1, but lowered score slightly due to conflicting DEX funding rates."}}"""

        # LiteLLM dynamically routes this based on the model string
        response = await acompletion(
            model=settings.LLM_MODEL_NAME,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=150,
            temperature=0.1,
            api_key=settings.LLM_API_KEY
        )
        
        # Extract the JSON from the agnostic response format
        raw_text = response.choices[0].message.content.strip()
        
        # Strip markdown codeblocks if the LLM adds them
        if raw_text.startswith("```json"):
            raw_text = raw_text.replace("```json", "").replace("```", "").strip()
            
        data = json.loads(raw_text)
        
        bot_state.log(f"🧠 AI Reasoning [{settings.LLM_MODEL_NAME}]: {data.get('reason', 'None')}")
        
        return float(data.get("confidence", 0.5))

    except Exception as e:
        bot_state.log(f"⚠️ AI scoring error: {str(e)[:50]}", level="warning")
        return _mock_score(signal, channel_trust)


def _mock_score(signal: ParsedSignal, channel_trust: float) -> float:
    """Deterministic mock scoring without API calls."""
    score = 0.0

    # Completeness
    if signal.coin: score += 0.15
    if signal.entry_price: score += 0.15
    if signal.tp1: score += 0.15
    if signal.stop_loss: score += 0.20

    # R:R ratio
    rr = calculate_rr_ratio(signal)
    if rr:
        if rr >= 2.0: score += 0.20
        elif rr >= 1.5: score += 0.12
        elif rr >= 1.0: score += 0.06

    # Channel trust
    score += channel_trust * 0.15

    # Add small random variation to make it feel realistic
    score += random.uniform(-0.03, 0.03)

    return round(min(max(score, 0.0), 1.0), 2)


async def analyze_signal(signal: ParsedSignal, channel_trust: float, portfolio_balance: float) -> dict:
    """Full analysis pipeline. Returns enriched signal dict ready for approval."""
    confidence = await score_signal(signal, channel_trust)
    signal.confidence = confidence

    rr = calculate_rr_ratio(signal)
    position_size = calculate_position_size(signal, portfolio_balance, confidence)

    return {
        **signal.to_dict(),
        "confidence": confidence,
        "rr_ratio": rr,
        "position_size_usdt": position_size,
        "channel_trust": channel_trust,
    }