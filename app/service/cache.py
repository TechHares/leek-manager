from app.db.session import db_connect
from app.models.rbac import Role
from app.models.user import User
from cachetools import TTLCache, cached

@cached(cache=TTLCache(maxsize=200, ttl=600))
def get_user_by_username(username: str):
    with db_connect() as db:
        user = db.query(User).filter(User.username == username).first()
        return user
    
@cached(cache=TTLCache(maxsize=1200, ttl=600))
def get_role_by_id(id: int):
    with db_connect() as db:
        role = db.query(Role).filter(Role.id == id).first()
        return role