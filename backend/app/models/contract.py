"""Contratos — plantilla editable con versión + registro de aceptaciones.

El Contrato Marco talento–plataforma se guarda como una plantilla versionada:
cada publicación desde el Master crea una versión nueva, de modo que cada
aceptación apunta a un texto exacto. Cuando un artista lo acepta electrónicamente,
la aceptación queda registrada (nombre, fecha/hora, versión, IP) y esa constancia
hace las veces de firma autógrafa conforme a la legislación mexicana aplicable.

Ambas tablas son nuevas -> las crea create_all() automáticamente.
"""
from __future__ import annotations

from sqlalchemy import Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin

# Por ahora sólo existe el contrato de artistas; el slug deja la puerta abierta a
# más plantillas (contratante, aviso de privacidad, etc.) sin tocar el esquema.
ARTIST_CONTRACT_SLUG = "artist_contract"


class ContractTemplate(Base, TimestampMixin):
    __tablename__ = "contract_templates"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(60), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)


class ContractAcceptance(Base, TimestampMixin):
    __tablename__ = "contract_acceptances"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(60), index=True)
    version: Mapped[int] = mapped_column(Integer)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    artist_id: Mapped[int | None] = mapped_column(Integer, index=True, default=None)
    signer_name: Mapped[str] = mapped_column(String(255))
    ip: Mapped[str | None] = mapped_column(String(64), default=None)
