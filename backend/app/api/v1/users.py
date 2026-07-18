"""User endpoints: current profile and (admin) listing."""
from fastapi import APIRouter, Depends
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession, require_permission
from app.models.user import User
from app.schemas.user import UserOut, UserSelfUpdate

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
