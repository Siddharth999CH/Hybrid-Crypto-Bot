import re
import json
import asyncio
import httpx
from typing import Optional
from dataclasses import dataclass, field
from datetime import datetime
from config import settings
from state import bot_state

@dataclass
class ParsedSignal:
    coin: str = ""
    direction: str = "LONG"        # LONG or SHORT
    entry_price: Optional[float] = None
    entry_low: Optional[float] = None
    entry_high: Optional[float] = None
    tp1: Optional[float] = None
    tp2: Optional[float] = None
    tp3: Optional[float] = None
    stop_loss: Optional[float] = None
    leverage: Optional[int] = None
    market_type: str = "spot"      # spot or futures
    confidence: float = 0.0
    channel: str = ""
    raw_text: str = ""
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    is_complete: bool = False

    def to_dict(self):
        return {
            "coin": self.coin,
            "direction": self.direction,
            "entry_price": self.entry_price,
            "entry_low": self.entry_low,
            "entry_high": self.entry_high,
            "tp1": self.tp1,
            "tp2": self.tp2,
            "tp3": self.tp3,
            "stop_loss": self.stop_loss,
            "leverage": self.leverage,
            "market_type": self.market_type,
            "confidence": self.confidence,
            "channel": self.channel,
            "raw_text": self.raw_text,
            "timestamp": self.timestamp,
            "is_complete": self.is_complete,
        }


# ─────────────────────────────────────────
# PASS 1: Regex-based fast parser
# ─────────────────────────────────────────
def regex_parse(text: str, channel: str) -> Optional[ParsedSignal]:
    """Extracts common structured signal formats using regex."""
    s = ParsedSignal(raw_text=text, channel=channel)
    upper = text.upper()

    # ── Coin symbol ──────────────────────────────
    coin_match = re.search(
        r'\b([A-Z]{2,10})(?:/USDT|USDT|/USD)?\b', upper
    )
    common_non_coins = {"THE", "AND", "FOR", "BUY", "SELL", "LONG", "SHORT", "USD", "USDT", "STOP", "TAKE", "ENTRY"}
    if coin_match:
        for m in re.finditer(r'\b([A-Z]{2,10})\b', upper):
            if m.group(1) not in common_non_coins:
                s.coin = m.group(1)
                break
    if not s.coin:
        return None

    # ── Direction ────────────────────────────────
    if any(w in upper for w in ["SHORT", "SELL", "BEARISH", "⬇", "🔴"]):
        s.direction = "SHORT"
    else:
        s.direction = "LONG"

    # ── Market type ──────────────────────────────
    if any(w in upper for w in ["FUTURES", "PERP", "LEVERAG", "LONG X", "SHORT X", "LEVERAGE"]):
        s.market_type = "futures"

    # ── Leverage ─────────────────────────────────
    lev = re.search(r'(\d{1,2})[xX]\s*(?:leverage)?', text)
    if lev:
        s.leverage = min(int(lev.group(1)), settings.MAX_LEVERAGE)
        s.market_type = "futures"

    # ── Entry price ──────────────────────────────
    entry = re.search(r'(?:entry|enter|buy\s*@?|price)[:\s@]*\$?([\d,]+\.?\d*)\s*[-–]\s*\$?([\d,]+\.?\d*)', text, re.IGNORECASE)
    if entry:
        s.entry_low = float(entry.group(1).replace(',', ''))
        s.entry_high = float(entry.group(2).replace(',', ''))
        s.entry_price = (s.entry_low + s.entry_high) / 2
    else:
        entry_single = re.search(r'(?:entry|enter|buy\s*@?|price)[:\s@]*\$?([\d,]+\.?\d*)', text, re.IGNORECASE)
        if entry_single:
            s.entry_price = float(entry_single.group(1).replace(',', ''))

    # ── Take profits ─────────────────────────────
    tps = re.findall(r'(?:tp|target|take\s*profit)\s*[1-3]?\s*[:\s@]*\$?([\d,]+\.?\d*)', text, re.IGNORECASE)
    if len(tps) >= 1: s.tp1 = float(tps[0].replace(',', ''))
    if len(tps) >= 2: s.tp2 = float(tps[1].replace(',', ''))
    if len(tps) >= 3: s.tp3 = float(tps[2].replace(',', ''))

    # ── Stop loss ────────────────────────────────
    sl = re.search(r'(?:sl|stop\s*loss|stop)[:\s@]*\$?([\d,]+\.?\d*)', text, re.IGNORECASE)
    if sl:
        s.stop_loss = float(sl.group(1).replace(',', ''))

    # ── Completeness check ───────────────────────
    has_entry = s.entry_price is not None or (s.entry_low and s.entry_high)
    has_tp = s.tp1 is not None
    has_sl = s.stop_loss is not None
    s.is_complete = bool(s.coin and has_sl)  # min: coin + SL
    
    return s if s.coin else None


# ─────────────────────────────────────────
# PASS 2: Claude AI parser for unstructured text
# ─────────────────────────────────────────
async def ai_parse(text: str, channel: str) -> Optional[ParsedSignal]:
    """Uses Claude Haiku to extract signal from free-form text."""
    if bot_state.ai_mock_mode:
        return _mock_ai_parse(text, channel)
    
    try:
        import anthropic
        client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)

        prompt = f"""Extract a crypto trading signal from this message. Return ONLY valid JSON, no markdown, no explanation.

Message: {text}

Return this exact JSON structure:
{{
  "coin": "BTC",
  "direction": "LONG",
  "entry_price": 67000.0,
  "entry_low": null,
  "entry_high": null,
  "tp1": 68000.0,
  "tp2": 69000.0,
  "tp3": null,
  "stop_loss": 65000.0,
  "leverage": null,
  "market_type": "spot",
  "confidence": 0.85
}}

Rules:
- direction must be LONG or SHORT
- market_type must be "spot" or "futures"  
- confidence is 0.0-1.0 based on how clear the signal is
- use null for missing fields
- if no valid trading signal exists, return {{"coin": null}}"""

        message = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}]
        )
        raw = message.content[0].text.strip()
        data = json.loads(raw)
        
        if not data.get("coin"):
            return None

        s = ParsedSignal(raw_text=text, channel=channel)
        s.coin = data.get("coin", "").upper()
        s.direction = data.get("direction", "LONG").upper()
        s.entry_price = data.get("entry_price")
        s.entry_low = data.get("entry_low")
        s.entry_high = data.get("entry_high")
        s.tp1 = data.get("tp1")
        s.tp2 = data.get("tp2")
        s.tp3 = data.get("tp3")
        s.stop_loss = data.get("stop_loss")
        s.leverage = data.get("leverage")
        s.market_type = data.get("market_type", "spot")
        s.confidence = float(data.get("confidence", 0.5))
        s.is_complete = bool(s.coin and s.stop_loss)
        return s

    except Exception as e:
        bot_state.log(f"⚠️ AI parse error: {str(e)[:60]}", level="warning")
        return None


def _mock_ai_parse(text: str, channel: str) -> Optional[ParsedSignal]:
    """Mock AI parser — returns realistic fake data without API calls."""
    import random
    s = ParsedSignal(raw_text=text, channel=channel)
    
    upper = text.upper()
    common_non_coins = {"THE", "AND", "FOR", "BUY", "SELL", "LONG", "SHORT",
                        "USD", "USDT", "STOP", "TAKE", "ENTRY", "TARGET", "SIGNAL"}
    for m in re.finditer(r'\b([A-Z]{2,10})\b', upper):
        if m.group(1) not in common_non_coins:
            s.coin = m.group(1)
            break
    if not s.coin:
        return None

    s.direction = "SHORT" if any(w in upper for w in ["SHORT", "SELL", "BEARISH"]) else "LONG"
    base = random.uniform(100, 70000)
    s.entry_price = round(base, 2)
    multiplier = 1 if s.direction == "LONG" else -1
    s.tp1 = round(base * (1 + multiplier * 0.03), 2)
    s.tp2 = round(base * (1 + multiplier * 0.06), 2)
    s.stop_loss = round(base * (1 - multiplier * 0.02), 2)
    s.confidence = round(random.uniform(0.55, 0.92), 2)
    s.market_type = "futures" if "FUTURE" in upper or "PERP" in upper else "spot"
    s.leverage = random.choice([2, 3, 5]) if s.market_type == "futures" else None
    s.is_complete = True
    return s


# ─────────────────────────────────────────
# MAIN ENTRY: Two-pass parse
# ─────────────────────────────────────────
async def parse_signal(text: str, channel: str) -> Optional[ParsedSignal]:
    """
    Pass 1: Try regex (fast, free).
    Pass 2: If regex fails or result is incomplete, call AI.
    """
    # Spam filter
    spam_kw = ["presale", "airdrop", "giveaway", "100x guaranteed", "dm me", "join our vip"]
    if any(kw in text.lower() for kw in spam_kw):
        return None
    if len(text.strip()) < 10:
        return None

    result = regex_parse(text, channel)

    # If regex got a complete result, trust it
    if result and result.is_complete and result.tp1:
        bot_state.log(f"📐 Regex parsed: {result.coin} {result.direction}")
        return result

    # Otherwise escalate to AI
    bot_state.log(f"🧠 Escalating to AI parser...")
    ai_result = await ai_parse(text, channel)
    if ai_result:
        return ai_result

    # Fall back to incomplete regex result if we got something
    return result


# GATE 1: The Whitelist (Top 50+ High-Volume Binance Coins)
# The AI must pick a coin from this list, otherwise it is instantly rejected.
KNOWN_TICKERS = {
    "BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "ADA", "AVAX", "LINK", "DOT",
    "MATIC", "TON", "SHIB", "LTC", "BCH", "UNI", "APT", "NEAR", "ARB", "OP",
    "INJ", "RNDR", "SUI", "SEI", "TIA", "WIF", "PEPE", "FTM", "SAND", "MANA",
    "GALA", "FET", "AGIX", "ORDI", "1000SATS", "JUP", "JTO", "PYTH", "ENA",
    "ETHFI", "STRK", "ZETA", "OM", "ONDO", "TRX", "ETC", "FIL", "ATOM", "VET",
    "ICP", "GRT", "STX", "IMX", "LDO", "XLM", "HBAR", "KAS", "MNT", "MKR"
}

async def verify_ticker(coin: str) -> bool:
    """Runs Gate 1 (Whitelist) and Gate 2 (Binance Live Ping)."""
    if not coin:
        return False
        
    # Clean the string (e.g., "INDIA/USDT" -> "INDIA")
    coin_upper = coin.upper().replace("USDT", "").replace("/", "").strip()

    # --- GATE 1: Whitelist Check ---
    if coin_upper not in KNOWN_TICKERS:
        print(f"🛡️ Gate 1 Blocked: '{coin_upper}' is not in the recognized ticker whitelist.")
        return False

    # --- GATE 2: Live Binance Exchange Ping ---
    # Even if it's on the whitelist, we verify Binance is currently trading the USDT pair.
    pair = f"{coin_upper}USDT"
    url = f"https://api.binance.com/api/v3/ticker/price?symbol={pair}"
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, timeout=5.0)
            
            if response.status_code == 200:
                # Binance returned a price! The coin is real and tradable.
                return True
            elif response.status_code == 400:
                print(f"🛡️ Gate 2 Blocked: Binance rejected '{pair}' (Invalid Symbol).")
                return False
            else:
                return False
    except Exception as e:
        print(f"❌ Gate 2 Error: Failed to ping Binance for '{pair}' - {e}")
        return False