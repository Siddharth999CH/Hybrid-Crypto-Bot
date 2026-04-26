import asyncio
from datetime import datetime, timedelta
from typing import Optional
from config import settings
from state import bot_state
from database import Trade, TradeStatus


def get_exchange():
    import ccxt
    exchange = ccxt.binance({
        'apiKey': settings.BINANCE_API_KEY,
        'secret': settings.BINANCE_SECRET,
        'enableRateLimit': True,
        'options': {'defaultType': 'future'}
    })
    if settings.BINANCE_TESTNET:
        exchange.set_sandbox_mode(True)
    return exchange


async def get_current_price(coin: str) -> Optional[float]:
    """Fetch current market price from Binance."""
    try:
        exchange = get_exchange()
        symbol = f"{coin}/USDT"
        ticker = exchange.fetch_ticker(symbol)
        return float(ticker['last'])
    except Exception as e:
        bot_state.log(f"⚠️ Price fetch failed for {coin}: {str(e)[:50]}", level="warning")
        return None


async def check_slippage(coin: str, signal_entry: float) -> tuple[bool, float]:
    """
    Returns (within_threshold, current_price).
    If price moved more than slippage_threshold % from signal entry → skip.
    """
    current = await get_current_price(coin)
    if not current or not signal_entry:
        return True, current or signal_entry

    diff_pct = abs(current - signal_entry) / signal_entry * 100
    within = diff_pct <= bot_state.slippage_threshold
    return within, current


class PaperTradeExecutor:
    """Simulates trade execution using real market prices but no real orders."""

    async def execute(self, trade: Trade, signal: dict) -> bool:
        try:
            current_price = await get_current_price(signal['coin'])
            if not current_price:
                current_price = signal.get('entry_price', 0)

            trade.entry_price = current_price
            trade.status = TradeStatus.OPEN
            trade.opened_at = datetime.utcnow()
            trade.is_paper = True

            bot_state.open_trades_count += 1
            bot_state.log(
                f"📝 PAPER {signal['direction']} {signal['coin']} @ ${current_price:,.2f} "
                f"| Size: ${trade.position_size_usdt:.0f}",
                level="info"
            )
            await bot_state.broadcast("trade_opened", {
                "coin": signal['coin'],
                "direction": signal['direction'],
                "entry": current_price,
                "is_paper": True,
                "trade_id": trade.id
            })
            return True
        except Exception as e:
            bot_state.log(f"❌ Paper execute error: {str(e)[:60]}", level="danger")
            return False

    async def close(self, trade: Trade, close_price: float, reason: str) -> float:
        """Calculate and record P&L for a paper trade."""
        if not trade.entry_price:
            return 0.0

        direction_mult = 1 if trade.direction == "LONG" else -1
        price_diff = (close_price - trade.entry_price) * direction_mult
        pnl_pct = price_diff / trade.entry_price
        pnl_usdt = trade.position_size_usdt * pnl_pct * (trade.leverage or 1)

        trade.pnl_usdt = round(pnl_usdt, 2)
        trade.pnl_pct = round(pnl_pct * 100, 2)
        trade.closed_at = datetime.utcnow()
        trade.status = TradeStatus.TP_HIT if "tp" in reason.lower() else TradeStatus.SL_HIT

        bot_state.open_trades_count = max(0, bot_state.open_trades_count - 1)
        bot_state.add_pnl(pnl_usdt)

        emoji = "🎯" if pnl_usdt > 0 else "🛑"
        bot_state.log(
            f"{emoji} PAPER {reason.upper()} | {trade.coin} | "
            f"{'+ ' if pnl_usdt >= 0 else ''}{pnl_usdt:.2f} USDT ({trade.pnl_pct:+.1f}%)",
            level="success" if pnl_usdt > 0 else "danger"
        )
        await bot_state.broadcast("trade_closed", {
            "coin": trade.coin,
            "pnl_usdt": pnl_usdt,
            "pnl_pct": trade.pnl_pct,
            "reason": reason,
            "is_paper": True
        })
        return pnl_usdt


class LiveTradeExecutor:
    """Executes real orders on Binance via ccxt."""

    async def execute(self, trade: Trade, signal: dict) -> bool:
        try:
            exchange = get_exchange()
            symbol = f"{signal['coin']}/USDT"
            side = "buy" if signal['direction'] == "LONG" else "sell"

            # Set leverage for futures
            if signal.get('market_type') == 'futures' and signal.get('leverage'):
                try:
                    exchange.set_leverage(signal['leverage'], symbol)
                except:
                    pass

            exchange.load_markets()
            current_price = exchange.fetch_ticker(symbol)['last']
            amount = float(exchange.amount_to_precision(
                symbol, trade.position_size_usdt / current_price
            ))

            order = exchange.create_market_order(symbol, side, amount)
            trade.entry_price = current_price
            trade.status = TradeStatus.OPEN
            trade.opened_at = datetime.utcnow()
            trade.is_paper = False
            bot_state.open_trades_count += 1

            # Place TP bracket orders
            exit_side = "sell" if side == "buy" else "buy"
            if signal.get('tp1'):
                try:
                    exchange.create_order(symbol, 'TAKE_PROFIT_MARKET', exit_side, amount,
                                          {'stopPrice': signal['tp1'], 'reduceOnly': True})
                    bot_state.log(f"🎯 TP1 bracket set @ ${signal['tp1']}")
                except Exception as e:
                    bot_state.log(f"⚠️ TP1 order failed: {str(e)[:40]}", level="warning")

            # Place SL bracket order
            if signal.get('stop_loss'):
                try:
                    exchange.create_order(symbol, 'STOP_MARKET', exit_side, amount,
                                          {'stopPrice': signal['stop_loss'], 'reduceOnly': True})
                    bot_state.log(f"🛡️ SL bracket set @ ${signal['stop_loss']}")
                except Exception as e:
                    bot_state.log(f"⚠️ SL order failed: {str(e)[:40]}", level="warning")

            bot_state.log(
                f"⚡ LIVE {signal['direction']} {signal['coin']} @ ${current_price:,.2f} | "
                f"Order: {order['id']}",
                level="success"
            )
            await bot_state.broadcast("trade_opened", {
                "coin": signal['coin'],
                "direction": signal['direction'],
                "entry": current_price,
                "is_paper": False
            })
            return True

        except Exception as e:
            bot_state.log(f"❌ Live execute error: {str(e)[:80]}", level="danger")
            return False


async def execute_trade(trade: Trade, signal: dict) -> bool:
    """Route to paper or live executor based on current mode."""
    can_trade, reason = bot_state.can_trade(signal['coin'])
    if not can_trade:
        bot_state.log(f"🚫 Trade blocked: {reason}", level="warning")
        return False

    # Slippage check
    if signal.get('entry_price'):
        within, current = await check_slippage(signal['coin'], signal['entry_price'])
        if not within:
            bot_state.log(
                f"⏭️ SKIPPED: {signal['coin']} price moved too far "
                f"(signal: ${signal['entry_price']:,.0f}, now: ${current:,.0f})",
                level="warning"
            )
            trade.status = TradeStatus.SKIPPED_SLIPPAGE
            return False

    if bot_state.paper_mode:
        executor = PaperTradeExecutor()
    else:
        executor = LiveTradeExecutor()

    return await executor.execute(trade, signal)
