import enum
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Role(str, enum.Enum):
    super_admin = "super_admin"
    boss = "boss"
    admin = "admin"
    guide = "guide"
    driver = "driver"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    phone: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    # username super admin tomonidan beriladi va o'zgarmaydi
    username: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(120), index=True)
    password_hash: Mapped[str] = mapped_column(String(100))
    role: Mapped[Role] = mapped_column(Enum(Role, native_enum=False, length=20), index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    boss_profile: Mapped["BossProfile | None"] = relationship(
        back_populates="user", uselist=False, lazy="joined", cascade="all, delete-orphan"
    )
    guide_profile: Mapped["GuideProfile | None"] = relationship(
        back_populates="user", uselist=False, lazy="joined", cascade="all, delete-orphan"
    )
    driver_profile: Mapped["DriverProfile | None"] = relationship(
        back_populates="user", uselist=False, lazy="joined", cascade="all, delete-orphan"
    )

    # Pydantic (from_attributes) uchun qulay xossalar
    @property
    def boss_percent(self):
        return self.boss_profile.super_admin_percent if self.boss_profile else None

    @property
    def guide_level(self):
        return self.guide_profile.level if self.guide_profile else None

    @property
    def car_model(self):
        return self.driver_profile.car_model if self.driver_profile else None


class BossProfile(Base):
    __tablename__ = "boss_profiles"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    # boshliqning oylik foydasidan super admin ulushi (masalan 15.00)
    super_admin_percent: Mapped[float] = mapped_column(Numeric(5, 2, asdecimal=False))
    user: Mapped[User] = relationship(back_populates="boss_profile")


class GuideProfile(Base):
    __tablename__ = "guide_profiles"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    level: Mapped[int] = mapped_column(Integer, default=1)
    completed_tours: Mapped[int] = mapped_column(Integer, default=0)
    # joriy darajada bajarilgan turlar (daraja ko'tarilganda 0 ga tushadi)
    level_tours: Mapped[int] = mapped_column(Integer, default=0)
    # 1-daraja chekboksları
    practice_done: Mapped[bool] = mapped_column(Boolean, default=False)
    interview_passed: Mapped[bool] = mapped_column(Boolean, default=False)
    user: Mapped[User] = relationship(back_populates="guide_profile")


class DriverProfile(Base):
    __tablename__ = "driver_profiles"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    car_model: Mapped[str] = mapped_column(String(80))
    user: Mapped[User] = relationship(back_populates="driver_profile")


class BossAdmin(Base):
    """Boshliq va admin o'rtasidagi ko'p-ko'pga bog'lanish."""
    __tablename__ = "boss_admins"

    boss_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    admin_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)


class LevelRate(Base):
    """Super admin belgilagan daraja bo'yicha gid summasi (3-7 daraja)."""
    __tablename__ = "level_rates"

    level: Mapped[int] = mapped_column(Integer, primary_key=True)
    amount: Mapped[int] = mapped_column(Integer)  # so'm
