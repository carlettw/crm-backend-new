from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.languages import clean_languages
from app.core.regions import clean_regions
from app.core.timeutil import to_utc
from app.models import AppKind, AppStatus, TourStatus


class StopIO(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    address: str = Field(min_length=1, max_length=255)
    duration_minutes: int = Field(0, ge=0)
    description: str = ""
    location_url: str | None = Field(None, max_length=500)
    arrival_time: str | None = Field(None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")


class GroupIO(BaseModel):
    """Turist guruhi: til + ism familya + aloqa + odam soni."""
    model_config = ConfigDict(from_attributes=True)
    language: str
    tourist_name: str = Field(min_length=1, max_length=120)
    tourist_phone: str | None = Field(None, max_length=30)
    tourist_email: str | None = Field(None, max_length=120)
    messenger: str | None = Field(None, max_length=120)
    pax_count: int = Field(1, ge=1)

    @field_validator("language")
    @classmethod
    def _lang(cls, v):
        return clean_languages([v])[0]


class TourBase(BaseModel):
    title: str = Field(min_length=2, max_length=160)
    groups: list[GroupIO] = Field(min_length=1)  # har bir guruh: til, ism familya, aloqa, odam soni
    needs_driver: bool = True  # False: gid yolg'iz chiqadi (haydovchisiz)
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

    @field_validator("start_at")
    @classmethod
    def _utc(cls, v):
        return to_utc(v)


class TourCreate(TourBase):
    pass


class TourUpdate(BaseModel):
    title: str | None = Field(None, min_length=2, max_length=160)
    groups: list[GroupIO] | None = Field(None, min_length=1)
    needs_driver: bool | None = None
    region: str | None = None

    @field_validator("region")
    @classmethod
    def _reg(cls, v):
        return clean_regions([v])[0] if v else None
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
    region: str  # tur shu viloyatda ishlamoqchi bo'lgan gidlarga yuboriladi

    @field_validator("region")
    @classmethod
    def _reg(cls, v):
        return clean_regions([v])[0]


class RedispatchIn(BaseModel):
    role: str = Field(pattern="^(guide|driver)$")
    min_guide_level: int | None = Field(None, ge=2, le=7)
    guide_amount: int | None = Field(None, ge=0)
    region: str | None = None

    @field_validator("region")
    @classmethod
    def _reg(cls, v):
        return clean_regions([v])[0] if v else v


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
    language: str
    notified_guides: int | None = None  # publish/redispatch javobida: nechta gidga yuborildi
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
    region: str | None = None
    needs_driver: bool
    groups: list[GroupIO]
    languages: list[str]
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
    urgent: bool = False
    hours_left: float | None = None


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
