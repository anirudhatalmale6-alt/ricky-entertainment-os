"""User endpoints: current profile, (admin) listing and password reset."""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession, require_permission
from app.core import security
from app.core.config import settings
from app.models.user import User
from app.schemas.auth import AdminResetResult
from app.schemas.user import UserOut, UserSelfUpdate
from app.services import mailer, passwords

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=UserOut)
async def read_me(current_user: CurrentUser):
    return current_user


@router.patch("/me", response_model=UserOut)
async def update_me(payload: UserSelfUpdate, current_user: CurrentUser, db: DbSession):
    """The signed-in user updates their own profile (display name)."""
    if payload.full_name is not None:
        name = payload.full_name.strip()
        if name:
            current_user.full_name = name
    await db.commit()
    await db.refresh(current_user)
    return current_user


@router.get(
    "",
    response_model=list[UserOut],
    dependencies=[Depends(require_permission("user.manage"))],
)
async def list_users(db: DbSession):
    res = await db.execute(select(User).order_by(User.id))
    return list(res.scalars().all())


@router.post(
    "/{user_id}/reset-password",
    response_model=AdminResetResult,
    dependencies=[Depends(require_permission("user.manage"))],
)
async def admin_reset_password(user_id: int, db: DbSession, mode: str = "temp"):
    """MASTER le restablece la contraseña a un usuario.

    - ``mode=temp``  (por omisión): le pone una contraseña temporal y la muestra
      una sola vez, para dictársela. Funciona SIN correo saliente.
    - ``mode=link``: genera el enlace de recuperación (y lo manda por correo si
      el SMTP está configurado), para que el propio usuario elija su clave.
    """
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Usuario no encontrado.")
    if not user.is_active:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Esa cuenta está desactivada.")

    if mode == "link":
        raw, _ = await passwords.issue_token(db, user, requested_by="admin")
        link = passwords.reset_link(raw)
        subject, text, html = mailer.reset_email(
            user.full_name, link, settings.RESET_TOKEN_MINUTES
        )
        sent = await mailer.send(user.email, subject, text, html)
        return AdminResetResult(
            user_id=user.id,
            email=user.email,
            full_name=user.full_name,
            reset_link=link,
            expires_minutes=settings.RESET_TOKEN_MINUTES,
            email_sent=sent,
        )

    temp = passwords.temp_password()
    user.hashed_password = security.hash_password(temp)
    await db.commit()
    return AdminResetResult(
        user_id=user.id,
        email=user.email,
        full_name=user.full_name,
        temp_password=temp,
    )
