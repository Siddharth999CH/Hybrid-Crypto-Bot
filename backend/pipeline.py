import asyncio
from datetime import datetime
from state import bot_state
from analyzer import analyze_sentiment_target

async def process_sentiment_target(target_coin: str, bucket_data: dict):
    """
    Consumes the flushed Phase A data, runs Phase B analysis, 
    and pushes to the Human-in-the-Loop queue.
    """
    bot_state.log(f"⚡ Lock & Flush triggered for {target_coin}. Routing to Quant Engine.")
    
    trade_payload = await analyze_sentiment_target(
        coin=target_coin,
        raw_messages=bucket_data["messages"],
        portfolio_balance=bot_state.portfolio_balance
    )

    if trade_payload:
        # Generate a unique integer ID for the React UI mapping
        signal_id = int(datetime.now().timestamp() * 1000) 
        trade_payload["signal_id"] = signal_id  # Inject ID so React can map it
        
        # Inject into global state
        bot_state.pending_approvals[signal_id] = trade_payload
        
        # Alert connected UI clients
        bot_state.log(f"🔔 Pushing {target_coin} to Approval Queue.")
        await bot_state.broadcast("approval_requested", trade_payload)
    else:
        bot_state.log(f"🛑 Analysis rejected {target_coin}. Awaiting next cycle.")


async def run_pipeline(queue: asyncio.Queue):
    """Background task to consume the raw signal queue from Phase A."""
    bot_state.log("🚀 Pipeline (Phase B) Started.")
    while True:
        try:
            # The scraper queue yields a tuple: (target_coin, bucket_data)
            target_coin, bucket_data = await queue.get()
            
            # Check if we are allowed to trade this coin
            can_trade, reason = bot_state.can_trade(target_coin)
            if not can_trade:
                bot_state.log(f"⏭️ Skipping {target_coin}: {reason}")
                queue.task_done()
                continue
                
            await process_sentiment_target(target_coin, bucket_data)
            queue.task_done()
            
        except Exception as e:
            bot_state.log(f"⚠️ Pipeline Error: {e}", level="warning")
            await asyncio.sleep(5) # Prevent tight loop failure