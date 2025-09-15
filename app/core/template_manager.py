import os
import importlib
from pathlib import Path
import inspect
from typing import Dict, List, Type, Set, TypeVar, Generic, Optional
from leek_core.base import LeekComponent
from leek_core.utils import get_logger
from abc import ABC
from app.schemas.template import TemplateResponse, ParameterField, FieldType, ChoiceType
from leek_core.data import *
from leek_core.executor import *
from leek_core.strategy import *
from leek_core.info_fabricator import *
 
from leek_core.policy import *
from leek_core.risk import *
from app.db.session import db_connect
from app.models.project_config import ProjectConfig
import sys
from asyncio import Lock

BASE_DIR = Path(__file__).parent.parent.parent.parent

logger = get_logger(__name__)

T = TypeVar('T')

class TemplateManager:
    def __init__(self, allowed_types: Set[Type] = None):
        self.templates: Dict[str, List[Type]] = {}  # 按目录存储模板
        self.allowed_types = allowed_types or set()
        self.default_templates: List[Type] = None

    def _is_allowed_type(self, template_type: Type) -> bool:
        """
        检查模板类型是否在允许的类型列表中，并且不是抽象类
        参数:
            template_type: 要检查的模板类型
        返回:
            如果类型被允许且不是抽象类则返回True，否则返回False
        """
        if not self.allowed_types:
            return True
        if inspect.isabstract(template_type):
            return False
        return any(issubclass(template_type, allowed_type) for allowed_type in self.allowed_types)

    def scan_module(self, module_path: str) -> List[Type]:
        """
        扫描指定模块中的所有类
        参数:
            module_path: 要扫描的模块路径 (例如: 'app.templates')
        返回:
            在模块中找到的所有类的列表
        """
        try:
            module = importlib.import_module(module_path)
            # for name, obj in inspect.getmembers(module):
            #     if inspect.ismodule(obj):
            #         full_name = obj.__name__
            #         if full_name in sys.modules:
            #             del sys.modules[full_name]
            # module = importlib.reload(module)
            classes = set()
            for name, obj in inspect.getmembers(module):
                if inspect.isclass(obj) and obj.__module__.startswith(module.__name__):
                    if self._is_allowed_type(obj):
                        classes.add(obj)
            return list(classes)
        except ImportError as e:
            logger.error(f"Failed to import module {module_path}: {e}")
            return []

    def scan_directory(self, directory_path: str) -> List[Type]:
        """
        递归扫描目录中的所有Python模块和类
        参数:
            directory_path: 要扫描的目录路径
        返回:
            在目录中找到的所有类的列表
        """
        classes = set()
        if directory_path not in sys.path:
                sys.path.append(directory_path)
        for root, dirs, files in os.walk(directory_path):
            # 排除 __pycache__ 目录
            dirs[:] = [d for d in dirs if d != '__pycache__']
            logger.info(f"scan_directory: {root}")
            for file in files:
                if file.endswith('.py') and not file.startswith('_') and not file.startswith('.'):
                    rel_path = os.path.relpath(root, directory_path)
                    module_path = os.path.join(rel_path, file[:-3]).replace(os.sep, '.')
                    if rel_path == '.':
                        module_path = file[:-3]
                    classes.update(self.scan_module(module_path))
        return list(classes)

    def add_directory(self, directory_path: str):
        """
        添加一个新的目录到模板管理器
        参数:
            directory_path: 要添加的目录路径
        """
        if directory_path == "default":
            self.__load_default_templates()
            self.templates["default"] = self.default_templates
            return
        if not os.path.exists(directory_path):
            logger.error(f"Directory does not exist: {directory_path}")
            return
        if directory_path not in self.templates:
            self._load_templates_from_directory(directory_path)

    def remove_directory(self, directory_path: str):
        """
        从模板管理器中移除一个目录及其相关的模板
        参数:
            directory_path: 要移除的目录路径
        """
        classes = self.templates.pop(directory_path, None)
        if directory_path == "default":
            return
        if classes:
            for cls in classes:
                parts = cls.__module__.split('.')
                for i in range(len(parts), 0, -1):
                    parent_name = '.'.join(parts[:i])
                    if parent_name in sys.modules:
                        del sys.modules[parent_name]
        
        if directory_path in sys.path and not directory_path.startswith(str(BASE_DIR)):
            sys.path.remove(directory_path)

    def _load_templates_from_directory(self, directory_path: str):
        """
        从指定目录加载模板类
        参数:
            directory_path: 要扫描的目录路径
        """
        classes = self.scan_directory(directory_path)
        self.templates[directory_path] = classes

    def get_template(self, template_name: str) -> Type:
        """
        通过名称获取模板类
        参数:
            template_name: 模板类的名称
        返回:
            如果找到则返回模板类，否则返回None
        """
        for templates in self.templates.values():
            for template in templates:
                if template.__name__ == template_name:
                    return template
        return None

    def get_templates_by_directory(self, directory_path: str) -> List[Type]:
        """
        获取指定目录下的所有模板类
        参数:
            directory_path: 目录路径
        返回:
            该目录下的所有模板类列表
        """
        return self.templates.get(directory_path, []).copy()

    def get_all_templates(self) -> Dict[str, List[Type]]:
        """
        获取所有已注册的模板类
        返回:
            目录路径到模板类列表的字典映射
        """
        return {k: v.copy() for k, v in self.templates.items()}

    def get_directories(self) -> Set[str]:
        """
        获取所有已注册的目录
        返回:
            已注册目录的集合
        """
        return set(self.templates.keys())
    
    def __load_default_templates(self):
        if self.default_templates is None:
            self.default_templates = []
            for m in ["leek_core.data", "leek_core.executor", "leek_core.strategy", "leek_core.policy",
                     "leek_core.sub_strategy", "leek_core.risk", "leek_core.alarm", "leek_core.info_fabricator"]:
                cls = self.scan_module(m)
                self.default_templates += cls

    def get_templates_by_type(self, template_type: Type) -> Dict[str, List[Type]]:
        """
        获取指定类型的所有模板
        参数:
            template_type: 模板类型
        返回:
            目录路径到模板列表的字典映射
        """
        templates_by_dir = {}
        for dir_path, template_list in self.templates.items():
            filtered_templates = []
            for template in template_list:
                if issubclass(template, template_type):
                    filtered_templates.append(template)
            if filtered_templates:  # 只添加有模板的目录
                templates_by_dir[dir_path] = filtered_templates
        return templates_by_dir


class LeekTemplateManager(Generic[T]):
    def __init__(self):
        self.project_managers: Dict[int, TemplateManager] = {}  # project_id -> TemplateManager
        self._lock = Lock()

    async def get_manager(self, project_id: int, force_load: bool = True) -> TemplateManager:
        """
        获取项目的模板管理器，如果不存在则创建
        """
        if project_id in self.project_managers:
            return self.project_managers[project_id]
        async with self._lock:
            if project_id in self.project_managers:
                return self.project_managers[project_id]
            
            tmp = TemplateManager(allowed_types={LeekComponent})
            if force_load:
                with db_connect() as db:
                    project_config = db.query(ProjectConfig).filter_by(project_id=project_id).first()
                    if project_config and project_config.mount_dirs:
                        await self.update_manager_dirs(tmp, project_config.mount_dirs)
                    else:
                        await self.update_manager_dirs(tmp, ["default"])
            self.project_managers[project_id] = tmp
            return self.project_managers[project_id]

    async def get_templates_by_project(self, project_id: int, template_type: Type[T], exclude_types: Optional[Set[Type]] = None) -> List[TemplateResponse]:
        """
        获取指定项目的指定类型模板
        参数:
            project_id: 项目ID
            template_type: 模板类型
            exclude_types: 要排除的类型集合
        返回:
            模板响应列表
        """
        assert project_id is not None, "project_id is required"
        
        manager = await self.get_manager(project_id)
        templates_by_dir = manager.get_templates_by_type(template_type)
        if not exclude_types:
            return await self._convert_to_template_responses(templates_by_dir)
        # 过滤掉排除的类型
        filtered_templates = {}
        for dir_path, template_list in templates_by_dir.items():
            filtered_list = [t for t in template_list if not inspect.isabstract(t) and t not in exclude_types]
            if filtered_list:
                filtered_templates[dir_path] = filtered_list
        return await self._convert_to_template_responses(filtered_templates)

    async def get_executors_by_project(self, project_id: int) -> List[TemplateResponse]:
        """
        获取指定项目的执行器模板
        参数:
            project_id: 项目ID
        返回:
            执行器模板列表
        """
        return await self.get_templates_by_project(project_id, Executor)
    
    async def get_strategy_by_project(self, project_id: int) -> List[TemplateResponse]:
        """
        获取指定项目的策略模板列表
        参数:
            project_id: 项目ID
        返回:
            List[TemplateResponse]: 策略模板列表，包含模板的基本信息、配置模式等
        """
        return await self.get_templates_by_project(project_id, Strategy, exclude_types={Strategy, CTAStrategy})
    
    # 进出场子策略模板接口已移除
    
    async def get_strategy_fabricator_by_project(self, project_id: int) -> List[TemplateResponse]:
        """
        获取指定项目的策略Fabricator模板列表
        参数:
            project_id: 项目ID
        返回:
            List[TemplateResponse]: 策略Fabricator模板列表，包含模板的基本信息、配置模式等
        """
        return await self.get_templates_by_project(project_id, Fabricator)
    
    async def get_strategy_policy_by_project(self, project_id: int) -> List[TemplateResponse]:
        """
        获取指定项目的策略风控模板列表
        参数:
            project_id: 项目ID
        返回:
            List[TemplateResponse]: 策略风控模板列表，包含模板的基本信息、配置模式等
        """
        from leek_core.sub_strategy import SubStrategy
        return await self.get_templates_by_project(project_id, SubStrategy)

    async def update_manager_dirs(self, manager: TemplateManager, directories: List[str]):
        """
        更新项目的模板目录列表
        """
        new_dirs = set(directories)
        # 删除不再需要的目录
        for dir_to_remove in manager.get_directories():
            manager.remove_directory(dir_to_remove)

        # 添加新的目录
        for dir_to_add in new_dirs:
            manager.add_directory(dir_to_add)
        
    async def update_dirs(self, project_id: int, directories: List[str]):
        """
        更新项目的模板目录列表
        参数:
            project_id: 项目ID
            directories: 新的目录列表
        """
        manager = await self.get_manager(project_id, force_load=False)
        async with self._lock:
            await self.update_manager_dirs(manager, directories)

    async def _convert_to_template_responses(self, templates_by_dir: Dict[str, List[Type]]) -> List[TemplateResponse]:
        """
        将模板字典转换为模板响应列表
        """
        responses = []
        for dir_path, template_list in templates_by_dir.items():
            for template in template_list:
                if not inspect.isabstract(template):
                    display_name = getattr(template, 'display_name', None) or template.__name__
                    init_params = getattr(template, 'init_params', [])
                    parameters = await self.convert_init_params(init_params)
                    just_backtest = getattr(template, 'just_backtest', None)
                    responses.append(TemplateResponse(
                        cls=f"{template.__module__}|{template.__name__}",
                        name=display_name,
                        tag=dir_path,
                        desc=getattr(template, '__doc__', '') or '',
                        parameters=parameters,
                        just_backtest=just_backtest
                    ))
        return responses

    async def _get_field_type(self, field_type: str) -> FieldType:
        """
        将字段类型字符串转换为FieldType枚举
        """
        type_mapping = {
            'str': FieldType.STRING,
            'int': FieldType.INT,
            'float': FieldType.FLOAT,
            'boolean': FieldType.BOOL,
            'datetime': FieldType.DATETIME,
            'radio': FieldType.RADIO,
            'select': FieldType.SELECT,
            'array': FieldType.ARRAY
        }
        return type_mapping.get(field_type.lower(), FieldType.STRING)

    async def _get_choice_type(self, field_type: str) -> Optional[ChoiceType]:
        """
        获取选择类型字段的值类型
        """
        match field_type.lower():
            case 'str':
                return ChoiceType.STR
            case 'int':
                return ChoiceType.INT
            case 'float':
                return ChoiceType.FLOAT
            case 'bool':
                return ChoiceType.BOOL
            case 'datetime':
                return ChoiceType.DATETIME
            case _:
                return None

    async def get_datasource_templates(self, project_id: int):
        from leek_core.data import DataSource
        return await self.get_templates_by_project(project_id, template_type=DataSource)
    
    async def get_policies_templates(self, project_id: int):
        from leek_core.policy import StrategyPolicy
        return await self.get_templates_by_project(project_id, template_type=StrategyPolicy)
    
    async def get_alarm_templates(self, project_id: int):
        from leek_core.alarm import AlarmSender
        return await self.get_templates_by_project(project_id, template_type=AlarmSender, exclude_types={AlarmSender})
    
    async def convert_init_params(self, init_params):
        """
        将 init_params 列表转换为 ParameterField 列表
        """
        parameters = []
        for param in init_params:
            param_type = await self._get_field_type(param.type.value)
            choice_type = await self._get_choice_type(param.type.value) if param_type in [FieldType.RADIO, FieldType.SELECT] else None
            parameters.append(ParameterField(
                name=param.name,
                label=param.label,
                description=param.description,
                type=param_type,
                default=param.default,
                length=param.length,
                min=param.min,
                max=param.max,
                required=param.required,
                choices=param.choices,
                choice_type=choice_type
            ))
        return parameters
    
leek_template_manager = LeekTemplateManager()
