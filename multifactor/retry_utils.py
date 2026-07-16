"""
API 重试装饰器 - 指数退避重试机制
支持网络超时、API 限流、临时错误自动重试
"""

import time
import logging
from functools import wraps
from typing import Callable, Optional

logger = logging.getLogger('retry')


class RetryConfig:
    """重试配置"""
    DEFAULT_MAX_RETRIES = 3
    DEFAULT_BACKOFF_FACTOR = 2.0  # 指数退避基数
    DEFAULT_BASE_DELAY = 1.0      # 初始延迟（秒）
    DEFAULT_MAX_DELAY = 60.0      # 最大延迟（秒）
    
    # 可重试的异常类型
    RETRIABLE_EXCEPTIONS = (
        ConnectionError,
        TimeoutError,
        Exception,  # 兜底
    )


def retry_with_backoff(
    max_retries: int = RetryConfig.DEFAULT_MAX_RETRIES,
    backoff_factor: float = RetryConfig.DEFAULT_BACKOFF_FACTOR,
    base_delay: float = RetryConfig.DEFAULT_BASE_DELAY,
    max_delay: float = RetryConfig.DEFAULT_MAX_DELAY,
    retriable_exceptions: tuple = RetryConfig.RETRIABLE_EXCEPTIONS,
    on_retry: Optional[Callable] = None
):
    """
    指数退避重试装饰器
    
    参数:
        max_retries: 最大重试次数
        backoff_factor: 退避基数
        base_delay: 初始延迟
        max_delay: 最大延迟
        retriable_exceptions: 可重试的异常类型
        on_retry: 重试回调函数 (exception, retry_count) -> None
    
    使用示例:
        @retry_with_backoff(max_retries=3)
        def api_call():
            return requests.get(url)
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                    
                except retriable_exceptions as e:
                    last_exception = e
                    
                    if attempt >= max_retries:
                        logger.error(f"❌ {func.__name__} 重试 {max_retries} 次后仍失败: {e}")
                        raise
                    
                    # 计算退避延迟
                    delay = min(base_delay * (backoff_factor ** attempt), max_delay)
                    
                    logger.warning(
                        f"⚠️ {func.__name__} 失败 ({attempt+1}/{max_retries+1}): {e}. "
                        f"{delay:.1f}秒后重试..."
                    )
                    
                    if on_retry:
                        try:
                            on_retry(e, attempt + 1)
                        except Exception:
                            pass
                    
                    time.sleep(delay)
            
            # 理论上不会到达这里
            raise last_exception if last_exception else RuntimeError("Unknown error")
        
        return wrapper
    return decorator


def retry_for_alpaca(func):
    """
    Alpaca API 专用重试装饰器
    处理 Alpaca 特定的限流和错误
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        max_retries = 5
        base_delay = 1.0
        
        for attempt in range(max_retries + 1):
            try:
                return func(*args, **kwargs)
                
            except Exception as e:
                error_str = str(e).lower()
                
                # 检查是否可重试
                retriable = any([
                    'rate limit' in error_str,
                    'too many requests' in error_str,
                    'timeout' in error_str,
                    'connection' in error_str,
                    '503' in error_str,  # Service Unavailable
                    '502' in error_str,  # Bad Gateway
                    '429' in error_str,  # Too Many Requests
                ])
                
                if not retriable or attempt >= max_retries:
                    raise
                
                # Alpaca 限流时等待更久
                if 'rate limit' in error_str or '429' in error_str:
                    delay = min(60, base_delay * (2 ** attempt))
                    logger.warning(f"⏱️ Alpaca 限流，等待 {delay:.0f} 秒后重试...")
                else:
                    delay = min(30, base_delay * (2 ** attempt))
                    logger.warning(f"🔄 Alpaca 错误，{delay:.1f}秒后重试 ({attempt+1}/{max_retries+1})...")
                
                time.sleep(delay)
        
        raise RuntimeError(f"Alpaca API 调用失败")
    
    return wrapper


# ============================================================
# 应用示例
# ============================================================

if __name__ == '__main__':
    import random
    
    # 测试重试装饰器
    @retry_with_backoff(max_retries=3, base_delay=0.5)
    def unstable_api():
        """模拟不稳定的 API"""
        if random.random() < 0.7:  # 70% 失败率
            raise ConnectionError("网络超时")
        return "成功！"
    
    try:
        result = unstable_api()
        print(f"结果: {result}")
    except Exception as e:
        print(f"最终失败: {e}")
    
    # 测试 Alpaca 专用重试
    @retry_for_alpaca
    def alpaca_api():
        if random.random() < 0.5:
            raise Exception("rate limit exceeded")
        return "Alpaca 成功"
    
    try:
        result = alpaca_api()
        print(f"Alpaca 结果: {result}")
    except Exception as e:
        print(f"Alpaca 最终失败: {e}")
