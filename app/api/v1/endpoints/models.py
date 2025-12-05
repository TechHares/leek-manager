from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from typing import Optional, List
from pathlib import Path
import os
import io
import joblib

from app.api import deps
from app.models.model import Model as ModelModel
from app.schemas.model import ModelOut, ModelCreate, ModelUpdate, ModelUpload
from app.schemas.common import PageResponse
from app.core.config_manager import config_manager
from leek_core.utils import get_logger

logger = get_logger(__name__)

router = APIRouter()

@router.get("/models", response_model=PageResponse[ModelOut])
async def list_models(
    db: Session = Depends(deps.get_db_session),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=2000),
    project_id: int = Depends(deps.get_project_id),
    name: Optional[str] = None,
    version: Optional[str] = None
):
    query = db.query(ModelModel)
    query = query.filter(ModelModel.project_id == project_id)
    query = query.filter(ModelModel.is_deleted == False)
    
    if name:
        query = query.filter(ModelModel.name.like(f"%{name}%"))
    if version:
        query = query.filter(ModelModel.version == version)
    
    total = query.count()
    items = (
        query.order_by(ModelModel.created_at.desc())
        .offset((page - 1) * size)
        .limit(size)
        .all()
    )
    
    return PageResponse(total=total, page=page, size=size, items=items)

@router.post("/models", response_model=ModelOut)
async def create_model(
    model: ModelCreate,
    db: Session = Depends(deps.get_db_session),
    project_id: int = Depends(deps.get_project_id)
):
    """创建模型记录（通常由训练任务调用）"""
    # 验证 file_path 必须是绝对路径
    file_path = Path(model.file_path)
    if not file_path.is_absolute():
        raise HTTPException(status_code=400, detail="file_path must be an absolute path")
    
    data = model.model_dump()
    data["project_id"] = project_id
    model_record = ModelModel(**data)
    db.add(model_record)
    db.commit()
    db.refresh(model_record)
    return model_record

@router.post("/models/upload", response_model=ModelOut)
async def upload_model(
    file: UploadFile = File(...),
    name: str = Form(...),
    version: str = Form(...),
    description: Optional[str] = Form(None),
    db: Session = Depends(deps.get_db_session),
    project_id: int = Depends(deps.get_project_id)
):
    """上传模型文件"""
    # 验证文件扩展名
    if not file.filename.endswith('.joblib'):
        raise HTTPException(status_code=400, detail="Only .joblib files are supported")
    
    # 验证文件内容（尝试加载）
    try:
        file_content = await file.read()
        joblib.load(io.BytesIO(file_content))
        await file.seek(0)  # Reset file pointer
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid model file: {e}")
    
    # 创建模型记录
    model_record = ModelModel(
        name=name,
        version=version,
        description=description,
        project_id=project_id,
        file_path="",  # Will be set after saving file
        file_size=len(file_content)
    )
    db.add(model_record)
    db.commit()
    db.refresh(model_record)
    
    # 保存文件
    models_dir = config_manager.get_models_dir()
    file_path = models_dir / f"{model_record.id}_{version}.joblib"
    
    with open(file_path, 'wb') as f:
        f.write(file_content)
    
    # 更新文件路径（全路径）
    model_record.file_path = str(file_path)
    db.commit()
    db.refresh(model_record)
    
    return model_record

@router.get("/models/{model_id}", response_model=ModelOut)
async def get_model(
    model_id: int,
    db: Session = Depends(deps.get_db_session),
    project_id: int = Depends(deps.get_project_id)
):
    model = db.query(ModelModel).filter(
        ModelModel.id == model_id,
        ModelModel.project_id == project_id
    ).first()
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")
    return model

@router.get("/models/{model_id}/download")
async def download_model(
    model_id: int,
    db: Session = Depends(deps.get_db_session),
    project_id: int = Depends(deps.get_project_id)
):
    """下载模型文件"""
    model = db.query(ModelModel).filter(
        ModelModel.id == model_id,
        ModelModel.project_id == project_id
    ).first()
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")
    
    # file_path 必须是绝对路径
    file_path = Path(model.file_path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Model file not found")
    
    return FileResponse(
        path=str(file_path),
        filename=f"{model.name}_{model.version}.joblib",
        media_type="application/octet-stream"
    )

@router.put("/models/{model_id}", response_model=ModelOut)
async def update_model(
    model_id: int,
    model_update: ModelUpdate,
    db: Session = Depends(deps.get_db_session),
    project_id: int = Depends(deps.get_project_id)
):
    model = db.query(ModelModel).filter(
        ModelModel.id == model_id,
        ModelModel.project_id == project_id
    ).first()
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")
    
    update_data = model_update.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(model, field, value)
    
    db.commit()
    db.refresh(model)
    return model

@router.delete("/models/{model_id}")
async def delete_model(
    model_id: int,
    db: Session = Depends(deps.get_db_session),
    project_id: int = Depends(deps.get_project_id)
):
    model = db.query(ModelModel).filter(
        ModelModel.id == model_id,
        ModelModel.project_id == project_id
    ).first()
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")
    
    # 删除文件（file_path 必须是绝对路径）
    file_path = Path(model.file_path)
    if file_path.exists():
        try:
            os.remove(file_path)
        except Exception as e:
            logger.warning(f"Failed to delete model file {file_path}: {e}")
    
    model.is_deleted = True
    db.commit()
    return {"status": "success"}

