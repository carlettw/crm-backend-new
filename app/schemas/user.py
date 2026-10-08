import re
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.user import Role
from app.schemas.auth import normalize_phone


class UserCreate(BaseModel):
    role: Role
    phone: str
    username: str
    full_name: str = Field(min_length=2, max_length=120)
    password: str = Field(min_length=6)
    # rolga xos maydonlar
    boss_percent: float | None = Field(default=None, ge=0, le=100)
    guide_level: int | None = Field(default=None, ge=1, le=7)
    car_model: str | None = Field(default=None, max_length=80)

    @field_validator("phone")
    @classmethod
    def _phone(cls, v):
        return normalize_phone(v)

    @field_validator("username")
    @classmethod
    def _username(cls, v):
        if not re.fullmatch(r"[A-Za-z0-9_]{3,32}", v):
            raise ValueError("Username 3-32 belgi: lotin harflari, raqam va _")
        return v.lower()

    @model_validator(mode="after")
    def _role_fields(self):
        if self.role == Role.super_admin:
            raise ValueError("Super admin API orqali yaratilmaydi")
        if self.role == Role.boss and self.boss_percent is None:
            raise ValueError("Boshliq uchun boss_percent majburiy")
        if self.role == Role.guide and self.guide_level is None:
            raise ValueError("Gid uchun guide_level majburiy")
        if self.role == Role.driver and not self.car_model:
            raise ValueError("Haydovchi uchun car_model (mashina rusumi) majburiy")
        return self


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    phone: str
    username: str
    full_name: str
    role: Role
    is_active: bool
    created_at: datetime
    boss_percent: float | None = None
    guide_level: int | None = None
    car_model: str | None = None


class UserListOut(BaseModel):
    total: int
    items: list[UserOut]


class ActiveIn(BaseModel):
    is_active: bool


class ResetPasswordIn(BaseModel):
    new_password: str = Field(min_length=6)


class LevelRateIn(BaseModel):
    amount: int = Field(gt=0)


class LevelRateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    level: int
    amount: int
