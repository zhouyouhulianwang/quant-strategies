import requests
import json
import base64
import time
from hashlib import sha256
from urllib.parse import urljoin

# API credentials
user_id = "515996"
api_token = "2409bf6b14feaf8a29481c3a83d0d1ae0110378ef98bcabe17c6a93427d3343e"
project_id = "34012459"
base_url = "https://www.quantconnect.com/api/v2"

def make_request(method, endpoint, data=None):
    timestamp = str(int(time.time()))
    password = sha256(f"{api_token}:{timestamp}".encode("utf-8")).hexdigest()
    
    headers = {
        "Timestamp": timestamp,
        "User-Agent": "Lean CLI 1.0.227",
        "Content-Type": "application/json"
    }
    
    full_url = urljoin(base_url, endpoint)
    
    if method == "post":
        resp = requests.post(full_url, headers=headers, auth=(user_id, password), json=data)
    else:
        resp = requests.get(full_url, headers=headers, auth=(user_id, password), params=data)
    
    print(f"{method.upper()} {endpoint} -> {resp.status_code}")
    try:
        result = resp.json()
        if not result.get("success", True):
            print(f"Errors: {result.get('errors', [])}")
        return result
    except:
        print(f"Raw: {resp.text[:500]}")
        return {"success": False, "text": resp.text}

# Read the updated main.py
with open('/home/pc/.openclaw/workspace/quantconnect-projects/labs/main.py', 'r') as f:
    code = f.read()

# 1. Get project files
print("=== Getting project files ===")
project_data = make_request("post", "projects/read", {"projectId": project_id})
print(json.dumps(project_data, indent=2)[:1000])

# Find the file ID for main.py
main_file_id = None
for file in project_data.get("files", []):
    if file.get("name") == "main.py":
        main_file_id = file.get("id")
        break

print(f"main.py file ID: {main_file_id}")

# 2. Update or create the file
if main_file_id:
    print("=== Updating main.py ===")
    update_resp = make_request("post", "files/update", {
        "projectId": project_id,
        "fileId": main_file_id,
        "name": "main.py",
        "content": code
    })
    print(json.dumps(update_resp, indent=2)[:500])
else:
    print("=== Creating main.py ===")
    create_resp = make_request("post", "files/create", {
        "projectId": project_id,
        "name": "main.py",
        "content": code
    })
    print(json.dumps(create_resp, indent=2)[:500])

# 3. Compile the project
print("=== Compiling project ===")
compile_data = make_request("post", "projects/compile", {"projectId": project_id})
print(json.dumps(compile_data, indent=2)[:500])
compile_id = compile_data.get("compileId")
print(f"Compile ID: {compile_id}")

if not compile_id:
    print("No compile ID received - aborting")
    exit(1)

# Wait for compilation
print("=== Waiting for compilation ===")
for i in range(30):
    time.sleep(2)
    status_data = make_request("post", "projects/compile/read", {
        "projectId": project_id,
        "compileId": compile_id
    })
    state = status_data.get("state")
    print(f"Compile state: {state}")
    if state in ["InQueue", "Building"]:
        continue
    elif state == "BuildError":
        print("Compilation failed!")
        print(json.dumps(status_data, indent=2))
        exit(1)
    elif state == "BuildSuccess":
        print("Compilation successful!")
        # 4. Run backtest
        print("=== Starting backtest ===")
        backtest_data = make_request("post", "backtests/create", {
            "projectId": project_id,
            "compileId": compile_id,
            "name": "vix_tp1.5_sl1.5"
        })
        print(json.dumps(backtest_data, indent=2)[:500])
        backtest_id = backtest_data.get("backtestId")
        print(f"Backtest ID: {backtest_id}")
        
        if not backtest_id:
            print("No backtest ID received - aborting")
            exit(1)
        
        # Wait for backtest to complete
        print("=== Waiting for backtest ===")
        for j in range(60):
            time.sleep(5)
            bt_data = make_request("post", "backtests/read", {
                "projectId": project_id,
                "backtestId": backtest_id
            })
            progress = bt_data.get("progress", 0)
            status = bt_data.get("status", "unknown")
            print(f"Backtest progress: {progress}%, status: {status}")
            if status in ["Completed", "Failed", "Cancelled"]:
                print("\n=== FINAL BACKTEST RESULTS ===")
                print(json.dumps(bt_data, indent=2)[:5000])
                
                # Extract key stats
                if bt_data.get("success"):
                    result = bt_data.get("result", {})
                    stats = result.get("Statistics", {})
                    print(f"\n=== KEY STATS ===")
                    print(f"Total Return: {stats.get('Total Return', 'N/A')}")
                    print(f"Sharpe Ratio: {stats.get('Sharpe Ratio', 'N/A')}")
                    print(f"Max Drawdown: {stats.get('Max Drawdown', 'N/A')}")
                    print(f"Win Rate: {stats.get('Win Rate', 'N/A')}")
                break
        break
    else:
        print(f"Unknown state: {state}")
        break
