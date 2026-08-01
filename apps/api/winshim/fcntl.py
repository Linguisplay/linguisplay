# 🪟 Windows 垫片: fcntl 是 Unix 专属, 生产 (Linux) 真锁, 本机开发/测试拿这个
# 无操作垫片顶上 — flock 在单人 dev 场景语义上安全 (没有第二个进程抢同一把锁)。
# 用法: 把本目录挂进 PYTHONPATH (smoke_client.js 已内置; pytest 见 conftest)。
# ⚠️ 只许进 PYTHONPATH, 绝不许 import 路径常驻生产代码。
LOCK_EX = 2
LOCK_SH = 1
LOCK_NB = 4
LOCK_UN = 8


def flock(fd, operation):   # noqa: ARG001 — 单机 dev 无锁可争
    return None


def lockf(fd, operation, *a, **k):   # noqa: ARG001
    return None


def fcntl(fd, op, arg=0):   # noqa: ARG001
    return 0


def ioctl(fd, request, arg=0, mutate_flag=True):   # noqa: ARG001
    return 0
