# Multifactor 盘中风控独立进程运行手册

本文件说明如何部署和运行 `risk_process.py` 作为独立的风控进程。

## 1. 运行方式

### 1.1 直接运行（Paper）

```bash
cd /home/pc/.openclaw/workspace/multifactor
export ALPACA_API_KEY="your_api_key"
export ALPACA_API_SECRET="your_api_secret"
export ALPACA_BASE_URL="https://paper-api.alpaca.markets"
python3 -m risk_process --paper --check-interval 30
```

### 1.2 直接运行（Live）

Live 模式需要显式确认，或设置环境变量 `ALPACA_LIVE_CONFIRMED=1`：

```bash
export ALPACA_API_KEY="your_live_api_key"
export ALPACA_API_SECRET="your_live_api_secret"
export ALPACA_BASE_URL="https://api.alpaca.markets"
export ALPACA_LIVE_CONFIRMED=1
python3 -m risk_process --live --check-interval 30
```

### 1.3 使用配置文件

```bash
python3 -m risk_process --config-path /etc/multifactor/config.json --check-interval 30
```

配置文件为 JSON 格式，会被解析为 `V14StrategyConfig` 的字段。

## 2. Systemd 服务示例

创建 `/etc/systemd/system/multifactor-risk.service`：

```ini
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
```

**安全提示**：生产环境建议将敏感凭证放到 `EnvironmentFile` 中，而不是直接写入 service 文件：

```ini
EnvironmentFile=/etc/multifactor/env
```

其中 `/etc/multifactor/env` 内容：

```text
ALPACA_API_KEY=your_api_key
ALPACA_API_SECRET=your_api_secret
ALPACA_BASE_URL=https://paper-api.alpaca.markets
```

并设置权限：

```bash
sudo chmod 600 /etc/multifactor/env
sudo chown root:root /etc/multifactor/env
```

## 3. 常用命令

```bash
# 重载 systemd
sudo systemctl daemon-reload

# 启用开机自启
sudo systemctl enable multifactor-risk.service

# 启动服务
sudo systemctl start multifactor-risk.service

# 查看状态
sudo systemctl status multifactor-risk.service

# 查看日志
journalctl -u multifactor-risk.service -f

# 停止服务
sudo systemctl stop multifactor-risk.service

# 重启服务
sudo systemctl restart multifactor-risk.service
```

## 4. 进程行为

- 以独立进程运行，不依赖主交易线程。
- 使用非 daemon 线程运行盘中监控循环，进程自身保持存活。
- 收到 SIGTERM 或 SIGINT 后，设置退出事件，等待当前监控循环完成，并调用 `IntradayMonitor.stop()` 优雅退出。
- 定期打印风控状态日志（VIX 阈值、风险等级、交易暂停状态、告警数量等）。
- 当触发 VIX 紧急阈值、日内回撤、累计回撤或个股暴跌时，独立调用 executor 的平仓接口。

## 5. 故障排查

### 进程无法启动

1. 检查环境变量 `ALPACA_API_KEY` 和 `ALPACA_API_SECRET` 是否已设置。
2. 检查 `ALPACA_BASE_URL` 是否为 `https://paper-api.alpaca.markets` 或 `https://api.alpaca.markets`。
3. 查看日志：`journalctl -u multifactor-risk.service -n 100`。

### 收到信号后未退出

- 默认 `TimeoutStopSec=30`，systemd 会先发送 SIGTERM。
- 如果 30 秒内未退出，systemd 会发送 SIGKILL。
- 检查是否某个监控循环阻塞（如网络请求超时）。

### 监控循环未触发平仓

- 检查 VIX 阈值、回撤阈值是否符合预期。
- 检查 executor 是否可用（mock 模式下不会连接真实 API）。
- 查看 `alerts/` 目录下的告警文件。
