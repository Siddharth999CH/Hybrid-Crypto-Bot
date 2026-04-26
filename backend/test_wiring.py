import asyncio
import json
from database import init_db, AsyncSessionLocal, MarketContext
from sqlalchemy import select
from api_worker import ingest_hyperliquid_meta
from signal_parser import verify_ticker, ParsedSignal
from analyzer import score_signal
from state import bot_state
from config import settings

async def run_diagnostics():
    print("🚀 IGNITING DIAGNOSTIC SEQUENCE...\n")
    await init_db()

    # --- TEST 1: DATABASE SYNCHRONIZATION ---
    print("=== TEST 1: HYPERLIQUID DEX INGESTION ===")
    async with AsyncSessionLocal() as db:
        await ingest_hyperliquid_meta(db)
        
        # Verify it saved by querying BTC
        stmt = select(MarketContext).where(
            MarketContext.coin == "BTC",
            MarketContext.data_type == "DEX_Metrics"
        )
        result = await db.execute(stmt)
        btc_context = result.scalar_one_or_none()
        
        if btc_context:
            print("✅ SUCCESS: MarketContext populated.")
            print(f"📊 BTC Memory Payload: {json.dumps(btc_context.payload, indent=2)}\n")
        else:
            print("❌ FAILED: Could not retrieve BTC DEX data from database.\n")


    # --- TEST 2: THE SHIELD (GATES 1 & 2) ---
    print("=== TEST 2: CHAOS TEST (FAKE TICKER) ===")
    fake_coin = "INDIA"
    print(f"🛡️ Testing Ticker: '{fake_coin}'")
    is_valid = await verify_ticker(fake_coin)
    
    if not is_valid:
        print(f"✅ SUCCESS: Shield successfully blocked '{fake_coin}'.\n")
    else:
        print(f"❌ FAILED: Shield allowed a fake ticker through!\n")


    # --- TEST 3: AI REASONING AUDIT (UPDATED FOR DYNAMIC LLMs) ---
    print("=== TEST 3: AI CONFLUENCE ENGINE ===")
    if bot_state.ai_mock_mode:
        print("⚠️ WARNING: AI_MOCK_MODE is True. Disabling for this test to hit the LLM API...")
        bot_state.ai_mock_mode = False
        
    if not settings.LLM_API_KEY:
        print("❌ FAILED: No LLM_API_KEY found. Go to the Settings UI, enter an API key, click 'Save AI Settings', and try again.")
        return

    print(f"🔌 Routing to Provider: {settings.LLM_PROVIDER.upper()} | Model: {settings.LLM_MODEL_NAME}")

    # Create a mock valid signal
    test_signal = ParsedSignal(
        coin="BTC",
        direction="LONG",
        entry_price=65000.0,
        tp1=68000.0,
        stop_loss=63000.0,
        leverage=10,
        market_type="futures",
        channel="Diagnostic_Test",
        raw_text="Test signal for BTC Long. Targeting 68k.",
        is_complete=True
    )
    
    print(f"🧠 Injecting {test_signal.direction} {test_signal.coin} into Analyzer...")
    # This will trigger score_signal, which pulls the DB context we just injected in Test 1
    confidence = await score_signal(test_signal, channel_trust=0.8)
    
    print(f"\n✅ SUCCESS: AI Audit Complete.")
    print(f"Final Confidence Score: {confidence}")
    print("Check the logs above for the '🧠 AI Reasoning' printout to verify DEX context was used.")

if __name__ == "__main__":
    asyncio.run(run_diagnostics())