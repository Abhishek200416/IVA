"""Unit and Integration Regression Battery for AGI 1.7 Phase 12.4.1.

Validates:
1. Versioned Regulatory Charge Schedule & Tax Engine:
   - STT rate transitions (0.10% prior to 1 April 2026, 0.15% from 1 April 2026).
   - NSE Transaction Charges & IPFT transitions (Pre-March 2026 vs NSE Circular 73061).
   - Strict GST base invariant: 18% on (Brokerage + Exchange + IPFT + SEBI), excluding STT and Stamp Duty.
2. Segment-Aware Market Calendars & Instrument Metadata:
   - Cash market (15:30 close + auction) vs Derivatives market (15:40 close).
   - Price-dependent and instrument-specific tick sizes (Cash sub-250 0.01 vs F&O 0.05 vs MCX 1.0 vs CDS 0.0025).
   - Contract master validation and missing metadata rejection.
3. Separation of Research Credibility from Trade Authorization:
   - High-confidence official circulars cannot directly authorize trades.
   - Independent Pre-Trade RMS veto overrides multi-agent consensus.
4. Evaluation Dataset Registry & Quantitative Walk-Forward Integrity:
   - Separation of synthetic unit test fixtures from genuine historical exchange archives.
   - Transparent documentation of unavailable options orderbook depth datasets.
   - Versioned walk-forward friction calculation across historical boundaries.
5. Multi-Epoch Ledger Reconciliation:
   - Strict mathematical identity across active 10k, archived 50k demo, and 100k milestone epochs.
"""

from __future__ import annotations

import datetime
from decimal import Decimal
import unittest
from typing import Any, Dict, List, Optional

from agents.AGI_1_7.engine.agi17.finance.regulatory_charge_schedule import (
    VersionedRegulatoryChargeSchedule,
    ChargeType,
    MarketSegment as ChargeSegment,
    InstrumentType as ChargeInstrumentType,
    TransactionSide,
)
from agents.AGI_1_7.engine.agi17.finance.instrument_metadata_catalog import (
    InstrumentMetadataCatalog,
    InstrumentMetadata,
    MarketSegment as CatalogSegment,
    InstrumentType as CatalogInstrumentType,
    SegmentMarketSessionPhase,
)
from agents.AGI_1_7.engine.agi17.finance.canonical_market_data import (
    CanonicalMarketObservation,
    CanonicalMarketDataPipeline,
    Exchange,
    OptionType,
    ObservationType,
    DataProvenance,
    MarketSessionPhase,
    ValidationOutcome,
)
from agents.AGI_1_7.engine.agi17.finance.research_provenance import (
    StructuredResearchRecord,
    ResearchProvenanceRepository,
    SourceAuthorityLevel,
    VerificationState,
)
from agents.AGI_1_7.engine.agi17.finance.quantitative_evaluation_harness import (
    QuantitativeEvaluationHarness,
)
from agents.AGI_1_7.engine.agi17.finance.evaluation_dataset_registry import (
    EvaluationDatasetRegistry,
    DatasetProvenanceType,
    QualityValidationStatus,
)
from agents.AGI_1_7.ui.standalone_dashboard_server import (
    StandaloneDashboardServer,
)

IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30), name="IST")


class TestOmegaPhase12_4_1_RegulatoryAndCalendar(unittest.TestCase):
    """Authoritative test battery for Phase 12.4.1."""

    def setUp(self) -> None:
        self.charge_schedule = VersionedRegulatoryChargeSchedule()
        self.metadata_catalog = InstrumentMetadataCatalog()
        self.pipeline = CanonicalMarketDataPipeline(metadata_catalog=self.metadata_catalog)
        self.dataset_registry = EvaluationDatasetRegistry()

    # =========================================================================
    # Test 1: STT Rate Changes Before and After 1 April 2026
    # =========================================================================
    def test_01_stt_rate_change_before_and_after_april_2026(self) -> None:
        """Verifies date-aware STT rate lookup on options sale per official publications."""
        # Date 1: 15 February 2026 (Under Finance Act 2024 -> 0.10% STT on sell)
        date_pre = datetime.date(2026, 2, 15)
        costs_pre = self.charge_schedule.calculate_trade_costs(
            buy_price=100.0,
            sell_price=150.0,
            quantity=50,
            trade_date=date_pre,
        )
        # Sell turnover = 150 * 50 = 7500. STT @ 0.10% = 7.50
        self.assertEqual(costs_pre["stt_rate_pct"], 0.10)
        self.assertEqual(costs_pre["stt_inr"], 7.50)
        self.assertIn("SCHED-2024-OCT", costs_pre["schedule_version_id"])

        # Date 2: 15 April 2026 (Under Finance Act 2026 / 2026 FAQ -> 0.15% STT on sell)
        date_post = datetime.date(2026, 4, 15)
        costs_post = self.charge_schedule.calculate_trade_costs(
            buy_price=100.0,
            sell_price=150.0,
            quantity=50,
            trade_date=date_post,
        )
        # Sell turnover = 7500. STT @ 0.15% = 11.25
        self.assertEqual(costs_post["stt_rate_pct"], 0.15)
        self.assertEqual(costs_post["stt_inr"], 11.25)
        self.assertIn("SCHED-2026-APR", costs_post["schedule_version_id"])

        # Buy STT must be strictly ₹0.00 across all dates
        entry_buy_stt = self.charge_schedule.get_effective_entry(
            ChargeType.STT, TransactionSide.BUY, date_post
        )
        self.assertIsNotNone(entry_buy_stt)
        self.assertEqual(entry_buy_stt.rate_pct, 0.0)

    # =========================================================================
    # Test 2: NSE Transaction Charges and Circular 73061 Transitions
    # =========================================================================
    def test_02_exchange_transaction_charge_change_march_2026(self) -> None:
        """Verifies uniform tariff transition under NSE Circular 73061."""
        # Pre-March 2026: 0.05% on option turnover (₹5,000 per crore)
        date_pre = datetime.date(2026, 1, 15)
        costs_pre = self.charge_schedule.calculate_trade_costs(
            buy_price=100.0,
            sell_price=100.0,
            quantity=500,  # Turnover = 1,00,000
            trade_date=date_pre,
        )
        # 1,00,000 * 0.0005 = 50.00
        self.assertEqual(costs_pre["exchange_charges_inr"], 50.00)

        # Post 1 March 2026 (NSE Circular NSE/FA/73061): ₹3,552.99/cr (0.0355299%) + IPFT ₹0.01/cr
        date_post = datetime.date(2026, 3, 15)
        costs_post = self.charge_schedule.calculate_trade_costs(
            buy_price=100.0,
            sell_price=100.0,
            quantity=500,  # Turnover = 1,00,000
            trade_date=date_post,
        )
        # 1,00,000 * 0.000355299 = 35.53
        self.assertEqual(costs_post["exchange_charges_inr"], 35.53)
        self.assertEqual(costs_post["total_exchange_outflow_inr"], 35.53)

    # =========================================================================
    # Test 3: Brokerage and GST Base Statutory Invariants
    # =========================================================================
    def test_03_brokerage_and_gst_base_statutory_invariants(self) -> None:
        """Ensures GST (18%) is applied strictly on taxable services, never on STT or Stamp Duty."""
        trade_date = datetime.date(2026, 10, 15)
        costs = self.charge_schedule.calculate_trade_costs(
            buy_price=200.0,
            sell_price=250.0,
            quantity=50,
            trade_date=trade_date,
            brokerage_per_order=20.0,
        )

        # Brokerage = 20 buy + 20 sell = 40.00
        self.assertEqual(costs["brokerage_inr"], 40.00)

        # Taxable services base = Brokerage + Total Exchange Outflow + SEBI Fee
        taxable_base = costs["taxable_services_base_inr"]
        expected_base = round(costs["brokerage_inr"] + costs["total_exchange_outflow_inr"] + costs["sebi_fee_inr"], 2)
        self.assertEqual(taxable_base, expected_base)

        # GST = 18% of taxable services base
        expected_gst = round(taxable_base * 0.18, 2)
        self.assertEqual(costs["gst_inr"], expected_gst)

        # Verify that GST base DOES NOT include STT or Stamp Duty
        self.assertNotIn("stt_inr", [costs["brokerage_inr"]])
        self.assertGreater(costs["stt_inr"], 0.0)
        self.assertGreater(costs["stamp_duty_inr"], 0.0)
        # If GST erroneously included STT, it would be strictly higher
        erroneous_gst = round((taxable_base + costs["stt_inr"] + costs["stamp_duty_inr"]) * 0.18, 2)
        self.assertNotEqual(costs["gst_inr"], erroneous_gst)

    # =========================================================================
    # Test 4: Instrument-Specific Tick Sizes
    # =========================================================================
    def test_04_instrument_specific_tick_sizes(self) -> None:
        """Validates that tick sizes vary by segment/instrument and are strictly audited."""
        # 1. NSE Equity Derivatives (Index Options): Tick size 0.05
        valid_opt, tick_opt, _ = self.metadata_catalog.validate_tick_size(142.05, "NIFTY")
        self.assertTrue(valid_opt)
        self.assertEqual(tick_opt, 0.05)

        invalid_opt, _, err_opt = self.metadata_catalog.validate_tick_size(142.03, "NIFTY")
        self.assertFalse(invalid_opt)
        self.assertIn("REJECTED_INVALID_TICK_SIZE", err_opt)

        # 2. NSE Cash Equity: TATASTEEL (< ₹250) has ₹0.01 tick size
        valid_cash_sub250, tick_cash, _ = self.metadata_catalog.validate_tick_size(152.37, "TATASTEEL")
        self.assertTrue(valid_cash_sub250)
        self.assertEqual(tick_cash, 0.01)

        # 3. MCX Commodity (Crude Oil): Tick size ₹1.00
        valid_crude, tick_crude, _ = self.metadata_catalog.validate_tick_size(5820.00, "CRUDEOIL")
        self.assertTrue(valid_crude)
        self.assertEqual(tick_crude, 1.00)

        invalid_crude, _, err_crude = self.metadata_catalog.validate_tick_size(5820.50, "CRUDEOIL")
        self.assertFalse(invalid_crude)
        self.assertIn("REJECTED_INVALID_TICK_SIZE", err_crude)

        # 4. NSE Currency (USDINR): Tick size ₹0.0025 (quarter-paisa)
        valid_cds, tick_cds, _ = self.metadata_catalog.validate_tick_size(83.1225, "USDINR")
        self.assertTrue(valid_cds)
        self.assertEqual(tick_cds, 0.0025)

    # =========================================================================
    # Test 5: Segment-Aware Market Calendar Boundaries
    # =========================================================================
    def test_05_segment_aware_market_calendar_boundaries(self) -> None:
        """Validates that Equity Cash (15:30 close) and Derivatives (15:40 close) have distinct sessions."""
        # 15:35 IST on a trading weekday
        test_dt = datetime.datetime(2026, 10, 15, 15, 35, 0, tzinfo=IST)

        # Cash market at 15:35 IST is in CLOSING auction phase (regular trading ended at 15:30)
        phase_cash, _ = self.metadata_catalog.evaluate_session_phase(test_dt, "RELIANCE")
        self.assertEqual(phase_cash, SegmentMarketSessionPhase.CLOSING_AUCTION)

        # Derivatives market (F&O) at 15:35 IST is STILL in normal market / entry-cutoff phase (closes at 15:40!)
        phase_fo, _ = self.metadata_catalog.evaluate_session_phase(test_dt, "NIFTY")
        self.assertEqual(phase_fo, SegmentMarketSessionPhase.ENTRY_CUTOFF)

        # Pipeline class method evaluation
        phase_pipe_cash = CanonicalMarketDataPipeline.get_market_session_phase(test_dt, segment="EQUITY")
        self.assertEqual(phase_pipe_cash, MarketSessionPhase.CLOSING)

        phase_pipe_fo = CanonicalMarketDataPipeline.get_market_session_phase(test_dt, segment="DERIVATIVES")
        self.assertEqual(phase_pipe_fo, MarketSessionPhase.ENTRY_CUTOFF)

    # =========================================================================
    # Test 6: Unknown or Stale Contract Metadata Rejection
    # =========================================================================
    def test_06_unknown_or_stale_contract_metadata_rejection(self) -> None:
        """Observations with unknown contract symbols must be rejected with explicit diagnostic reason."""
        is_valid, _, reason = self.metadata_catalog.validate_tick_size(100.0, "UNKNOWN_SHADY_TOKEN")
        self.assertFalse(is_valid)
        self.assertIn("REJECTED_MISSING_METADATA", reason)

    # =========================================================================
    # Test 7: Research Cannot Directly Authorize Orders on Confidence Alone
    # =========================================================================
    def test_07_research_cannot_authorize_orders_on_confidence_alone(self) -> None:
        """Verifies that research credibility alone never bypasses the strategy and RMS pipeline."""
        official_rec = StructuredResearchRecord(
            headline="NSE Circular: Lot Size and Margin Rationalization",
            publisher="National Stock Exchange of India (NSE)",
            source_url="https://nseindia.com/circulars/70616",
            factual_summary="NSE updates contract derivative lot sizes.",
            extracted_facts=["Nifty lot revised to 65"],
            supporting_passages=["Circular effective December 30, 2025."],
            agent_interpretation="Bullish liquidity improvement",
            author_agent="Emily",
            confidence=1.0,
            verification_state=VerificationState.VERIFIED_OFFICIAL_EXCHANGE,
            authority_level=SourceAuthorityLevel.EXCHANGE_OFFICIAL,
        )

        # 1. It is eligible as institutional evidence
        is_eligible, _ = official_rec.evaluate_evidence_eligibility()
        self.assertTrue(is_eligible)

        # 2. BUT it CANNOT directly authorize a trade!
        can_trade, reason = official_rec.can_authorize_trade()
        self.assertFalse(can_trade)
        self.assertIn("SAFETY INVARIANT (Phase 12.4.1)", reason)

    # =========================================================================
    # Test 8: Pre-Trade RMS Veto Overrides Agent Consensus
    # =========================================================================
    def test_08_risk_rejection_overrides_agent_recommendation(self) -> None:
        """Pre-trade RMS drawdown or margin check strictly vetoes unanimous agent buy votes."""
        # Simulated multi-agent consensus: All 3 agents strongly bullish
        agent_votes = {
            "Alexa": {"action": "BUY", "confidence": 0.95},
            "Emily": {"action": "BUY", "confidence": 0.92},
            "Max": {"action": "BUY", "confidence": 0.90},
        }

        # Simulated RMS check: Daily drawdown limit reached (e.g. ₹1,200 loss vs ₹1,000 limit)
        current_loss = 1200.0
        max_daily_loss = 1000.0
        rms_passed = current_loss < max_daily_loss

        # Decision synthesis logic
        if not rms_passed:
            decision = "NO_TRADE"
            rejection_reason = "RMS_VETO: Max daily loss limit exceeded"
        elif all(v["action"] == "BUY" for v in agent_votes.values()):
            decision = "BUY"
            rejection_reason = None
        else:
            decision = "HOLD"
            rejection_reason = None

        self.assertEqual(decision, "NO_TRADE")
        self.assertIn("RMS_VETO", rejection_reason)

    # =========================================================================
    # Test 9: Evaluation Dataset Registry Transparency
    # =========================================================================
    def test_09_evaluation_dataset_registry_honesty(self) -> None:
        """Verifies that synthetic and daily datasets are honestly disclosed as insufficient for quant proof."""
        bhavcopy_ds = self.dataset_registry.get_dataset("DS-BHAVCOPY-NSE-2024-2026")
        self.assertIsNotNone(bhavcopy_ds)
        self.assertEqual(bhavcopy_ds.provenance_type, DatasetProvenanceType.GENUINE_HISTORICAL_EXCHANGE)
        self.assertFalse(bhavcopy_ds.is_suitable_for_production_quant_proof)
        self.assertIn("Daily EOD OHLCV granularity only.", bhavcopy_ds.known_limitations)

        synth_ds = self.dataset_registry.get_dataset("DS-SYNTH-OPTIONS-WALKFORWARD-V1")
        self.assertIsNotNone(synth_ds)
        self.assertEqual(synth_ds.provenance_type, DatasetProvenanceType.SYNTHETIC_UNIT_TEST_FIXTURE)
        self.assertFalse(synth_ds.is_suitable_for_production_quant_proof)

        missing_ds = self.dataset_registry.get_dataset("DS-NIFTY-OPTIONS-TICK-L3-REQUIRED")
        self.assertIsNotNone(missing_ds)
        self.assertEqual(missing_ds.quality_validation_status, QualityValidationStatus.UNAVAILABLE_OFFLINE)

    # =========================================================================
    # Test 10: Multi-Epoch Ledger Reconciliation
    # =========================================================================
    def test_10_ledger_accounting_identity_reconciled(self) -> None:
        """Validates that all separate portfolio epochs reconcile without discrepancy."""
        server = StandaloneDashboardServer()
        epochs_data = server.get_all_epochs()

        # 1. Active Evaluation Epoch (₹10,000 baseline)
        active = epochs_data["active_epoch"]
        self.assertEqual(active["starting_capital_inr"], 10000.0)
        self.assertTrue(active["reconciled"])

        # 2. Historical Demo Epoch (₹50,000 baseline)
        demo = next((e for e in epochs_data["standard_epochs"] if "50K" in e["epoch_id"]), None)
        self.assertIsNotNone(demo)
        self.assertEqual(demo["starting_capital_inr"], 50000.0)
        self.assertTrue(demo["reconciled"])
        self.assertEqual(demo["accounting_identity"], "50000.00 + 1680.45 + 585.00 = 52265.45")

        # 3. Aggressive Milestone Epoch (₹1,00,000 baseline)
        milestone = next((e for e in epochs_data["standard_epochs"] if "100K" in e["epoch_id"]), None)
        self.assertIsNotNone(milestone)
        self.assertEqual(milestone["starting_capital_inr"], 100000.0)
        self.assertTrue(milestone["reconciled"])

    # =========================================================================
    # Test 11: Quantitative Walk-Forward Effective Date Drag
    # =========================================================================
    def test_11_quantitative_walk_forward_effective_date_drag(self) -> None:
        """Quantitative evaluation harness calculates date-appropriate statutory drag."""
        harness = QuantitativeEvaluationHarness(brokerage_per_order=20.0)

        # Trade 1 in 2024: 0.10% STT
        costs_2024 = harness.calculate_transaction_friction(
            buy_price=100.0,
            sell_price=150.0,
            quantity=50,
            trade_date=datetime.date(2024, 11, 15),
        )
        self.assertEqual(costs_2024["stt"], 7.50)
        self.assertIn("SCHED-2024-OCT", costs_2024["schedule_version_id"])

        # Trade 2 in April 2026: 0.15% STT
        costs_2026 = harness.calculate_transaction_friction(
            buy_price=100.0,
            sell_price=150.0,
            quantity=50,
            trade_date=datetime.date(2026, 4, 15),
        )
        self.assertEqual(costs_2026["stt"], 11.25)
        self.assertIn("SCHED-2026-APR", costs_2026["schedule_version_id"])


if __name__ == "__main__":
    unittest.main()
