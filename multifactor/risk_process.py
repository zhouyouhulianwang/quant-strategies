"""
盘中风控独立进程 (Risk Process)

以独立 OS 进程运行，与主交易进程解耦。即使主交易线程被阻塞或崩溃，
本进程仍可监控 VIX、日内回撤、个股暴跌并触发紧急平仓。

运行方式：
    ALPACA_API_KEY=xxx ALPACA_API_SECRET=yyy ALPACA_BASE_URL=... \
        python risk_process.py --paper --check-interval 30

CLI 参数:
    --paper          使用 Alpaca Paper 交易（默认）
    --live           使用 Alpaca Live 实盘交易
    --mock           使用模拟执行器（不连接真实 API，仅用于测试）
    --check-interval 监控检查间隔（秒）
    --config-path    配置文件路径（JSON 格式，可选）

Systemd 服务示例见本文件末尾 docstring 或 RISK_RUNBOOK.md。
"""

import argparse
import json
import logging
import os
import signal
import sys
import threading
import time
from datetime import datetime


logger = logging.getLogger(__name__)

from version import get_version

# 复用现有模块，不引入新依赖
from alpaca_executor import AlpacaExecutor
from risk_monitor import RiskMonitor
from intraday_monitor import IntradayMonitor
from config import V14StrategyConfig, get_config, set_config


def parse_args(argv=None):
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(
        description='Multifactor Intraday Risk Process'
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        '--paper', action='store_true', default=None,
        help='Use Alpaca Paper trading (default)'
    )
    mode.add_argument(
        '--live', action='store_true', default=None,
        help='Use Alpaca Live trading'
    )
    parser.add_argument(
        '--mock', action='store_true', default=False,
        help='Use mock executor (no real API connection, for testing only)'
    )
    parser.add_argument(
        '--check-interval', type=int, default=None,
        help='Monitoring check interval (seconds)'
    )
    parser.add_argument(
        '--config-path', type=str, default=None,
        help='Config file path (JSON format)'
    )
    parser.add_argument(
        '--version', action='version', version=f'%(prog)s {get_version()}',
        help='Show version and exit'
    )
    return parser.parse_args(argv)


class RiskProcess:
    """
    风控独立进程控制器。

    参数:
        args: argparse.Namespace，可选
        executor_factory: callable(paper) -> executor，可选，用于测试注入
        monitor_factory: callable(executor, config) -> (RiskMonitor, IntradayMonitor)，可选
    """

    def __init__(self, args=None, executor_factory=None, monitor_factory=None):
        self.args = args or parse_args()
        self.executor_factory = executor_factory or self._default_executor_factory
        self.monitor_factory = monitor_factory or self._default_monitor_factory
        self.shutdown_event = threading.Event()
        self.executor = None
        self.risk_monitor = None
        self.intraday_monitor = None
        self._setup_signal_handlers()

    def _setup_signal_handlers(self):
        """注册 SIGTERM / SIGINT 信号处理器，实现优雅退出。"""
        def _on_signal(signum, frame):
            signame = signal.Signals(signum).name
            logger.info(f"Received {signame}, starting graceful shutdown...")
            self.shutdown_event.set()

        signal.signal(signal.SIGTERM, _on_signal)
        signal.signal(signal.SIGINT, _on_signal)

    def _load_config(self):
        """加载配置。优先使用 --config-path，否则使用全局默认配置。"""
        if self.args.config_path:
            with open(self.args.config_path, 'r') as f:
                data = json.load(f)
            config = V14StrategyConfig(**data)
            set_config(config)
        else:
            config = get_config()

        if self.args.check_interval is not None:
            config.trading.check_interval = self.args.check_interval

        return config

    def _default_executor_factory(self, paper):
        """默认 executor 工厂：从环境变量读取凭证并创建 AlpacaExecutor。"""
        api_key = os.getenv('ALPACA_API_KEY')
        api_secret = os.getenv('ALPACA_API_SECRET')
        base_url = os.getenv('ALPACA_BASE_URL')
        if not base_url:
            base_url = 'https://paper-api.alpaca.markets' if paper else 'https://api.alpaca.markets'

        return AlpacaExecutor(
            api_key=api_key,
            api_secret=api_secret,
            base_url=base_url,
            paper=paper,
            mock=self.args.mock,
        )

    def _default_monitor_factory(self, executor, config):
        """默认监控器工厂：创建 RiskMonitor 和 IntradayMonitor。"""
        risk_monitor = RiskMonitor(
            max_drawdown_limit=config.risk.max_drawdown_limit,
            max_position_pct=config.risk.max_position_pct,
            max_sector_pct=0.30,
            daily_loss_limit=0.03,
            vix_pause_level=config.risk.vix_panic_threshold,
        )
        intraday_monitor = IntradayMonitor(
            executor=executor,
            risk_monitor=risk_monitor,
            check_interval=config.trading.check_interval,
            vix_emergency_level=config.risk.vix_panic_threshold,
            max_intraday_dd=config.risk.max_intraday_dd,
            single_stock_limit=config.risk.single_stock_limit,
            max_total_drawdown=config.risk.max_drawdown_limit,
        )
        return risk_monitor, intraday_monitor

    def _resolve_paper_mode(self):
        """解析 paper/live 模式。"""
        if self.args.live:
            return False
        if self.args.paper:
            return True
        return True

    def initialize(self):
        """初始化 executor 与监控器。"""
        config = self._load_config()
        paper = self._resolve_paper_mode()
        self.executor = self.executor_factory(paper)
        self.risk_monitor, self.intraday_monitor = self.monitor_factory(
            self.executor, config
        )
        logger.info(
            f"Risk process initialized: paper={paper}, mock={self.args.mock}, "
            f"check_interval={config.trading.check_interval}s"
        )

    def _print_status(self):
        """打印当前风控状态日志。"""
        if not self.intraday_monitor or not self.risk_monitor:
            return
        status = self.intraday_monitor.get_status()
        risk_summary = self.risk_monitor.get_risk_summary()
        logger.info(
            f"Risk status | monitoring={status['monitoring']} "
            f"risk_level={risk_summary['risk_level']} "
            f"trading_halted={risk_summary['trading_halted']} "
            f"alerts={risk_summary['total_alerts']} "
            f"last_check={status['last_check']}"
        )

    def run(self):
        """启动风控进程主循环。"""
        try:
            self.initialize()
            # 使用非 daemon 方式运行监控循环，确保进程持续运行
            self.intraday_monitor.start(daemon=False)
            logger.info("[START] Risk monitor loop started (non-daemon)")

            while not self.shutdown_event.is_set():
                self._print_status()
                self.shutdown_event.wait(self.intraday_monitor.check_interval)

            logger.info("[STOP] Stopping monitor...")
            self.intraday_monitor.stop()
            logger.info("[OK] Risk process exited")
            return 0
        except Exception as e:
            logger.exception(f"Risk process exception: {e}")
            return 1


def main(argv=None):
    """入口函数。"""
    args = parse_args(argv)
    process = RiskProcess(args)
    return process.run()


if __name__ == '__main__':
    sys.exit(main())


# ============================================================
# Systemd 服务示例
# ============================================================
"""
创建 /etc/systemd/system/multifactor-risk.service：

---
[Unit]
Description=Multifactor Intraday Risk Process
After=network.target

[Service]
Type=simple
User=pc
Group=pc
WorkingDirectory=/home/pc/.openclaw/workspace/multifactor
Environment="ALPACA_API_KEY=your_api_key"
Environment="ALPACA_API_SECRET=your_api_secret"
Environment="ALPACA_BASE_URL=https://paper-api.alpaca.markets"
ExecStart=/home/pc/.openclaw/workspace/multifactor/.venv/bin/python -m risk_process --paper --check-interval 30
ExecStop=/bin/kill -SIGTERM $MAINPID
TimeoutStopSec=30
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
---

然后执行：
    sudo systemctl daemon-reload
    sudo systemctl enable multifactor-risk.service
    sudo systemctl start multifactor-risk.service
    sudo systemctl status multifactor-risk.service

查看日志：
    journalctl -u multifactor-risk.service -f

停止服务：
    sudo systemctl stop multifactor-risk.service

注意：
- 生产环境建议使用 systemd 的 EnvironmentFile 加载 /etc/multifactor/env 而不是直接写入 Key。
- 使用 --live 时，务必确认已配置 LIVE API 凭证并启用二次确认（ALPACA_LIVE_CONFIRMED=1）。
"""
