"""AGI 1.7 OMEGA COMMAND — Phase 6 Acceptance Test Suite.

Validates all 18 Phase 6 Objectives:
- Objective 1: Reality audit and stale data rejection.
- Objective 2: Three-agent persona contracts (Alexa, Emily, Max v1.7.2).
- Objective 2: Structured message protocol and dialectical consensus.
- Objective 2: Material disagreement preservation (Prefer No-Trade).
- Objective 3 & 4: Visual chart reasoning with 5-layer annotation separation.
- Objective 4: Strict no-future-leakage guarantee.
- Objective 5: 10-step causal event reconstruction with breadth and volume.
- Objective 5: Honest reporting of unexplained moves without direct evidence.
- Objective 6: 7 calibrated scenarios strictly summing to 100.0%.
- Objective 6: Brier score calculation and sample size gate (N >= 30).
- Objective 7: Institutional downside-first options risk governor.
- Objective 7: Kelly sizing retained solely as informational research benchmark.
- Objective 3B: Independent dual-index analysis (NIFTY 50 and BANK NIFTY).
- Objective 3C: FII/DII cash flow publication timestamp preservation.
- Objective 12: Statutory charges with 0.15% STT effective 1 April 2026.
- Objective 12: Rate schedule metadata and advance tax estimate disclaimer.
- Objective 11: Browser interaction path profiler with empirical median and p95 latency.
- Objective 11: Coordinate invalidation on navigation and layout shift.
- Objective 10: 10-step post-mortem with root-cause taxonomy.
- Objective 10: Strategy rollback to immutable baseline on degraded out-of-sample test.
- Objective 14: Standalone dashboard Phase 6 REST endpoints (/api/charts, /api/telemetry, /api/fii_dii).
- Objective 15: End-of-session structured agent reports and persona evolution.
"""

from __future__ import annotations

import datetime
import json
from pathlib import Path
import shutil
import tempfile
import unittest
import urllib.request

from agents.AGI_1_7.engine.agi17.browser.computer_use_engine import (
    BrowserLatencyTelemetrySummary,
    ComputerUseEngine,
    InteractionPathProfiler,
    InteractionStepLatency,
    SimulatedInputAdapter,
)
from agents.AGI_1_7.engine.agi17.finance.adaptive_strategy_learner import (
    AdaptiveStrategyLearner,
    LossRootCause,
    TradePostMortemReport,
)
from agents.AGI_1_7.engine.agi17.finance.calibrated_scenario_forecaster import (
    CalibratedScenarioForecaster,
    ScenarioArchetype,
    ScenarioForecastBattery,
)
from agents.AGI_1_7.engine.agi17.finance.dual_index_relationship import (
    DualIndexCrossRelationshipEngine,
    DualIndexTrendAgreement,
)
from agents.AGI_1_7.engine.agi17.finance.live_accounting import (
    LiveBrokerLedger,
    StatutoryCostSchedule,
)
from agents.AGI_1_7.engine.agi17.finance.market_event_reconstructor import (
    ExplanationClass,
    MarketEventReconstructionEngine,
    MoveType,
)
from agents.AGI_1_7.engine.agi17.finance.multi_horizon_quant_engine import (
    MultiHorizonQuantEngine,
)
from agents.AGI_1_7.engine.agi17.finance.options_risk_governor import (
    InstitutionalOptionsRiskGovernor,
    OptionsRiskAudit,
)
from agents.AGI_1_7.engine.agi17.finance.three_agent_contract import (
    ALEXA_PERSONA,
    EMILY_PERSONA,
    MAX_PERSONA,
    AgentMessage,
    DisagreementRecord,
    EndOfSessionAgentReport,
    ThreeAgentContractCoordinator,
)
from agents.AGI_1_7.engine.agi17.finance.trading_orchestrator import (
    AutonomousTradingOrchestrator,
)
from agents.AGI_1_7.engine.agi17.finance.visual_chart_reasoning import (
    VisualAnnotationType,
    VisualChartReasoningEngine,
    VisualChartSnapshot,
)
from agents.AGI_1_7.ui.standalone_dashboard_server import StandaloneDashboardServer


class TestOmegaPhase6Acceptance(unittest.TestCase):
    """22-Criterion Acceptance Test Suite for Phase 6."""

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    # -------------------------------------------------------------------------
    # Criterion 01: Stale Data Rejection & Reality Audit
    # -------------------------------------------------------------------------
    def test_01_reality_audit_and_stale_data_rejection(self):
        governor = InstitutionalOptionsRiskGovernor(authorized_capital_inr=50000.0)
        # Quote age 4.5s exceeds 3.0s threshold
        audit = governor.audit_proposal(
            candidate_id="CAND-STALE-01",
            underlying="NIFTY 50",
            instrument="NIFTY24200CE",
            spot_price=24200.0,
            strike_price=24200.0,
            is_call=True,
            quantity=25,
            entry_premium=100.0,
            stop_premium=90.0,
            target_premium=120.0,
            data_age_seconds=4.5,
        )
        self.assertFalse(audit.is_approved)
        self.assertIn("STALE_DATA_REJECTION", audit.rejection_reason)

    # -------------------------------------------------------------------------
    # Criterion 02: Three-Agent Persona Contracts and Versions
    # -------------------------------------------------------------------------
    def test_02_three_agent_persona_contracts_and_versions(self):
        self.assertEqual(ALEXA_PERSONA.name, "Alexa")
        self.assertEqual(ALEXA_PERSONA.version, "1.7.2")
        self.assertTrue(ALEXA_PERSONA.binding_rejection_authority)

        self.assertEqual(EMILY_PERSONA.name, "Emily")
        self.assertEqual(EMILY_PERSONA.version, "1.7.2")
        self.assertTrue(EMILY_PERSONA.binding_rejection_authority)

        self.assertEqual(MAX_PERSONA.name, "Max")
        self.assertEqual(MAX_PERSONA.version, "1.7.2")
        self.assertTrue(MAX_PERSONA.binding_rejection_authority)

    # -------------------------------------------------------------------------
    # Criterion 03: Structured Agent Message Protocol
    # -------------------------------------------------------------------------
    def test_03_structured_agent_message_protocol(self):
        coordinator = ThreeAgentContractCoordinator(storage_dir=self.temp_dir)
        msg = AgentMessage(
            session_id="SESS-001",
            timestamp="2026-10-13 10:15:00 IST",
            sender="Emily",
            data_source="Reserve Bank of India Monetary Policy Statement",
            proposed_action="ASSESS_MACRO_RISK",
            inputs={"repo_rate": 6.50, "stance": "NEUTRAL"},
            calculations={"tail_risk_score": 0.15, "direction": "BULLISH"},
            uncertainty=0.10,
            evidence_references=["https://www.rbi.org.in/press"],
            conclusion="Domestic liquidity conditions favorable for trend continuation.",
        )
        coordinator.log_message(msg)
        # Verify persistence in SQLite WAL
        with coordinator._get_connection() as conn:
            cur = conn.execute("SELECT * FROM agent_messages WHERE session_id = 'SESS-001'")
            row = cur.fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row["sender"], "Emily")
            self.assertEqual(row["data_source"], "Reserve Bank of India Monetary Policy Statement")

    # -------------------------------------------------------------------------
    # Criterion 04: Material Disagreement Preservation Prefers No-Trade
    # -------------------------------------------------------------------------
    def test_04_material_disagreement_preservation_prefers_no_trade(self):
        coordinator = ThreeAgentContractCoordinator(storage_dir=self.temp_dir)
        # Emily detects active tail risk
        emily_radar = {"tail_risk_flag": True, "evidence_sources": ["OPEC Emergency Disruption"]}
        max_quant = {"decision": "APPROVED", "net_expectancy_inr": 250.0, "risk_calc_inr": 200.0, "instrument": "NIFTY24200CE"}
        alexa_ui = {"browser_ready": True, "inputs_verified": True}

        approved, reason, record = coordinator.evaluate_consensus("SESS-002", emily_radar, max_quant, alexa_ui)
        self.assertFalse(approved)
        self.assertIn("PREFER_NO_TRADE", reason)
        self.assertIsNotNone(record)
        self.assertEqual(record.resolution, "PREFER_NO_TRADE")
        self.assertIn("Emily", record.agent_stances)

    # -------------------------------------------------------------------------
    # Criterion 05: Visual Chart Structure & 5-Layer Annotations
    # -------------------------------------------------------------------------
    def test_05_visual_chart_structure_and_5_layer_annotation(self):
        candles = [
            {"timestamp": f"10:{i:02d}", "open": 24100 + i, "high": 24110 + i, "low": 24095 + i, "close": 24105 + i, "volume": 1000}
            for i in range(15)
        ]
        # Introduce a swing high
        candles[7]["high"] = 24150.0
        snapshot = VisualChartReasoningEngine.analyze_chart("NIFTY 50", "1m", candles)

        self.assertGreater(len(snapshot.swing_highs), 0)
        self.assertGreater(len(snapshot.support_resistance_zones), 0)

        # Attach projection
        target_ann, inval_ann = VisualChartReasoningEngine.attach_scenario_projection(
            snapshot, "BULLISH_ORB", 24180.0, 24090.0, "15m", 0.62
        )
        self.assertTrue(target_ann.label.startswith("[PROJECTION]"))
        self.assertTrue(inval_ann.label.startswith("[PROJECTION INVALIDATION]"))
        self.assertEqual(target_ann.layer_type, VisualAnnotationType.SCENARIO_TARGET_ZONE)
        self.assertEqual(inval_ann.layer_type, VisualAnnotationType.INVALIDATION_POINT)

    # -------------------------------------------------------------------------
    # Criterion 06: Visual Chart No-Future-Leakage Guarantee
    # -------------------------------------------------------------------------
    def test_06_visual_chart_no_future_leakage(self):
        candles = [
            {"timestamp": "2026-10-13 10:00:00", "open": 24100, "high": 24110, "low": 24090, "close": 24105, "volume": 1000},
            {"timestamp": "2026-10-13 10:05:00", "open": 24105, "high": 24120, "low": 24100, "close": 24115, "volume": 1200},
            {"timestamp": "2026-10-13 10:10:00", "open": 24115, "high": 24130, "low": 24110, "close": 24125, "volume": 1500},
        ]
        snapshot = VisualChartReasoningEngine.analyze_chart("NIFTY 50", "5m", candles)

        # Cutoff at 10:10:00 -> Valid
        self.assertTrue(VisualChartReasoningEngine.verify_no_future_leakage("2026-10-13 10:10:00", snapshot))
        # Cutoff at 10:02:00 -> Invalid (candles at 10:05 and 10:10 leak)
        self.assertFalse(VisualChartReasoningEngine.verify_no_future_leakage("2026-10-13 10:02:00", snapshot))

    # -------------------------------------------------------------------------
    # Criterion 07: 10-Step Event Reconstruction with Evidence
    # -------------------------------------------------------------------------
    def test_07_ten_step_event_reconstruction_with_evidence(self):
        engine = MarketEventReconstructionEngine(self.temp_dir)
        start_candle = {"timestamp": "10:00 IST", "open": 24100.0}
        end_candle = {"timestamp": "10:15 IST", "close": 24230.0}  # +130 pts (> 0.5%)
        news = [{
            "headline": "RBI MPC Governor announces unexpected CRR reduction",
            "source_name": "Reserve Bank of India",
            "source_url": "https://rbi.org.in/press",
            "source_class": "OFFICIAL",
        }]

        event = engine.reconstruct_price_move(
            "NIFTY 50", start_candle, end_candle,
            breadth_peers={"BANKNIFTY": 0.8}, verified_news_items=news, volume_ratio=2.1
        )
        self.assertEqual(event.move_type, MoveType.SHARP_RALLY)
        self.assertEqual(event.breadth_impact, "BROAD_BASED_INDEX_ALIGNMENT")
        self.assertEqual(event.volume_regime, "SURGE_VOLUME")
        self.assertEqual(event.primary_explanation.explanation_class, ExplanationClass.DIRECT_EVIDENCE_PROVED)
        self.assertGreater(event.primary_explanation.confidence_score, 0.90)

    # -------------------------------------------------------------------------
    # Criterion 08: Event Reconstruction Honest Unexplained Report
    # -------------------------------------------------------------------------
    def test_08_event_reconstruction_honest_unexplained_report(self):
        engine = MarketEventReconstructionEngine(self.temp_dir)
        start_candle = {"timestamp": "11:00 IST", "open": 24200.0}
        end_candle = {"timestamp": "11:15 IST", "close": 24080.0}  # -120 pts

        # No matching news
        event = engine.reconstruct_price_move("NIFTY 50", start_candle, end_candle, verified_news_items=None)
        self.assertEqual(event.primary_explanation.explanation_class, ExplanationClass.UNEXPLAINED_NO_DIRECT_EVIDENCE)
        self.assertIn("CAUSE_CANNOT_BE_DETERMINED_RELIABLY", event.primary_explanation.hypothesis)
        self.assertLessEqual(event.primary_explanation.confidence_score, 0.30)

    # -------------------------------------------------------------------------
    # Criterion 09: Seven Scenario Forecast Battery Sums to 100%
    # -------------------------------------------------------------------------
    def test_09_seven_scenario_forecast_battery_sum_100_percent(self):
        battery = CalibratedScenarioForecaster.generate_scenarios(
            instrument="NIFTY 50",
            current_price=24150.0,
            vwap=24140.0,
            atr=45.0,
            rsi=54.0,
        )
        self.assertEqual(len(battery.scenarios), 7)
        total_prob = sum(s.probability_pct for s in battery.scenarios)
        self.assertAlmostEqual(total_prob, 100.0, places=1)
        self.assertGreater(battery.entropy_uncertainty, 0.0)

    # -------------------------------------------------------------------------
    # Criterion 10: Scenario Brier Score and Sample Size Gate
    # -------------------------------------------------------------------------
    def test_10_scenario_brier_score_and_sample_size_gate(self):
        # Pairs of (predicted probability 0.0-1.0, binary outcome 0 or 1)
        pairs = [(0.7, 1), (0.6, 1), (0.3, 0), (0.8, 1), (0.2, 0)]
        brier = CalibratedScenarioForecaster.compute_brier_score(pairs)
        self.assertLess(brier, 0.20)

        # Sample size 25 < 30 -> Rejected
        calibrated, msg = CalibratedScenarioForecaster.is_model_calibrated(brier, sample_size=25)
        self.assertFalse(calibrated)
        self.assertIn("CALIBRATION_PENDING", msg)

        # Sample size 50 >= 30 -> Calibrated
        calibrated_ok, msg_ok = CalibratedScenarioForecaster.is_model_calibrated(brier, sample_size=50)
        self.assertTrue(calibrated_ok)
        self.assertIn("CALIBRATED", msg_ok)

    # -------------------------------------------------------------------------
    # Criterion 11: Institutional Options Downside-First Risk
    # -------------------------------------------------------------------------
    def test_11_institutional_options_downside_first_risk(self):
        governor = InstitutionalOptionsRiskGovernor(authorized_capital_inr=50000.0)

        # Risk breach case: 25 quantity * (100 - 80) = ₹500 planned loss > ₹250 limit (0.5%)
        audit_breach = governor.audit_proposal(
            candidate_id="CAND-RISK-01",
            underlying="NIFTY 50",
            instrument="NIFTY24200CE",
            spot_price=24200.0,
            strike_price=24200.0,
            is_call=True,
            quantity=25,
            entry_premium=100.0,
            stop_premium=80.0,
            target_premium=130.0,
        )
        self.assertFalse(audit_breach.is_approved)
        self.assertIn("RISK_BUDGET_BREACH", audit_breach.rejection_reason)

        # Compliant case: 25 quantity * (100 - 92) = ₹200 planned loss <= ₹250 limit
        audit_ok = governor.audit_proposal(
            candidate_id="CAND-RISK-02",
            underlying="NIFTY 50",
            instrument="NIFTY24200CE",
            spot_price=24200.0,
            strike_price=24200.0,
            is_call=True,
            quantity=25,
            entry_premium=100.0,
            stop_premium=92.0,
            target_premium=125.0,
        )
        self.assertTrue(audit_ok.is_approved)
        self.assertEqual(audit_ok.planned_stop_loss_inr, 200.0)
        self.assertGreater(audit_ok.premium_exposure_inr, 0.0)
        self.assertGreater(audit_ok.greeks.delta, 0.0)

    # -------------------------------------------------------------------------
    # Criterion 12: Kelly Sizing Retained Solely as Research Benchmark
    # -------------------------------------------------------------------------
    def test_12_kelly_sizing_retained_only_as_research_benchmark(self):
        governor = InstitutionalOptionsRiskGovernor(authorized_capital_inr=50000.0)
        audit = governor.audit_proposal(
            candidate_id="CAND-KELLY-01",
            underlying="NIFTY 50",
            instrument="NIFTY24200CE",
            spot_price=24200.0,
            strike_price=24200.0,
            is_call=True,
            quantity=25,  # 1 lot
            entry_premium=100.0,
            stop_premium=92.0,
            target_premium=135.0,
        )
        self.assertTrue(audit.is_approved)
        # Kelly lots calculated for research, but actual quantity remains the approved 25
        self.assertIsInstance(audit.kelly_research_lots, int)
        self.assertEqual(audit.quantity, 25)

    # -------------------------------------------------------------------------
    # Criterion 13: Independent Dual Index Analysis (NIFTY & BANK NIFTY)
    # -------------------------------------------------------------------------
    def test_13_independent_dual_index_analysis_nifty_and_banknifty(self):
        summary = DualIndexCrossRelationshipEngine.evaluate_independent_signals(
            nifty_spot=24250.0,
            nifty_open=24150.0,
            nifty_vwap=24180.0,
            nifty_rsi=58.0,
            nifty_iv=0.14,
            bank_spot=51100.0,
            bank_open=51300.0,
            bank_vwap=51250.0,
            bank_rsi=44.0,
            bank_iv=0.17,
        )
        self.assertTrue(summary.independent_analysis_guarantee)
        self.assertEqual(summary.nifty_signal.primary_signal, "BULLISH")
        self.assertEqual(summary.banknifty_signal.primary_signal, "BEARISH")
        self.assertEqual(summary.trend_agreement, DualIndexTrendAgreement.DIVERGENT_NIFTY_BULL_BANK_BEAR)
        self.assertEqual(summary.leadership, "NIFTY_LEAD")

    # -------------------------------------------------------------------------
    # Criterion 14: FII/DII Cash Flow Publication Timestamp Preservation
    # -------------------------------------------------------------------------
    def test_14_fii_dii_cash_flow_timestamp_preservation(self):
        orch = AutonomousTradingOrchestrator(storage_root=self.temp_dir)
        events = orch.global_risk_radar.get_active_events()
        # Find FII/DII domestic driver event
        dom_events = [e for e in events if "FII" in e.headline or "DII" in e.headline]
        self.assertGreater(len(dom_events), 0)
        e = dom_events[0]
        self.assertTrue(len(e.publication_timestamp) > 0)
        self.assertIn("provisional", e.supporting_evidence.lower())

    # -------------------------------------------------------------------------
    # Criterion 15: Statutory Charges Updated STT 0.15% (1 April 2026)
    # -------------------------------------------------------------------------
    def test_15_statutory_charges_updated_stt_0_15_percent(self):
        # 1. Historical rate (prior to April 2026 / default) -> 0.10%
        charges_hist = LiveBrokerLedger.calculate_statutory_charges(side="SELL", quantity=25, premium=100.0)
        self.assertEqual(charges_hist["stt_rate_pct"], 0.10)
        self.assertEqual(charges_hist["stt_inr"], round(2500.0 * 0.0010, 2))  # ₹2.50

        # 2. Updated Schedule rate effective 1 April 2026 -> 0.15%
        charges_2026 = LiveBrokerLedger.calculate_statutory_charges(
            side="SELL", quantity=25, premium=100.0, as_of_date="2026-04-01"
        )
        self.assertEqual(charges_2026["stt_rate_pct"], 0.15)
        self.assertEqual(charges_2026["stt_inr"], round(2500.0 * 0.0015, 2))  # ₹3.75
        self.assertEqual(charges_2026["stt_effective_date"], "2026-04-01")

    # -------------------------------------------------------------------------
    # Criterion 16: Statutory Rates Metadata and Tax Estimate Disclaimer
    # -------------------------------------------------------------------------
    def test_16_statutory_rates_metadata_and_tax_estimate_disclaimer(self):
        self.assertIn("STT_SALE_2026", StatutoryCostSchedule.RATES)
        stt_meta = StatutoryCostSchedule.RATES["STT_SALE_2026"]
        self.assertEqual(stt_meta.rate_pct, 0.15)
        self.assertEqual(stt_meta.effective_date, "2026-04-01")

        charges = LiveBrokerLedger.calculate_statutory_charges(
            side="SELL", quantity=25, premium=100.0, net_trade_pnl=500.0
        )
        self.assertEqual(charges["income_tax_estimate_inr"], 100.0)  # 20% on ₹500
        self.assertIn("ESTIMATE_ONLY", charges["tax_disclaimer"])

    # -------------------------------------------------------------------------
    # Criterion 17: Browser Interaction Path Profiler Telemetry
    # -------------------------------------------------------------------------
    def test_17_browser_interaction_path_profiler_telemetry(self):
        profiler = InteractionPathProfiler()
        # Record sample cycles
        for total_ms in [28.0, 32.0, 35.0, 42.0, 50.0, 65.0, 72.0, 80.0, 95.0, 110.0]:
            profiler.record_step_latency(InteractionStepLatency(
                screenshot_acquisition_ms=8.0,
                page_state_extraction_ms=6.0,
                target_identification_ms=4.0,
                physical_dispatch_ms=5.0,
                next_visual_observation_ms=7.0,
                state_verification_ms=5.0,
                total_cycle_ms=total_ms,
                action_type="CLICK",
                success=True,
            ))
            profiler.record_navigation(success=True)
            profiler.record_element_identification(success=True)
            profiler.record_order_form_check(match=True)

        summary = profiler.get_telemetry_summary()
        self.assertEqual(summary.total_samples, 10)
        self.assertGreater(summary.median_latency_ms, 0.0)
        self.assertGreater(summary.p95_latency_ms, summary.median_latency_ms)
        self.assertEqual(summary.navigation_success_rate_pct, 100.0)
        self.assertEqual(summary.order_form_mismatch_rate_pct, 0.0)

    # -------------------------------------------------------------------------
    # Criterion 18: Coordinate Invalidation on Layout Shift
    # -------------------------------------------------------------------------
    def test_18_coordinate_invalidation_on_layout_shift(self):
        adapter = SimulatedInputAdapter(screen_width=1920, screen_height=1080)
        engine = ComputerUseEngine(adapter=adapter)
        engine.cache_coordinate("btn_buy", (450, 320))
        self.assertEqual(engine.get_cached_coordinate("btn_buy"), (450, 320))

        # Invalidate on layout shift
        engine.invalidate_coordinates(reason="layout_shift")
        self.assertIsNone(engine.get_cached_coordinate("btn_buy"))

    # -------------------------------------------------------------------------
    # Criterion 19: 10-Step Post-Mortem and Root Cause Taxonomy
    # -------------------------------------------------------------------------
    def test_19_ten_step_loss_post_mortem_and_root_cause(self):
        learner = AdaptiveStrategyLearner(storage_root=self.temp_dir)
        report = learner.conduct_10_step_post_mortem(
            trade_id="TRD-LOSS-101",
            strategy_id="STRAT-BASE-VWAP-ORB",
            entry_timestamp="2026-10-13 10:15:00 IST",
            exit_timestamp="2026-10-13 10:35:00 IST",
            original_thesis="Long breakout above 15m high",
            forecast_direction="BULLISH",
            planned_entry=100.0,
            actual_fill=101.5,
            planned_exit=92.0,
            actual_exit=91.0,
            quantity=25,
            statutory_charges_inr=42.50,
            root_cause=LossRootCause.EXECUTION_SLIPPAGE,
            root_cause_notes="Bid-ask spread widened during entry fill cascade.",
        )
        self.assertEqual(report.root_cause, LossRootCause.EXECUTION_SLIPPAGE)
        self.assertGreater(report.slippage_drag_inr, 0.0)
        self.assertTrue(report.baseline_intact)
        self.assertTrue(report.revenge_size_blocked)

    # -------------------------------------------------------------------------
    # Criterion 20: Strategy Rollback to Immutable Baseline
    # -------------------------------------------------------------------------
    def test_20_strategy_rollback_to_immutable_baseline(self):
        learner = AdaptiveStrategyLearner(storage_root=self.temp_dir)
        # Attempt alternative with inferior metrics
        promoted, hypo = learner.evaluate_alternative_hypothesis(
            strategy_id="STRAT-EXP-DEGRADED",
            version="2.0.0",
            hypothesis_statement="Aggressive 1m scalping without vwap filter",
            parameters={"orb_window_mins": 1},
            out_of_sample_expectancy=110.0,  # Below baseline 185.0
            profit_factor=1.10,
            max_drawdown_pct=0.08,           # Higher drawdown
            directional_accuracy_pct=49.0,
            win_rate_pct=45.0,
            sample_size_trades=120,
        )
        self.assertFalse(promoted)
        rolled_back = learner.rollback_to_baseline("STRAT-EXP-DEGRADED")
        self.assertEqual(rolled_back.strategy_id, "STRAT-BASE-VWAP-ORB")

    # -------------------------------------------------------------------------
    # Criterion 21: Standalone Dashboard Phase 6 Endpoints
    # -------------------------------------------------------------------------
    def test_21_standalone_dashboard_phase6_endpoints(self):
        server = StandaloneDashboardServer(
            host="127.0.0.1",
            port=8189,  # Use isolated port for test
            chart_provider=lambda: {"NIFTY_50": {"current_price": 24200.0}},
            telemetry_provider=lambda: {"median_latency_ms": 32.5},
            fii_dii_provider=lambda: {"fii_net_inr_cr": -1420.0},
        )
        server.start_background()
        try:
            # Query /api/charts
            req = urllib.request.Request("http://127.0.0.1:8189/api/charts")
            with urllib.request.urlopen(req, timeout=2.0) as resp:
                self.assertEqual(resp.status, 200)
                data = json.loads(resp.read().decode("utf-8"))
                self.assertIn("NIFTY_50", data)

            # Query /api/telemetry
            req_tel = urllib.request.Request("http://127.0.0.1:8189/api/telemetry")
            with urllib.request.urlopen(req_tel, timeout=2.0) as resp:
                self.assertEqual(resp.status, 200)
                data_tel = json.loads(resp.read().decode("utf-8"))
                self.assertEqual(data_tel["median_latency_ms"], 32.5)

            # Query /api/fii_dii
            req_fii = urllib.request.Request("http://127.0.0.1:8189/api/fii_dii")
            with urllib.request.urlopen(req_fii, timeout=2.0) as resp:
                self.assertEqual(resp.status, 200)
                data_fii = json.loads(resp.read().decode("utf-8"))
                self.assertEqual(data_fii["fii_net_inr_cr"], -1420.0)
        finally:
            server.stop_server()

    # -------------------------------------------------------------------------
    # Criterion 22: End-of-Session Agent Reports and Persona Evolution
    # -------------------------------------------------------------------------
    def test_22_end_of_session_agent_reports_and_evolution(self):
        coordinator = ThreeAgentContractCoordinator(storage_dir=self.temp_dir)
        reports = [
            EndOfSessionAgentReport(
                agent_name="Alexa",
                version="1.7.2",
                session_id="SESS-003",
                timestamp="2026-10-13 15:35:00 IST",
                completed_tasks_count=18,
                findings_summary="DOM latency stable at 32ms median; zero coordinate drift observed.",
                unresolved_questions=[],
                contributed_evidence_count=18,
                rejections_issued_count=0,
                identified_failure_events=[],
                suggested_improvements="Enable pre-cached screenshot acquisition pipeline.",
            ),
            EndOfSessionAgentReport(
                agent_name="Emily",
                version="1.7.2",
                session_id="SESS-003",
                timestamp="2026-10-13 15:35:00 IST",
                completed_tasks_count=24,
                findings_summary="Monitored 5 layers; FII cash outflow absorbed by domestic mutual funds.",
                unresolved_questions=["Track OPEC prompt-month crack spreads ahead of weekend"],
                contributed_evidence_count=24,
                rejections_issued_count=1,
                identified_failure_events=[],
                suggested_improvements="Integrate secondary broker volume data feeds.",
            ),
            EndOfSessionAgentReport(
                agent_name="Max",
                version="1.7.2",
                session_id="SESS-003",
                timestamp="2026-10-13 15:35:00 IST",
                completed_tasks_count=12,
                findings_summary="Evaluated 10 candidates; 1 executed, positive expectancy realized.",
                unresolved_questions=[],
                contributed_evidence_count=12,
                rejections_issued_count=9,
                identified_failure_events=[],
                suggested_improvements="Calibrate local volatility smile for weekly expiry options.",
            ),
        ]
        coordinator.record_session_reports("SESS-003", reports)

        with coordinator._get_connection() as conn:
            cur = conn.execute("SELECT COUNT(*) as cnt FROM session_agent_reports WHERE session_id = 'SESS-003'")
            count = cur.fetchone()["cnt"]
            self.assertEqual(count, 3)


if __name__ == "__main__":
    unittest.main()
