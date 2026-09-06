from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core import security
from ..core.db import get_db, utcnow
from ..models import User
from ..services.audit import audit
from .deps import client_ip, get_current_user
from .schemas import LoginIn

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginOut(BaseModel):
    token: str
    username: str
    role: str


@router.post("/login", response_model=LoginOut)
async def login(body: LoginIn, request: Request, session: AsyncSession = Depends(get_db)):
    user = (await session.execute(select(User).where(User.username == body.username.strip()))).scalar_one_or_none()
    if not user or user.status != "active" or not security.verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="invalid username or password")
    token = security.create_access_token(user.username, user.role)
    user.updated_at = utcnow()
    await audit(session, "auth.login", resource_type="user", resource_id=user.id, ip=client_ip(request))
    await session.commit()
    return LoginOut(token=token, username=user.username, role=user.role)


@router.get("/me")
async def me(user: User = Depends(get_current_user)):
    return {"username": user.username, "role": user.role, "id": user.id}
