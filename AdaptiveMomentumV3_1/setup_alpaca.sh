#!/bin/bash
# Alpaca API Key 配置助手
# 运行: source setup_alpaca.sh

echo "🚀 Alpaca API Key 配置"
echo "======================"
echo ""
echo "请从 https://alpaca.markets 获取 Paper Trading API Key"
echo ""

read -p "请输入 API Key ID: " ALPACA_KEY
read -p "请输入 API Secret Key: " ALPACA_SECRET

# 写入环境变量
export ALPACA_API_KEY="$ALPACA_KEY"
export ALPACA_API_SECRET="$ALPACA_SECRET"
export ALPACA_BASE_URL="https://paper-api.alpaca.markets"

# 添加到 ~/.bashrc (持久化)
echo "" >> ~/.bashrc
echo "# Alpaca API Keys" >> ~/.bashrc
echo "export ALPACA_API_KEY=\"$ALPACA_KEY\"" >> ~/.bashrc
echo "export ALPACA_API_SECRET=\"$ALPACA_SECRET\"" >> ~/.bashrc
echo "export ALPACA_BASE_URL=\"https://paper-api.alpaca.markets\"" >> ~/.bashrc

echo ""
echo "✅ API Key 已配置!"
echo "  Key ID: ${ALPACA_KEY:0:10}..."
echo "  Secret: ${ALPACA_SECRET:0:10}..."
echo ""
echo "环境变量已写入 ~/.bashrc"
echo ""
echo "测试连接:"
echo "  cd /home/pc/.openclaw/workspace/AdaptiveMomentumV3_1"
echo "  python3 alpaca_paper_test.py"
