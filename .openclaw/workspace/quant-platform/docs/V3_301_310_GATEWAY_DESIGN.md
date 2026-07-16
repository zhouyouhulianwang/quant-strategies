# LocalQuant 统一访问入口设计 (v3.301-v3.310)

## 目标
整合现有所有 API 端点，通过统一入口访问，配合权限管理 (RBAC)，确保安全可控。

## 架构

```
客户端请求 → API Gateway → RBAC 验证 → 路由分发 → 后端服务
                ↓              ↓
           认证/授权      访问日志/审计
```

## 组件

### 1. API Gateway (v3.301)
- 统一入口: `/api/*` 和 `/api/v2/*`
- 请求路由到对应后端服务
- 负载均衡（未来扩展）

### 2. Authentication Middleware (v3.302)
- Token 验证 (JWT/自定义 Token)
- Session 管理
- API Key 支持

### 3. RBAC Integration (v3.303)
- 基于角色的权限验证
- 端点级别的权限控制
- 拒绝无权限请求

### 4. Access Logging (v3.304)
- 记录所有请求
- 审计追踪
- 性能监控

### 5. Unified Server (v3.305)
- 单一进程启动所有服务
- 配置文件管理
- 优雅关闭

## 端点映射

| 统一端点 | 后端服务 | 所需权限 |
|----------|----------|----------|
| `/api/v2/health` | Health Check | 无 |
| `/api/v2/auth/login` | Auth | 无 |
| `/api/v2/market/:symbol` | Market Data | strategy:read |
| `/api/v2/portfolio` | Portfolio | portfolio:read |
| `/api/v2/strategies` | Strategy | strategy:read |
| `/api/v2/strategies` (POST) | Strategy | strategy:create |
| `/api/v2/orders` (POST) | Execution | trade:execute |
| `/api/v2/risk/summary` | Risk | risk:read |
| `/api/v2/reports/backtest` | Report | strategy:read |
| `/api/v2/system/status` | System | system:monitor |

## 认证流程

```
1. 用户登录 → /api/v2/auth/login
2. 返回 Token
3. 后续请求 Header: Authorization: Bearer <token>
4. Gateway 验证 Token
5. Gateway 检查 RBAC 权限
6. 转发到后端服务
7. 记录访问日志
```

## 权限矩阵

| 角色 | 策略 | 交易 | 组合 | 风控 | 系统 | 审计 |
|------|------|------|------|------|------|------|
| admin | CRUD | CRUD | CRUD | CRUD | CRUD | R |
| researcher | CRUD | - | R | R | - | - |
| trader | R | CRUD | CRUD | R | - | - |
| risk_officer | R | R | R | CRUD | - | R |
| operator | R | - | R | - | CRUD | - |
| auditor | R | R | R | R | - | R |
| viewer | R | - | R | R | - | - |

## 实施计划

### v3.301: API Gateway
- 创建 `web/api_gateway.py`
- 请求路由
- 基础认证

### v3.302: Auth Middleware
- Token 验证
- Session 管理

### v3.303: RBAC Integration
- 权限验证
- 拒绝处理

### v3.304: Access Logging
- 请求日志
- 审计日志

### v3.305: Unified Server
- 统一启动
- 配置管理

## 安全特性

- HTTPS 支持（配置证书）
- 请求速率限制
- IP 白名单
- 输入验证
- SQL 注入防护
- XSS 防护

## 监控指标

- 请求总数
- 请求延迟 (P50/P95/P99)
- 错误率
- 活跃用户
- 权限拒绝次数

## 测试

- 单元测试: 认证、权限、路由
- 集成测试: 端到端请求
- 安全测试: 未授权访问、越权访问
