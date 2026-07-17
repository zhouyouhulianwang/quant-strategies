"""
速率限制器 - 防止 Alpaca API 触发 429 限制
使用线程安全的 Token Bucket 算法
"""

import time
import threading
import logging
from functools import wraps

# P2修复：统一全链路日志格式

logger = logging.getLogger(__name__)


class TokenBucket:
    """
    线程安全的 Token Bucket 速率限制器
    
    使用:
        bucket = TokenBucket(rate=200, capacity=200)  # 每秒 200 请求，最大突发 200
        with bucket:
            api.call()
    """
    
    def __init__(self, rate=200.0, capacity=200.0, burst=50.0):
        """
        初始化
        
        参数:
            rate: float, 每秒允许的平均请求数 (Alpaca 免费账户约 200/min ≈ 3.3/sec)
            capacity: float, 桶容量（最大突发数）
            burst: float, 兼容参数，同 capacity
        """
        self.rate = float(rate)
        self.capacity = float(capacity or burst)
        self.tokens = self.capacity
        self.last_update = time.time()
        self._lock = threading.Lock()
    
    def _add_tokens(self):
        """根据时间流逝添加 token"""
        now = time.time()
        elapsed = now - self.last_update
        self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
        self.last_update = now
    
    def acquire(self, tokens=1.0, timeout=None):
        """
        获取 token，必要时等待
        
        参数:
            tokens: float, 需要获取的 token 数
            timeout: float, 最大等待时间（秒），None 表示无限等待
        
        返回:
            bool: 是否成功获取
        """
        end_time = time.time() + timeout if timeout is not None else None
        
        while True:
            with self._lock:
                self._add_tokens()
                
                if self.tokens >= tokens:
                    self.tokens -= tokens
                    return True
                
                # 计算需要等待的时间
                need = tokens - self.tokens
                wait_time = need / self.rate if self.rate > 0 else 1.0
            
            if end_time is not None and time.time() + wait_time > end_time:
                return False
            
            logger.debug(f"速率限制: 等待 {wait_time:.3f} 秒")
            time.sleep(wait_time)
    
    def __enter__(self):
        self.acquire()
        return self
    
    def __exit__(self, *args):
        return False


class RateLimitedAPI:
    """
    Alpaca REST API 的速率限制包装器
    
    包装所有 API 调用，自动 acquire token
    """
    
    # Alpaca 免费账户限制: 200 请求 / 分钟
    DEFAULT_RATE_PER_MIN = 200
    
    def __init__(self, api, rate_per_min=None):
        """
        初始化
        
        参数:
            api: Alpaca REST 实例
            rate_per_min: int, 每分钟最大请求数，默认 200
        """
        self._api = api
        self._bucket = TokenBucket(
            rate=(rate_per_min or self.DEFAULT_RATE_PER_MIN) / 60.0,
            capacity=(rate_per_min or self.DEFAULT_RATE_PER_MIN) / 2.0
        )
    
    def __getattr__(self, name):
        """
        代理到真实 API，但在调用前获取 token
        """
        attr = getattr(self._api, name)
        
        if callable(attr):
            @wraps(attr)
            def wrapper(*args, **kwargs):
                # 获取 token
                self._bucket.acquire()
                return attr(*args, **kwargs)
            return wrapper
        
        return attr


# 全局默认速率限制器（用于非 API 调用的通用限速）
_default_bucket = TokenBucket(rate=3.0, capacity=10.0)


def rate_limited(rate=3.0, capacity=10.0):
    """
    装饰器：给函数加上速率限制
    
    使用:
        @rate_limited(rate=3.0, capacity=10.0)
        def my_func():
            pass
    """
    bucket = TokenBucket(rate=rate, capacity=capacity)
    
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            bucket.acquire()
            return func(*args, **kwargs)
        return wrapper
    return decorator
