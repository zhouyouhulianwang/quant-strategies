# Interactive Brokers (IB) 账户配置与 QuantConnect 连接指南

## 1. 开立 IB 账户

### 步骤
1. 访问 https://www.interactivebrokers.com
2. 点击 "Open Account" → 选择 "Individual"（个人账户）
3. 填写个人信息：
   - 姓名、地址、联系方式
   - 税务信息（W-9 或 W-8BEN，非美国居民）
   - 就业状况、收入来源
   - 投资经验（选择有一定经验，方便通过审核）
4. 选择账户类型：
   - **推荐：Margin Account**（保证金账户，支持做空和杠杆）
   - Cash Account（现金账户，限制较多）
5. 提交申请，等待审核（通常1-3个工作日）
6. 存入资金：
   - 最低入金：$0（但建议至少 $10,000）
   - 电汇（Wire Transfer）或 ACH（美国银行账户）

### 重要设置
- **交易权限**：申请股票（Stocks）和期权（Options，如需要对冲）
- **杠杆**：默认 2:1（Reg T），日内可达 4:1
- **数据订阅**：
  - US Securities Snapshot and Futures Value Bundle（免费实时快照）
  - 或 US Equity and Options Add-On Streaming Bundle（$4.50/月，实时流数据）

---

## 2. 启用 IB API

### 步骤
1. 登录 **IB Trader Workstation (TWS)** 或 **IB Gateway**
   - TWS：完整交易平台（下载：https://www.interactivebrokers.com/en/index.php?f=16457）
   - IB Gateway：轻量版，仅API连接（推荐用于自动化）
2. 进入 **Edit → Global Configuration → API → Settings**
3. 勾选 **"Enable ActiveX and Socket Clients"**
4. 设置：
   - **Socket port**: `7496`（实盘）或 `7497`（模拟账户）
   - **Master Client ID**: `0`
   - **Allow connections from localhost only**: 取消勾选（允许远程连接，如果从VPS运行）
   - **Create API message log**: 勾选（调试用）
5. 点击 **Apply** 或 **OK**

### 防火墙/VPS 配置
如果从云服务器（VPS）连接IB：
```bash
# 在IB服务器上允许QuantConnect IP
# 或者使用IB Gateway + SSH隧道
ssh -L 7496:localhost:7496 user@your-vps-ip
```

---

## 3. QuantConnect Live Trading 配置

### 方法 A：通过 Lean CLI（推荐）

```bash
# 1. 确保 Lean CLI 已配置
lean config set user-id 515996
lean config set api-token 2409bf6b14feaf8a29481c3a83d0d1ae0110378ef98bcabe17c6a93427d3343e

# 2. 启动实盘交易
lean cloud live "AdaptiveMomentumV3_1" \
  --brokerage "Interactive Brokers" \
  --ib-account "YOUR_IB_ACCOUNT_NUMBER" \
  --ib-user-name "YOUR_IB_USERNAME" \
  --ib-password "YOUR_IB_PASSWORD" \
  --ib-trading-mode "live"  # 实盘
  # 或 --ib-trading-mode "paper"  # 模拟盘（先测试！）
```

### 方法 B：通过 QuantConnect 网站

1. 访问 https://www.quantconnect.com
2. 登录 → 选择项目 **AdaptiveMomentumV3_1**
3. 点击 **"Deploy"** → **"Live Trading"**
4. 选择 **Brokerage: Interactive Brokers**
5. 填写：
   - Account Number: `UXXXXXX`（IB账户号）
   - User Name: IB登录用户名
   - Password: IB登录密码
   - Trading Mode: `Paper`（先模拟）或 `Live`（实盘）
6. 点击 **Deploy**

### 方法 C：本地 Lean + IB（高级）

```bash
# 1. 配置 Lean 本地连接 IB
lean config set brokerage-id "InteractiveBrokers"
lean config set ib-account "UXXXXXX"
lean config set ib-user-name "your_username"
lean config set ib-password "your_password"
lean config set ib-host "127.0.0.1"
lean config set ib-port "7496"

# 2. 本地运行（需要本地数据）
lean live /path/to/project --brokerage "Interactive Brokers"
```

---

## 4. 关键配置参数

### 账户相关
| 参数 | 说明 | 示例 |
|------|------|------|
| IB Account Number | 账户号 | U1234567 |
| IB User Name | 登录名 | dave_trader |
| IB Password | 密码 | your_password |
| Trading Mode | 实盘/模拟 | paper / live |
| IB Host | IB Gateway IP | 127.0.0.1（本地）|
| IB Port | API端口 | 7496（实盘）/ 7497（模拟）|

### 策略参数（实盘调整）
```python
# 在 main.py 中修改 Initialize()
self.SetCash(10000)  # 初始资金 $10,000
self.SetBrokerageModel(
    BrokerageName.INTERACTIVE_BROKERS_BROKERAGE,
    AccountType.MARGIN
)
```

---

## 5. 预部署检查清单

### 模拟盘测试（必须！）
- [ ] 在 IB 开立 **Paper Trading** 账户（免费，与实盘并行）
- [ ] 使用 Paper 账户运行策略至少 **2周**
- [ ] 对比模拟盘与回测表现：
  - 收益是否接近预期？
  - 滑点是否可接受？
  - 订单是否及时执行？

### 资金检查
- [ ] 确认账户净值 >= $10,000
- [ ] 确认购买力 >= $20,000（Margin 2:1）
- [ ] 预留 $2,000 不投入策略（应急）
- [ ] 确认无其他策略占用资金

### 技术检查
- [ ] IB Gateway/TWS 运行中
- [ ] API 端口开放（7496 或 7497）
- [ ] 网络连接稳定（建议有线/VPS）
- [ ] QuantConnect 订阅有效（Live Trading 需要付费计划）
- [ ] 手机安装 IB Key（2FA 认证）

---

## 6. 常见问题

### Q: IB 账户审核被拒怎么办？
- 确保填写真实信息
- 投资经验选择 "Limited" 或 "Good"（不要选 None）
- 收入/净资产填写合理数值（不要太低）
- 如有问题，联系 IB 客服

### Q: 如何切换 Paper/Live？
```bash
# 停止当前实盘
lean cloud live stop "AdaptiveMomentumV3_1"

# 重新部署为 Paper
lean cloud live "AdaptiveMomentumV3_1" \
  --ib-trading-mode "paper"
```

### Q: API 连接失败？
- 检查 IB Gateway 是否运行
- 检查端口是否正确（7496 live / 7497 paper）
- 检查防火墙设置
- 检查 QuantConnect IP 是否被允许

### Q: 订单被拒？
- 检查购买力是否足够（Margin 要求）
- 检查股票是否可做空（如果策略做空）
- 检查是否触发日内交易规则（PDT，$25,000以下账户）

### Q: 数据延迟？
- 免费 IB 数据是快照，非实时流
- 建议订阅实时数据（$4.50/月）
- 或依赖 QuantConnect 数据（免费，但可能延迟几秒）

---

## 7. 安全建议

1. **先 Paper 后 Live**：至少模拟运行2周
2. **小额起步**：$10,000 初始，验证策略后再增加
3. **启用通知**：QuantConnect 和 IB 都开启邮件/短信通知
4. **备用方案**：准备手动干预流程（IB 网页/APP可直接操作）
5. **定期审查**：每周检查策略表现 vs 回测预期
6. **止损意识**：即使策略有自动风控，也要设定人工止损线（如总亏损 > 20% 手动暂停）

---

## 8. 快速启动命令

```bash
# 第一步：推送最新代码
lean cloud push

# 第二步：模拟盘测试（2周）
lean cloud backtest "AdaptiveMomentumV3_1"  # 确认回测正常
lean cloud live "AdaptiveMomentumV3_1" \
  --brokerage "Interactive Brokers" \
  --ib-account "U1234567" \
  --ib-user-name "dave" \
  --ib-password "password" \
  --ib-trading-mode "paper"

# 第三步：监控模拟盘
lean cloud live log "AdaptiveMomentumV3_1"

# 第四步：实盘部署（2周后，确认表现正常）
lean cloud live "AdaptiveMomentumV3_1" \
  --brokerage "Interactive Brokers" \
  --ib-account "U1234567" \
  --ib-user-name "dave" \
  --ib-password "password" \
  --ib-trading-mode "live"
```

---

*配置时间: 2026-07-10*
*策略版本: AdaptiveMomentumStrategy v3.1 P2*
*最低资金要求: $10,000 USD*
