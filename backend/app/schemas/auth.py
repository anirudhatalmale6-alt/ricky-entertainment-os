"""Auth-related request/response schemas."""
from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=2, max_length=255)
    password: str = Field(min_length=8, max_length=128)
    role: str = Field(default="booker")  # booker | artist | admin | finance


class ArtistRegisterRequest(BaseModel):
    """Self sign-up for an artist/proveedor: creates the login + the profile."""
    email: EmailStr
    full_name: str = Field(min_length=2, max_length=255)
    password: str = Field(min_length=8, max_length=128)
    stage_name: str = Field(min_length=2, max_length=255)  # nombre artistico
    artist_type: str | None = None
    phone: str | None = None
    base_city: str | None = None


class ContratanteRegisterRequest(BaseModel):
    """Self sign-up for a hotel/venue manager. Either joins an existing company
    (company_id) or creates a new one on the fly (company_name)."""
    email: EmailStr
    full_name: str = Field(min_length=2, max_length=255)
    password: str = Field(min_length=8, max_length=128)
    company_id: int | None = None
    company_name: str | None = Field(default=None, max_length=255)
    group_id: int | None = None       # a group director oversees the whole chain
    position: str | None = None       # e.g. "Director de actividades"
    phone: str | None = None


class MeOut(BaseModel):
    """Who am I + what slice I own - the frontend uses this to render the right
    dashboard and gate the Partner features."""
    id: int
    email: EmailStr
    full_name: str
    role: str | None = None
    permissions: list[str] = []
    is_admin: bool = False
    artist_id: int | None = None
    company_id: int | None = None
    group_id: int | None = None
    artist_name: str | None = None
    company_name: str | None = None


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
