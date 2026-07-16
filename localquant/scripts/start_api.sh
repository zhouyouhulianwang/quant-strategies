#!/bin/bash
# 启动 LocalQuant 完整系统

cd /home/pc/.openclaw/workspace/localquant

# 启动 API 后端
echo "Starting API server..."
nohup python3 -c "
import sys
sys.path.insert(0, '.')
sys.path.insert(0, 'localquant')
from localquant.api.server import app
import uvicorn
uvicorn.run(app, host='0.0.0.0', port=8000, log_level='warning')
" > /tmp/api.log 2>&1 &
echo "API PID: $!"
sleep 3

# 测试 API
echo "Testing API..."
curl -s http://localhost:8000/health | python3 -m json.tool

echo ""
echo "API running at http://localhost:8000"
echo "Health check: curl http://localhost:8000/health"
echo "Strategies: curl http://localhost:8000/strategies"
echo ""
echo "To start frontend: streamlit run web/dashboard.py"
