"""Domain enums and their business-rule tables.

These encode the commission model David defined in REVISION RICKY (calls with
proveedores, artistas and hoteles). Keeping the rates here — next to the enum —
means there is a single source of truth for the numbers.
"""
from __future__ import annotations

import enum


class PayoutSpeed(str, enum.Enum):
    """"Plan de liquidacion" - how fast an artist wants to receive their money.

    The faster they want it, the higher the extra commission the platform
    charges the artist for advancing/prioritising the payout. Values and
    percentages taken from David's definitive registration sheet ("Hoja
    Registro", 2026-07-11).
    """

    STANDARD = "standard"   # after client pays + 3 business days -> no cost
    FAST = "fast"           # 15 days after the event            -> +1.5%
    PRIORITY = "priority"   # 7 days after the event             -> +2.5%
    EXPRESS = "express"     # 3 days after the event             -> +4%


# Extra commission charged to the ARTIST for each payout speed.
PAYOUT_COMMISSION: dict[PayoutSpeed, float] = {
    PayoutSpeed.STANDARD: 0.0,
    PayoutSpeed.FAST: 0.015,
    PayoutSpeed.PRIORITY: 0.025,
    PayoutSpeed.EXPRESS: 0.04,
}

# Days until the artist receives the money (Standard counts from client payment
# + 3 business days; the rest count from the event date).
PAYOUT_DAYS: dict[PayoutSpeed, int] = {
    PayoutSpeed.STANDARD: 3,
    PayoutSpeed.FAST: 15,
    PayoutSpeed.PRIORITY: 7,
    PayoutSpeed.EXPRESS: 3,
}


class RiskTier(str, enum.Enum):
    """Payment-behaviour risk tier for a contracting company (contratante).

    Drives the commission charged to the hotel/venue. Everybody starts at A.
    A+ is a reward earned by paying fast and consistently; B / B++ are earned
    by paying late, or negotiated up-front at sign-up if the company already
    knows it wants longer payment terms.
    """

    A_PLUS = "A+"        # pays in < 15 days  -> 5.6%
    A = "A"              # pays in 15-30 days -> 7.4%  (default on sign-up)
    B = "B"              # pays in > 30 days  -> 11%
    B_PLUS_PLUS = "B++"  # pays in > 40 days  -> 18%


# Commission charged to the CONTRATANTE for each risk tier.
RISK_COMMISSION: dict[RiskTier, float] = {
    RiskTier.A_PLUS: 0.056,
    RiskTier.A: 0.074,
    RiskTier.B: 0.11,
    RiskTier.B_PLUS_PLUS: 0.18,
}


def risk_tier_for_days(avg_payment_days: float) -> RiskTier:
    """Map a company's average days-to-pay to its earned risk tier.

    Used after the 3-month regularisation window to auto-adjust a company's
    tier from its real payment behaviour.
    """
    if avg_payment_days < 15:
        return RiskTier.A_PLUS
    if avg_payment_days <= 30:
        return RiskTier.A
    if avg_payment_days <= 40:
        return RiskTier.B
    return RiskTier.B_PLUS_PLUS
