import asyncio
import aiohttp
from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from database import MarketContext, AsyncSessionLocal
from state import bot_state

async def ingest_hyperliquid_meta(db: AsyncSession, session: aiohttp.ClientSession):
    """Fetches Funding Rates and Open Interest for all coins on Hyperliquid."""
    try:
        headers = {"Content-Type": "application/json"}
        payload = {"type": "metaAndAssetCtxs"}
        
        async with session.post("https://api.hyperliquid.xyz/info", json=payload, headers=headers) as resp:
            data = await resp.json()
            
            if not isinstance(data, list) or len(data) < 2:
                return

            universe = data[0].get("universe", [])
            asset_ctxs = data[1]

            for idx, asset_info in enumerate(universe):
                coin = asset_info.get("name")
                if not coin or idx >= len(asset_ctxs):
                    continue

                ctx = asset_ctxs[idx]
                
                # Format the DEX data payload
                dex_payload = {
                    "source": "Hyperliquid DEX",
                    "funding_rate": ctx.get("funding"),
                    "open_interest": ctx.get("openInterest"),
                    "predicted_funding": ctx.get("predictedFunding"),
                    "mark_price": ctx.get("markPx")
                }

                # Upsert into MarketContext table
                stmt = select(MarketContext).where(
                    MarketContext.coin == coin,
                    MarketContext.data_type == "DEX_Metrics"
                )
                result = await db.execute(stmt)
                context = result.scalar_one_or_none()

                if context:
                    context.payload = dex_payload
                    context.last_updated = datetime.now(timezone.utc)
                else:
                    context = MarketContext(
                        coin=coin,
                        data_type="DEX_Metrics",
                        payload=dex_payload
                    )
                    db.add(context)
            
            await db.commit()
            bot_state.log("🔄 Hyperliquid DEX Data mapped to memory.")

    except Exception as e:
        bot_state.log(f"⚠️ Failed to ingest Hyperliquid Data: {e}", level="warning")


async def ingest_fear_and_greed(db: AsyncSession, session: aiohttp.ClientSession):
    """Fetches the global crypto Fear & Greed Index (0-100)."""
    try:
        async with session.get("https://api.alternative.me/fng/?limit=1") as resp:
            data = await resp.json()
            if not data or 'data' not in data: return
            
            fgi_data = data['data'][0]
            payload = {
                "source": "Alternative.me FGI",
                "value": int(fgi_data['value']),
                "classification": fgi_data['value_classification']
            }

            stmt = select(MarketContext).where(
                MarketContext.coin == "GLOBAL",
                MarketContext.data_type == "Fear_And_Greed"
            )
            result = await db.execute(stmt)
            context = result.scalar_one_or_none()

            if context:
                context.payload = payload
                context.last_updated = datetime.now(timezone.utc)
            else:
                context = MarketContext(
                    coin="GLOBAL",
                    data_type="Fear_And_Greed",
                    payload=payload
                )
                db.add(context)
            await db.commit()
            bot_state.log(f"🧠 Macro Sentiment Updated: {payload['classification']} ({payload['value']}/100)")
    except Exception as e:
        bot_state.log(f"⚠️ Failed to ingest Fear & Greed: {e}", level="warning")


async def ingest_binance_ls_ratio(db: AsyncSession, session: aiohttp.ClientSession):
    """Fetches what the top 20% most profitable Binance accounts are doing with BTC."""
    symbol = "BTCUSDT"
    try:
        url = f"https://fapi.binance.com/futures/data/topLongShortAccountRatio?symbol={symbol}&period=5m"
        async with session.get(url) as resp:
            data = await resp.json()
            if not data or len(data) == 0: return

            latest = data[-1]
            payload = {
                "source": "Binance Top Traders (Whales)",
                "long_ratio_pct": float(latest['longAccount']) * 100,
                "short_ratio_pct": float(latest['shortAccount']) * 100,
                "long_short_ratio": float(latest['longShortRatio'])
            }

            stmt = select(MarketContext).where(
                MarketContext.coin == "BTC",
                MarketContext.data_type == "Whale_L_S_Ratio"
            )
            result = await db.execute(stmt)
            context = result.scalar_one_or_none()

            if context:
                context.payload = payload
                context.last_updated = datetime.now(timezone.utc)
            else:
                context = MarketContext(
                    coin="BTC",
                    data_type="Whale_L_S_Ratio",
                    payload=payload
                )
                db.add(context)
            await db.commit()
            bot_state.log(f"🐋 Whale Positioning Updated: {payload['long_ratio_pct']:.1f}% LONG on BTC.")
    except Exception as e:
        bot_state.log(f"⚠️ Failed to ingest Whale Ratio: {e}", level="warning")


async def run_api_worker_loop():
    """Main background loop that runs every 5 minutes."""
    bot_state.log("📡 Starting Data Ingestion Worker...")
    
    while True:
        try:
            async with AsyncSessionLocal() as db:
                async with aiohttp.ClientSession() as session:
                    # Run all three data ingestion tasks concurrently
                    await asyncio.gather(
                        ingest_hyperliquid_meta(db, session),
                        ingest_fear_and_greed(db, session),
                        ingest_binance_ls_ratio(db, session)
                    )
        except Exception as e:
            bot_state.log(f"⚠️ API Worker Loop Error: {e}", level="error")
            
        # Sleep for 5 minutes before fetching fresh data
        await asyncio.sleep(300)

if __name__ == "__main__":
    # For standalone testing of the worker
    asyncio.run(run_api_worker_loop())