import asyncio
from contextlib import contextmanager

@contextmanager
def leek_loop():
    """事件循环上下文管理器"""
    loop_created = False
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError("Event loop is closed")
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop_created = True
    
    try:
        yield loop
    finally:
        if loop_created and not loop.is_closed():
            loop.close()