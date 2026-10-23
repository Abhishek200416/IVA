"""Acceptance tests for Multi-Horizon Options Structure Screener & Ratio Spread Engine.

TASK-BN-28:
Covers:
1. Multi-horizon IV term structure slope computation and regime classification (CONTANGO, BACKWARDATION, FLAT).
2. Long Calendar Spread pricing, positive theta harvest, and vega resilience.
3. SEBI Circular 2024/132 calendar margin offset removal on expiry day (T-0).
4. 1x2 Ratio Spread payoff modeling, net credit collection, asymmetric wing risk, and breakeven calculation.
5. Pre-trade risk rejection guardrails for excessive tail risk or margin deficit.
6. Quantitative composite scoring and ranking of multi-leg option structures.
"""

from __future__ import annotations

import math
import unittest
from typing import List

from agents.AGI_1_7.engine.agi17.finance.bank_nifty_market import BankNiftyContractSpec
from agents.AGI_1_7.engine.agi17.finance.bank_nifty_paper_trader import OrderSide
from agents.AGI_1_7.engine.agi17.finance.options_structure_screener import (
    OptionsStructureProposal,
    OptionsStructureScreener,
    SpreadLeg,
    StructureType,
    TermStructureCurve,
    TermStructureRegime,
)


class TestOmegaOptionsStructureScreener(unittest.TestCase):
    """Test suite for OptionsStructureScreener and term structure analysis."""

    def test_term_structure_slope_and_regimes(self) -> None:
        """Verify IV term structure slope calculation across Contango, Backwardation, and Flat."""
        # 1. Contango (Calm / normal market: far IV > near IV)
        contango_curve = OptionsStructureScreener.analyze_term_structure(
            near_dte_days=7,
            near_iv=0.14,
            far_dte_days=35,
            far_iv=0.18,
        )
        self.assertEqual(contango_curve.regime, TermStructureRegime.CONTANGO)
        self.assertGreater(contango_curve.term_slope, 0.02)

        # 2. Backwardation (Event / panic market: near IV > far IV)
        backwardation_curve = OptionsStructureScreener.analyze_term_structure(
            near_dte_days=7,
            near_iv=0.24,
            far_dte_days=35,
            far_iv=0.17,
        )
        self.assertEqual(backwardation_curve.regime, TermStructureRegime.BACKWARDATION)
        self.assertLess(backwardation_curve.term_slope, -0.02)

        # 3. Flat (Minimal slope)
        flat_curve = OptionsStructureScreener.analyze_term_structure(
            near_dte_days=7,
            near_iv=0.150,
            far_dte_days=35,
            far_iv=0.152,
        )
        self.assertEqual(flat_curve.regime, TermStructureRegime.FLAT)
        self.assertAlmostEqual(flat_curve.term_slope, 0.0, delta=0.02)

    def test_calendar_spread_pricing_and_greeks(self) -> None:
        """Verify Long Calendar Spread Greeks: positive Theta harvest and positive Vega."""
        spot = 50000.0
        strike = 50000.0

        proposal = OptionsStructureScreener.screen_calendar_spread(
            spot=spot,
            strike=strike,
            near_dte_days=7,
            near_iv=0.15,
            far_dte_days=35,
            far_iv=0.16,
            is_call=True,
            is_near_expiry_day=False,
            lots=1,
        )

        self.assertEqual(proposal.structure_type, StructureType.LONG_CALENDAR_SPREAD)
        self.assertEqual(len(proposal.legs), 2)
        self.assertTrue(proposal.is_risk_acceptable)

        # Verify net debit paid
        self.assertGreater(proposal.net_debit_or_credit_inr, 0.0)

        # In calendar spread: short near decays faster -> net Theta > 0
        self.assertGreater(proposal.aggregate_theta, 0.0)

        # Long far option has more vega -> net Vega > 0
        self.assertGreater(proposal.aggregate_vega, 0.0)

        # Lot size multiple
        for leg in proposal.legs:
            self.assertEqual(leg.units, BankNiftyContractSpec.LOT_SIZE)

    def test_sebi_calendar_spread_margin_offset_removal(self) -> None:
        """Verify SEBI Circular 2024/132 removes calendar spread benefit on expiry day."""
        spot = 50000.0
        strike = 50000.0

        # Normal day: Calendar spread offset permitted
        normal_proposal = OptionsStructureScreener.screen_calendar_spread(
            spot=spot,
            strike=strike,
            near_dte_days=7,
            near_iv=0.15,
            far_dte_days=35,
            far_iv=0.16,
            is_near_expiry_day=False,
            lots=1,
        )
        self.assertTrue(normal_proposal.sebi_calendar_benefit_allowed)

        # Expiry day (T-0): Calendar spread offset disallowed by SEBI
        expiry_proposal = OptionsStructureScreener.screen_calendar_spread(
            spot=spot,
            strike=strike,
            near_dte_days=1,
            near_iv=0.15,
            far_dte_days=28,
            far_iv=0.16,
            is_near_expiry_day=True,
            lots=1,
        )
        self.assertFalse(expiry_proposal.sebi_calendar_benefit_allowed)

        # Expiry day requires significantly higher margin (independent SPAN + 5.5% ELM on short leg)
        self.assertGreater(
            expiry_proposal.total_margin_required_inr,
            normal_proposal.total_margin_required_inr,
        )

    def test_ratio_1x2_spread_payoff_and_greeks(self) -> None:
        """Verify 1x2 Ratio Call Spread payoff, peak profit at short strike, and uncapped wing risk."""
        spot = 50000.0
        long_strike = 50000.0
        short_strike = 50500.0

        proposal = OptionsStructureScreener.screen_ratio_spread(
            spot=spot,
            long_strike=long_strike,
            short_strike=short_strike,
            dte_days=14,
            atm_iv=0.15,
            is_call=True,
            is_expiry_day=False,
            lots=1,
        )

        self.assertEqual(proposal.structure_type, StructureType.RATIO_1X2_SPREAD)
        self.assertEqual(len(proposal.legs), 2)

        # Leg 1: Long 1 lot (15 units)
        long_leg = proposal.legs[0]
        self.assertEqual(long_leg.side, OrderSide.BUY)
        self.assertEqual(long_leg.units, BankNiftyContractSpec.LOT_SIZE)

        # Leg 2: Short 2 lots (30 units)
        short_leg = proposal.legs[1]
        self.assertEqual(short_leg.side, OrderSide.SELL)
        self.assertEqual(short_leg.units, BankNiftyContractSpec.LOT_SIZE * 2)

        # Max loss is open-ended (infinity) due to unhedged second short call
        self.assertTrue(math.isinf(proposal.max_loss_inr))

        # Peak profit occurs at short strike (50,500)
        self.assertGreater(proposal.max_profit_inr, 0.0)

        # Breakeven price is strictly above the short strike
        self.assertEqual(len(proposal.breakeven_prices), 1)
        self.assertGreater(proposal.breakeven_prices[0], short_strike)

    def test_ratio_spread_risk_rejection_guardrails(self) -> None:
        """Verify screener rejects ratio spread if margin or unhedged tail risk exceeds limits."""
        spot = 50000.0
        # Extreme tiny risk limit (₹1,000 max capital risk)
        proposal = OptionsStructureScreener.screen_ratio_spread(
            spot=spot,
            long_strike=50000.0,
            short_strike=50500.0,
            dte_days=14,
            atm_iv=0.15,
            lots=1,
            max_capital_risk_inr=1_000.0,  # Unrealistic low budget triggers rejection
        )

        self.assertFalse(proposal.is_risk_acceptable)
        self.assertIsNotNone(proposal.rejection_reason)
        self.assertIn("exceeds", proposal.rejection_reason.lower())

    def test_structure_ranking_engine(self) -> None:
        """Verify ranking engine sorts candidate proposals by score descending."""
        spot = 50000.0
        p1 = OptionsStructureScreener.screen_calendar_spread(
            spot=spot, strike=50000.0, near_dte_days=7, near_iv=0.15, far_dte_days=35, far_iv=0.16
        )
        p2 = OptionsStructureScreener.screen_calendar_spread(
            spot=spot, strike=50200.0, near_dte_days=7, near_iv=0.15, far_dte_days=35, far_iv=0.16
        )
        p3 = OptionsStructureScreener.screen_ratio_spread(
            spot=spot, long_strike=50000.0, short_strike=50600.0, dte_days=14, atm_iv=0.15
        )

        ranked = OptionsStructureScreener.rank_proposals([p1, p2, p3])

        self.assertEqual(len(ranked), 3)
        # Verify strict descending score order
        for i in range(len(ranked) - 1):
            self.assertGreaterEqual(ranked[i].score, ranked[i + 1].score)


if __name__ == "__main__":
    unittest.main()
