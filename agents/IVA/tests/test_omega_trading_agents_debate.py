"""Acceptance tests for TradingAgents Multi-Agent Debate & Consensus Framework.

TASK-BN-17:
Covers:
1. BullishResearchAnalyst momentum, VWAP, and Put OI scoring.
2. BearishResearchAnalyst resistance, EMA, and Call OI scoring.
3. PortfolioSynthesizer dialectical debate resolution:
   - Strong Bull -> Bull Call Spread
   - Strong Bear -> Bear Put Spread
   - Sideways / Chop -> Short Strangle (IV >= 12%) or No Trade
4. RiskManagerAuditor pre-trade drawdown circuit-breaker override.
"""

from __future__ import annotations

import unittest

from agents.AGI_1_7.engine.agi17.finance.trading_agents_debate import (
    AnalystReport,
    StrategyType,
    SynthesizedTradeDecision,
    TradingAgentsDebateEngine,
)


class TestOmegaTradingAgentsDebate(unittest.TestCase):
    """Test suite for TradingAgents Multi-Agent Consensus Framework."""

    def test_01_bull_analyst_evaluation(self) -> None:
        """Verifies Bullish Analyst produces high conviction on trend alignment."""
        spot = 50200.0
        vwap = 50050.0
        ema20 = 50100.0
        call_oi_change = 5.0
        put_oi_change = 25.0

        rep = TradingAgentsDebateEngine.evaluate_bullish_analyst(
            spot=spot,
            vwap=vwap,
            ema20=ema20,
            call_oi_change_pct=call_oi_change,
            put_oi_change_pct=put_oi_change,
        )

        self.assertIsInstance(rep, AnalystReport)
        self.assertEqual(rep.agent_role, "BullishResearchAnalyst")
        self.assertEqual(rep.stance, "BULLISH")
        self.assertAlmostEqual(rep.conviction, 1.0, delta=0.01)
        self.assertEqual(len(rep.catalysts), 3)

    def test_02_bear_analyst_evaluation(self) -> None:
        """Verifies Bearish Analyst produces high conviction on breakdown."""
        spot = 49800.0
        vwap = 50050.0
        ema20 = 49950.0
        iv = 0.18
        call_oi_change = 30.0
        put_oi_change = 2.0

        rep = TradingAgentsDebateEngine.evaluate_bearish_analyst(
            spot=spot,
            vwap=vwap,
            ema20=ema20,
            iv=iv,
            call_oi_change_pct=call_oi_change,
            put_oi_change_pct=put_oi_change,
        )

        self.assertIsInstance(rep, AnalystReport)
        self.assertEqual(rep.agent_role, "BearishResearchAnalyst")
        self.assertEqual(rep.stance, "BEARISH")
        self.assertAlmostEqual(rep.conviction, 1.0, delta=0.01)
        self.assertEqual(len(rep.catalysts), 3)

    def test_03_bull_consensus_synthesis(self) -> None:
        """Verifies synthesizer selects Bull Call Spread when Bull conviction dominates."""
        bull_rep = AnalystReport(
            agent_role="BullishResearchAnalyst",
            stance="BULLISH",
            conviction=0.90,
            thesis="Dominant buying",
            catalysts=["Above VWAP"],
        )
        bear_rep = AnalystReport(
            agent_role="BearishResearchAnalyst",
            stance="NEUTRAL",
            conviction=0.20,
            thesis="Low bearish pressure",
            catalysts=[],
        )

        decision = TradingAgentsDebateEngine.synthesize_debate_decision(
            spot=50000.0,
            bull_report=bull_rep,
            bear_report=bear_rep,
            iv=0.15,
            account_drawdown_pct=0.01,
        )

        self.assertIsInstance(decision, SynthesizedTradeDecision)
        self.assertEqual(decision.strategy, StrategyType.BULL_CALL_SPREAD)
        self.assertEqual(decision.risk_status, "APPROVED")
        self.assertEqual(decision.target_strikes, [50000.0, 50300.0])
        self.assertGreater(decision.net_conviction, 0.35)

    def test_04_bear_consensus_synthesis(self) -> None:
        """Verifies synthesizer selects Bear Put Spread when Bear conviction dominates."""
        bull_rep = AnalystReport(
            agent_role="BullishResearchAnalyst",
            stance="NEUTRAL",
            conviction=0.10,
            thesis="No upside traction",
            catalysts=[],
        )
        bear_rep = AnalystReport(
            agent_role="BearishResearchAnalyst",
            stance="BEARISH",
            conviction=0.85,
            thesis="Heavy supply",
            catalysts=["Below VWAP"],
        )

        decision = TradingAgentsDebateEngine.synthesize_debate_decision(
            spot=50000.0,
            bull_report=bull_rep,
            bear_report=bear_rep,
            iv=0.18,
            account_drawdown_pct=0.01,
        )

        self.assertEqual(decision.strategy, StrategyType.BEAR_PUT_SPREAD)
        self.assertEqual(decision.risk_status, "APPROVED")
        self.assertEqual(decision.target_strikes, [50000.0, 49700.0])
        self.assertLess(decision.net_conviction, -0.35)

    def test_05_sideways_strangle_synthesis(self) -> None:
        """Verifies synthesizer selects Short Strangle in balanced sideways debate."""
        bull_rep = AnalystReport(
            agent_role="BullishResearchAnalyst",
            stance="NEUTRAL",
            conviction=0.30,
            thesis="Rangebound",
            catalysts=[],
        )
        bear_rep = AnalystReport(
            agent_role="BearishResearchAnalyst",
            stance="NEUTRAL",
            conviction=0.30,
            thesis="Rangebound",
            catalysts=[],
        )

        decision = TradingAgentsDebateEngine.synthesize_debate_decision(
            spot=50000.0,
            bull_report=bull_rep,
            bear_report=bear_rep,
            iv=0.16,
            account_drawdown_pct=0.005,
        )

        self.assertEqual(decision.strategy, StrategyType.SHORT_STRANGLE)
        self.assertEqual(decision.risk_status, "APPROVED")
        self.assertEqual(decision.target_strikes, [49600.0, 50400.0])
        self.assertAlmostEqual(decision.net_conviction, 0.0)

    def test_06_rms_drawdown_override(self) -> None:
        """Verifies Risk Manager Auditor halts trading if account drawdown limit breached."""
        bull_rep = AnalystReport(
            agent_role="BullishResearchAnalyst",
            stance="BULLISH",
            conviction=0.95,
            thesis="Strong breakout",
            catalysts=[],
        )
        bear_rep = AnalystReport(
            agent_role="BearishResearchAnalyst",
            stance="NEUTRAL",
            conviction=0.10,
            thesis="None",
            catalysts=[],
        )

        # Account has 3.5% drawdown, exceeding 3.0% threshold
        decision = TradingAgentsDebateEngine.synthesize_debate_decision(
            spot=50000.0,
            bull_report=bull_rep,
            bear_report=bear_rep,
            iv=0.15,
            account_drawdown_pct=0.035,
            max_drawdown_limit=0.03,
        )

        self.assertEqual(decision.strategy, StrategyType.NO_TRADE_NEUTRAL)
        self.assertEqual(decision.risk_status, "REJECTED_BY_RMS")
        self.assertEqual(decision.target_strikes, [])
        self.assertTrue(decision.debate_transcript["rms_override"])
        self.assertIn("RMS CIRCUIT BREAKER", decision.rationale)


if __name__ == "__main__":
    unittest.main()
