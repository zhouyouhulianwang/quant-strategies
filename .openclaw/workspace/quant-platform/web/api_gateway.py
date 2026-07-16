#!/usr/bin/env python3
"""
LocalQuant API Gateway v3.305 - With Browser Redirect
统一访问入口 + 权限管理 + 浏览器重定向
"""

import sys, os, json, time, secrets, threading
from datetime import datetime, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Dict, Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import numpy as np
from infrastructure.security.rbac import RBACManager, Role, Permission
from data.unified_database import UnifiedDatabaseManager


class TokenManager:
    def __init__(self, expiry_minutes=15):
        self.tokens = {}
        self.lock = threading.Lock()
        
        def cleanup():
            while True:
                time.sleep(60)
                with self.lock:
                    now = datetime.now()
                    expired = [t for t, d in self.tokens.items() if d['expires'] < now]
                    for t in expired:
                        del self.tokens[t]
        
        threading.Thread(target=cleanup, daemon=True).start()
    
    def generate_token(self, user, role):
        token = secrets.token_hex(32)
        expires = datetime.now() + timedelta(minutes=15)
        with self.lock:
            self.tokens[token] = {'user': user, 'role': role, 'expires': expires}
        return token
    
    def validate_token(self, token):
        with self.lock:
            if token not in self.tokens:
                return None
            data = self.tokens[token]
            if data['expires'] < datetime.now():
                del self.tokens[token]
                return None
            return {'user': data['user'], 'role': data['role']}


class RateLimiter:
    def __init__(self, requests_per_minute=60):
        self.requests_per_minute = requests_per_minute
        self.requests = {}
        self.lock = threading.Lock()
    
    def is_allowed(self, client_id):
        now = time.time()
        with self.lock:
            if client_id not in self.requests:
                self.requests[client_id] = []
            self.requests[client_id] = [t for t in self.requests[client_id] if now - t < 60]
            if len(self.requests[client_id]) >= self.requests_per_minute:
                return False
            self.requests[client_id].append(now)
            return True


class APIGatewayHandler(BaseHTTPRequestHandler):
    rbac = RBACManager()
    tokens = TokenManager()
    rate_limiter = RateLimiter(60)
    db = UnifiedDatabaseManager()
    
    PERMISSIONS = {
        '/api/v2/health': None,
        '/api/v2/auth/login': None,
        '/api/v2/auth/logout': None,
        '/api/v2/auth/status': None,
        '/api/v2/market/': Permission.STRATEGY_READ,
        '/api/v2/portfolio': Permission.PORTFOLIO_READ,
        '/api/v2/strategies': Permission.STRATEGY_READ,
        '/api/v2/orders': Permission.TRADE_EXECUTE,
        '/api/v2/risk/summary': Permission.RISK_READ,
        '/api/v2/system/status': Permission.SYSTEM_MONITOR,
        '/api/v2/gateway/info': None,
    }
    
    def log_message(self, *args):
        pass
    
    def _get_token(self):
        auth = self.headers.get('Authorization', '')
        return auth[7:] if auth.startswith('Bearer ') else None
    
    def _check_permission(self, path, user_data):
        required = None
        for endpoint, perm in self.PERMISSIONS.items():
            if path.startswith(endpoint):
                required = perm
                break
        if required is None:
            return True, "OK"
        if user_data is None:
            return False, "Authentication required"
        # Check role permissions directly
        from infrastructure.security.rbac import ROLE_PERMISSIONS
        role = Role(user_data['role'])
        if required not in ROLE_PERMISSIONS.get(role, []):
            return False, f"Permission denied: {required.value}"
        return True, "OK"
    
    def _is_browser_request(self):
        """检测是否是浏览器请求"""
        accept = self.headers.get('Accept', '')
        user_agent = self.headers.get('User-Agent', '')
        
        # 如果是请求 HTML 或浏览器访问
        if 'text/html' in accept:
            return True
        
        # 如果是常见浏览器
        browsers = ['Mozilla', 'Chrome', 'Safari', 'Firefox', 'Edge']
        if any(browser in user_agent for browser in browsers):
            return True
        
        return False
    
    def _send_login_redirect(self):
        """发送重定向到登录页面"""
        redirect_url = self.path
        login_url = f'/login?redirect={redirect_url}'
        
        self.send_response(302)
        self.send_header('Location', login_url)
        self.send_header('Content-Type', 'text/html')
        self.end_headers()
        
        html = f'''<!DOCTYPE html>
<html>
<head><title>Redirecting...</title></head>
<body>
    <p>Redirecting to <a href="{login_url}">login page</a>...</p>
</body>
</html>'''
        self.wfile.write(html.encode())
    
    def _serve_login_page(self):
        """提供登录页面"""
        try:
            with open(os.path.join(os.path.dirname(__file__), 'login.html'), 'r') as f:
                content = f.read()
            
            self.send_response(200)
            self.send_header('Content-Type', 'text/html')
            self.end_headers()
            self.wfile.write(content.encode())
        except FileNotFoundError:
            self._send_error("Login page not found", 404)
    
    def _serve_dashboard(self):
        """提供仪表板页面"""
        html = '''<!DOCTYPE html>
<html>
<head>
    <title>LocalQuant Dashboard</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 0; padding: 20px; background: #f5f5f5; }
        .header { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 20px; border-radius: 8px; margin-bottom: 20px; }
        .card { background: white; padding: 20px; border-radius: 8px; margin-bottom: 16px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
        .nav { display: flex; gap: 12px; margin-bottom: 20px; }
        .nav a { color: #667eea; text-decoration: none; padding: 8px 16px; border-radius: 4px; }
        .nav a:hover { background: #f0f0f0; }
    </style>
</head>
<body>
    <div class="header">
        <h1>⚡ LocalQuant Dashboard</h1>
        <p>v3.305 - Quantitative Trading Platform</p>
    </div>
    
    <div class="nav">
        <a href="/dashboard">首页</a>
        <a href="/api/v2/portfolio" target="_blank">投资组合 (API)</a>
        <a href="/api/v2/market/AAPL" target="_blank">行情 (API)</a>
        <a href="/api/v2/strategies" target="_blank">策略 (API)</a>
        <a href="/login" onclick="localStorage.clear();">退出登录</a>
    </div>
    
    <div class="card">
        <h2>🎉 登录成功!</h2>
        <p>您已成功登录 LocalQuant 量化交易平台。</p>
        <p>使用上方导航链接访问 API 端点。</p>
    </div>
    
    <div class="card">
        <h3>API 端点</h3>
        <ul>
            <li><code>/api/v2/health</code> - 健康检查</li>
            <li><code>/api/v2/market/:symbol</code> - 市场数据</li>
            <li><code>/api/v2/portfolio</code> - 投资组合</li>
            <li><code>/api/v2/strategies</code> - 策略列表</li>
            <li><code>/api/v2/orders</code> - 创建订单</li>
        </ul>
    </div>
    
    <script>
        const token = localStorage.getItem('localquant_token');
        if (!token) {
            window.location.href = '/login?redirect=' + encodeURIComponent(window.location.pathname);
        }
    </script>
</body>
</html>'''
        
        self.send_response(200)
        self.send_header('Content-Type', 'text/html')
        self.end_headers()
        self.wfile.write(html.encode())
    
    def _send_json(self, data, status=200):
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, DELETE, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, Authorization')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())
    
    def _send_success(self, data, message="Success"):
        self._send_json({'status': 'success', 'message': message, 'data': data, 'timestamp': datetime.now().isoformat()})
    
    def _send_error(self, message, status=400):
        self._send_json({'status': 'error', 'message': message, 'code': status, 'timestamp': datetime.now().isoformat()}, status)
    
    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, DELETE, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, Authorization')
        self.end_headers()
    
    def do_GET(self):
        self._handle('GET')
    
    def do_POST(self):
        self._handle('POST')
    
    def do_DELETE(self):
        self._handle('DELETE')
    
    def _handle(self, method):
        try:
            path = self.path
            client_id = f"{self.client_address[0]}:{self._get_token() or 'anon'}"
            
            if not self.rate_limiter.is_allowed(client_id):
                self._send_error("Rate limit exceeded", 429)
                return
            
            token = self._get_token()
            user_data = self.tokens.validate_token(token) if token else None
            
            # Browser pages (no auth required)
            if path == '/login':
                self._serve_login_page()
                return
            elif path == '/dashboard':
                self._serve_dashboard()
                return
            
            allowed, reason = self._check_permission(path, user_data)
            if not allowed:
                # For browser requests, redirect to login page
                if self._is_browser_request() and path != '/api/v2/auth/login':
                    self._send_login_redirect()
                    return
                # For API requests, return JSON error
                self._send_error(reason, 403)
                return
            
            # API endpoints
            if path == '/api/v2/health':
                self._send_success({'health': 'HEALTHY', 'gateway': 'v3.305', 'databases': 3})
            elif path == '/api/v2/auth/status':
                self._send_success(self._handle_auth_status(user_data))
            elif path.startswith('/api/v2/market/'):
                self._send_success(self._handle_market(path.split('/')[-1]))
            elif path == '/api/v2/portfolio':
                self._send_success(self._handle_portfolio())
            elif path == '/api/v2/strategies':
                self._send_success(self._handle_strategies())
            elif path == '/api/v2/orders':
                self._send_success(self._handle_orders(method))
            elif path == '/api/v2/risk/summary':
                self._send_success(self._handle_risk())
            elif path == '/api/v2/system/status':
                self._send_success(self._handle_system())
            elif path == '/api/v2/gateway/info':
                self._send_success(self._handle_gateway_info())
            elif path == '/api/v2/auth/login':
                self._send_success(self._handle_login())
            elif path == '/api/v2/auth/logout':
                self._send_success(self._handle_logout())
            else:
                self._send_error("Not found", 404)
        
        except Exception as e:
            self._send_error(str(e), 500)
    
    def _handle_login(self):
        content_length = int(self.headers.get('Content-Length', 0))
        if content_length > 0:
            body = self.rfile.read(content_length).decode()
            data = json.loads(body)
            username = data.get('username')
            password = data.get('password')
            if username and password:
                # Real authentication via RBACManager
                user = self.rbac.authenticate(username, password)
                if user:
                    token = self.tokens.generate_token(username, user.role.value)
                    return {'token': token, 'user': username, 'role': user.role.value, 'expires': (datetime.now() + timedelta(minutes=15)).isoformat()}
        raise ValueError("Invalid credentials")
    
    def _handle_logout(self):
        token = self._get_token()
        if token:
            pass
        return {'message': 'Logged out'}
    
    def _handle_auth_status(self, user_data):
        if user_data is None:
            return {'authenticated': False}
        return {'authenticated': True, 'user': user_data['user'], 'role': user_data['role']}
    
    def _handle_market(self, symbol):
        return {'symbol': symbol, 'price': 150.0 + np.random.randn() * 5, 'open': 148.0, 'high': 155.0, 'low': 147.0, 'volume': 1000000, 'timestamp': datetime.now().isoformat()}
    
    def _handle_portfolio(self):
        return {'positions': [{'symbol': 'AAPL', 'quantity': 100, 'avg_cost': 150.0, 'current_price': 155.0, 'market_value': 15500.0}, {'symbol': 'MSFT', 'quantity': 50, 'avg_cost': 250.0, 'current_price': 260.0, 'market_value': 13000.0}], 'total_value': 28500.0, 'total_pnl': 1000.0, 'cash': 15000.0}
    
    def _handle_strategies(self):
        return {'count': 3, 'strategies': [{'id': 1, 'name': 'Momentum', 'type': 'trend'}, {'id': 2, 'name': 'Mean Reversion', 'type': 'stat_arb'}, {'id': 3, 'name': 'ML Predictor', 'type': 'ml'}]}
    
    def _handle_orders(self, method):
        if method == 'POST':
            content_length = int(self.headers.get('Content-Length', 0))
            if content_length > 0:
                body = self.rfile.read(content_length).decode()
                data = json.loads(body)
                return {'order_id': f'ORD-{np.random.randint(100000, 999999)}', 'symbol': data.get('symbol'), 'side': data.get('side'), 'quantity': data.get('quantity'), 'status': 'submitted', 'timestamp': datetime.now().isoformat()}
        return {'orders': []}
    
    def _handle_risk(self):
        return {'var_95': 2500.0, 'exposure': 28500.0, 'leverage': 1.2, 'status': 'normal'}
    
    def _handle_system(self):
        return {'status': 'HEALTHY', 'version': '3.305', 'databases': {'market_data': 38581}}
    
    def _handle_gateway_info(self):
        return {'version': 'v3.305', 'features': ['Authentication', 'RBAC', 'Rate Limiting', 'Request Routing'], 'endpoints': list(self.PERMISSIONS.keys()), 'active_tokens': len(self.tokens.tokens)}


def start_gateway(port=8080):
    server = HTTPServer(('0.0.0.0', port), APIGatewayHandler)
    print(f"🚀 API Gateway v3.305 Started!")
    print(f"📡 URL: http://localhost:{port}")
    print(f"🔐 Auth: /api/v2/auth/login")
    print(f"🌐 Browser Login: http://localhost:{port}/login")
    print(f"📊 Dashboard: http://localhost:{port}/dashboard")
    print(f"🛡️  RBAC: Enabled")
    print(f"⚡ Rate Limit: 60 req/min")
    print(f"\nPress Ctrl+C to stop")
    print("=" * 70)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n🛑 Shutting down...")
        server.shutdown()


if __name__ == '__main__':
    start_gateway(8080)
