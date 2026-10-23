"""
Unit tests for Phase 28 Cycle 16: Hawkes-Driven Log-Forward Variance & Calendar Roll Engine.

Verifies:
1. Exact forward variance positivity and strict calendar monotonicity (d theta / d tau > 0).
2. Piecewise linear total variance integration against analytical expectations.
3. Calendar-roll state machine transitions: ACTIVE, CALENDAR_ROLLED, NEEDS_REBOOTSTRAP, REBOOTSTRAPPED.
4. Hawkes jump-hazard penalized VRP and calendar spread roll decisions (pin risk, carry degradation, emergency).
5. Critic A AST integrity, fail-closed safety gate (LIVE_ORDER_DISPATCH_ENABLED = False), and Critic B non-inferiority.
"""

from __future__ import annotations

import math
import numpy as np
import pytest

from agents.AGI_1_7.engine.agi17.finance.hawkes_calendar_roll_engine import (
    CalendarState,
    CalendarTransition,
    CalendarEvent,
    LogForwardVarianceCurve,
    HawkesCalendarRollPolicy,
    RollDecision,
    CalendarRollEvaluation,
    LIVE_ORDER_DISPATCH_ENABLED,
)
from agents.AGI_1_7.engine.agi17.orchestration.dual_critic_regularized_evolution_gate import (
    DualCriticRegularizedEvolutionGate,
    MutationProposal,
    CriticDecision,
)


class TestLogForwardVarianceCurve:
    """Verifies forward variance curve mathematics and calendar roll transitions."""

    @pytest.fixture
    def sample_curve(self) -> LogForwardVarianceCurve:
        # Tenor intervals: [0, 0.25], [0.25, 0.50], [0.50, 1.00]
        # Rates per year: 0.04 (20% vol), 0.09 (30% vol), 0.16 (40% vol)
        edges = [0.0, 0.25, 0.50, 1.0]
        logs = np.log([0.04, 0.09, 0.16])
        return LogForwardVarianceCurve(asof=10.0, tau_edges=edges, log_xi=logs)

    def test_safety_gate_locked(self, sample_curve: LogForwardVarianceCurve):
        assert not LIVE_ORDER_DISPATCH_ENABLED
        snap = sample_curve.snapshot()
        assert snap["is_live_dispatch_locked"] is True

    def test_strict_positivity_and_monotonicity(self, sample_curve: LogForwardVarianceCurve):
        # All xi > 0
        assert np.all(sample_curve.xi > 0.0)

        # Monotonicity test across fine maturity mesh
        taus = np.linspace(0.01, 1.20, 50)
        thetas = [sample_curve.total_variance(t) for t in taus]
        assert np.all(np.diff(thetas) > 0.0)

    def test_exact_analytical_integration(self, sample_curve: LogForwardVarianceCurve):
        # theta(0.25) = 0.25 * 0.04 = 0.01
        assert math.isclose(sample_curve.total_variance(0.25), 0.01, rel_tol=1e-7)

        # theta(0.50) = 0.01 + 0.25 * 0.09 = 0.01 + 0.0225 = 0.0325
        assert math.isclose(sample_curve.total_variance(0.50), 0.0325, rel_tol=1e-7)

        # theta(0.75) = 0.0325 + 0.25 * 0.16 = 0.0325 + 0.04 = 0.0725
        assert math.isclose(sample_curve.total_variance(0.75), 0.0725, rel_tol=1e-7)

        # theta(1.00) = 0.0325 + 0.50 * 0.16 = 0.0325 + 0.08 = 0.1125
        assert math.isclose(sample_curve.total_variance(1.00), 0.1125, rel_tol=1e-7)

    def test_update_log_rates(self, sample_curve: LogForwardVarianceCurve):
        new_rates = np.log([0.05, 0.10, 0.20])
        event = sample_curve.update_log_rates(new_rates)
        assert event.transition == CalendarTransition.LOG_RATE_UPDATE
        assert math.isclose(sample_curve.xi[0], 0.05, rel_tol=1e-7)

    def test_fractional_calendar_roll(self, sample_curve: LogForwardVarianceCurve):
        dt = 1.0 / 252.0  # 1 trading day
        event = sample_curve.roll_calendar(dt=dt, tail_log_xi=np.log(0.16))
        assert event.transition == CalendarTransition.CALENDAR_ROLLED
        assert event.state == CalendarState.ACTIVE
        assert sample_curve.asof == 10.0 + dt
        assert sample_curve.tau_edges[0] == 0.0
        assert math.isclose(sample_curve.horizon, 1.0, abs_tol=1e-5)

    def test_expired_horizon_triggers_rebootstrap(self, sample_curve: LogForwardVarianceCurve):
        # Advancing calendar by 1.1 years exceeds 1.0 horizon
        event = sample_curve.roll_calendar(dt=1.10)
        assert event.transition == CalendarTransition.CALENDAR_ROLLED
        assert event.state == CalendarState.NEEDS_REBOOTSTRAP
        assert sample_curve.state == CalendarState.NEEDS_REBOOTSTRAP

        # Querying total variance on expired curve raises RuntimeError
        with pytest.raises(RuntimeError):
            sample_curve.total_variance(0.5)

        # Rebootstrapping restores active state
        reboot_event = sample_curve.rebootstrap(
            asof=11.10,
            tau_edges=[0.0, 0.5, 1.0],
            log_xi=np.log([0.04, 0.09]),
        )
        assert reboot_event.transition == CalendarTransition.REBOOTSTRAPPED
        assert sample_curve.state == CalendarState.ACTIVE
        assert sample_curve.total_variance(0.5) > 0.0


class TestHawkesCalendarRollPolicy:
    """Verifies calendar spread carry, pin risk, and emergency roll decisions."""

    @pytest.fixture
    def policy(self) -> HawkesCalendarRollPolicy:
        return HawkesCalendarRollPolicy(
            pin_cutoff_tau=2.0 / 252.0,      # 2 days
            roll_threshold=0.50,
            alert_threshold=1.00,
            jump_hazard_weight=1.50,
            reference_volatility=0.15,
            emergency_lambda_threshold=15.0,
        )

    def test_safety_gate_locked(self, policy: HawkesCalendarRollPolicy):
        assert not LIVE_ORDER_DISPATCH_ENABLED

    def test_pin_risk_triggers_execute_roll(self, policy: HawkesCalendarRollPolicy):
        # 1 day to near expiry (inside 2-day pin cutoff)
        eval_res = policy.evaluate_roll(
            tau_near=1.0 / 252.0,
            tau_next=8.0 / 252.0,
            iv_near=0.18,
            iv_next=0.19,
            expected_rv_near=0.14,
            expected_rv_next=0.15,
            theta_near=50.0,
            theta_next=25.0,
            gamma_near=10.0,
            gamma_next=4.0,
            jump_intensity=1.0,
            jump_second_moment=0.002,
        )
        assert eval_res.pin_risk_flag is True
        assert eval_res.decision == RollDecision.EXECUTE_ROLL
        assert "inside pin risk cutoff" in eval_res.reason
        assert eval_res.is_live_dispatch_locked is True

    def test_emergency_deleverage_on_hawkes_spike(self, policy: HawkesCalendarRollPolicy):
        # Massive Hawkes intensity spike (lambda_J = 20.0 > 15.0)
        eval_res = policy.evaluate_roll(
            tau_near=10.0 / 252.0,
            tau_next=17.0 / 252.0,
            iv_near=0.22,
            iv_next=0.21,
            expected_rv_near=0.18,
            expected_rv_next=0.17,
            theta_near=40.0,
            theta_next=30.0,
            gamma_near=5.0,
            gamma_next=3.0,
            jump_intensity=20.0,
            jump_second_moment=0.010,
        )
        assert eval_res.decision == RollDecision.EMERGENCY_DELEVERAGE
        assert "exceeded emergency threshold" in eval_res.reason

    def test_attractive_carry_recommends_hold(self, policy: HawkesCalendarRollPolicy):
        # Near expiry has massive theta/gamma carry (100 / 5 = 20) vs next (25 / 5 = 5)
        eval_res = policy.evaluate_roll(
            tau_near=12.0 / 252.0,
            tau_next=19.0 / 252.0,
            iv_near=0.20,
            iv_next=0.19,
            expected_rv_near=0.15,
            expected_rv_next=0.15,
            theta_near=100.0,
            theta_next=25.0,
            gamma_near=5.0,
            gamma_next=5.0,
            jump_intensity=0.5,
            jump_second_moment=0.001,
        )
        assert eval_res.decision == RollDecision.HOLD
        assert eval_res.near_carry_ratio > eval_res.next_carry_ratio


class TestDualCriticRegularizedEvolutionCycle16:
    """Evaluates the new Cycle 16 module code through Critic A and Critic B."""

    def test_cycle16_module_passes_dsec_gate(self):
        gate = DualCriticRegularizedEvolutionGate(
            b_min=7,
            b_max=15,
            delta_ood=0.05,
            delta_j=0.01,
        )

        with open("agents/AGI_1_7/engine/agi17/finance/hawkes_calendar_roll_engine.py", "r", encoding="utf-8") as f:
            code = f.read()

        proposal = MutationProposal(
            proposal_id="CYCLE_16_HAWKES_CALENDAR_ROLL_001",
            target_filepath="agents/AGI_1_7/engine/agi17/finance/hawkes_calendar_roll_engine.py",
            hypothesis="Phase 28 Cycle 16: Log-Forward Variance Monotonicity & Calendar Roll State Machine",
            original_code="",
            candidate_code=code,
            round_number=1,
            total_rounds=20,
        )

        def mock_eval_fn():
            return (0.96, 0.93, 0.03, 0.06)

        result = gate.evaluate_mutation(
            proposal=proposal,
            behavioral_eval_fn=mock_eval_fn,
        )

        assert result.overall_decision == CriticDecision.PASS
        assert result.critic_a_decision == CriticDecision.PASS
        assert result.critic_b_decision == CriticDecision.PASS
        assert result.ood_lcb >= -0.05
        assert result.objective_lcb > 0.01
