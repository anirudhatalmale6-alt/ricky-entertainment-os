"""Seed baseline RBAC (roles + permissions) and an initial admin user.

Run:  python seed.py
"""
import asyncio

from sqlalchemy import select

from app.core.security import hash_password
from app.db.session import AsyncSessionLocal, init_db
from app.models.user import Permission, Role, User

PERMISSIONS = [
    ("user.manage", "Create / edit / deactivate users"),
    ("artist.manage", "Approve and manage artists"),
    ("company.manage", "Manage hotels / venues"),
    ("booking.manage", "Manage bookings and requests"),
    ("invoice.manage", "Manage CFDI invoicing"),
    ("payment.manage", "Manage payments and settlements"),
    ("report.view", "View reports and BI"),
]

# role -> list of permission codes ("*" means all)
ROLES = {
    "admin": ["*"],
    "finance": ["invoice.manage", "payment.manage", "report.view"],
    "booker": ["booking.manage", "report.view"],
    "artist": [],
}

ADMIN_EMAIL = "admin@ricky.os"
ADMIN_PASSWORD = "Admin123!"  # change after first login


async def main() -> None:
    await init_db()
    async with AsyncSessionLocal() as db:
        # Permissions
        perm_by_code: dict[str, Permission] = {}
        for code, desc in PERMISSIONS:
            res = await db.execute(select(Permission).where(Permission.code == code))
            p = res.scalar_one_or_none()
            if not p:
                p = Permission(code=code, description=desc)
                db.add(p)
            perm_by_code[code] = p
        await db.flush()

        # Roles
        role_by_name: dict[str, Role] = {}
        for name, codes in ROLES.items():
            res = await db.execute(select(Role).where(Role.name == name))
            r = res.scalar_one_or_none()
            if not r:
                r = Role(name=name, description=f"{name.capitalize()} role")
                db.add(r)
            perms = list(perm_by_code.values()) if codes == ["*"] else [perm_by_code[c] for c in codes]
            r.permissions = perms
            role_by_name[name] = r
        await db.flush()

        # Admin user
        res = await db.execute(select(User).where(User.email == ADMIN_EMAIL))
        if not res.scalar_one_or_none():
            db.add(
                User(
                    email=ADMIN_EMAIL,
                    full_name="RICKY Admin",
                    hashed_password=hash_password(ADMIN_PASSWORD),
                    is_superuser=True,
                    role_id=role_by_name["admin"].id,
                )
            )

        await db.commit()
    print("Seed complete.")
    print(f"  Admin login: {ADMIN_EMAIL} / {ADMIN_PASSWORD}")
    print(f"  Roles: {', '.join(ROLES)}")


if __name__ == "__main__":
    asyncio.run(main())
