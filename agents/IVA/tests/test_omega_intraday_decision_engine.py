"""Acceptance test suite for Bank Nifty Intraday Decision Engine (CPR, PCR, GEX, and Checklist)."""

import unittest

from agents.AGI_1_7.engine.agi17.finance.intraday_decision_engine import (
    BankNiftyIntradayDecisionEngine,
    CPRLevels,
    CPRRegime,
    GEXProfile,
    GEXRegime,
    IntradayChecklistResult,
    IntradayDecisionAction,
    OpenRelationToCPR,
    PCRMetrics,
    PCRSentiment,
    StrikeGEXItem,
)


class TestOmegaIntradayDecisionEngine(unittest.TestCase):
    """Test suite for BankNiftyIntradayDecisionEngine."""

    def setUp(self) -> None:
        self.engine = BankNiftyIntradayDecisionEngine(
            lot_size=15,
            tick_size=0.05,
            baseline_cpr_width_pts=120.0,
        )

    def test_cpr_calculation_and_width_regimes(self) -> None:
        """Verify CPR formulas, floor pivots, and width regimes."""
        prev_h = 50000.0
        prev_l = 49600.0
        prev_c = 49850.0

        cpr = self.engine.compute_cpr_levels(prev_high=prev_h, prev_low=prev_l, prev_close=prev_c)

        # Expected:
        # P = (50000 + 49600 + 49850) / 3 = 49816.67
        # BC = (50000 + 49600) / 2 = 49800.0
        # TC = 2 * 49816.67 - 49800 = 49833.34
        self.assertAlmostEqual(cpr.pivot, 49816.67, places=1)
        self.assertAlmostEqual(cpr.bottom_central, 49800.0, places=1)
        self.assertAlmostEqual(cpr.top_central, 49833.34, places=1)

        # Width = 49833.34 - 49800.0 = 33.34 pts
        # Baseline = 120.0 pts. 33.34 < 0.60 * 120 (72.0) -> NARROW_BREAKOUT
        self.assertEqual(cpr.regime, CPRRegime.NARROW_BREAKOUT)

        # Floor pivots
        # R1 = 2*P - L = 2*49816.67 - 49600 = 50033.34
        # S1 = 2*P - H = 2*49816.67 - 50000 = 49633.34
        self.assertAlmostEqual(cpr.r1, 50033.34, places=1)
        self.assertAlmostEqual(cpr.s1, 49633.34, places=1)

        # Wide CPR test (When close is at extreme High, CPR width = 1/3 * (H - L))
        # H = 50500, L = 49200, C = 50500 -> Width = 433.34 pts > 1.40 * 120 (168 pts)
        wide_cpr = self.engine.compute_cpr_levels(prev_high=50500.0, prev_low=49200.0, prev_close=50500.0)
        self.assertEqual(wide_cpr.regime, CPRRegime.WIDE_RANGE_BOUND)

    def test_open_relation_to_cpr(self) -> None:
        """Verify open positioning classification relative to CPR."""
        cpr = self.engine.compute_cpr_levels(prev_high=50000.0, prev_low=49600.0, prev_close=49850.0)

        # Open above TC (49833.34)
        rel_above = self.engine.evaluate_open_relation(open_price=49920.0, cpr=cpr)
        self.assertEqual(rel_above, OpenRelationToCPR.ABOVE_TC_BULLISH)

        # Open below BC (49800.0)
        rel_below = self.engine.evaluate_open_relation(open_price=49750.0, cpr=cpr)
        self.assertEqual(rel_below, OpenRelationToCPR.BELOW_BC_BEARISH)

        # Open inside CPR
        rel_inside = self.engine.evaluate_open_relation(open_price=49815.0, cpr=cpr)
        self.assertEqual(rel_inside, OpenRelationToCPR.INSIDE_CPR_RANGE)

    def test_pcr_sentiment_and_contrarian_extremes(self) -> None:
        """Verify Put-Call Ratio thresholds and contrarian extremes."""
        # Bullish: More Puts than Calls (PCR > 1.1)
        call_oi = {49700.0: 10000, 49800.0: 20000, 49900.0: 30000}  # total 60,000
        put_oi_bullish = {49700.0: 35000, 49800.0: 30000, 49900.0: 15000}  # total 80,000 -> PCR = 1.333
        pcr_bull = self.engine.compute_pcr(call_oi, put_oi_bullish)
        self.assertEqual(pcr_bull.sentiment, PCRSentiment.BULLISH)
        self.assertAlmostEqual(pcr_bull.pcr, 1.333, places=2)

        # Bearish: PCR < 0.8
        put_oi_bearish = {49700.0: 15000, 49800.0: 15000, 49900.0: 10000}  # total 40,000 -> PCR = 0.667
        pcr_bear = self.engine.compute_pcr(call_oi, put_oi_bearish)
        self.assertEqual(pcr_bear.sentiment, PCRSentiment.BEARISH)

        # Extreme Oversold: PCR >= 1.50
        put_oi_oversold = {49700.0: 50000, 49800.0: 50000}  # total 100,000 / 60,000 = 1.667
        pcr_ext_bull = self.engine.compute_pcr(call_oi, put_oi_oversold)
        self.assertEqual(pcr_ext_bull.sentiment, PCRSentiment.EXTREME_OVERSOLD_REVERSAL_UP)

    def test_max_pain_calculation(self) -> None:
        """Verify Max Pain strike minimizes aggregate option payout."""
        # Setup symmetric chain where strike 49800 has massive straddle OI
        call_oi = {49700.0: 5000, 49800.0: 45000, 49900.0: 60000}
        put_oi = {49700.0: 55000, 49800.0: 40000, 49900.0: 5000}

        mp = self.engine.compute_max_pain(call_oi, put_oi)
        self.assertEqual(mp, 49800.0)

    def test_gex_profile_and_walls(self) -> None:
        """Verify Gamma Exposure profile, Call/Put walls, and GEX regime."""
        spot = 49850.0
        quotes = [
            {"strike": 49600.0, "gamma": 0.0008, "call_oi": 5000, "put_oi": 48000},  # Heavy Puts (Put Wall)
            {"strike": 49700.0, "gamma": 0.0012, "call_oi": 12000, "put_oi": 32000},
            {"strike": 49800.0, "gamma": 0.0020, "call_oi": 25000, "put_oi": 22000},
            {"strike": 49900.0, "gamma": 0.0018, "call_oi": 38000, "put_oi": 14000},
            {"strike": 50000.0, "gamma": 0.0010, "call_oi": 65000, "put_oi": 4000},  # Heavy Calls (Call Wall)
        ]

        gex = self.engine.compute_gex_profile(spot=spot, quotes=quotes)

        self.assertEqual(gex.put_wall_strike, 49600.0)
        self.assertEqual(gex.call_wall_strike, 50000.0)
        self.assertGreater(len(gex.strike_items), 0)
        self.assertIn(gex.regime, (GEXRegime.POSITIVE_GAMMA_PINNING, GEXRegime.NEGATIVE_GAMMA_VOLATILE, GEXRegime.NEUTRAL_GAMMA))

    def test_intraday_decision_checklist(self) -> None:
        """Verify full 6-point checklist logic for bullish, inside CPR, and 15:15 cutoff cases."""
        cpr = self.engine.compute_cpr_levels(prev_high=50000.0, prev_low=49600.0, prev_close=49850.0)
        call_oi = {49700.0: 10000, 49800.0: 20000, 49900.0: 30000}
        put_oi = {49700.0: 35000, 49800.0: 30000, 49900.0: 15000}
        pcr = self.engine.compute_pcr(call_oi, put_oi)  # PCR = 1.333 (Bullish)

        quotes = [
            {"strike": 49700.0, "gamma": 0.0012, "call_oi": 10000, "put_oi": 35000},
            {"strike": 49800.0, "gamma": 0.0020, "call_oi": 20000, "put_oi": 30000},
            {"strike": 49900.0, "gamma": 0.0015, "call_oi": 30000, "put_oi": 15000},
        ]
        gex = self.engine.compute_gex_profile(spot=49880.0, quotes=quotes)

        # 1. Bullish scenario at 09:35 AM IST (Spot > TC, Open > TC, PCR Bullish)
        res_bull = self.engine.evaluate_intraday_decision_checklist(
            current_spot=49880.0,
            open_price=49860.0,  # Above TC (49833.34)
            cpr=cpr,
            pcr_metrics=pcr,
            gex_profile=gex,
            prev_high=50000.0,
            prev_low=49600.0,
            current_time_str="09:35",
            atr_14=150.0,
        )

        self.assertTrue(res_bull.passed)
        self.assertEqual(res_bull.action, IntradayDecisionAction.BUY_CALL)
        self.assertEqual(res_bull.recommended_option_type, "CE")
        self.assertGreaterEqual(res_bull.risk_reward_ratio, 2.0)
        self.assertGreater(res_bull.confidence_score, 0.60)

        # 2. Inside CPR range scenario -> SHORT_STRANGLE
        res_inside = self.engine.evaluate_intraday_decision_checklist(
            current_spot=49815.0,
            open_price=49815.0,  # Inside CPR (49800 - 49833)
            cpr=cpr,
            pcr_metrics=PCRMetrics(60000, 60000, 1.0, 0, 0, PCRSentiment.NEUTRAL),
            gex_profile=gex,
            prev_high=50000.0,
            prev_low=49600.0,
            current_time_str="10:30",
        )
        self.assertTrue(res_inside.passed)
        self.assertEqual(res_inside.action, IntradayDecisionAction.SHORT_STRANGLE)

        # 3. Past 15:15 IST cutoff scenario -> NO_TRADE_WAIT
        res_late = self.engine.evaluate_intraday_decision_checklist(
            current_spot=49880.0,
            open_price=49860.0,
            cpr=cpr,
            pcr_metrics=pcr,
            gex_profile=gex,
            prev_high=50000.0,
            prev_low=49600.0,
            current_time_str="15:18",  # Past cutoff
        )
        self.assertFalse(res_late.passed)
        self.assertEqual(res_late.action, IntradayDecisionAction.NO_TRADE_WAIT)
        self.assertIn("15:15 IST", res_late.rationale[0])
