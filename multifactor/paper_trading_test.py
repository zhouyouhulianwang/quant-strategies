"""
Alpaca Paper Trading 连接/小单验证测试
- 只使用环境变量，不硬编码密钥
- 连接账户、查询市场状态、下 1 股小单、检查状态、撤单/平仓
"""
import os
import time
import logging
from datetime import datetime
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest, GetOrdersRequest
from alpaca.trading.enums import OrderSide, TimeInForce, QueryOrderStatus
from alpaca.common.exceptions import APIError
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockLatestTradeRequest

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger('paper_test')


def main():
    # 1. 读取环境变量
    api_key = os.environ.get('ALPACA_API_KEY')
    api_secret = os.environ.get('ALPACA_API_SECRET')
    base_url = os.environ.get('ALPACA_BASE_URL', 'https://paper-api.alpaca.markets')

    if not api_key or not api_secret:
        logger.error('ALPACA_API_KEY / ALPACA_API_SECRET 未设置')
        return 1

    paper = 'paper' in base_url.lower()
    logger.info(f'base_url={base_url} paper={paper}')

    # 2. 连接 TradingClient
    try:
        trading_client = TradingClient(api_key, api_secret, paper=paper)
        account = trading_client.get_account()
        logger.info(f'账户连接成功')
        logger.info(f'  account_id={account.id}')
        logger.info(f'  cash={account.cash}')
        logger.info(f'  portfolio_value={account.portfolio_value}')
        logger.info(f'  equity={account.equity}')
        logger.info(f'  buying_power={account.buying_power}')
    except APIError as e:
        logger.error(f'连接账户失败: {e}')
        return 1
    except Exception as e:
        logger.error(f'连接账户异常: {e}')
        return 1

    # 3. 获取市场时钟
    try:
        clock = trading_client.get_clock()
        logger.info(f'市场时钟: is_open={clock.is_open}, next_open={clock.next_open}, next_close={clock.next_close}')
    except Exception as e:
        logger.warning(f'获取市场时钟失败: {e}')
        clock = None

    # 4. 获取最新价格（用于日志和限价单参考）
    symbol = 'AAPL'
    try:
        data_client = StockHistoricalDataClient(api_key, api_secret)
        latest = data_client.get_stock_latest_trade(StockLatestTradeRequest(symbol_or_symbols=symbol))
        last_price = latest[symbol].price if symbol in latest else None
        logger.info(f'{symbol} 最新成交价: {last_price}')
    except Exception as e:
        logger.warning(f'获取 {symbol} 最新价格失败: {e}')
        last_price = None

    # 5. 下一个小单：1 股 AAPL 市价单
    order_id = None
    try:
        order_req = MarketOrderRequest(
            symbol=symbol,
            qty=1,
            side=OrderSide.BUY,
            time_in_force=TimeInForce.DAY,
        )
        order = trading_client.submit_order(order_req)
        order_id = order.id
        logger.info(f'已提交订单: id={order_id}, symbol={order.symbol}, qty={order.qty}, side={order.side}, status={order.status}')
    except APIError as e:
        logger.error(f'提交订单失败: {e}')
        return 1
    except Exception as e:
        logger.error(f'提交订单异常: {e}')
        return 1

    # 6. 等待并检查订单状态
    time.sleep(5)
    try:
        order = trading_client.get_order_by_id(order_id)
        logger.info(f'订单状态: id={order.id}, status={order.status}, filled_qty={order.filled_qty}, filled_avg_price={order.filled_avg_price}')
    except Exception as e:
        logger.error(f'查询订单失败: {e}')

    # 7. 如果未完全成交，撤单
    if order and order.status not in ('filled', 'canceled', 'closed', 'expired'):
        try:
            trading_client.cancel_order_by_id(order_id)
            logger.info(f'已撤单: {order_id}')
        except Exception as e:
            logger.warning(f'撤单失败或订单已成交: {e}')

    # 8. 查询持仓
    try:
        positions = trading_client.get_all_positions()
        logger.info(f'当前持仓数量: {len(positions)}')
        for p in positions:
            logger.info(f'  {p.symbol}: qty={p.qty}, market_value={p.market_value}, avg_entry_price={p.avg_entry_price}')
    except Exception as e:
        logger.warning(f'查询持仓失败: {e}')

    # 9. 如果仍有 AAPL 持仓，平仓
    try:
        aapl_pos = next((p for p in positions if p.symbol == symbol), None)
        if aapl_pos and float(aapl_pos.qty) > 0:
            sell_req = MarketOrderRequest(
                symbol=symbol,
                qty=int(float(aapl_pos.qty)),
                side=OrderSide.SELL,
                time_in_force=TimeInForce.DAY,
            )
            sell_order = trading_client.submit_order(sell_req)
            logger.info(f'已提交平仓单: id={sell_order.id}, symbol={sell_order.symbol}, qty={sell_order.qty}')
    except Exception as e:
        logger.warning(f'平仓失败: {e}')

    logger.info('Paper Trading 测试完成')
    return 0


if __name__ == '__main__':
    exit(main())
