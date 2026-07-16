#!/bin/bash
# 启动 LocalQuant v2.0 完整系统

cd /home/pc/.openclaw/workspace/localquant

echo "================================================"
echo "LocalQuant v2.0 - 启动脚本"
echo "================================================"

# 1. 初始化数据库
echo "[1/3] 初始化数据库..."
python3 -c "
from localquant.db.schema import init_db
init_db('./data_cache/localquant.db')
print('✅ Database initialized')
"

# 2. 启动后端 API
echo "[2/3] 启动后端 API..."
pkill -f "uvicorn" 2>/dev/null; sleep 2

nohup python3 -c "
import sys
sys.path.insert(0, '.')
from localquant.api.server import app
import uvicorn
uvicorn.run(app, host='0.0.0.0', port=8000, log_level='warning')
" > /tmp/api_v2.log 2>&1 &
echo "API PID: $!"
sleep 5

# 测试 API
curl -s http://localhost:8000/health > /dev/null
if [ $? -eq 0 ]; then
    echo "✅ API running at http://localhost:8000"
else
    echo "❌ API failed to start"
    exit 1
fi

# 3. 启动前端
echo "[3/3] 启动前端 Dashboard..."
echo "✅ Frontend: streamlit run web/dashboard_v2.py"
echo ""

echo "================================================"
echo "系统启动完成！"
echo "================================================"
echo "API:    http://localhost:8000"
echo "Health: curl http://localhost:8000/health"
echo ""
echo "Frontend:"
echo "  streamlit run web/dashboard_v2.py"
echo ""
echo "测试命令:"
echo "  curl http://localhost:8000/strategies"
echo "  curl -X POST http://localhost:8000/backtest -H 'Content-Type: application/json' -d '{...}'"
echo "================================================"
