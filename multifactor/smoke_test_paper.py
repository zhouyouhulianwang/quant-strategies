"""可选的纸交易连接性 smoke test。

默认不运行：仅当同时提供 Alpaca 凭证并设置 RUN_PAPER_SMOKE=1 时才会执行。
执行逻辑：连接账户、获取最新行情、提交一个 1 股限价/市价单并立即取消，
用于验证 Alpaca paper 环境的完整链路。

手动触发：
    RUN_PAPER_SMOKE=1 ALPACA_API_KEY=xxx ALPACA_API_SECRET=yyy \
        python -m pytest smoke_test_paper.py -v
"""
import os
import time
import pytest

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import LimitOrderRequest, GetOrdersRequest
from alpaca.trading.enums import OrderSide, TimeInForce, QueryOrderStatus
from alpaca.common.exceptions import APIError
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockLatestTradeRequest


CREDS_AVAILABLE = bool(
    os.environ.get('ALPACA_API_KEY') and os.environ.get('ALPACA_API_SECRET')
)
RUN_ENABLED = os.environ.get('RUN_PAPER_SMOKE', '').lower() in ('1', 'true', 'yes')


@pytest.mark.skipif(
    not (CREDS_AVAILABLE and RUN_ENABLED),
    reason='Set RUN_PAPER_SMOKE=1 and provide ALPACA_API_KEY/ALPACA_API_SECRET to run live paper smoke test'
)
class TestPaperSmokeConnectivity:
    """真实 Alpaca paper 连接性验证（默认跳过）。"""

    @pytest.fixture(scope='class')
    def trading_client(self):
        """创建并返回真实 Alpaca paper TradingClient。"""
        return TradingClient(
            os.environ['ALPACA_API_KEY'],
            os.environ['ALPACA_API_SECRET'],
            paper=True,
        )

    def test_account_connectivity(self, trading_client):
        """验证能正常读取账户信息。"""
        account = trading_client.get_account()
        assert account is not None
        assert account.status == 'ACTIVE'
        assert float(account.equity) >= 0
        assert float(account.buying_power) >= 0

    def test_latest_quote_connectivity(self):
        """验证能获取行情数据。"""
        data_client = StockHistoricalDataClient(
            os.environ['ALPACA_API_KEY'],
            os.environ['ALPACA_API_SECRET'],
        )
        latest = data_client.get_stock_latest_trade(StockLatestTradeRequest(symbol_or_symbols='SPY'))
        assert 'SPY' in latest
        assert latest['SPY'].price > 0

    def test_submit_and_cancel_order(self, trading_client):
        """提交并立即取消一个小额订单，验证下单与撤单能力。"""
        symbol = 'SPY'
        qty = 1

        # 使用限价单避免立即成交，便于撤单验证
        order_req = LimitOrderRequest(
            symbol=symbol,
            qty=qty,
            side=OrderSide.BUY,
            time_in_force=TimeInForce.DAY,
            limit_price=1.0,  # 极低限价，确保不会成交
        )
        order = trading_client.submit_order(order_req)
        assert order is not None
        assert order.symbol == symbol
        order_id = order.id
        assert order_id

        try:
            # 等待订单状态同步
            time.sleep(2)
            fetched = trading_client.get_order_by_id(order_id)
            assert fetched.id == order_id

            # 撤单
            trading_client.cancel_order_by_id(order_id)
            time.sleep(2)
            fetched = trading_client.get_order_by_id(order_id)
            assert fetched.status in ('canceled', 'expired', 'closed', 'filled')
        except APIError as e:
            # 若订单已不存在或已取消，视为可接受
            if 'order does not exist' not in str(e).lower():
                raise
        finally:
            # 兜底：再次尝试撤单
            try:
                trading_client.cancel_order_by_id(order_id)
            except APIError:
                pass

        # 验证没有遗留订单
        open_orders = trading_client.get_orders(
            filter=GetOrdersRequest(status=QueryOrderStatus.OPEN)
        )
        assert order_id not in {o.id for o in open_orders}
