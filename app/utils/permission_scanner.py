from typing import Dict, List, Set, Tuple
import importlib
import inspect
import pkgutil
import os
import sys
from fastapi import APIRouter
from app.api.v1 import endpoints

def scan_api_endpoints() -> list:
    """
    扫描所有API端点，返回树形结构
    """
    # 直接用当前文件相对路径定位 endpoints 目录
    endpoints_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../api/v1/endpoints"))
    all_routes = []
    for _, module_name, _ in pkgutil.iter_modules([endpoints_path]):
        module = importlib.import_module(f"app.api.v1.endpoints.{module_name}")
        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            if isinstance(attr, APIRouter):
                for route in attr.routes:
                    path = route.path
                    methods = route.methods
                    parts = [p for p in path.split("/") if p and not p.startswith("{")]
                    if not parts:
                        continue
                    for method in methods:
                        if method in ["GET", "HEAD", "OPTIONS"]:
                            action = "read"
                        else:
                            action = "write"
                        all_routes.append((parts, action))

    def insert(tree, parts, action):
        node = tree
        for i, part in enumerate(parts):
            found = None
            for child in node.get("children", []):
                if child["label"] == part:
                    found = child
                    break
            if not found:
                found = {"id": part, "label": part}
                if i < len(parts) - 1:
                    found["children"] = []
                node.setdefault("children", []).append(found)
            node = found
        node.setdefault("actions", [])
        if action not in [a["action"] for a in node["actions"]]:
            node["actions"].append({"action": action, "label": "读" if action == "read" else "写"})

    tree = {"children": []}
    for parts, action in all_routes:
        insert(tree, parts, action)

    return sorted([e for e in tree["children"] if e["label"] not in ["auth", "system"]], key=lambda x: x["label"])

def get_available_permissions() -> List[Dict[str, str]]:
    """
    获取所有可用的权限
    
    Returns:
        List[Dict[str, str]]: 权限列表
    """
    try:
        permissions = scan_api_endpoints()
    except Exception as e:
        # 如果发生错误，返回基础权限集
        print(f"Error scanning endpoints: {e}")
        permissions = [
            {"resource": "users", "permission": "read"},
            {"resource": "users", "permission": "write"},
            {"resource": "roles", "permission": "read"},
            {"resource": "roles", "permission": "write"},
            {"resource": "permissions", "permission": "read"}
        ]
    
    # 添加通配符权限
    if {"resource": "*", "permission": "*"} not in permissions:
        permissions.append({"resource": "*", "permission": "*"})
    
    return permissions 