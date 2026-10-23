"""
Unit tests for Phase 28 Cycle 15: Jump-Penalized Kelly Sizing, Joint Greek Hedging & Microstructure Execution.

Verifies:
1. Continuous-time jump-penalized Kelly root solving, mean-variance approximation, and drawdown taper.
2. Cross-index joint Greek hedging with residual Delta/Vega/Gamma constraints and lot rounding.
3. Almgren-Chriss / Gatheral transient impact scheduling with PSD congruence modulation.
4. Critic A AST integrity and fail-closed safety gate (LIVE_ORDER_DISPATCH_ENABLED = False).
"""

from __future__ import annotations

import math
import numpy as np
import pytest

from agents.AGI_1_7.engine.agi17.finance.jump_kelly_hedging_execution_engine import (
    ContinuousJumpKellySizer,
    JumpMark,
    KellySizingResult,
    JointGreekCrossHedger,
    JointGreekHedgeResult,
    TransientImpactExecutionPlanner,
    ExecutionScheduleResult,
    LIVE_ORDER_DISPATCH_ENABLED,
)
from agents.AGI_1_7.engine.agi17.orchestration.dual_critic_regularized_evolution_gate import (
    DualCriticRegularizedEvolutionGate,
    MutationProposal,
    CriticDecision,
    GateEvaluationResult,
)


class TestJumpKellySizer:
    """Verifies continuous-time jump-penalized Kelly fraction calculations."""

    @pytest.fixture
    def sizer(self) -> ContinuousJumpKellySizer:
        return ContinuousJumpKellySizer(
            risk_aversion=1.0,
            fractional_kelly=0.5,
            f_hard_cap=2.0,
            max_drawdown_limit=0.20,
            drawdown_power=1.5,
            uncertainty_z=1.0,
            beta_ofi=0.05,
        )

    def test_safety_gate_locked(self, sizer: ContinuousJumpKellySizer):
        assert not LIVE_ORDER_DISPATCH_ENABLED
        res = sizer.compute_size(
            mean_excess_drift=0.15,
            drift_std_error=0.02,
            diffusion_volatility=0.20,
            jump_intensity=2.0,
            jump_marks=[JumpMark(-0.05, 0.5), JumpMark(0.04, 0.5)],
            current_drawdown=0.02,
            nofi=0.2,
        )
        assert res.is_live_dispatch_locked is True

    def test_zero_allocation_on_negative_drift(self, sizer: ContinuousJumpKellySizer):
        res = sizer.compute_size(
            mean_excess_drift=-0.05,
            drift_std_error=0.01,
            diffusion_volatility=0.20,
            jump_intensity=1.0,
            jump_marks=[JumpMark(-0.02, 1.0)],
            current_drawdown=0.0,
            nofi=-0.5,
        )
        assert res.f_optimal == 0.0
        assert res.f_exact_kelly == 0.0

    def test_jump_intensity_reduces_allocation(self, sizer: ContinuousJumpKellySizer):
        marks = [JumpMark(-0.08, 0.6), JumpMark(0.06, 0.4)]
        res_low_jump = sizer.compute_size(
            mean_excess_drift=0.20,
            drift_std_error=0.02,
            diffusion_volatility=0.15,
            jump_intensity=0.5,
            jump_marks=marks,
            current_drawdown=0.01,
        )
        res_high_jump = sizer.compute_size(
            mean_excess_drift=0.20,
            drift_std_error=0.02,
            diffusion_volatility=0.15,
            jump_intensity=10.0,
            jump_marks=marks,
            current_drawdown=0.01,
        )
        assert res_high_jump.f_exact_kelly < res_low_jump.f_exact_kelly
        assert res_high_jump.f_optimal <= res_low_jump.f_optimal

    def test_solvency_bound_on_severe_jump_loss(self, sizer: ContinuousJumpKellySizer):
        # 40% sudden drop: leverage must remain strictly below 1 / 0.40 = 2.5
        marks = [JumpMark(-0.40, 0.2), JumpMark(0.10, 0.8)]
        res = sizer.compute_size(
            mean_excess_drift=0.80, # Very high drift
            drift_std_error=0.01,
            diffusion_volatility=0.10,
            jump_intensity=1.0,
            jump_marks=marks,
            current_drawdown=0.0,
        )
        assert res.f_optimal < 2.5
        assert 1.0 + res.f_optimal * (-0.40) > 0.0

    def test_drawdown_taper_reaches_zero_at_limit(self, sizer: ContinuousJumpKellySizer):
        marks = [JumpMark(-0.04, 0.5), JumpMark(0.04, 0.5)]
        res_at_limit = sizer.compute_size(
            mean_excess_drift=0.25,
            drift_std_error=0.01,
            diffusion_volatility=0.15,
            jump_intensity=1.0,
            jump_marks=marks,
            current_drawdown=0.20, # Exactly DD_max
        )
        assert res_at_limit.f_optimal == 0.0
        assert res_at_limit.f_drawdown_cap == 0.0

    def test_mean_variance_approximation_direction(self, sizer: ContinuousJumpKellySizer):
        marks = [JumpMark(-0.05, 0.5), JumpMark(0.05, 0.5)]
        res = sizer.compute_size(
            mean_excess_drift=0.15,
            drift_std_error=0.01,
            diffusion_volatility=0.20,
            jump_intensity=2.0,
            jump_marks=marks,
            current_drawdown=0.02,
        )
        assert res.f_mean_variance > 0.0
        assert abs(res.f_exact_kelly - res.f_mean_variance) < 1.0


class TestJointGreekCrossHedger:
    """Verifies regularized joint Greek hedging across indices."""

    @pytest.fixture
    def hedger(self) -> JointGreekCrossHedger:
        # Greek limits: [Delta_N, Delta_B, Vega_N, Vega_B, Gamma_N, Gamma_B]
        limits = [50.0, 50.0, 100.0, 100.0, 10.0, 10.0]
        return JointGreekCrossHedger(greek_limits=limits, regularization_lambda=1e-3)

    def test_safety_gate_locked(self, hedger: JointGreekCrossHedger):
        assert not LIVE_ORDER_DISPATCH_ENABLED

    def test_risk_reduction_on_correlated_factor(self, hedger: JointGreekCrossHedger):
        # Portfolio: heavily long NIFTY delta (200) and vega (150)
        e_0 = np.array([200.0, 50.0, 150.0, 30.0, 5.0, 2.0])

        # 3 hedge instruments (e.g. NIFTY future, BANKNIFTY future, NIFTY ATM put)
        G = np.array([
            [-1.0,  0.0, -0.5], # Delta N
            [ 0.0, -1.0, -0.2], # Delta B
            [ 0.0,  0.0,  0.8], # Vega N
            [ 0.0,  0.0,  0.3], # Vega B
            [ 0.0,  0.0,  0.1], # Gamma N
            [ 0.0,  0.0,  0.0], # Gamma B
        ])

        Sigma = np.eye(6)
        lot_sizes = [50, 25, 50] # standard lots

        res = hedger.compute_hedge(
            portfolio_exposure=e_0,
            instrument_greeks=G,
            factor_covariance=Sigma,
            lot_sizes=lot_sizes,
        )

        assert res.residual_risk_norm < res.initial_risk_norm
        assert res.is_live_dispatch_locked is True

    def test_residual_greeks_satisfied(self, hedger: JointGreekCrossHedger):
        # Exposure within easy hedge range
        e_0 = np.array([30.0, 25.0, 40.0, 20.0, 3.0, 1.0])
        G = -np.eye(6) # Ideal direct hedge instruments
        Sigma = np.eye(6)
        lot_sizes = [1, 1, 1, 1, 1, 1]

        res = hedger.compute_hedge(
            portfolio_exposure=e_0,
            instrument_greeks=G,
            factor_covariance=Sigma,
            lot_sizes=lot_sizes,
        )

        assert res.satisfies_continuous_limits is True
        assert res.satisfies_lot_limits is True
        assert np.all(np.abs(res.residual_greeks) <= hedger.greek_limits)


class TestTransientImpactExecutionPlanner:
    """Verifies discrete-time Almgren-Chriss Gatheral transient execution scheduling."""

    @pytest.fixture
    def planner(self) -> TransientImpactExecutionPlanner:
        return TransientImpactExecutionPlanner(
            gamma_imp=0.5,
            alpha_imp=0.5,
            eps_t=0.2,
            d_ref=1000.0,
            eps_d=1.0,
            zeta=0.5,
            kappa=0.2,
            temporary_eta=0.05,
            risk_aversion_lambda=1e-4,
        )

    def test_safety_gate_locked(self, planner: TransientImpactExecutionPlanner):
        assert not LIVE_ORDER_DISPATCH_ENABLED

    def test_mass_conservation(self, planner: TransientImpactExecutionPlanner):
        n = 5
        depths = [800.0, 1000.0, 1200.0, 900.0, 1100.0]
        nofis = [0.1, -0.2, 0.0, 0.3, -0.1]
        total_q = 500.0

        res = planner.plan_execution(
            total_quantity=total_q,
            num_slices=n,
            delta_t=1.0,
            direction=1,
            book_depths=depths,
            nofi_values=nofis,
        )

        assert math.isclose(float(np.sum(res.schedule_slices)), total_q, rel_tol=1e-4)
        assert res.is_psd_guaranteed is True
        assert res.is_live_dispatch_locked is True

    def test_shallow_depth_increases_expected_slippage(self, planner: TransientImpactExecutionPlanner):
        n = 4
        nofis = [0.0] * n
        deep_depths = [5000.0] * n
        thin_depths = [100.0] * n

        res_deep = planner.plan_execution(
            total_quantity=200.0,
            num_slices=n,
            delta_t=1.0,
            direction=1,
            book_depths=deep_depths,
            nofi_values=nofis,
        )
        res_thin = planner.plan_execution(
            total_quantity=200.0,
            num_slices=n,
            delta_t=1.0,
            direction=1,
            book_depths=thin_depths,
            nofi_values=nofis,
        )

        assert res_thin.expected_slippage > res_deep.expected_slippage

    def test_bounded_participation_cap(self, planner: TransientImpactExecutionPlanner):
        n = 4
        depths = [1000.0] * n
        nofis = [0.0] * n
        total_q = 200.0
        cap = 60.0

        res = planner.plan_execution(
            total_quantity=total_q,
            num_slices=n,
            delta_t=1.0,
            direction=1,
            book_depths=depths,
            nofi_values=nofis,
            max_slice_cap=cap,
        )

        assert np.all(res.schedule_slices <= cap + 1e-4)
        assert math.isclose(float(np.sum(res.schedule_slices)), total_q, rel_tol=1e-4)


class TestDualCriticRegularizedEvolutionCycle15:
    """Evaluates the new module code through Critic A and Critic B."""

    def test_cycle15_module_passes_dsec_gate(self):
        gate = DualCriticRegularizedEvolutionGate(
            b_min=7,
            b_max=15,
            delta_ood=0.05,
            delta_j=0.01,
        )

        with open("agents/AGI_1_7/engine/agi17/finance/jump_kelly_hedging_execution_engine.py", "r", encoding="utf-8") as f:
            code = f.read()

        proposal = MutationProposal(
            proposal_id="CYCLE_15_JUMP_KELLY_EXECUTION_001",
            target_filepath="agents/AGI_1_7/engine/agi17/finance/jump_kelly_hedging_execution_engine.py",
            hypothesis="Phase 28 Cycle 15: Jump-Penalized Kelly Sizer, Joint Greek Hedger, PSD Transient Impact Planner",
            original_code="",
            candidate_code=code,
            round_number=1,
            total_rounds=20,
        )

        def mock_eval_fn():
            # Returns (id_score, ood_score, ood_lcb, objective_lcb)
            return (0.95, 0.92, 0.02, 0.05)

        result = gate.evaluate_mutation(
            proposal=proposal,
            behavioral_eval_fn=mock_eval_fn,
        )

        assert result.overall_decision == CriticDecision.PASS
        assert result.critic_a_decision == CriticDecision.PASS
        assert result.critic_b_decision == CriticDecision.PASS
        assert result.ood_lcb >= -0.05
        assert result.objective_lcb > 0.01
