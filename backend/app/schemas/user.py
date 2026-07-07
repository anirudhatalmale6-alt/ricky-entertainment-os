"""User / role read schemas."""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr


class RoleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    description: str | None = None


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    email: EmailStr
    full_name: str
    is_active: bool
    is_superuser: bool
    totp_enabled: bool
    role: RoleOut | None = None
    created_at: datetime
