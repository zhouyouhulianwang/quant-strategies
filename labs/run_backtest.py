import sys
sys.path.insert(0, '/home/pc/.local/lib/python3.12/site-packages')

from lean.components.util.http_client import HTTPClient
from lean.components.util.logger import Logger
from lean.components.api.api_client import APIClient
from lean.components.api.backtest_client import BacktestClient
from lean.components.api.file_client import FileClient
from lean.components.api.compile_client import CompileClient
from lean.components.api.project_client import ProjectClient
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

compile_id = "2a6656dd4c5bb77bd353f00d3ce9922f-5a4a6a94d20b0a0775c0067f4ec253c0"

# Wait for compilation
print("Waiting for compilation...")
for i in range(60):
    time.sleep(3)
    status = api.compiles.get(project_id, compile_id)
    print(f"  State: {status.state}")
    if status.state == "BuildSuccess":
        print("Compilation successful!")
        
        # Run backtest
        print("\nStarting backtest...")
        backtest = api.backtests.create(project_id, compile_id, "vix_tp1.5_sl1.5")
        print(f"Backtest ID: {backtest.backtestId}")
        backtest_id = backtest.backtestId
        
        # Wait for backtest
        print("\nWaiting for backtest...")
        for j in range(120):
            time.sleep(5)
            bt = api.backtests.get(project_id, backtest_id)
            print(f"  Progress: {bt.progress}%, Status: {bt.status}")
            if bt.status in ["Completed", "Failed", "Cancelled"]:
                print("\n=== BACKTEST COMPLETE ===")
                print(f"Status: {bt.status}")
                
                # Print statistics
                if bt.statistics:
                    stats = bt.statistics
                    print(f"\n=== STATISTICS ===")
                    for key, value in stats.items():
                        print(f"  {key}: {value}")
                else:
                    print("No statistics available")
                
                # Print alpha statistics if available
                if bt.alpha and bt.alpha.alpha_statistics:
                    alpha_stats = bt.alpha.alpha_statistics
                    print(f"\n=== ALPHA STATS ===")
                    for key, value in alpha_stats.items():
                        print(f"  {key}: {value}")
                
                break
        break
        
    elif status.state == "BuildError":
        print("Compilation failed!")
        print(f"Logs: {status.logs}")
        break

print("\nDone.")
