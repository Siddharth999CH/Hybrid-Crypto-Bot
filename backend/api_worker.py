import asyncio
import httpx
import json
from datetime import datetime
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from database import AsyncSessionLocal, ApiSource, MarketContext
from state import bot_state

# We use httpx for async HTTP requests
async def fetch_api_data(client: httpx.AsyncClient, url: str):
    """Fetches data from an API endpoint."""
    try:
        response = await client.get(url, timeout=10.0)
        response.raise_for_status()
        
        # Hyperliquid returns a list, CoinGecko returns a dict. 
        # We need to handle both gracefully.
        try:
            return response.json()
        except json.JSONDecodeError:
            return {"raw_text": response.text}
            
    except Exception as e:
        print(f"❌ API Error fetching {url}: {e}")
        return None

async def ingest_hyperliquid_meta(db: AsyncSession):
    """
    Specifically fetches Hyperliquid meta data (funding rates, open interest)
    and saves it to the MarketContext JSON memory bank.
    """
    url = "https://api.hyperliquid.xyz/info"
    payload = {"type": "metaAndAssetCtxs"}
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=payload, timeout=10.0)
            response.raise_for_status()
            data = response.json()
            
            # Hyperliquid returns two lists:
            # data[0]['universe'] contains the coin names (BTC, ETH, etc.)
            # data[1] contains the actual metrics (funding, open interest)
            
            universe = data[0].get("universe", [])
            contexts = data[1]
            
            if len(universe) != len(contexts):
                print("⚠️ Hyperliquid data length mismatch.")
                return

            print(f"🔄 Ingesting DEX Data for {len(universe)} coins...")
            
            for i, coin_info in enumerate(universe):
                coin_name = coin_info.get("name")
                metrics = contexts[i]
                
                # Format the payload for our AI memory bank
                ai_payload = {
                    "source": "Hyperliquid DEX",
                    "funding_rate": metrics.get("funding"),
                    "open_interest": metrics.get("openInterest"),
                    "predicted_funding": metrics.get("predictedFunding"),
                    "mark_price": metrics.get("markPx")
                }
                
                # Check if we already have context for this coin
                result = await db.execute(
                    select(MarketContext).where(
                        MarketContext.coin == coin_name,
                        MarketContext.data_type == "DEX_Metrics"
                    )
                )
                existing_context = result.scalar_one_or_none()
                
                if existing_context:
                    existing_context.payload = ai_payload
                    existing_context.updated_at = datetime.utcnow()
                else:
                    new_context = MarketContext(
                        coin=coin_name,
                        data_type="DEX_Metrics",
                        payload=ai_payload
                    )
                    db.add(new_context)
                    
            await db.commit()
            print("✅ Hyperliquid DEX Data mapped to memory.")
            
    except Exception as e:
        print(f"❌ Failed to ingest Hyperliquid data: {e}")

async def run_worker():
    """The main loop that runs forever in the background."""
    print("🤖 API Worker started. Ingesting market context...")
    
    while True:
        try:
            async with AsyncSessionLocal() as db:
                # 1. Fetch data from any custom URLs added via the React UI
                result = await db.execute(select(ApiSource).where(ApiSource.is_active == True))
                active_sources = result.scalars().all()
                
                async with httpx.AsyncClient() as client:
                    for source in active_sources:
                        data = await fetch_api_data(client, source.endpoint_url)
                        if data:
                            # Save custom API data (like the CoinGecko ping)
                            context = MarketContext(
                                coin=None, # Macro data
                                data_type=f"Custom_API_{source.name}",
                                payload=data
                            )
                            db.add(context)
                            print(f"✅ Ingested custom API: {source.name}")
                
                await db.commit()
                
                # 2. Hardcoded High-Value Ingestion (Hyperliquid)
                await ingest_hyperliquid_meta(db)
                
        except Exception as e:
             print(f"❌ API Worker Critical Error: {e}")
             
        # Sleep for 5 minutes before fetching again
        print("💤 API Worker sleeping for 5 minutes...")
        await asyncio.sleep(300)

if __name__ == "__main__":
    asyncio.run(run_worker())