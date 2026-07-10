"""Domain enums and their business-rule tables.

These encode the commission model David defined in REVISION RICKY (calls with
proveedores, artistas and hoteles). Keeping the rates here — next to the enum —
means there is a single source of truth for the numbers.
"""
from __future__ import annotations

import enum


class PayoutSpeed(str, enum.Enum):
    """How fast an artist wants to receive their money.

    The faster they want it, the higher the commission the platform charges
    the artist for advancing/prioritising the payout.
    """

    MENSUAL = "mensual"   # pays out monthly   -> 3.5%
    FAST = "fast"         # pays out in 15 days -> 7.5%
    EXPRESS = "express"   # pays out in 7 days  -> 12%


# Commission charged to the ARTIST for each payout speed.
PAYOUT_COMMISSION: dict[PayoutSpeed, float] = {
    PayoutSpeed.MENSUAL: 0.035,
    PayoutSpeed.FAST: 0.075,
    PayoutSpeed.EXPRESS: 0.12,
}

# Days until the artist receives the money.
PAYOUT_DAYS: dict[PayoutSpeed, int] = {
    PayoutSpeed.MENSUAL: 30,
    PayoutSpeed.FAST: 15,
    PayoutSpeed.EXPRESS: 7,
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
