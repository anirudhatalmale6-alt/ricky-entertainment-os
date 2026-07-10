"""SQLAlchemy models - imported here so metadata is fully registered."""
from app.models.user import User, Role, Permission, role_permissions
from app.models.company import Company
from app.models.venue import Venue
from app.models.booker import Booker
from app.models.artist import Artist
from app.models.show import Show
from app.models.seasonal_rate import ShowSeasonalRate
from app.models.media import ShowImage, ArtistDocument
from app.models.enums import (
    PayoutSpeed,
    RiskTier,
    PAYOUT_COMMISSION,
    PAYOUT_DAYS,
    RISK_COMMISSION,
    risk_tier_for_days,
    ARTIST_CATEGORIES,
    ARTIST_SUBCATEGORIES,
    MAX_ARTIST_IMAGES,
)

__all__ = [
    "User",
    "Role",
    "Permission",
    "role_permissions",
    "Company",
    "Venue",
    "Booker",
    "Artist",
    "Show",
    "ShowSeasonalRate",
    "ShowImage",
    "ArtistDocument",
    "PayoutSpeed",
    "RiskTier",
    "PAYOUT_COMMISSION",
    "PAYOUT_DAYS",
    "RISK_COMMISSION",
    "risk_tier_for_days",
    "ARTIST_CATEGORIES",
    "ARTIST_SUBCATEGORIES",
    "MAX_ARTIST_IMAGES",
]
