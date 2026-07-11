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

# Create a simple logger
class SimpleLogger:
    def debug(self, msg):
        print(f"[DEBUG] {msg}")
    
    def debug_logging_enabled(self):
        return True

logger = SimpleLogger()
http_client = HTTPClient(logger)

user_id = "515996"
api_token = "2409bf6b14feaf8a29481c3a83d0d1ae0110378ef98bcabe17c6a93427d3343e"
project_id = 34012459

api = APIClient(logger, http_client, user_id, api_token)

# Test authentication
print("Authenticating...")
try:
    auth = api.is_authenticated()
    print(f"Authenticated: {auth}")
except Exception as e:
    print(f"Auth error: {e}")

# Read project files
print("\nReading project files...")
try:
    files = api.files.get_all(project_id)
    print(f"Found {len(files)} files")
    for f in files:
        print(f"  - {f.name}")
except Exception as e:
    print(f"Error reading files: {e}")

# Read main.py content
print("\nReading main.py...")
try:
    main_file = api.files.get(project_id, "main.py")
    print(f"main.py content length: {len(main_file.content)}")
except Exception as e:
    print(f"Error reading main.py: {e}")

# Read updated main.py
with open('/home/pc/.openclaw/workspace/quantconnect-projects/labs/main.py', 'r') as f:
    new_code = f.read()

# Update main.py
print("\nUpdating main.py...")
try:
    api.files.update(project_id, "main.py", new_code)
    print("Updated successfully!")
except Exception as e:
    print(f"Error updating: {e}")

# Compile
print("\nCompiling...")
try:
    compile_result = api.compiles.create(project_id)
    print(f"Compile ID: {compile_result.compile_id}")
    compile_id = compile_result.compile_id
except Exception as e:
    print(f"Error compiling: {e}")
    compile_id = None

if compile_id:
    # Wait for compilation
    print("\nWaiting for compilation...")
    for i in range(30):
        time.sleep(2)
        try:
            status = api.compiles.get(project_id, compile_id)
            print(f"  State: {status.state}")
            if status.state == "BuildSuccess":
                print("Compilation successful!")
                
                # Run backtest
                print("\nStarting backtest...")
                try:
                    backtest = api.backtests.create(project_id, compile_id, "vix_tp1.5_sl1.5")
                    print(f"Backtest ID: {backtest.backtest_id}")
                    backtest_id = backtest.backtest_id
                    
                    # Wait for backtest
                    print("\nWaiting for backtest...")
                    for j in range(60):
                        time.sleep(5)
                        bt = api.backtests.get(project_id, backtest_id)
                        print(f"  Progress: {bt.progress}%, Status: {bt.status}")
                        if bt.status in ["Completed", "Failed", "Cancelled"]:
                            print("\n=== BACKTEST COMPLETE ===")
                            print(f"Status: {bt.status}")
                            if hasattr(bt, 'statistics') and bt.statistics:
                                stats = bt.statistics
                                print(f"\n=== STATISTICS ===")
                                for k, v in stats.__dict__.items() if hasattr(stats, '__dict__') else stats.items():
                                    print(f"  {k}: {v}")
                            else:
                                print(f"Backtest data: {bt}")
                            break
                    
                except Exception as e:
                    print(f"Error starting backtest: {e}")
                break
                
            elif status.state == "BuildError":
                print("Compilation failed!")
                print(f"Logs: {status.logs}")
                break
        except Exception as e:
            print(f"Error checking compile status: {e}")
            break
