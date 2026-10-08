import enum
from datetime import datetime

from sqlalchemy import (
    Boolean, DateTime, Enum, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.user import User


class TourStatus(str, enum.Enum):
    draft = "draft"          # saqlangan shablon
    open = "open"            # yuborilgan, gid yoki haydovchi kutilmoqda
    ready = "ready"          # gid ham, haydovchi ham bor
    completed = "completed"
    cancelled = "cancelled"


class AppKind(str, enum.Enum):
    driver = "driver"
    practice = "practice"    # 1-daraja amaliyotchi gid


class AppStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"
    withdrawn = "withdrawn"


class EarnKind(str, enum.Enum):
    guide = "guide"
    driver = "driver"
    admin = "admin"


class PayStatus(str, enum.Enum):
    paid_by_boss = "paid_by_boss"
    confirmed = "confirmed"


def _enum(e, length=20):
    return Enum(e, native_enum=False, length=length)


class Tour(Base):
    __tablename__ = "tours"

    id: Mapped[int] = mapped_column(primary_key=True)
    boss_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    title: Mapped[str] = mapped_column(String(160), index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    pickup_address: Mapped[str] = mapped_column(String(255), default="")
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)

    total_price: Mapped[int] = mapped_column(Integer, default=0)  # har doim so'mda (hisob-kitob uchun)
    # admin narxni so'mda yoki dollarda kiritishi mumkin; asl qiymat va kurs saqlanadi
    price_currency: Mapped[str] = mapped_column(String(3), default="UZS")
    price_original: Mapped[float] = mapped_column(Numeric(14, 2, asdecimal=False), default=0)
    usd_rate_used: Mapped[float | None] = mapped_column(Numeric(12, 2, asdecimal=False), nullable=True)
    platform_percent: Mapped[float] = mapped_column(Numeric(5, 2, asdecimal=False), default=0)
    guide_amount: Mapped[int] = mapped_column(Integer, default=0)
    driver_amount: Mapped[int] = mapped_column(Integer, default=0)
    guide_note: Mapped[str] = mapped_column(Text, default="")
    driver_note: Mapped[str] = mapped_column(Text, default="")
    min_guide_level: Mapped[int | None] = mapped_column(Integer, nullable=True)

    tourist_name: Mapped[str] = mapped_column(String(120))
    tourist_phone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    tourist_email: Mapped[str | None] = mapped_column(String(120), nullable=True)
    messenger: Mapped[str | None] = mapped_column(String(120), nullable=True)
    pax_count: Mapped[int] = mapped_column(Integer, default=1)

    status: Mapped[TourStatus] = mapped_column(_enum(TourStatus), default=TourStatus.draft, index=True)
    guide_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    driver_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    guide_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    driver_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    late_reported: Mapped[bool] = mapped_column(Boolean, default=False)
    fine_decided: Mapped[bool] = mapped_column(Boolean, default=False)

    # tur yakunlanganda yoziladigan hisob-kitob (so'm)
    platform_fee: Mapped[int] = mapped_column(Integer, default=0)
    guide_cost: Mapped[int] = mapped_column(Integer, default=0)
    driver_cost: Mapped[int] = mapped_column(Integer, default=0)
    admin_cost: Mapped[int] = mapped_column(Integer, default=0)
    profit: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    stops: Mapped[list["TourStop"]] = relationship(
        lazy="selectin", order_by="TourStop.position", cascade="all, delete-orphan"
    )
    guide: Mapped[User | None] = relationship(foreign_keys=[guide_id], lazy="joined")
    driver: Mapped[User | None] = relationship(foreign_keys=[driver_id], lazy="joined")

    @property
    def guide_name(self):
        return self.guide.full_name if self.guide else None

    @property
    def driver_name(self):
        return self.driver.full_name if self.driver else None

    @property
    def fine_prompt(self):
        return self.status == TourStatus.completed and self.late_reported and not self.fine_decided


class TourStop(Base):
    __tablename__ = "tour_stops"

    id: Mapped[int] = mapped_column(primary_key=True)
    tour_id: Mapped[int] = mapped_column(ForeignKey("tours.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    address: Mapped[str] = mapped_column(String(255))
    duration_minutes: Mapped[int] = mapped_column(Integer, default=0)
    description: Mapped[str] = mapped_column(Text, default="")


class TourApplication(Base):
    """Haydovchi arizasi yoki 1-daraja gid amaliyot arizasi (admin tasdiqlaydi)."""
    __tablename__ = "tour_applications"
    __table_args__ = (UniqueConstraint("tour_id", "user_id", "kind"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    tour_id: Mapped[int] = mapped_column(ForeignKey("tours.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    kind: Mapped[AppKind] = mapped_column(_enum(AppKind))
    status: Mapped[AppStatus] = mapped_column(_enum(AppStatus), default=AppStatus.pending)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped[User] = relationship(lazy="joined")


class TourCancellation(Base):
    """Bekor qilishlar tarixi."""
    __tablename__ = "tour_cancellations"

    id: Mapped[int] = mapped_column(primary_key=True)
    tour_id: Mapped[int] = mapped_column(ForeignKey("tours.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    role: Mapped[str] = mapped_column(String(20))
    by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    by_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    reason: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Fine(Base):
    __tablename__ = "fines"

    id: Mapped[int] = mapped_column(primary_key=True)
    boss_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    tour_id: Mapped[int] = mapped_column(ForeignKey("tours.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    amount: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    payment_id: Mapped[int | None] = mapped_column(ForeignKey("payments.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Rating(Base):
    __tablename__ = "ratings"

    id: Mapped[int] = mapped_column(primary_key=True)
    tour_id: Mapped[int] = mapped_column(ForeignKey("tours.id"), unique=True)
    driver_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    guide_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    stars: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Earning(Base):
    """Tur yakunlanganda hisoblangan, hali to'lanmagan/to'langan haq."""
    __tablename__ = "earnings"

    id: Mapped[int] = mapped_column(primary_key=True)
    tour_id: Mapped[int] = mapped_column(ForeignKey("tours.id"), index=True)
    boss_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    kind: Mapped[EarnKind] = mapped_column(_enum(EarnKind))
    amount: Mapped[int] = mapped_column(Integer)
    payment_id: Mapped[int | None] = mapped_column(ForeignKey("payments.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(primary_key=True)
    boss_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    tours_count: Mapped[int] = mapped_column(Integer)
    gross: Mapped[int] = mapped_column(Integer)
    fines_total: Mapped[int] = mapped_column(Integer, default=0)
    net: Mapped[int] = mapped_column(Integer)
    status: Mapped[PayStatus] = mapped_column(_enum(PayStatus), default=PayStatus.paid_by_boss)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[User] = relationship(foreign_keys=[user_id], lazy="joined")


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    sender_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)  # None = tizim
    recipient_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    sender: Mapped[User | None] = relationship(foreign_keys=[sender_id], lazy="joined")

    @property
    def sender_name(self):
        return self.sender.full_name if self.sender else "Tizim"


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(50), primary_key=True)
    value: Mapped[str] = mapped_column(String(100))


class UsdRateLog(Base):
    """Super admin kiritgan dollar kurslari tarixi (oxirgisi amaldagi kurs)."""
    __tablename__ = "usd_rate_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    rate: Mapped[float] = mapped_column(Numeric(12, 2, asdecimal=False))
    set_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
