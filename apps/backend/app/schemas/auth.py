from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=1024)


class AuthUserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    email: EmailStr
    role: Literal["student", "professor", "admin"]


class LoginResponse(BaseModel):
    access_token: str | None = None
    token_type: Literal["bearer"] = "bearer"
    user: AuthUserRead
