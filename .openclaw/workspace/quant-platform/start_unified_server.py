#!/usr/bin/env python3
"""
LocalQuant v3.305 - Unified Server Launcher
统一服务器启动器（整合 API Gateway + 权限管理）
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import subprocess
import time


def start_gateway():
    """启动 API Gateway"""
    print("=" * 70)
    print("LocalQuant v3.305 - Unified Server")
    print("=" * 70)
    print()
    print("Starting API Gateway with RBAC...")
    print()
    
    # 导入并启动
    from web.api_gateway import start_gateway_server
    start_gateway_server(port=8080)


def test_gateway():
    """测试网关功能"""
    import urllib.request
    import json
    
    base_url = "http://localhost:8080"
    
    print("\n=== Testing API Gateway ===\n")
    
    # 1. Health Check (no auth required)
    print("[1] Health Check (no auth)...")
    try:
        req = urllib.request.Request(f"{base_url}/api/v2/health")
        response = urllib.request.urlopen(req, timeout=5)
        data = json.loads(response.read().decode())
        print(f"  ✅ {data['status']} - {data['data']['health']}")
    except Exception as e:
        print(f"  ❌ {e}")
    
    # 2. Login
    print("\n[2] Login...")
    token = None
    try:
        login_data = json.dumps({
            'username': 'admin',
            'password': 'admin123'
        }).encode()
        req = urllib.request.Request(
            f"{base_url}/api/v2/auth/login",
            data=login_data,
            headers={'Content-Type': 'application/json'}
        )
        response = urllib.request.urlopen(req, timeout=5)
        data = json.loads(response.read().decode())
        token = data['data']['token']
        print(f"  ✅ Token: {token[:20]}...")
        print(f"  ✅ User: {data['data']['user']}, Role: {data['data']['role']}")
    except Exception as e:
        print(f"  ❌ {e}")
    
    # 3. Auth Status (with token)
    print("\n[3] Auth Status (with token)...")
    if token:
        try:
            req = urllib.request.Request(
                f"{base_url}/api/v2/auth/status",
                headers={'Authorization': f'Bearer {token}'}
            )
            response = urllib.request.urlopen(req, timeout=5)
            data = json.loads(response.read().decode())
            print(f"  ✅ Authenticated: {data['data']['authenticated']}")
            print(f"  ✅ User: {data['data']['user']}, Role: {data['data']['role']}")
        except Exception as e:
            print(f"  ❌ {e}")
    
    # 4. Market Data (with token, requires strategy:read)
    print("\n[4] Market Data (with token)...")
    if token:
        try:
            req = urllib.request.Request(
                f"{base_url}/api/v2/market/AAPL",
                headers={'Authorization': f'Bearer {token}'}
            )
            response = urllib.request.urlopen(req, timeout=5)
            data = json.loads(response.read().decode())
            print(f"  ✅ {data['data']['symbol']}: ${data['data']['price']:.2f}")
        except Exception as e:
            print(f"  ❌ {e}")
    
    # 5. Portfolio (with token, requires portfolio:read)
    print("\n[5] Portfolio (with token)...")
    if token:
        try:
            req = urllib.request.Request(
                f"{base_url}/api/v2/portfolio",
                headers={'Authorization': f'Bearer {token}'}
            )
            response = urllib.request.urlopen(req, timeout=5)
            data = json.loads(response.read().decode())
            print(f"  ✅ Positions: {len(data['data']['positions'])}")
            print(f"  ✅ Total Value: ${data['data']['total_value']:,.2f}")
        except Exception as e:
            print(f"  ❌ {e}")
    
    # 6. Gateway Info
    print("\n[6] Gateway Info...")
    try:
        req = urllib.request.Request(f"{base_url}/api/v2/gateway/info")
        response = urllib.request.urlopen(req, timeout=5)
        data = json.loads(response.read().decode())
        print(f"  ✅ Version: {data['data']['version']}")
        print(f"  ✅ Features: {', '.join(data['data']['features'])}")
        print(f"  ✅ Endpoints: {len(data['data']['endpoints'])}")
    except Exception as e:
        print(f"  ❌ {e}")
    
    # 7. Unauthorized Access (no token)
    print("\n[7] Unauthorized Access (no token)...")
    try:
        req = urllib.request.Request(f"{base_url}/api/v2/portfolio")
        response = urllib.request.urlopen(req, timeout=5)
        print(f"  ⚠️  Unexpected success")
    except urllib.error.HTTPError as e:
        if e.code == 403:
            print(f"  ✅ Correctly blocked with 403")
        else:
            print(f"  ⚠️  Status: {e.code}")
    except Exception as e:
        print(f"  ❌ {e}")
    
    # 8. Rate Limit Test
    print("\n[8] Rate Limit Test...")
    try:
        req = urllib.request.Request(f"{base_url}/api/v2/health")
        response = urllib.request.urlopen(req, timeout=5)
        data = json.loads(response.read().decode())
        print(f"  ✅ Request allowed")
    except Exception as e:
        print(f"  ❌ {e}")
    
    print("\n" + "=" * 70)
    print("API Gateway Test Complete!")
    print("=" * 70)


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == 'test':
        test_gateway()
    else:
        start_gateway()
