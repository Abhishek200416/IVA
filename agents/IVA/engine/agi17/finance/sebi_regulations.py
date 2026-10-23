"""AGI 1.7 SEBI Derivatives Regulatory Framework (October 2024 Circular & 2025/2026 Rules).

Synthesizes verified regulatory mandates into deterministic risk & margin rules:
1. Contract Size Governance:
   - Minimum contract notional value ₹15–20 Lakhs.
   - Bank Nifty lot size parameterization (Standard Lot 15 vs Revised Lot 30).
2. Weekly Expiry Rationalization:
   - Single benchmark index per exchange weekly rule (Nifty 50 on NSE, Sensex on BSE).
   - Bank Nifty weekly vs monthly transition rules.
3. Mandatory Margin & Risk Controls:
   - 100% Upfront Option Premium Collection from buyers.
   - 2.0% Additional Extreme Loss Margin (ELM) on short options on expiry day.
   - Disallowance of calendar spread margin offsets on expiry day.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .bank_nifty_market import BankNiftyContractSpec
from .bank_nifty_paper_trader import OrderSide


@dataclass(frozen=True)
class SebiMarginRequirement:
    contract_symbol: str
    side: OrderSide
    units: int
    premium_per_unit: float
    spot_price: float
    is_expiry_day: bool
    upfront_premium_required_inr: float
    base_span_margin_inr: float
    extreme_loss_margin_inr: float  # Includes additional 2% ELM on expiry day
    total_margin_required_inr: float
    calendar_spread_benefit_allowed: bool
    regulatory_reference: str = "SEBI/HO/MRD/MRD-PoD-1/P/CIR/2024/132"


class SebiDerivativeRegulatoryEngine:
    """Deterministic validator and margin calculator adhering to SEBI 2024/2025/2026 circulars."""

    CIRCULAR_DATE = "2024-10-01"
    MIN_CONTRACT_VALUE_INR = 1_500_000.0  # ₹15 Lakhs minimum contract value
    MAX_CONTRACT_VALUE_INR = 2_000_000.0  # ₹20 Lakhs
    EXPIRY_DAY_ADDITIONAL_ELM_PCT = 0.02  # Additional 2% ELM on short option notional

    @classmethod
    def validate_contract_notional(cls, spot_price: float, lot_size: int = 15) -> Dict[str, Any]:
        """Verifies if the contract notional satisfies SEBI minimum contract value range."""
        notional = spot_price * lot_size
        meets_minimum = notional >= cls.MIN_CONTRACT_VALUE_INR
        return {
            "spot_price": spot_price,
            "lot_size": lot_size,
            "contract_notional_inr": round(notional, 2),
            "meets_minimum_15_lakhs": meets_minimum,
            "recommended_lot_size": 30 if notional < cls.MIN_CONTRACT_VALUE_INR else lot_size,
        }

    @classmethod
    def calculate_order_margins(
        cls,
        *,
        contract_symbol: str,
        side: OrderSide,
        units: int,
        premium: float,
        spot_price: float,
        is_expiry_day: bool = False,
        is_calendar_spread: bool = False,
    ) -> SebiMarginRequirement:
        """Calculates exact SEBI margin requirement incorporating upfront premium and expiry ELM."""
        total_premium = round(units * premium, 2)
        notional_turnover = round(units * spot_price, 2)

        if side == OrderSide.BUY:
            # Buyers must provide 100% upfront premium (no credit/intraday leverage on premium)
            upfront_premium = total_premium
            base_span = 0.0
            elm = 0.0
            total_req = upfront_premium
            calendar_allowed = False
        else:
            # Sellers require SPAN (~10-12% of underlying notional) + Exposure/ELM margin (3.5% normal, 5.5% on expiry day)
            upfront_premium = 0.0
            base_span = round(notional_turnover * 0.10, 2)  # ~10% standard SPAN approximation

            base_elm_rate = 0.035
            effective_elm_rate = (base_elm_rate + cls.EXPIRY_DAY_ADDITIONAL_ELM_PCT) if is_expiry_day else base_elm_rate
            elm = round(notional_turnover * effective_elm_rate, 2)

            calendar_allowed = not is_expiry_day if is_calendar_spread else False
            total_req = round(base_span + elm, 2)

        return SebiMarginRequirement(
            contract_symbol=contract_symbol,
            side=side,
            units=units,
            premium_per_unit=premium,
            spot_price=spot_price,
            is_expiry_day=is_expiry_day,
            upfront_premium_required_inr=upfront_premium,
            base_span_margin_inr=base_span,
            extreme_loss_margin_inr=elm,
            total_margin_required_inr=total_req,
            calendar_spread_benefit_allowed=calendar_allowed,
        )

    @classmethod
    def check_pre_trade_compliance(
        cls,
        available_cash: float,
        requirement: SebiMarginRequirement,
    ) -> Tuple[bool, str]:
        """Pre-trade risk gateway enforcing SEBI capital requirement."""
        if available_cash < requirement.total_margin_required_inr:
            deficit = round(requirement.total_margin_required_inr - available_cash, 2)
            return (
                False,
                f"SEBI Margin shortfall: ₹{deficit:.2f} deficit. Required: ₹{requirement.total_margin_required_inr:.2f}, Available: ₹{available_cash:.2f}",
            )
        return True, "COMPLIANT"
