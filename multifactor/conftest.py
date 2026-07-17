import os
import pytest


@pytest.fixture(autouse=True)
def cleanup_scheduler_state():
    """自动清理调度器持久化文件，避免测试状态泄漏"""
    last_run_file = os.path.join(
        os.path.dirname(__file__), '.last_rebalance.json'
    )
    if os.path.exists(last_run_file):
        os.remove(last_run_file)
    yield
    if os.path.exists(last_run_file):
        os.remove(last_run_file)


@pytest.fixture(autouse=True)
def cleanup_risk_state_files():
    """每个测试前清理风控/盘中持久化状态文件和 kill switch，避免测试间状态串扰。"""
    files = [
        os.path.join(os.path.dirname(__file__), 'data', 'risk_state.json'),
        os.path.join(os.path.dirname(__file__), 'data', 'intraday_state.json'),
        os.path.join(os.path.dirname(__file__), 'data', 'kill_switch'),
    ]
    for f in files:
        if os.path.exists(f):
            os.remove(f)
    yield
    for f in files:
        if os.path.exists(f):
            os.remove(f)
