import re

from pydantic import BaseModel, field_validator

PHONE_RE = re.compile(r"^\+998\d{9}$")


def normalize_phone(v: str) -> str:
    v = re.sub(r"[\s\-()]", "", v)
    if re.fullmatch(r"\d{9}", v):
        v = "+998" + v
    elif re.fullmatch(r"998\d{9}", v):
        v = "+" + v
    if not PHONE_RE.match(v):
        raise ValueError("Telefon raqam +998XXXXXXXXX formatida bo'lishi kerak")
    return v


class LoginIn(BaseModel):
    username: str
    password: str

    @field_validator("username")
    @classmethod
    def _username(cls, v):
        return v.strip().lower()


class TokenOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshIn(BaseModel):
    refresh_token: str


class ChangePasswordIn(BaseModel):
    old_password: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def _len(cls, v):
        if len(v) < 6:
            raise ValueError("Parol kamida 6 belgi bo'lishi kerak")
        return v
