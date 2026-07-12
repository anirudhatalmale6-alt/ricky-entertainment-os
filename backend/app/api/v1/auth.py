"""Authentication endpoints: register, login (with 2FA), TOTP setup/enable."""
import qrcode
import qrcode.image.svg
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select

from app.api.deps import CurrentScope, CurrentUser, DbSession
from app.core import security
from app.models.artist import Artist
from app.models.booker import Booker
from app.models.company import Company
from app.models.user import Role, User
from app.schemas.auth import (
    ArtistRegisterRequest,
    ContratanteRegisterRequest,
    LoginRequest,
    LoginResult,
    MeOut,
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


async def _email_taken(db: DbSession, email: str) -> bool:
    return (await db.execute(select(User).where(User.email == email))).scalar_one_or_none() is not None


@router.post("/register/artist", response_model=LoginResult, status_code=status.HTTP_201_CREATED)
async def register_artist(payload: ArtistRegisterRequest, db: DbSession):
    """Artist self sign-up: creates the login + artist profile and returns a
    token so they land straight in their dashboard."""
    if await _email_taken(db, payload.email):
        raise HTTPException(status.HTTP_409_CONFLICT, "Email already registered")

    role = await _get_role(db, "artist")
    user = User(
        email=payload.email,
        full_name=payload.full_name,
        hashed_password=security.hash_password(payload.password),
        role_id=role.id if role else None,
    )
    db.add(user)
    await db.flush()

    artist = Artist(
        user_id=user.id,
        stage_name=payload.stage_name,
        artist_type=payload.artist_type,
        phone=payload.phone,
        base_city=payload.base_city,
        email=payload.email,
    )
    db.add(artist)
    await db.commit()
    return LoginResult(access_token=security.create_access_token(user.id))


@router.post("/register/contratante", response_model=LoginResult, status_code=status.HTTP_201_CREATED)
async def register_contratante(payload: ContratanteRegisterRequest, db: DbSession):
    """Hotel/venue manager self sign-up: creates the login + booker profile,
    joining an existing company or creating a new one on the fly."""
    if await _email_taken(db, payload.email):
        raise HTTPException(status.HTTP_409_CONFLICT, "Email already registered")

    company_id = payload.company_id
    if company_id is not None:
        if await db.get(Company, company_id) is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Company not found")
    elif payload.company_name:
        company = Company(name=payload.company_name, group_id=payload.group_id)
        db.add(company)
        await db.flush()
        company_id = company.id
    elif payload.group_id is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Provide company_id, company_name or group_id",
        )

    role = await _get_role(db, "booker")
    user = User(
        email=payload.email,
        full_name=payload.full_name,
        hashed_password=security.hash_password(payload.password),
        role_id=role.id if role else None,
    )
    db.add(user)
    await db.flush()

    booker = Booker(
        user_id=user.id,
        company_id=company_id,
        group_id=payload.group_id,
        position=payload.position,
        phone=payload.phone,
    )
    db.add(booker)
    await db.commit()
    return LoginResult(access_token=security.create_access_token(user.id))


@router.get("/me", response_model=MeOut)
async def me(scope: CurrentScope, db: DbSession):
    """Identity + resolved scope for the logged-in user."""
    user = scope.user
    perms = [p.code for p in user.role.permissions] if user.role else []
    artist_name = None
    if scope.artist_id:
        a = await db.get(Artist, scope.artist_id)
        artist_name = a.stage_name if a else None
    company_name = None
    if scope.company_id:
        c = await db.get(Company, scope.company_id)
        company_name = c.name if c else None
    return MeOut(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=scope.role,
        permissions=perms,
        is_admin=scope.is_admin,
        artist_id=scope.artist_id,
        company_id=scope.company_id,
        group_id=scope.group_id,
        artist_name=artist_name,
        company_name=company_name,
    )


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
