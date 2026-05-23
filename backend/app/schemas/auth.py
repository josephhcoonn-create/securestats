import re

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.models.user import UserRole

# Allow letters/digits/underscore/hyphen; 3-50 chars. Anchored.
_USERNAME_RE = re.compile(r"^[A-Za-z0-9_-]{3,50}$")


class UserCreate(BaseModel):
    """
    Registration payload — username/email/password with tight bounds.

    - username: 3-50 chars, [A-Za-z0-9_-] only
    - email   : validated by EmailStr, capped at 255 chars (Postgres column width)
    - password: min 8 chars, at least one uppercase, one lowercase, one digit
    """

    username: str = Field(..., min_length=3, max_length=50)
    email: EmailStr = Field(..., max_length=255)
    password: str = Field(..., min_length=8, max_length=128)

    @field_validator("username")
    @classmethod
    def username_pattern(cls, v: str) -> str:
        if not _USERNAME_RE.match(v):
            raise ValueError(
                "username may only contain letters, digits, hyphens, and underscores"
            )
        return v

    @field_validator("password")
    @classmethod
    def password_complexity(cls, v: str) -> str:
        if not any(c.islower() for c in v):
            raise ValueError("password must contain at least one lowercase letter")
        if not any(c.isupper() for c in v):
            raise ValueError("password must contain at least one uppercase letter")
        if not any(c.isdigit() for c in v):
            raise ValueError("password must contain at least one digit")
        return v


class UserLogin(BaseModel):
    username: str = Field(..., min_length=1, max_length=50)
    password: str = Field(..., min_length=1, max_length=128)


class UserResponse(BaseModel):
    id: int
    username: str
    email: str
    role: UserRole
    is_active: bool

    model_config = {"from_attributes": True}


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
