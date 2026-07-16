# Alpaca API Key 获取指南

## 快速步骤 (3分钟)

### 1. 注册账户
- 访问: https://alpaca.markets
- 点击 "Get Started" 或 "Sign Up"
- 填写邮箱、密码、姓名
- 验证邮箱

### 2. 进入 Paper Trading
- 登录后点击左上角菜单
- 选择 **Paper Trading** (模拟交易)
- 不需要实名认证即可使用 Paper Trading

### 3. 生成 API Key
- 在 Paper Trading 页面左侧菜单
- 点击 **API Keys** 或 **Generate API Key**
- 点击 **Generate New Key**
- 复制 **API Key ID** 和 **Secret Key**

⚠️ **Secret Key 只显示一次，请立即保存！**

### 4. 配置到本地
```bash
# 方式1: 直接设置环境变量
export ALPACA_API_KEY='PKxxxxx...'
export ALPACA_API_SECRET='xxxxxxxx...'

# 方式2: 运行配置脚本
cd /home/pc/.openclaw/workspace/AdaptiveMomentumV3_1
chmod +x setup_alpaca.sh
source setup_alpaca.sh
# 然后按提示输入 Key
```

### 5. 测试连接
```bash
cd /home/pc/.openclaw/workspace/AdaptiveMomentumV3_1
python3 alpaca_paper_test.py
```

---

## 注意事项

| 项目 | 说明 |
|------|------|
| **费用** | Paper Trading 完全免费 |
| **资金** | 默认提供 $100,000 模拟资金 |
| **限制** | 200 API 调用/分钟 |
| **市场** | 美股 (NYSE, NASDAQ) |
| **时间** | 实时交易 + 盘前盘后 |

---

## 常见问题

**Q: 需要实名认证吗？**  
A: Paper Trading 不需要，实盘交易需要。

**Q: 可以用国内手机号吗？**  
A: 可以，Alpaca 支持全球用户。

**Q: 支持加密货币吗？**  
A: 支持，通过 Alpaca Crypto API。

---

## 配置完成后

运行策略:
```bash
cd /home/pc/.openclaw/workspace/AdaptiveMomentumV3_1

# 基本测试
python3 alpaca_paper_test.py

# 策略模拟
python3 alpaca_paper_test.py strategy

# 使用 Mock 模式 (无需 Key)
.venv/bin/python alpaca_mock_test.py strategy
```

---

**需要帮助？**  
- Alpaca 文档: https://alpaca.markets/docs/
- API 参考: https://alpaca.markets/docs/api-documentation/api-v2/
