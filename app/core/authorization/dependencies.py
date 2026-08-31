from fastapi import Depends
from app.models.user import User
from app.core.dependencies import get_current_user
from app.core.authorization.permissions import Permission
from app.core.authorization.service import authorize

def require_permission(permission: Permission):
    def dependency(current_user: User = Depends(get_current_user)) -> User:
        authorize(current_user, permission)
        return current_user
    return dependency
