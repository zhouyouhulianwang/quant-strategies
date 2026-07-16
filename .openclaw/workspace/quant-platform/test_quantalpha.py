#!/usr/bin/env python3
"""
QuantAlpha v3.305 - 专业自动化测试套件
测试工程师: Qs
测试目标: API Gateway + RBAC + 浏览器重定向
"""

import requests
import json
import time
import sys
from datetime import datetime

# 测试配置
BASE_URL = "http://localhost:8080"
TEST_RESULTS = []

class TestReporter:
    """测试报告生成器"""
    
    def __init__(self):
        self.tests = []
        self.passed = 0
        self.failed = 0
        
    def add_test(self, name, status, detail="", role=""):
        self.tests.append({
            'name': name,
            'status': status,
            'detail': detail,
            'role': role,
            'timestamp': datetime.now().isoformat()
        })
        if status == 'PASS':
            self.passed += 1
        else:
            self.failed += 1
    
    def print_report(self):
        print("\n" + "=" * 70)
        print("QuantAlpha v3.305 - 自动化测试报告")
        print("=" * 70)
        print(f"测试时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"测试工程师: Qs")
        print(f"目标服务器: {BASE_URL}")
        print("-" * 70)
        
        for i, test in enumerate(self.tests, 1):
            icon = "✅" if test['status'] == 'PASS' else "❌"
            role_tag = f"[{test['role']}]" if test['role'] else ""
            print(f"{icon} 测试 {i:2d}: {test['name']} {role_tag}")
            if test['detail']:
                print(f"    详情: {test['detail']}")
        
        print("-" * 70)
        total = self.passed + self.failed
        pass_rate = (self.passed / total * 100) if total > 0 else 0
        print(f"总计: {total} | ✅ 通过: {self.passed} | ❌ 失败: {self.failed} | 通过率: {pass_rate:.1f}%")
        print("=" * 70)

reporter = TestReporter()


def test_health_check():
    """测试 1: 健康检查（无需认证）"""
    try:
        resp = requests.get(f"{BASE_URL}/api/v2/health", timeout=5)
        data = resp.json()
        assert data['status'] == 'success'
        assert data['data']['health'] == 'HEALTHY'
        reporter.add_test('Health Check', 'PASS', f"Status: {data['data']['health']}")
    except Exception as e:
        reporter.add_test('Health Check', 'FAIL', str(e))


def test_gateway_info():
    """测试 2: Gateway 信息（无需认证）"""
    try:
        resp = requests.get(f"{BASE_URL}/api/v2/gateway/info", timeout=5)
        data = resp.json()
        assert data['status'] == 'success'
        endpoints = len(data['data']['endpoints'])
        features = ', '.join(data['data']['features'])
        reporter.add_test('Gateway Info', 'PASS', f"Endpoints: {endpoints}, Features: {features}")
    except Exception as e:
        reporter.add_test('Gateway Info', 'FAIL', str(e))


def test_login(role, username, password):
    """测试登录并返回 token"""
    try:
        resp = requests.post(
            f"{BASE_URL}/api/v2/auth/login",
            json={'username': username, 'password': password},
            timeout=5
        )
        data = resp.json()
        
        if data['status'] == 'success':
            token = data['data']['token']
            actual_role = data['data']['role']
            reporter.add_test(
                f'Login as {role}',
                'PASS',
                f"Token: {token[:20]}..., Role: {actual_role}",
                role
            )
            return token
        else:
            reporter.add_test(
                f'Login as {role}',
                'FAIL',
                data.get('message', 'Unknown error'),
                role
            )
            return None
    except Exception as e:
        reporter.add_test(f'Login as {role}', 'FAIL', str(e), role)
        return None


def test_market_data(token, role):
    """测试市场数据访问"""
    try:
        resp = requests.get(
            f"{BASE_URL}/api/v2/market/AAPL",
            headers={'Authorization': f'Bearer {token}'},
            timeout=5
        )
        data = resp.json()
        assert data['status'] == 'success'
        price = data['data']['price']
        reporter.add_test(
            'Market Data (AAPL)',
            'PASS',
            f"Price: ${price:.2f}",
            role
        )
    except Exception as e:
        reporter.add_test('Market Data (AAPL)', 'FAIL', str(e), role)


def test_portfolio(token, role):
    """测试投资组合访问"""
    try:
        resp = requests.get(
            f"{BASE_URL}/api/v2/portfolio",
            headers={'Authorization': f'Bearer {token}'},
            timeout=5
        )
        data = resp.json()
        assert data['status'] == 'success'
        positions = len(data['data']['positions'])
        total = data['data']['total_value']
        reporter.add_test(
            'Portfolio Access',
            'PASS',
            f"Positions: {positions}, Total: ${total:,.2f}",
            role
        )
    except Exception as e:
        reporter.add_test('Portfolio Access', 'FAIL', str(e), role)


def test_strategies(token, role):
    """测试策略列表访问"""
    try:
        resp = requests.get(
            f"{BASE_URL}/api/v2/strategies",
            headers={'Authorization': f'Bearer {token}'},
            timeout=5
        )
        data = resp.json()
        assert data['status'] == 'success'
        count = data['data']['count']
        reporter.add_test(
            'Strategy List',
            'PASS',
            f"Count: {count}",
            role
        )
    except Exception as e:
        reporter.add_test('Strategy List', 'FAIL', str(e), role)


def test_risk_summary(token, role):
    """测试风控摘要访问"""
    try:
        resp = requests.get(
            f"{BASE_URL}/api/v2/risk/summary",
            headers={'Authorization': f'Bearer {token}'},
            timeout=5
        )
        data = resp.json()
        assert data['status'] == 'success'
        var_95 = data['data']['var_95']
        reporter.add_test(
            'Risk Summary',
            'PASS',
            f"VaR 95%: ${var_95:,.2f}",
            role
        )
    except Exception as e:
        reporter.add_test('Risk Summary', 'FAIL', str(e), role)


def test_create_order(token, role, should_succeed=True):
    """测试创建订单（权限控制）"""
    try:
        resp = requests.post(
            f"{BASE_URL}/api/v2/orders",
            headers={'Authorization': f'Bearer {token}'},
            json={'symbol': 'AAPL', 'side': 'BUY', 'quantity': 100, 'price': 150.0},
            timeout=5
        )
        
        if should_succeed:
            if resp.status_code == 200:
                data = resp.json()
                order_id = data['data']['order_id']
                reporter.add_test(
                    'Create Order',
                    'PASS',
                    f"Order ID: {order_id}",
                    role
                )
            else:
                reporter.add_test(
                    'Create Order',
                    'FAIL',
                    f"Expected 200, got {resp.status_code}",
                    role
                )
        else:
            if resp.status_code == 403:
                reporter.add_test(
                    'Create Order (Blocked)',
                    'PASS',
                    f"Correctly blocked with 403",
                    role
                )
            else:
                reporter.add_test(
                    'Create Order (Blocked)',
                    'FAIL',
                    f"Expected 403, got {resp.status_code}",
                    role
                )
    except Exception as e:
        reporter.add_test('Create Order', 'FAIL', str(e), role)


def test_unauthorized_access():
    """测试未授权访问"""
    try:
        # 测试无 token 访问
        resp = requests.get(f"{BASE_URL}/api/v2/portfolio", timeout=5)
        if resp.status_code == 403:
            reporter.add_test(
                'Unauthorized Access (No Token)',
                'PASS',
                "Correctly blocked with 403"
            )
        else:
            reporter.add_test(
                'Unauthorized Access (No Token)',
                'FAIL',
                f"Expected 403, got {resp.status_code}"
            )
        
        # 测试无效 token
        resp = requests.get(
            f"{BASE_URL}/api/v2/portfolio",
            headers={'Authorization': 'Bearer invalid_token'},
            timeout=5
        )
        if resp.status_code == 403:
            reporter.add_test(
                'Unauthorized Access (Invalid Token)',
                'PASS',
                "Correctly blocked with 403"
            )
        else:
            reporter.add_test(
                'Unauthorized Access (Invalid Token)',
                'FAIL',
                f"Expected 403, got {resp.status_code}"
            )
    except Exception as e:
        reporter.add_test('Unauthorized Access', 'FAIL', str(e))


def test_browser_redirect():
    """测试浏览器重定向"""
    try:
        # 模拟浏览器请求
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)',
            'Accept': 'text/html'
        }
        resp = requests.get(
            f"{BASE_URL}/api/v2/portfolio",
            headers=headers,
            allow_redirects=False,
            timeout=5
        )
        
        if resp.status_code == 302 and '/login' in resp.headers.get('Location', ''):
            reporter.add_test(
                'Browser Redirect',
                'PASS',
                f"Redirected to {resp.headers.get('Location')}"
            )
        else:
            reporter.add_test(
                'Browser Redirect',
                'FAIL',
                f"Expected 302 redirect, got {resp.status_code}"
            )
    except Exception as e:
        reporter.add_test('Browser Redirect', 'FAIL', str(e))


def test_login_page():
    """测试登录页面可访问性"""
    try:
        resp = requests.get(f"{BASE_URL}/login", timeout=5)
        if resp.status_code == 200 and 'QuantAlpha' in resp.text:
            reporter.add_test(
                'Login Page',
                'PASS',
                "Page loaded with QuantAlpha branding"
            )
        else:
            reporter.add_test(
                'Login Page',
                'FAIL',
                f"Status: {resp.status_code}"
            )
    except Exception as e:
        reporter.add_test('Login Page', 'FAIL', str(e))


def run_full_test_suite():
    """运行完整测试套件"""
    print("=" * 70)
    print("QuantAlpha v3.305 - 专业自动化测试套件")
    print("=" * 70)
    print(f"开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"目标服务器: {BASE_URL}")
    print("-" * 70)
    
    # 1. 基础测试（无需认证）
    print("\n[阶段 1/5] 基础端点测试...")
    test_health_check()
    test_gateway_info()
    test_login_page()
    
    # 2. 未授权访问测试
    print("\n[阶段 2/5] 安全测试...")
    test_unauthorized_access()
    test_browser_redirect()
    
    # 3. Admin 角色测试
    print("\n[阶段 3/5] Admin 角色测试...")
    admin_token = test_login('admin', 'admin', '***')
    if admin_token:
        test_market_data(admin_token, 'admin')
        test_portfolio(admin_token, 'admin')
        test_strategies(admin_token, 'admin')
        test_risk_summary(admin_token, 'admin')
        test_create_order(admin_token, 'admin', should_succeed=True)
    
    # 4. Trader 角色测试
    print("\n[阶段 4/5] Trader 角色测试...")
    trader_token = test_login('trader', 'trader1', '***')
    if trader_token:
        test_market_data(trader_token, 'trader')
        test_portfolio(trader_token, 'trader')
        test_create_order(trader_token, 'trader', should_succeed=True)
    
    # 5. Researcher 角色测试（应被拒绝创建订单）
    print("\n[阶段 5/5] Researcher 角色测试...")
    research_token = test_login('researcher', 'researcher1', '***')
    if research_token:
        test_market_data(research_token, 'researcher')
        test_portfolio(research_token, 'researcher')
        test_create_order(research_token, 'researcher', should_succeed=False)
    
    # 生成报告
    reporter.print_report()


if __name__ == '__main__':
    run_full_test_suite()
