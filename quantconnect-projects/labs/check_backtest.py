import sys
sys.path.insert(0, '/home/pc/.local/lib/python3.12/site-packages')

from lean.components.util.http_client import HTTPClient
from lean.components.util.logger import Logger
from lean.components.api.api_client import APIClient
from lean.components.api.backtest_client import BacktestClient
import time

class SimpleLogger:
    def debug(self, msg):
        pass
    def debug_logging_enabled(self):
        return False

logger = SimpleLogger()
http_client = HTTPClient(logger)

user_id = "515996"
api_token = "2409bf6b14feaf8a29481c3a83d0d1ae0110378ef98bcabe17c6a93427d3343e"
project_id = 34012459

api = APIClient(logger, http_client, user_id, api_token)

backtest_id = "d7c97677d93d63994cbe64c343a126ef"

bt = api.backtests.get(project_id, backtest_id)
print(f"Status: '{bt.status}'")
print(f"Completed: {bt.completed}")
print(f"Error: {bt.error}")
print(f"Progress: {bt.progress}")

print("\n=== STATISTICS ===")
if bt.statistics:
    for key, value in bt.statistics.items():
        print(f"  {key}: {value}")
else:
    print("No statistics")

print("\n=== RUNTIME STATISTICS ===")
if bt.runtimeStatistics:
    for key, value in bt.runtimeStatistics.items():
        print(f"  {key}: {value}")
else:
    print("No runtime statistics")

print("\n=== RAW BACKTEST DATA ===")
import json
# Try to get more details
try:
    data = bt.model_dump()
    print(json.dumps(data, indent=2, default=str)[:3000])
except Exception as e:
    print(f"Error dumping: {e}")
