"""Seed baseline RBAC (roles + permissions) and an initial admin user.

Run:  python seed.py
"""
import asyncio

from sqlalchemy import select

from app.core.security import hash_password
from app.db.session import AsyncSessionLocal, init_db
from app.models.contract import ARTIST_CONTRACT_SLUG, ContractTemplate
from app.models.tax_figure import TaxFigure
from app.models.user import Permission, Role, User

# 4 figuras fiscales que definió David con su contador (2026-07-26). La comisión
# SHOWMA al músico es 3.7% ("Platform Services"); en el lado hotel se cobra 7.2%
# ("Service Fee") sobre ingresos — ese va aparte, no en la figura del artista.
# Todo es editable desde Master → Impuestos. Se siembran sólo si el catálogo está
# vacío (no resucita lo que él borre/edite).
ARTIST_TAX_FIGURES = [
    dict(name="Persona Física – Actividad Empresarial y Profesional",
         commission_pct=3.7, iva_traslado_pct=16, iva_ret_pct=10.6667, isr_ret_pct=10,
         isr_variable=False, is_default=True,
         notes="Aplica retenciones. Neto = Subtotal + IVA − Ret. IVA − Ret. ISR."),
    dict(name="Persona Física – RESICO",
         commission_pct=3.7, iva_traslado_pct=16, iva_ret_pct=10.6667, isr_ret_pct=1.25,
         isr_variable=True, is_default=False,
         notes="ISR variable (1% a 2.5%), configurable por artista. Aplica retenciones."),
    dict(name="Persona Moral – Régimen General",
         commission_pct=3.7, iva_traslado_pct=16, iva_ret_pct=0, isr_ret_pct=0,
         isr_variable=False, is_default=False, notes="Sin retenciones. Neto = Subtotal + IVA."),
    dict(name="Persona Moral – Otros regímenes vigentes",
         commission_pct=3.7, iva_traslado_pct=16, iva_ret_pct=0, isr_ret_pct=0,
         isr_variable=False, is_default=False, notes="Sin retenciones. Neto = Subtotal + IVA."),
]

# Versión preliminar del Contrato Marco talento–plataforma (David, 2026-07-26).
# Se siembra como v1 sólo si aún no existe ninguna versión; el Master lo edita
# después desde Configuración / Plantillas y esto no vuelve a tocarlo.
ARTIST_CONTRACT_TITLE = (
    "Contrato Marco de Prestación de Servicios y Uso de la Plataforma SHOWMA"
)
ARTIST_CONTRACT_BODY = """CONTRATO MARCO DE PRESTACIÓN DE SERVICIOS Y USO DE LA PLATAFORMA SHOWMA
SHOWMA GROUP, S.A. DE C.V.

Modelo para aceptación electrónica. Debe ser revisado por asesor jurídico antes de su uso definitivo.

ACEPTACIÓN ELECTRÓNICA
La aceptación mediante la plataforma produce efectos legales equivalentes a la firma autógrafa conforme a la legislación mexicana aplicable.

PARTES
SHOWMA GROUP, S.A. DE C.V. y el prestador de servicios registrado ('EL ARTISTA').

OBJETO
Plataforma tecnológica para promoción artística, contratación, administración de eventos, generación de documentación administrativa y fiscal y programación de pagos.

RELACIÓN
El Artista es un prestador independiente; no existe relación laboral con SHOWMA.

CONTRATACIONES
Cada evento confirmado constituye una Orden de Servicio.

FACTURACIÓN
SHOWMA podrá generar el CFDI para revisión del Artista, quien es responsable de mantener correcta su información fiscal.

PAGOS
Sujetos a prestación del servicio, validación administrativa, documentación completa y CFDI correcto.

COMISIONES
Se aplicarán conforme al porcentaje vigente publicado en la plataforma.

OBLIGACIONES
Puntualidad, profesionalismo, cumplimiento de reglamentos y actualización de información fiscal y bancaria.

CANCELACIONES
Las cancelaciones injustificadas podrán generar penalizaciones y suspensión.

NO CIRCUNVENCIÓN
El Artista se compromete a no contratar directamente con clientes presentados por SHOWMA durante 24 meses, sujeto a validación legal.

PROPIEDAD INTELECTUAL
El Artista conserva sus derechos y concede una licencia no exclusiva para promoción.

USO DE IMAGEN
Autorización para utilizar fotografías y videos con fines promocionales.

DATOS PERSONALES
Tratamiento conforme al Aviso de Privacidad.

LIMITACIÓN DE RESPONSABILIDAD
SHOWMA no responde por accidentes, pérdidas de equipo, incumplimientos atribuibles al cliente, fuerza mayor ni daños indirectos.

INDEMNIZACIÓN
El Artista mantendrá a SHOWMA en paz y a salvo frente a reclamaciones derivadas de sus incumplimientos.

TERMINACIÓN
SHOWMA podrá suspender o cancelar cuentas por fraude, documentación falsa o incumplimientos.

JURISDICCIÓN
Leyes de México y tribunales competentes del domicilio social de SHOWMA GROUP, S.A. DE C.V.

ACEPTACIÓN FINAL
El Artista declara haber leído y aceptado el contrato, los Términos y Condiciones y el Aviso de Privacidad."""

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

        # Contrato de artistas (versión preliminar) — sólo si no existe ninguna
        res = await db.execute(
            select(ContractTemplate).where(ContractTemplate.slug == ARTIST_CONTRACT_SLUG)
        )
        if not res.scalars().first():
            db.add(ContractTemplate(
                slug=ARTIST_CONTRACT_SLUG,
                version=1,
                title=ARTIST_CONTRACT_TITLE,
                body=ARTIST_CONTRACT_BODY,
            ))

        # Figuras fiscales — sólo si el catálogo está totalmente vacío
        res = await db.execute(select(TaxFigure).limit(1))
        if not res.scalars().first():
            for fig in ARTIST_TAX_FIGURES:
                db.add(TaxFigure(**fig, active=True))

        await db.commit()
    print("Seed complete.")
    print(f"  Admin login: {ADMIN_EMAIL} / {ADMIN_PASSWORD}")
    print(f"  Roles: {', '.join(ROLES)}")


if __name__ == "__main__":
    asyncio.run(main())
