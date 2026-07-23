"""SQLAlchemy models - imported here so metadata is fully registered."""
from app.models.user import User, Role, Permission, role_permissions
from app.models.property_group import PropertyGroup
from app.models.company import Company
from app.models.venue import Venue
from app.models.property_budget import PropertyBudget
from app.models.booker import Booker
from app.models.artist import Artist
from app.models.show import Show
from app.models.seasonal_rate import ShowSeasonalRate
from app.models.media import ShowImage, ArtistDocument
from app.models.booking import Booking
from app.models.product_request import ProductRequest, RequestProposal
from app.models.conversation import Conversation, Message
from app.models.hotel_lead import HotelLead
from app.models.notification import ArtistNotification
from app.models.blocked_date import ArtistBlockedDate
from app.models.tax_figure import TaxFigure
from app.models.enums import (
    PayoutSpeed,
    RiskTier,
    BookingStatus,
    RequestStatus,
    ProposalStatus,
    PAYOUT_COMMISSION,
    PAYOUT_DAYS,
    RISK_COMMISSION,
    risk_tier_for_days,
    ARTIST_CATEGORIES,
    ARTIST_SUBCATEGORIES,
    MAX_ARTIST_IMAGES,
    CANCELLATION_CUTOFF_HOURS,
    TRAVEL_BUFFER_HOURS,
)

__all__ = [
    "User",
    "Role",
    "Permission",
    "role_permissions",
    "PropertyGroup",
    "Company",
    "Venue",
    "PropertyBudget",
    "Booker",
    "Artist",
    "Show",
    "ShowSeasonalRate",
    "ShowImage",
    "ArtistDocument",
    "Booking",
    "ProductRequest",
    "RequestProposal",
    "Conversation",
    "Message",
    "HotelLead",
    "ArtistNotification",
    "ArtistBlockedDate",
    "TaxFigure",
    "PayoutSpeed",
    "RiskTier",
    "BookingStatus",
    "RequestStatus",
    "ProposalStatus",
    "PAYOUT_COMMISSION",
    "PAYOUT_DAYS",
    "RISK_COMMISSION",
    "risk_tier_for_days",
    "ARTIST_CATEGORIES",
    "ARTIST_SUBCATEGORIES",
    "MAX_ARTIST_IMAGES",
    "CANCELLATION_CUTOFF_HOURS",
    "TRAVEL_BUFFER_HOURS",
]
