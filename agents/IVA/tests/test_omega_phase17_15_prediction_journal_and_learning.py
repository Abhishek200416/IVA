"""Unit Test Suite for Phase 17.15 Prediction Journal, Forecasting & Learning Engine.

Verifies:
1. Immutable prediction recording with data cutoffs.
2. Probability distribution sum invariant (must sum to 1.0).
3. Prohibition of in-place mutation / re-evaluation of evaluated tickets.
4. Multiclass Brier score calculation and directional accuracy.
5. Global Brier Skill Score calculation against uniform baseline.
6. Opening gap scenario generation and bounds calculation.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agents.AGI_1_7.engine.agi17.finance.prediction_journal import (
    ForecastHorizon,
    MarketForecastTicket,
    PredictionJournal,
    PredictionStatus,
    QuantitativeForecastingEngine,
)


class TestPredictionJournalAndLearning(unittest.TestCase):
    """Authoritative test cases for prediction journal, scoring, and forecasting."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.journal_path = Path(self.temp_dir.name) / "prediction_journal.json"
        self.journal = PredictionJournal(storage_path=self.journal_path)
        self.engine = QuantitativeForecastingEngine(journal=self.journal)

    def tearDown(self) -> None:
        try:
            self.temp_dir.cleanup()
        except Exception:
            pass

    def test_record_immutable_prediction(self) -> None:
        """Verify recording a valid pre-market forecast ticket with 1.0 probability sum."""
        ticket = MarketForecastTicket(
            prediction_id="PRED-TEST-001",
            instrument="NIFTY",
            created_at_ist="2026-10-16 08:45:00 IST",
            cutoff_timestamp_utc="2026-10-16T03:15:00Z",
            horizon=ForecastHorizon.OPENING_AUCTION,
            data_provenance="HISTORICAL_REPLAY",
            model_version="STRAT-PRED-V1",
            reference_price=24500.0,
            scenario_probabilities={"GAP_UP": 0.40, "FLAT": 0.40, "GAP_DOWN": 0.20},
            projected_low=24400.0,
            projected_high=24600.0,
            projected_range_width=200.0,
            confidence_interval_pct=90.0,
            invalidation_rules=["Global index gap > 1.5%"],
        )
        rec = self.journal.record_prediction(ticket)
        self.assertEqual(rec.status, PredictionStatus.RECORDED)
        self.assertIn("PRED-TEST-001", self.journal.tickets)

        # Duplicate ID rejection
        with self.assertRaises(ValueError):
            self.journal.record_prediction(ticket)

    def test_probability_sum_invariant_enforcement(self) -> None:
        """Verify rejecting predictions where scenario probabilities do not sum to 1.0."""
        bad_ticket = MarketForecastTicket(
            prediction_id="PRED-BAD-001",
            instrument="NIFTY",
            created_at_ist="2026-10-16 08:45:00 IST",
            cutoff_timestamp_utc="2026-10-16T03:15:00Z",
            horizon=ForecastHorizon.OPENING_AUCTION,
            data_provenance="HISTORICAL_REPLAY",
            model_version="STRAT-PRED-V1",
            reference_price=24500.0,
            scenario_probabilities={"GAP_UP": 0.60, "FLAT": 0.60, "GAP_DOWN": 0.20},  # Sum = 1.40
            projected_low=24400.0,
            projected_high=24600.0,
            projected_range_width=200.0,
            confidence_interval_pct=90.0,
            invalidation_rules=[],
        )
        with self.assertRaises(ValueError):
            self.journal.record_prediction(bad_ticket)

    def test_evaluate_prediction_and_brier_scoring(self) -> None:
        """Verify empirical evaluation computes exact Multiclass Brier score and directional accuracy."""
        ticket = MarketForecastTicket(
            prediction_id="PRED-EVAL-001",
            instrument="BANKNIFTY",
            created_at_ist="2026-10-16 08:45:00 IST",
            cutoff_timestamp_utc="2026-10-16T03:15:00Z",
            horizon=ForecastHorizon.OPENING_AUCTION,
            data_provenance="HISTORICAL_REPLAY",
            model_version="STRAT-PRED-V1",
            reference_price=51500.0,
            scenario_probabilities={"GAP_UP": 0.70, "FLAT": 0.20, "GAP_DOWN": 0.10},
            projected_low=51300.0,
            projected_high=51700.0,
            projected_range_width=400.0,
            confidence_interval_pct=90.0,
            invalidation_rules=[],
        )
        self.journal.record_prediction(ticket)

        # Actual outcome materialized as GAP_UP @ 51650.0
        # Expected Brier: (0.7 - 1.0)^2 + (0.2 - 0)^2 + (0.1 - 0)^2 = 0.09 + 0.04 + 0.01 = 0.14
        ev = self.journal.evaluate_prediction("PRED-EVAL-001", actual_price=51650.0, actual_category="GAP_UP")
        self.assertEqual(ev.status, PredictionStatus.EVALUATED)
        self.assertAlmostEqual(ev.brier_score, 0.14, places=2)
        self.assertTrue(ev.directional_accuracy)
        self.assertEqual(ev.actual_outcome_category, "GAP_UP")

        # Prohibition of in-place re-evaluation
        with self.assertRaises(ValueError):
            self.journal.evaluate_prediction("PRED-EVAL-001", actual_price=51200.0, actual_category="GAP_DOWN")

    def test_aggregate_calibration_and_skill_score(self) -> None:
        """Verify calculating aggregate calibration and Brier Skill Score against baseline."""
        # Record and evaluate a ticket with good calibration (Brier = 0.14)
        t1 = MarketForecastTicket(
            prediction_id="PRED-P1",
            instrument="NIFTY",
            created_at_ist="2026-10-16 08:45:00 IST",
            cutoff_timestamp_utc="2026-10-16T03:15:00Z",
            horizon=ForecastHorizon.OPENING_AUCTION,
            data_provenance="HISTORICAL_REPLAY",
            model_version="STRAT-PRED-V1",
            reference_price=24500.0,
            scenario_probabilities={"GAP_UP": 0.70, "FLAT": 0.20, "GAP_DOWN": 0.10},
            projected_low=24400.0,
            projected_high=24600.0,
            projected_range_width=200.0,
            confidence_interval_pct=90.0,
            invalidation_rules=[],
        )
        self.journal.record_prediction(t1)
        self.journal.evaluate_prediction("PRED-P1", actual_price=24580.0, actual_category="GAP_UP")

        cal = self.journal.compute_aggregate_calibration()
        self.assertEqual(cal["total_evaluated"], 1)
        self.assertAlmostEqual(cal["mean_brier_score"], 0.14, places=2)
        self.assertEqual(cal["directional_accuracy_pct"], 100.0)
        # BSS = 1 - (0.14 / 0.6667) = +0.79
        self.assertGreater(cal["brier_skill_score_uniform"], 0.70)

    def test_opening_gap_forecast_generator(self) -> None:
        """Verify generating disciplined opening gap scenario ticket."""
        ticket = self.engine.generate_opening_gap_forecast(
            instrument="NIFTY",
            previous_close=24500.0,
            overnight_sentiment_score=0.4,
        )
        self.assertIn("NIFTY", ticket.instrument)
        self.assertEqual(ticket.reference_price, 24500.0)
        self.assertAlmostEqual(sum(ticket.scenario_probabilities.values()), 1.0, places=2)
        self.assertGreater(ticket.scenario_probabilities["GAP_UP"], ticket.scenario_probabilities["GAP_DOWN"])
        self.assertIn(ticket.prediction_id, self.journal.tickets)


if __name__ == "__main__":
    unittest.main()
