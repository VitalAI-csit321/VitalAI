from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.enums import UserRole


class UserRegister(BaseModel):
    email: str
    password: str = Field(min_length=8, max_length=128)
    full_name: str = Field(min_length=1, max_length=255)
    role: UserRole = UserRole.FRONT_DESK


class ElevateRoleRequest(BaseModel):
    new_role: UserRole


class UserLogin(BaseModel):
    email: str
    password: str


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class TokenPayload(BaseModel):
    sub: str
    role: UserRole
    exp: int


class UserOut(BaseModel):
    id: UUID
    email: str
    full_name: str
    role: UserRole
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}