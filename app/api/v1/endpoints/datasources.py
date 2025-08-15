from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Query, Header
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.api import deps
from app.schemas.datasource import DataSource, DataSourceCreate, DataSourceUpdate
from app.models.datasource import DataSource as DataSourceModel
from app.core.template_manager import leek_template_manager
from app.core.engine import engine_manager
from app.api.deps import get_project_id
from leek_core.base import create_component,load_class_from_str

class DataSourceBase(BaseModel):
    name: str
    description: Optional[str]
    class_name: str
    params: Optional[Dict[str, Any]]
    
class DataSourceExe(BaseModel):
    class_name: str
    params: Optional[Dict[str, Any]]

router = APIRouter()

@router.get("/datasources", response_model=List[DataSource])
def list_datasources(
    db: Session = Depends(deps.get_db_session),
    skip: int = 0,
    limit: int = 100,
    project_id: int = Depends(get_project_id),
    enable: bool = None
):
    query = db.query(DataSourceModel)
    query = query.filter(DataSourceModel.project_id == project_id)
    if enable is not None:
        query = query.filter(DataSourceModel.is_enabled == enable)
    query = query.order_by(DataSourceModel.created_at.desc())
    # limit=0 时返回全部
    if limit is not None and limit > 0:
        query = query.offset(skip).limit(limit)
    datasources = query.all()
    return datasources

@router.post("/datasources", response_model=DataSource)
async def create_datasource(
    datasource: DataSourceBase,
    db: Session = Depends(deps.get_db_session),
    project_id: int = Depends(get_project_id)
):
    datasource_model = DataSourceModel(**datasource.model_dump())
    datasource_model.project_id = project_id
    db.add(datasource_model)
    db.commit()
    db.refresh(datasource_model)
    client = engine_manager.get_client(project_id=project_id)
    if client:
        await client.add_data_source(datasource_model.dumps_map())
    return datasource_model

@router.get("/datasources/{datasource_id}", response_model=DataSource)
def get_datasource(
    *,
    db: Session = Depends(deps.get_db_session),
    project_id: int = Depends(get_project_id),
    datasource_id: int
):
    datasource = db.query(DataSourceModel).filter(DataSourceModel.id == datasource_id, DataSourceModel.project_id == project_id).first()
    if not datasource:
        raise HTTPException(status_code=404, detail="DataSource not found")
    return datasource

@router.put("/datasources/{datasource_id}", response_model=DataSource)
async def update_datasource(
    *,
    db: Session = Depends(deps.get_db_session),
    datasource_id: int,
    project_id: int = Depends(get_project_id),
    datasource_in: DataSourceUpdate
):
    datasource = db.query(DataSourceModel).filter(DataSourceModel.id == datasource_id, DataSourceModel.project_id == project_id).first()
    if not datasource:
        raise HTTPException(status_code=404, detail="DataSource not found")
    update_data = datasource_in.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(datasource, field, value)
    db.commit()
    db.refresh(datasource)
    client = engine_manager.get_client(project_id=project_id)
    if client:
        if datasource.is_enabled:
            await client.update_data_source(datasource.dumps_map())
        else:
            await client.remove_data_source(datasource.id)
    return datasource

@router.delete("/datasources/{datasource_id}")
async def delete_datasource(
    *,
    db: Session = Depends(deps.get_db_session),
    project_id: int = Depends(get_project_id),
    datasource_id: int
):
    datasource = db.query(DataSourceModel).filter(DataSourceModel.id == datasource_id, DataSourceModel.project_id == project_id).first()
    if not datasource:
        raise HTTPException(status_code=404, detail="DataSource not found")
    db.delete(datasource)
    db.commit()
    client = engine_manager.get_client(project_id=project_id)
    if client:
        await client.remove_data_source(datasource.id)
    return {"status": "success"}

@router.get("/templates/datasource")
async def get_datasource_templates(
    project_id: int = Depends(get_project_id),
    just_backtest: bool | None = Query(None)
):
    items = await leek_template_manager.get_datasource_templates(project_id)
    # 过滤逻辑：
    # - 未传时仅返回非回测专用（正式）
    # - 传 true 时仅回测专用
    # - 传 false 时仅非回测专用
    if just_backtest is None:
        return [x for x in items if not getattr(x, 'just_backtest', False)]
    return [x for x in items if (getattr(x, 'just_backtest', False) is True) == (just_backtest is True)]
    
@router.post("/templates/datasource")
async def exe_datasource_templates(datasource: DataSourceExe, project_id: int = Depends(get_project_id)):

    component = create_component(cls=load_class_from_str(datasource.class_name), **datasource.params)
    from leek_core.data import DataSource
    assert isinstance(component, DataSource)
    return await leek_template_manager.convert_init_params(component.get_supported_parameters())
