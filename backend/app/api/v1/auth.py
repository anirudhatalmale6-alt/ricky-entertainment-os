"""Authentication endpoints: register, login (with 2FA), TOTP setup/enable."""
import qrcode
import qrcode.image.svg
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.core import security
from app.models.user import Role, User
from app.schemas.auth import (
    LoginRequest,
    LoginResult,
    RegisterRequest,
    TotpSetupResponse,
    TotpVerifyRequest,
)
from app.schemas.user import UserOut

router = APIRouter(prefix="/auth", tags=["auth"])


async def _get_role(db: DbSession, name: str) -> Role | None:
    res = await db.execute(select(Role).where(Role.name == name))
    return res.scalar_one_or_none()


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def register(payload: RegisterRequest, db: DbSession):
    existing = await db.execute(select(User).where(User.email == payload.email))
    if existing.scalar_one_or_none():
        raise HTTPException(status.HTTP_409_CONFLICT, "Email already registered")

    role = await _get_role(db, payload.role)
    user = User(
        email=payload.email,
        full_name=payload.full_name,
        hashed_password=security.hash_password(payload.password),
        role_id=role.id if role else None,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


@router.post("/login", response_model=LoginResult)
async def login(payload: LoginRequest, db: DbSession):
    res = await db.execute(select(User).where(User.email == payload.email))
    user = res.scalar_one_or_none()
    if not user or not security.verify_password(payload.password, user.hashed_password):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect email or password")
    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Inactive user")

    # 2FA gate
    if user.totp_enabled:
        if not payload.totp_code:
            return LoginResult(requires_2fa=True)
        if not security.verify_totp(user.totp_secret or "", payload.totp_code):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid 2FA code")

    token = security.create_access_token(user.id)
    return LoginResult(access_token=token)


@router.post("/2fa/setup", response_model=TotpSetupResponse)
async def setup_2fa(current_user: CurrentUser, db: DbSession):
    """Generate a TOTP secret + QR. Call /2fa/enable with a code to activate."""
    secret = security.generate_totp_secret()
    current_user.totp_secret = secret
    await db.commit()

    uri = security.totp_provisioning_uri(secret, current_user.email)
    img = qrcode.make(uri, image_factory=qrcode.image.svg.SvgImage)
    from io import BytesIO

    buf = BytesIO()
    img.save(buf)
    return TotpSetupResponse(
        secret=secret,
        provisioning_uri=uri,
        otpauth_qr_svg=buf.getvalue().decode("utf-8"),
    )


@router.post("/2fa/enable", response_model=UserOut)
async def enable_2fa(payload: TotpVerifyRequest, current_user: CurrentUser, db: DbSession):
    if not current_user.totp_secret:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Run /2fa/setup first")
    if not security.verify_totp(current_user.totp_secret, payload.code):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid 2FA code")
    current_user.totp_enabled = True
    await db.commit()
    await db.refresh(current_user)
    return current_user


@router.post("/2fa/disable", response_model=UserOut)
async def disable_2fa(payload: TotpVerifyRequest, current_user: CurrentUser, db: DbSession):
    if not current_user.totp_enabled or not current_user.totp_secret:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "2FA is not enabled")
    if not security.verify_totp(current_user.totp_secret, payload.code):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid 2FA code")
    current_user.totp_enabled = False
    current_user.totp_secret = None
    await db.commit()
    await db.refresh(current_user)
    return current_user
