"""Auth-related request/response schemas."""
from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=2, max_length=255)
    password: str = Field(min_length=8, max_length=128)
    role: str = Field(default="booker")  # booker | artist | admin | finance


class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    totp_code: str | None = None  # required if 2FA is enabled


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class LoginResult(BaseModel):
    """Login can either return a token or ask for a 2FA code."""
    requires_2fa: bool = False
    access_token: str | None = None
    token_type: str = "bearer"


class TotpSetupResponse(BaseModel):
    secret: str
    provisioning_uri: str
    otpauth_qr_svg: str  # inline SVG the frontend can render directly


class TotpVerifyRequest(BaseModel):
    code: str = Field(min_length=6, max_length=6)
