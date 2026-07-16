"""Aggregate v1 router."""
from fastapi import APIRouter

from app.api.v1 import (
    artists,
    auth,
    bookings,
    chat,
    companies,
    groups,
    intelligence,
    leads,
    me,
    requests,
    shows,
    users,
)

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(artists.router)
api_router.include_router(shows.router)
api_router.include_router(companies.router)
api_router.include_router(groups.router)
api_router.include_router(bookings.router)
api_router.include_router(requests.router)
api_router.include_router(chat.router)
api_router.include_router(intelligence.router)
api_router.include_router(leads.router)
api_router.include_router(me.router)
