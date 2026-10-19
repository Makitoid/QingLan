"""登录失败的进程内节流（C-01 补偿控制）。

产品要求保留全站统一初始密码，因此无法用 per-user 随机口令消除「同学之间
互相撞号」的风险；这里用两道限制抬高成本：

- 账号维度：连续失败达到阈值后指数退避（30s 起，最长 15 分钟），
  退避期内即使密码正确也先返回 423，避免在线爆破；
- IP 维度：滑动窗口内失败次数过多返回 429，抑制同一来源的密码喷洒。

状态只在本进程内存中，重启即清零；多副本部署时应换成 Redis 等共享存储。
"""
from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass

from . import config

_LOCK = threading.Lock()


@dataclass
class _AccountState:
    failures: int = 0
    locked_until: float = 0.0


_accounts: dict[str, _AccountState] = {}
_ip_failures: dict[str, deque[float]] = {}
# 防御性上限：账号/IP 字典不会因随机用户名无限膨胀
_MAX_KEYS = 10_000


def _prune(now: float) -> None:
    """清理已解锁且长时间无失败的账号、以及过期的 IP 窗口。"""
    stale = [key for key, state in _accounts.items()
             if state.locked_until <= now and state.failures == 0]
    for key in stale:
        _accounts.pop(key, None)
    window = config.LOGIN_IP_WINDOW_S
    for key in list(_ip_failures):
        bucket = _ip_failures[key]
        while bucket and bucket[0] <= now - window:
            bucket.popleft()
        if not bucket:
            _ip_failures.pop(key, None)


def _bounded_set(store: dict, key: str, value) -> None:
    if key not in store and len(store) >= _MAX_KEYS:
        # 极端情况下丢弃最早插入的一项，保证内存有界
        store.pop(next(iter(store)), None)
    store[key] = value


def check(account: str, ip: str) -> tuple[str, int] | None:
    """返回 (限制类型, 需等待秒数)；未命中限制时返回 None。"""
    if not config.LOGIN_THROTTLE_ENABLED:
        return None
    now = time.monotonic()
    key = account.strip().lower()
    with _LOCK:
        _prune(now)
        state = _accounts.get(key)
        if state and state.locked_until > now:
            return "account", max(1, int(state.locked_until - now + 0.999))
        bucket = _ip_failures.get(ip)
        if bucket:
            while bucket and bucket[0] <= now - config.LOGIN_IP_WINDOW_S:
                bucket.popleft()
            if len(bucket) >= config.LOGIN_IP_FAILURE_THRESHOLD:
                retry = max(1, int(bucket[0] + config.LOGIN_IP_WINDOW_S - now + 0.999))
                return "ip", retry
    return None


def record_failure(account: str, ip: str) -> tuple[str, int] | None:
    """记录一次失败；若本次触发了新的锁定，返回 (类型, 等待秒数)。"""
    if not config.LOGIN_THROTTLE_ENABLED:
        return None
    now = time.monotonic()
    key = account.strip().lower()
    triggered: tuple[str, int] | None = None
    with _LOCK:
        _prune(now)
        state = _accounts.get(key) or _AccountState()
        state.failures += 1
        if state.failures >= config.LOGIN_ACCOUNT_FAILURE_THRESHOLD:
            exponent = state.failures - config.LOGIN_ACCOUNT_FAILURE_THRESHOLD
            lock_s = min(config.LOGIN_ACCOUNT_LOCK_BASE_S * (2 ** exponent),
                         config.LOGIN_ACCOUNT_LOCK_MAX_S)
            state.locked_until = now + lock_s
            triggered = ("account", lock_s)
        _bounded_set(_accounts, key, state)

        bucket = _ip_failures.get(ip)
        if bucket is None:
            bucket = deque()
            _bounded_set(_ip_failures, ip, bucket)
        bucket.append(now)
        while bucket and bucket[0] <= now - config.LOGIN_IP_WINDOW_S:
            bucket.popleft()
        if len(bucket) >= config.LOGIN_IP_FAILURE_THRESHOLD:
            retry = max(1, int(bucket[0] + config.LOGIN_IP_WINDOW_S - now + 0.999))
            triggered = triggered or ("ip", retry)
    return triggered


def record_success(account: str, ip: str) -> None:
    if not config.LOGIN_THROTTLE_ENABLED:
        return
    key = account.strip().lower()
    with _LOCK:
        # 只清该账号的失败计数；IP 维度的失败窗口保留，
        # 避免攻击者用自己账号登录成功一次就把同 IP 的喷洒记录抹掉。
        _accounts.pop(key, None)


def reset_all() -> None:
    """测试与运维用：清空全部节流状态。"""
    with _LOCK:
        _accounts.clear()
        _ip_failures.clear()
