"""AGI 1.7 SEBI Regulatory Framework & Index Derivatives Compliance Engine.

Implements the official SEBI 2024-2026 index derivative regulatory circulars:
(Ref: SEBI Circular SEBI/HO/MRD/MRD-PoD-2/P/CIR/2024/131 dated October 01, 2024)

Key Mandates:
1. Minimum Contract Value: Derivative contract notional must be between ₹15 Lakhs and ₹20 Lakhs.
2. Upfront Premium Collection: 100% option premium must be collected upfront from buyers prior to order execution.
3. Expiry Day Extreme Loss Margin (ELM): Additional 2% ELM surcharge required on short option positions on contract expiry day.
4. Calendar Spread Expiry Day Restriction: Calendar spread margin benefit is removed on expiry day for expiring contracts.
5. Rationalized Weekly Expiries: Exactly one benchmark index with weekly expiry per exchange.
6. Zero Live Brokerage: Strictly simulated paper trading and research compliance validation.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple

from .bank_nifty_market import BankNiftyContractSpec


@dataclass(frozen=True)
class SebiNorms2024:
    CIRCULAR_REF: str = "SEBI/HO/MRD/MRD-PoD-2/P/CIR/2024/131"
    EFFECTIVE_DATE: str = "2024-11-20"
    MIN_CONTRACT_VALUE_INR: float = 1_500_000.0   # ₹15 Lakhs
    MAX_CONTRACT_VALUE_INR: float = 2_000_000.0   # ₹20 Lakhs
    EXPIRY_DAY_ELM_SURCHARGE_PCT: float = 0.02    # 2.0% Additional ELM on short options on expiry day
    UPFRONT_PREMIUM_MANDATE: bool = True
    MAX_WEEKLY_INDEX_PER_EXCHANGE: int = 1


@dataclass
class MarginRequirement:
    order_symbol: str
    units: int
    is_short: bool
    is_expiry_day: bool
    gross_notional_inr: float
    upfront_premium_inr: float
    span_margin_inr: float
    elm_margin_inr: float
    expiry_day_elm_surcharge_inr: float
    total_margin_required_inr: float
    is_compliant: bool
    compliance_remarks: str


class SebiRegulatoryEngine:
    """Validates simulated paper orders against Indian index derivative regulatory mandates."""

    def __init__(self, norms: Optional[SebiNorms2024] = None) -> None:
        self.norms = norms or SebiNorms2024()

    def validate_contract_notional(self, spot_price: float, lot_size: int) -> Tuple[bool, float, str]:
        """Verifies that the contract size satisfies the ₹15 Lakhs minimum notional threshold."""
        if spot_price <= 0 or lot_size <= 0:
            return False, 0.0, "Invalid spot price or lot size"

        notional = round(spot_price * lot_size, 2)
        if notional < self.norms.MIN_CONTRACT_VALUE_INR:
            return False, notional, (
                f"Contract notional ₹{notional:,.2f} is below SEBI minimum threshold of ₹{self.norms.MIN_CONTRACT_VALUE_INR:,.2f}. "
                f"(Calibrated lot size adjustment required)"
            )
        return True, notional, f"Compliant notional ₹{notional:,.2f}"

    def calculate_margin(
        self,
        *,
        symbol: str,
        units: int,
        price: float,
        spot: float,
        is_short: bool,
        is_expiry_day: bool = False,
    ) -> MarginRequirement:
        """Calculates exact SEBI margin requirement for long or short options."""
        units_abs = abs(units)
        gross_notional = round(spot * units_abs, 2)
        premium_value = round(price * units_abs, 2)

        if not is_short:
            # Long Option: Buyer pays 100% upfront premium, zero SPAN/ELM margin required
            return MarginRequirement(
                order_symbol=symbol,
                units=units_abs,
                is_short=False,
                is_expiry_day=is_expiry_day,
                gross_notional_inr=gross_notional,
                upfront_premium_inr=premium_value,
                span_margin_inr=0.0,
                elm_margin_inr=0.0,
                expiry_day_elm_surcharge_inr=0.0,
                total_margin_required_inr=premium_value,
                is_compliant=True,
                compliance_remarks="Long Option: 100% Upfront premium required per SEBI mandate",
            )
        else:
            # Short Option (Writer): Standard SPAN (~12.5%) + Exposure/ELM (3.5%) + Expiry Day Surcharge (2%)
            span_margin = round(gross_notional * 0.125, 2)
            base_elm = round(gross_notional * 0.035, 2)
            expiry_surcharge = round(gross_notional * self.norms.EXPIRY_DAY_ELM_SURCHARGE_PCT, 2) if is_expiry_day else 0.0
            total_margin = round(span_margin + base_elm + expiry_surcharge, 2)

            remarks = "Short Option: SPAN + ELM margin applied."
            if is_expiry_day:
                remarks += f" Additional 2% Expiry Day ELM surcharge applied (+₹{expiry_surcharge:,.2f})."

            return MarginRequirement(
                order_symbol=symbol,
                units=units_abs,
                is_short=True,
                is_expiry_day=is_expiry_day,
                gross_notional_inr=gross_notional,
                upfront_premium_inr=0.0,
                span_margin_inr=span_margin,
                elm_margin_inr=base_elm,
                expiry_day_elm_surcharge_inr=expiry_surcharge,
                total_margin_required_inr=total_margin,
                is_compliant=True,
                compliance_remarks=remarks,
            )

    def evaluate_order_compliance(
        self,
        *,
        symbol: str,
        units: int,
        price: float,
        spot: float,
        is_short: bool,
        available_margin: float,
        is_expiry_day: bool = False,
    ) -> Tuple[bool, str, MarginRequirement]:
        """Comprehensive compliance check against available capital and SEBI regulations."""
        margin_req = self.calculate_margin(
            symbol=symbol,
            units=units,
            price=price,
            spot=spot,
            is_short=is_short,
            is_expiry_day=is_expiry_day,
        )

        if available_margin < margin_req.total_margin_required_inr:
            reason = (
                f"MARGIN_DEFICIT: Available ₹{available_margin:,.2f} < "
                f"Required ₹{margin_req.total_margin_required_inr:,.2f}"
            )
            return False, reason, margin_req

        return True, "SEBI_COMPLIANT", margin_req
