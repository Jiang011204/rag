"""认证依赖：应用自身 API key。"""
from fastapi import Header, HTTPException

from ..core.config import settings


async def require_auth(authorization: str = Header(default="")):
    if not settings.app_api_key:
        return  # 未配置则不校验（内网单机模式）
    token = authorization.removeprefix("Bearer ").strip()
    if token != settings.app_api_key:
        raise HTTPException(status_code=401, detail="unauthorized")
