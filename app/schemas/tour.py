from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.timeutil import to_utc
from app.models import AppKind, AppStatus, TourStatus


class StopIO(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    address: str = Field(min_length=1, max_length=255)
    duration_minutes: int = Field(0, ge=0)
    description: str = ""


class TourBase(BaseModel):
    title: str = Field(min_length=2, max_length=160)
    description: str = ""
    pickup_address: str = ""
    start_at: datetime
    stops: list[StopIO] = []
    total_price: float = Field(0, ge=0)  # price_currency birligida
    price_currency: Literal["UZS", "USD"] = "UZS"
    platform_percent: float = Field(0, ge=0, le=100)
    guide_note: str = ""
    driver_note: str = ""
    guide_amount: int = Field(0, ge=0)
    driver_amount: int = Field(0, ge=0)
    tourist_name: str = Field(min_length=1, max_length=120)
    tourist_phone: str | None = None
    tourist_email: str | None = None
    messenger: str | None = None
    pax_count: int = Field(1, ge=1)

    @field_validator("start_at")
    @classmethod
    def _utc(cls, v):
        return to_utc(v)


class TourCreate(TourBase):
    pass


class TourUpdate(BaseModel):
    title: str | None = Field(None, min_length=2, max_length=160)
    description: str | None = None
    pickup_address: str | None = None
    start_at: datetime | None = None
    stops: list[StopIO] | None = None
    total_price: float | None = Field(None, ge=0)
    price_currency: Literal["UZS", "USD"] | None = None
    platform_percent: float | None = Field(None, ge=0, le=100)
    guide_note: str | None = None
    driver_note: str | None = None
    guide_amount: int | None = Field(None, ge=0)
    driver_amount: int | None = Field(None, ge=0)
    tourist_name: str | None = None
    tourist_phone: str | None = None
    tourist_email: str | None = None
    messenger: str | None = None
    pax_count: int | None = Field(None, ge=1)

    @field_validator("start_at")
    @classmethod
    def _utc(cls, v):
        return to_utc(v) if v else v


class CloneIn(TourUpdate):
    start_at: datetime  # nusxa uchun yangi sana majburiy

    @field_validator("start_at")
    @classmethod
    def _utc2(cls, v):
        return to_utc(v)


class PublishIn(BaseModel):
    min_guide_level: int = Field(ge=2, le=7)


class RedispatchIn(BaseModel):
    role: str = Field(pattern="^(guide|driver)$")
    min_guide_level: int | None = Field(None, ge=2, le=7)
    guide_amount: int | None = Field(None, ge=0)


class AssignIn(BaseModel):
    role: str = Field(pattern="^(guide|driver)$")
    user_id: int


class CancelWorkerIn(BaseModel):
    role: str = Field(pattern="^(guide|driver)$")
    reason: str = ""


class ReasonIn(BaseModel):
    reason: str = ""


class UserIdIn(BaseModel):
    user_id: int


class FineIn(BaseModel):
    user_id: int
    amount: int = Field(gt=0)
    reason: str = ""


class TourOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    boss_id: int
    created_by: int
    title: str
    description: str
    pickup_address: str
    start_at: datetime
    stops: list[StopIO]
    total_price: int  # so'mda
    price_currency: str
    price_original: float
    usd_rate_used: float | None
    platform_percent: float
    guide_amount: int
    driver_amount: int
    guide_note: str
    driver_note: str
    min_guide_level: int | None
    tourist_name: str
    tourist_phone: str | None
    tourist_email: str | None
    messenger: str | None
    pax_count: int
    status: TourStatus
    guide_id: int | None
    guide_name: str | None
    driver_id: int | None
    driver_name: str | None
    guide_confirmed_at: datetime | None
    driver_confirmed_at: datetime | None
    completed_at: datetime | None
    fine_prompt: bool


class ApplicationOut(BaseModel):
    id: int
    user_id: int
    full_name: str
    phone: str
    kind: AppKind
    status: AppStatus
    car_model: str | None = None
    rating: float | None = None
    guide_level: int | None = None


class RateIn(BaseModel):
    stars: int = Field(ge=1, le=5)


class LateIn(BaseModel):
    note: str = ""
