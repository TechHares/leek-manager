from fastapi import FastAPI, status, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from leek_core import engine
from app.api.v1.endpoints import config, auth, users, rbac, projects, executors, datasources, position, strategies, signal, order, dashboard, transaction
from app.middlewares.system_permission import system_permission_middleware
import sys
from app.core.engine import engine_manager, start_engine_manager
from app.core.scheduler import scheduler
from app.core.config_manager import config_manager
import asyncio
from contextlib import asynccontextmanager
import os
import logging
from leek_core.utils import get_logger
import time
from starlette.middleware.base import BaseHTTPMiddleware

logger = get_logger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("lifespan: 应用启动")
    # 启动时
    engine_task = asyncio.create_task(start_engine_manager())
    # 启动调度器
    scheduler.start()
    logger.info("lifespan: 启动完成，进入yield")
    yield
    logger.info("lifespan: 收到关闭信号，开始清理")
    # 关闭时
    engine_task.cancel()
    try:
        await engine_task
    except asyncio.CancelledError:
        logger.info("lifespan: 引擎任务已取消")
    # 关闭调度器
    scheduler.shutdown()
    logger.info("lifespan: 应用关闭完成")

# 配置日志级别，减少 uvicorn 的日志输出
logging.getLogger("uvicorn").setLevel(logging.ERROR)
logging.getLogger("uvicorn.access").setLevel(logging.ERROR)
logging.getLogger("uvicorn.error").setLevel(logging.ERROR)

app = FastAPI(
    title="Leek Manager API",
    description="API for Leek Manager application",
    version="1.0.0",
    lifespan=lifespan
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, replace with specific origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 统计接口耗时的中间件
class TimingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        start_time = time.time()
        response = await call_next(request)
        process_time = (time.time() - start_time) * 1000  # 毫秒
        logger.info(f"接口 {request.url.path} 耗时: {process_time:.2f} ms")
        response.headers["X-Process-Time"] = str(process_time)
        return response

# 注册全局系统级权限中间件
app.add_middleware(TimingMiddleware)
app.middleware("http")(system_permission_middleware)

# Include routers
app.include_router(config.router, prefix="/api/v1", tags=["configuration"])
app.include_router(auth.router, prefix="/api/v1/auth", tags=["authentication"])
app.include_router(users.router, prefix="/api/v1", tags=["users"])
app.include_router(rbac.router, prefix="/api/v1", tags=["rbac"])
app.include_router(projects.router, prefix="/api/v1", tags=["projects"]) 
app.include_router(executors.router, prefix="/api/v1", tags=["executors"])
app.include_router(datasources.router, prefix="/api/v1", tags=["datasources"])
app.include_router(position.router, prefix="/api/v1", tags=["position"])

app.include_router(strategies.router, prefix="/api/v1", tags=["strategies"])
app.include_router(signal.router, prefix="/api/v1", tags=["signal"])
app.include_router(order.router, prefix="/api/v1", tags=["order"])
app.include_router(transaction.router, prefix="/api/v1", tags=["transaction"])
app.include_router(dashboard.router, prefix="/api/v1", tags=["dashboard"])

# 静态文件服务
static_dir = os.path.join(os.path.dirname(__file__), "..", "static")
no_static = not os.path.exists(static_dir)
if no_static:
    logger.warning("前端未构建，将没有页面， 只有api服务...")
else:
    app.mount("/assets", StaticFiles(directory=os.path.join(static_dir, "assets")), name="assets")
    app.mount("/favicon.ico", StaticFiles(directory=static_dir), name="favicon")
    app.mount("/img", StaticFiles(directory=os.path.join(static_dir, "img")), name="img")

@app.get("/api/health")
async def health_check():
    return {"status": "healthy"}

# 处理 Vue 路由 - 所有非 API 请求都返回 index.html
@app.get("/{full_path:path}")
async def serve_spa(full_path: str):
    # 如果是 API 请求，不处理
    if full_path.startswith("api/") or no_static:
        raise HTTPException(status_code=404, detail="Not found")
    
    # 返回 index.html，让 Vue 路由处理
    static_dir = os.path.join(os.path.dirname(__file__), "..", "static")
    index_path = os.path.join(static_dir, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    else:
        raise HTTPException(status_code=404, detail="Not found")

scheduler.add_cron_job(func=engine_manager.storage_position_image, hour="*", minute="0", second="0", id="asset_snapshot_hourly", name="资产快照每小时生成任务")

