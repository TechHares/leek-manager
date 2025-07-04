from fastapi import APIRouter, Depends, HTTPException
from typing import Dict, Any
import psutil
import os
import requests
import logging
from app.core.config import settings
from app.core.engine import engine_manager
from app.api.deps import get_current_user
from app.models.project import Project
from app.api.deps import get_project_id
from app.models.user import User
from sqlalchemy.orm import Session
from leek_core import __version__ as core_version
import time
from app.api import deps

router = APIRouter()
logger = logging.getLogger(__name__)
_version_cache = [0, "未获取到", "..."]

@router.get("/dashboard/overview", response_model=Dict[str, Any])
async def get_dashboard_overview(current_user: User = Depends(get_current_user), db: Session = Depends(deps.get_db), project_id: int = Depends(get_project_id)):
    try:
        engine = engine_manager.get_client(project_id)
        if engine is None:
            return {
                "core_version": core_version,
            "sys_version": settings.VERSION,
            }
        engine_state = await engine.invoke("engine_state")
        global _version_cache
        if time.time() - _version_cache[0] > 12*3600:
            try:
                version, body = await new_version()
                _version_cache = [time.time(), version, body]
            except Exception as e:
                _version_cache[0] = time.time()
        return {
            "core_version": core_version,
            "sys_version": settings.VERSION,
            "version": _version_cache[1],
            "body": _version_cache[2],
            "resources": engine_state.get("resources", {}),
            "state": engine_state.get("state", {}),
        }
    except Exception as e:
        logger.error(f"Dashboard overview error: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"获取系统信息失败: {str(e)}"
        ) 

async def new_version():
    res = requests.get('https://api.github.com/repos/TechHares/leek/releases/latest')
    js = res.json()
    print(js)
    return js['tag_name'][1:], js["body"]