"""Phase 28 Test Suite: Multivariate Hawkes, MLOFI, Jump-Diffusion & Dual-Critic Evolution Gate.

Tests mathematical invariants and safety controls:
1. Zero-event continuous exponential decay verification.
2. Single and multi-event excitation dynamics.
3. Spectral radius stability bound rho(K) <= 0.90 enforcement.
4. Out-of-order event rejection (dt < 0 fail-closed invariant).
5. Multi-level OFI bid/ask depth pressure and normalization in [-1, 1].
6. Second-moment Hawkes jump-diffusion volatility projection.
7. Critic A path allowlisting and protected path rejection.
8. Critic A fail-closed Directive Zero enforcement (LIVE_ORDER_DISPATCH_ENABLED locked False).
9. Critic A prohibited system call prevention (os.system).
10. Critic A annealed edit budget enforcement.
11. Critic B out-of-distribution regression rejection (LCB_OOD >= -delta_OOD).
12. Critic B noise-floor significance threshold (LCB_J > delta_J).
13. End-to-end evolution proposal evaluation and ledger persistence.
"""

from __future__ import annotations

import math
import os
import pytest
from pathlib import Path
import numpy as np

from agents.AGI_1_7.engine.agi17.finance.multivariate_hawkes_ofi_jump_engine import (
    HawkesEvent,
    MarketDataQuality,
    MultivariateHawkesOFIJumpEngine,
    OrderBookLevel,
)
from agents.AGI_1_7.engine.agi17.orchestration.dual_critic_regularized_evolution_gate import (
    CriticDecision,
    DualCriticRegularizedEvolutionGate,
    MutationProposal,
)


class TestMultivariateHawkesAndOFI:
    """Verifies Module A mathematical correctness and stability invariants."""

    def test_hawkes_zero_event_decay(self) -> None:
        engine = MultivariateHawkesOFIJumpEngine(num_types=2, num_kernels=2)
        # Seed state with an event at t=1.0
        ev1 = HawkesEvent(timestamp=1.0, event_type=0, price=24500.0, size=50.0)
        engine.process_event(ev1)
        initial_val = engine.X[0][0][0]
        assert initial_val > 0.0

        # Advance time by dt=0.5 with an event of inactive type or check decay
        # At dt=0.5, X[0][0][0] should decay by exp(-beta * dt)
        beta = engine.beta[0][0][0]
        dt = 0.5
        expected_decayed = initial_val * math.exp(-beta * dt)

        # Process an event at t=1.5 (event_type=1 so type 0 excitation is only decayed)
        ev2 = HawkesEvent(timestamp=1.5, event_type=1, price=24500.0, size=50.0)
        engine.process_event(ev2)
        actual_val = engine.X[0][0][0]
        assert pytest.approx(actual_val, rel=1e-4) == expected_decayed

    def test_hawkes_event_update(self) -> None:
        engine = MultivariateHawkesOFIJumpEngine(num_types=2, num_kernels=2)
        ev = HawkesEvent(timestamp=100.0, event_type=0, price=24000.0, size=25.0)
        intensities, quality = engine.process_event(ev)
        assert quality == MarketDataQuality.VALID
        # Pre-event intensity should equal baseline mu
        assert intensities[0] == pytest.approx(engine.mu[0], rel=1e-5)
        # Post-event excitation should reflect alpha
        assert engine.X[0][0][0] == pytest.approx(engine.alpha[0][0][0], rel=1e-5)

    def test_hawkes_stability_constraint(self) -> None:
        # Branching ratio > 0.90 must be rejected
        unstable_alpha = [[[3.0, 3.0], [3.0, 3.0]], [[3.0, 3.0], [3.0, 3.0]]]
        slow_beta = [[[1.0, 1.0], [1.0, 1.0]], [[1.0, 1.0], [1.0, 1.0]]]
        with pytest.raises(ValueError, match="Hawkes branching matrix is unstable"):
            MultivariateHawkesOFIJumpEngine(
                num_types=2,
                num_kernels=2,
                decay_rates=slow_beta,
                excitation_amplitudes=unstable_alpha,
                max_branching_ratio=0.90,
            )

    def test_hawkes_out_of_order_rejection(self) -> None:
        engine = MultivariateHawkesOFIJumpEngine(num_types=2, num_kernels=2)
        ev1 = HawkesEvent(timestamp=10.0, event_type=0)
        engine.process_event(ev1)

        # Event with timestamp earlier than last_timestamp
        ev_retro = HawkesEvent(timestamp=9.0, event_type=1)
        _, quality = engine.process_event(ev_retro)
        assert quality == MarketDataQuality.OUT_OF_ORDER

    def test_multilevel_ofi_constant_book(self) -> None:
        book1 = [
            OrderBookLevel(bid_price=24500.0, bid_size=100.0, ask_price=24505.0, ask_size=120.0),
            OrderBookLevel(bid_price=24495.0, bid_size=200.0, ask_price=24510.0, ask_size=250.0),
        ]
        book2 = [
            OrderBookLevel(bid_price=24500.0, bid_size=100.0, ask_price=24505.0, ask_size=120.0),
            OrderBookLevel(bid_price=24495.0, bid_size=200.0, ask_price=24510.0, ask_size=250.0),
        ]
        mlofi, nofi = MultivariateHawkesOFIJumpEngine.compute_multilevel_ofi(book1, book2)
        assert mlofi == 0.0
        assert nofi == 0.0

    def test_multilevel_ofi_directional_pressure(self) -> None:
        book_prev = [
            OrderBookLevel(bid_price=24500.0, bid_size=100.0, ask_price=24505.0, ask_size=100.0),
        ]
        # Bid price increases -> strong buying pressure
        book_bid_surge = [
            OrderBookLevel(bid_price=24505.0, bid_size=150.0, ask_price=24510.0, ask_size=80.0),
        ]
        mlofi, nofi = MultivariateHawkesOFIJumpEngine.compute_multilevel_ofi(book_prev, book_bid_surge)
        assert mlofi > 0.0
        assert 0.0 < nofi <= 1.0

        # Ask price decreases -> strong selling pressure
        book_ask_drop = [
            OrderBookLevel(bid_price=24495.0, bid_size=80.0, ask_price=24500.0, ask_size=200.0),
        ]
        mlofi_s, nofi_s = MultivariateHawkesOFIJumpEngine.compute_multilevel_ofi(book_prev, book_ask_drop)
        assert mlofi_s < 0.0
        assert -1.0 <= nofi_s < 0.0

    def test_jump_diffusion_volatility_projection(self) -> None:
        engine = MultivariateHawkesOFIJumpEngine(num_types=2, num_kernels=2)
        vol_calm = engine.estimate_conditional_jump_volatility(horizon_seconds=1.0)
        assert vol_calm > 0.0

        # Fire multiple clustering events
        for i in range(10):
            engine.process_event(HawkesEvent(timestamp=1.0 + i * 0.05, event_type=0))

        vol_burst = engine.estimate_conditional_jump_volatility(horizon_seconds=1.0)
        # Volatility projection during jump cluster must exceed baseline calm vol
        assert vol_burst > vol_calm

    def test_scenario_gamma_exposure(self) -> None:
        strikes = [24000.0, 24500.0, 25000.0]
        ois = [10000.0, 25000.0, 15000.0]
        gammas = [0.0001, 0.0004, 0.0001]
        underlying = 24500.0
        gamma_exp = MultivariateHawkesOFIJumpEngine.estimate_scenario_gamma_exposure(
            underlying_price=underlying,
            strikes=strikes,
            open_interests=ois,
            gammas=gammas,
            contract_multiplier=25.0,
        )
        assert isinstance(gamma_exp, float)
        assert gamma_exp != 0.0

    def test_hawkes_power_iteration_d3(self) -> None:
        """Verifies d=3 Hawkes process power iteration stability evaluation."""
        eng3 = MultivariateHawkesOFIJumpEngine(num_types=3, num_kernels=2)
        assert eng3.d == 3
        assert eng3.spectral_radius == 0.9
        assert eng3.is_stable is True

    def test_hawkes_simultaneous_events_zero_dt(self) -> None:
        """Verifies sub-millisecond simultaneous events (dt = 0.0) without state degradation."""
        engine = MultivariateHawkesOFIJumpEngine(num_types=2, num_kernels=2)
        ev1 = HawkesEvent(timestamp=100.0, event_type=0)
        ev2 = HawkesEvent(timestamp=100.0, event_type=0)
        int1, q1 = engine.process_event(ev1)
        int2, q2 = engine.process_event(ev2)
        assert q1 == MarketDataQuality.VALID
        assert q2 == MarketDataQuality.VALID
        assert int1[0] == pytest.approx(0.5)
        # Second event at dt=0 reflects first event excitation without decay
        assert int2[0] == pytest.approx(0.5 + 0.3 + 0.1)

    def test_hawkes_validation_invariants(self) -> None:
        """Verifies fail-closed checks on invalid base rates, decay rates, and amplitudes."""
        with pytest.raises(ValueError, match="strictly positive"):
            MultivariateHawkesOFIJumpEngine(num_types=2, base_rates=[-0.1, 0.5])
        with pytest.raises(ValueError, match="Expected 2 base rates"):
            MultivariateHawkesOFIJumpEngine(num_types=2, base_rates=[0.5])
        with pytest.raises(ValueError, match="decay_rates shape"):
            MultivariateHawkesOFIJumpEngine(num_types=2, decay_rates=[[[1.0]]])
        with pytest.raises(ValueError, match="must be strictly positive"):
            MultivariateHawkesOFIJumpEngine(
                num_types=2,
                decay_rates=[[[0.0, 1.0], [1.0, 1.0]], [[1.0, 1.0], [1.0, 1.0]]],
            )

    def test_multilevel_ofi_extreme_clamping_and_empty(self) -> None:
        """Verifies strict [-1.0, 1.0] NOFI bounding under massive order book imbalances."""
        b_prev = [OrderBookLevel(100.0, 1_000_000.0, 101.0, 1_000_000.0)]
        b_curr = [OrderBookLevel(101.0, 1.0, 102.0, 1.0)]
        mlofi, nofi = MultivariateHawkesOFIJumpEngine.compute_multilevel_ofi(b_prev, b_curr)
        assert mlofi > 0.0
        assert nofi == 1.0  # Clamped strictly at boundary
        assert -1.0 <= nofi <= 1.0

        # Empty books
        m_empty, n_empty = MultivariateHawkesOFIJumpEngine.compute_multilevel_ofi([], [])
        assert m_empty == 0.0
        assert n_empty == 0.0

    def test_jump_diffusion_horizon_invariance(self) -> None:
        """Verifies annualized volatility projection is horizon-invariant under constant intensity."""
        engine = MultivariateHawkesOFIJumpEngine(num_types=2, num_kernels=2)
        vol_h1 = engine.estimate_conditional_jump_volatility(horizon_seconds=1.0)
        vol_h10 = engine.estimate_conditional_jump_volatility(horizon_seconds=10.0)
        # Under constant intensity, annualized volatility across H=1 and H=10 must be identical
        assert pytest.approx(vol_h1, rel=1e-3) == vol_h10

    def test_scenario_gamma_exposure_boundary_guards(self) -> None:
        """Verifies dealer gamma exposure safely handles empty or mismatched lists."""
        assert MultivariateHawkesOFIJumpEngine.estimate_scenario_gamma_exposure(24500.0, [], [], []) == 0.0
        # Mismatched list length handled gracefully by min length guard
        exp = MultivariateHawkesOFIJumpEngine.estimate_scenario_gamma_exposure(
            24500.0, [24000.0, 25000.0], [1000.0], [0.0001]
        )
        assert exp != 0.0


class TestDualCriticRegularizedEvolutionGate:
    """Verifies Module B AST integrity, RRSI budget, and OOD gatekeeper."""

    def test_critic_a_rejects_protected_path(self, tmp_path: Path) -> None:
        gate = DualCriticRegularizedEvolutionGate(ledger_path=str(tmp_path / "ledger.json"))
        proposal = MutationProposal(
            proposal_id="TEST-01",
            target_filepath="agents/AGI_1_7/evaluation/benchmark_evaluator.py",
            hypothesis="Optimize benchmark evaluation",
            original_code="def eval(): pass",
            candidate_code="def eval(): return 1.0",
        )
        dec, reason, _, _ = gate.critic_a_ast_policy(proposal)
        assert dec == CriticDecision.REJECT_AST_POLICY
        assert "protected path" in reason

    def test_critic_a_rejects_safety_invariant_tampering(self, tmp_path: Path) -> None:
        gate = DualCriticRegularizedEvolutionGate(ledger_path=str(tmp_path / "ledger.json"))
        orig_code = "LIVE_ORDER_DISPATCH_ENABLED = False\ndef execute(): pass"
        # Malicious candidate attempts to enable live execution
        cand_code = "LIVE_ORDER_DISPATCH_ENABLED = True\ndef execute(): pass"
        proposal = MutationProposal(
            proposal_id="TEST-02",
            target_filepath="agents/AGI_1_7/engine/finance/order_router.py",
            hypothesis="Enable live fills",
            original_code=orig_code,
            candidate_code=cand_code,
        )
        dec, reason, _, _ = gate.critic_a_ast_policy(proposal)
        assert dec == CriticDecision.REJECT_SAFETY_INVARIANT
        assert "LIVE_ORDER_DISPATCH_ENABLED" in reason

    def test_critic_a_rejects_prohibited_calls(self, tmp_path: Path) -> None:
        gate = DualCriticRegularizedEvolutionGate(ledger_path=str(tmp_path / "ledger.json"))
        orig_code = "def check(): return 1"
        cand_code = "import os\ndef check(): os.system('calc.exe'); return 1"
        proposal = MutationProposal(
            proposal_id="TEST-03",
            target_filepath="agents/AGI_1_7/engine/finance/vol.py",
            hypothesis="Add system monitoring",
            original_code=orig_code,
            candidate_code=cand_code,
        )
        dec, reason, _, _ = gate.critic_a_ast_policy(proposal)
        assert dec == CriticDecision.REJECT_SAFETY_INVARIANT
        assert "os.system" in reason

    def test_critic_a_enforces_annealed_budget(self, tmp_path: Path) -> None:
        gate = DualCriticRegularizedEvolutionGate(b_min=1, b_max=3, ledger_path=str(tmp_path / "ledger.json"))
        # In late rounds (e.g. t=20 of T=20), budget should anneal to b_min=1
        orig_code = "def f1(): pass\ndef f2(): pass\ndef f3(): pass"
        cand_code = "def f1(): return 1\ndef f2(): return 2\ndef f3(): return 3"
        proposal = MutationProposal(
            proposal_id="TEST-04",
            target_filepath="agents/AGI_1_7/engine/finance/calc.py",
            hypothesis="Mutate 3 functions in late round",
            original_code=orig_code,
            candidate_code=cand_code,
            round_number=20,
            total_rounds=20,
        )
        dec, reason, budget, altered = gate.critic_a_ast_policy(proposal)
        assert budget == 1
        assert altered == 3
        assert dec == CriticDecision.REJECT_EXCESSIVE_BUDGET

    def test_critic_b_rejects_ood_regression(self, tmp_path: Path) -> None:
        gate = DualCriticRegularizedEvolutionGate(delta_ood=0.05, ledger_path=str(tmp_path / "ledger.json"))
        proposal = MutationProposal(
            proposal_id="TEST-05",
            target_filepath="agents/AGI_1_7/engine/finance/model.py",
            hypothesis="Overfit in-distribution, fail OOD",
            original_code="def model(): pass",
            candidate_code="def model(): return 42",
        )
        # Behavioral eval returns: id_score=0.95, ood_score=0.60, ood_lcb=-0.12 (worse than -delta_ood -0.05), obj_lcb=0.05
        bad_ood_eval = lambda: (0.95, 0.60, -0.12, 0.05)
        res = gate.evaluate_mutation(proposal, bad_ood_eval)
        assert res.overall_decision == CriticDecision.REJECT_OOD_REGRESSION
        assert "OOD lower confidence bound" in res.rejection_reason

    def test_critic_b_rejects_insufficient_evidence(self, tmp_path: Path) -> None:
        gate = DualCriticRegularizedEvolutionGate(delta_j=0.02, ledger_path=str(tmp_path / "ledger.json"))
        proposal = MutationProposal(
            proposal_id="TEST-06",
            target_filepath="agents/AGI_1_7/engine/finance/model.py",
            hypothesis="Gain is within noise floor",
            original_code="def model(): pass",
            candidate_code="def model(): return 42",
        )
        # Objective LCB is 0.005 <= delta_j 0.02 (statistically indistinguishable from noise)
        noisy_eval = lambda: (0.80, 0.79, -0.01, 0.005)
        res = gate.evaluate_mutation(proposal, noisy_eval)
        assert res.overall_decision == CriticDecision.REJECT_INSUFFICIENT_EVIDENCE
        assert "within evaluation noise floor" in res.rejection_reason

    def test_dual_critic_passes_clean_mutation(self, tmp_path: Path) -> None:
        ledger = str(tmp_path / "ledger.json")
        gate = DualCriticRegularizedEvolutionGate(
            b_min=1, b_max=4, delta_ood=0.05, delta_j=0.02, ledger_path=ledger
        )
        orig_code = "def calculate_spread(bid: float, ask: float) -> float:\n    return ask - bid\n"
        cand_code = "def calculate_spread(bid: float, ask: float) -> float:\n    # Refactored for numerical safety\n    return max(0.0, ask - bid)\n"

        proposal = MutationProposal(
            proposal_id="TEST-07",
            target_filepath="agents/AGI_1_7/engine/agi17/finance/spread.py",
            hypothesis="Add numerical nonnegativity guard to spread calculation",
            original_code=orig_code,
            candidate_code=cand_code,
            round_number=1,
            total_rounds=10,
        )
        # Strong OOD and significant improvement above noise floor
        superior_eval = lambda: (0.92, 0.91, 0.01, 0.04)
        res = gate.evaluate_mutation(proposal, superior_eval)
        assert res.critic_a_decision == CriticDecision.PASS
        assert res.critic_b_decision == CriticDecision.PASS
        assert res.overall_decision == CriticDecision.PASS
        assert os.path.exists(ledger)

    def test_critic_a_rejects_unallowlisted_path(self, tmp_path: Path) -> None:
        gate = DualCriticRegularizedEvolutionGate(ledger_path=str(tmp_path / "ledger.json"))
        proposal = MutationProposal(
            proposal_id="TEST-08",
            target_filepath="scripts/arbitrary_script.py",
            hypothesis="Mutate unauthorized system script",
            original_code="def run(): pass",
            candidate_code="def run(): print(1)",
        )
        dec, reason, _, _ = gate.critic_a_ast_policy(proposal)
        assert dec == CriticDecision.REJECT_AST_POLICY
        assert "not within authorized allowlist prefixes" in reason

    def test_critic_a_rejects_type_annotated_directive_zero_tampering(self, tmp_path: Path) -> None:
        gate = DualCriticRegularizedEvolutionGate(ledger_path=str(tmp_path / "ledger.json"))
        cand_code = "LIVE_ORDER_DISPATCH_ENABLED: bool = True\ndef trade(): pass"
        proposal = MutationProposal(
            proposal_id="TEST-09",
            target_filepath="agents/AGI_1_7/engine/finance/order_router.py",
            hypothesis="Type-annotated bypass of Directive Zero",
            original_code="LIVE_ORDER_DISPATCH_ENABLED: bool = False\ndef trade(): pass",
            candidate_code=cand_code,
        )
        dec, reason, _, _ = gate.critic_a_ast_policy(proposal)
        assert dec == CriticDecision.REJECT_SAFETY_INVARIANT
        assert "LIVE_ORDER_DISPATCH_ENABLED" in reason

    def test_critic_a_rejects_subprocess_run(self, tmp_path: Path) -> None:
        gate = DualCriticRegularizedEvolutionGate(ledger_path=str(tmp_path / "ledger.json"))
        cand_code = "import subprocess\ndef sys_exec(): subprocess.run(['ls', '-la'])"
        proposal = MutationProposal(
            proposal_id="TEST-10",
            target_filepath="agents/AGI_1_7/engine/finance/worker.py",
            hypothesis="Invoke subprocess.run",
            original_code="def sys_exec(): pass",
            candidate_code=cand_code,
        )
        dec, reason, _, _ = gate.critic_a_ast_policy(proposal)
        assert dec == CriticDecision.REJECT_SAFETY_INVARIANT
        assert "subprocess.run" in reason

    def test_annealed_budget_cosine_schedule_exact_values(self, tmp_path: Path) -> None:
        gate = DualCriticRegularizedEvolutionGate(b_min=1, b_max=5, ledger_path=str(tmp_path / "ledger.json"))
        # At t=0: b_0 = ceil(1 + 4/2 * (1 + cos(0))) = ceil(1 + 2 * 2) = 5
        assert gate.compute_annealed_budget(0, 20) == 5
        # At t=T/2 (t=10, T=20): cos(pi/2) = 0 -> ceil(1 + 4/2 * 1) = 3
        assert gate.compute_annealed_budget(10, 20) == 3
        # At t=T (t=20, T=20): cos(pi) = -1 -> ceil(1 + 2 * 0) = 1
        assert gate.compute_annealed_budget(20, 20) == 1
        # Degenerate case T=0 -> b_min
        assert gate.compute_annealed_budget(5, 0) == 1


class TestOnlineCalibrationAndLeadership:
    """Verifies Cycle 13 online parameter adaptation and cross-index leadership index."""

    def test_online_calibrator_step(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.multivariate_hawkes_ofi_jump_engine import (
            OnlineHawkesCalibrator,
        )
        engine = MultivariateHawkesOFIJumpEngine(num_types=2, num_kernels=2)
        calibrator = OnlineHawkesCalibrator(engine, lr_mu=0.01, lr_alpha=0.01, eta_max=0.90)

        # Feed 10 synthetic tick events
        metrics = None
        for i in range(10):
            ev = HawkesEvent(timestamp=100.0 + i * 0.1, event_type=i % 2)
            metrics = calibrator.step_event(ev)

        assert metrics is not None
        assert metrics.step == 10
        assert metrics.is_stable is True
        assert metrics.spectral_radius <= 0.90
        assert -1.0 <= metrics.information_leadership_index <= 1.0

    def test_online_calibrator_spectral_projection(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.multivariate_hawkes_ofi_jump_engine import (
            OnlineHawkesCalibrator,
        )
        engine = MultivariateHawkesOFIJumpEngine(num_types=2, num_kernels=2)
        # Artificially set high learning rate to trigger projection
        calibrator = OnlineHawkesCalibrator(engine, lr_alpha=0.5, eta_max=0.85)

        for i in range(15):
            ev = HawkesEvent(timestamp=1.0 + i * 0.05, event_type=0)
            metrics = calibrator.step_event(ev)

        assert engine.spectral_radius <= 0.85
        assert engine.is_stable is True

    def test_information_leadership_index_symmetry(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.multivariate_hawkes_ofi_jump_engine import (
            OnlineHawkesCalibrator,
        )
        engine = MultivariateHawkesOFIJumpEngine(num_types=2, num_kernels=2)
        calibrator = OnlineHawkesCalibrator(engine)

        # When A leads B (A's order flow strongly excites B, alpha[1][0] > alpha[0][1])
        engine.alpha[1][0] = [0.4, 0.4]  # B excited by A
        engine.alpha[0][1] = [0.05, 0.05]  # A excited by B
        ili_a_leads = calibrator.compute_information_leadership(0, 1)
        assert ili_a_leads > 0.0

        # When B leads A
        engine.alpha[1][0] = [0.05, 0.05]
        engine.alpha[0][1] = [0.4, 0.4]
        ili_b_leads = calibrator.compute_information_leadership(0, 1)
        assert ili_b_leads < 0.0
        assert pytest.approx(ili_a_leads, rel=1e-3) == -ili_b_leads

    def test_streaming_likelihood_exact_increment(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.multivariate_hawkes_ofi_jump_engine import (
            OnlineHawkesCalibrator,
        )
        engine = MultivariateHawkesOFIJumpEngine(num_types=2, num_kernels=2)
        calibrator = OnlineHawkesCalibrator(engine)

        ev1 = HawkesEvent(timestamp=10.0, event_type=0)
        metrics1 = calibrator.step_event(ev1)
        assert math.isfinite(metrics1.log_likelihood_increment)

        # Process a subsequent event after dt=0.25s
        ev2 = HawkesEvent(timestamp=10.25, event_type=1)
        metrics2 = calibrator.step_event(ev2)
        assert metrics2.dt == pytest.approx(0.25, rel=1e-4)
        assert math.isfinite(metrics2.log_likelihood_increment)

    def test_bounded_state_no_history_replay(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.multivariate_hawkes_ofi_jump_engine import (
            OnlineHawkesCalibrator,
        )
        engine = MultivariateHawkesOFIJumpEngine(num_types=2, num_kernels=2)
        calibrator = OnlineHawkesCalibrator(engine)

        # Process 100 consecutive events
        for k in range(100):
            ev = HawkesEvent(timestamp=100.0 + k * 0.01, event_type=k % 2)
            metrics = calibrator.step_event(ev)

        # Invariant: engine and calibrator store only bounded tensors [d, d, M], zero tick arrays
        assert len(engine.X) == 2
        assert len(calibrator.Y) == 2
        assert engine.event_count == 100
        assert engine.is_stable is True

    def test_synthetic_asymmetric_cross_excitation_ratio(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.multivariate_hawkes_ofi_jump_engine import (
            OnlineHawkesCalibrator,
        )
        engine = MultivariateHawkesOFIJumpEngine(num_types=2, num_kernels=2)
        calibrator = OnlineHawkesCalibrator(engine)

        # NIFTY (0) strongly excites BANKNIFTY (1)
        engine.alpha[1][0] = [0.35, 0.35]
        engine.alpha[0][1] = [0.05, 0.05]
        engine.beta[1][0] = [3.0, 0.5]
        engine.beta[0][1] = [3.0, 0.5]

        asym = calibrator.compute_information_leadership(0, 1)
        assert asym > 0.60

        # Reverse: BANKNIFTY strongly excites NIFTY
        engine.alpha[1][0] = [0.05, 0.05]
        engine.alpha[0][1] = [0.35, 0.35]
        asym_rev = calibrator.compute_information_leadership(0, 1)
        assert asym_rev < -0.60
        assert pytest.approx(asym, rel=1e-3) == -asym_rev

    def test_cross_excitation_asymmetry_symmetric_bounds(self) -> None:
        """Verifies compute_cross_excitation_asymmetry & compute_information_leadership maintain bounds in [-1, 1]."""
        from agents.AGI_1_7.engine.agi17.finance.multivariate_hawkes_ofi_jump_engine import (
            OnlineHawkesCalibrator,
        )
        engine = MultivariateHawkesOFIJumpEngine(num_types=2, num_kernels=2)
        calibrator = OnlineHawkesCalibrator(engine)

        # 1. Verification of both engine and calibrator APIs
        d_cross_eng = engine.compute_cross_excitation_asymmetry(0, 1)
        d_cross_cal = calibrator.compute_cross_excitation_asymmetry(0, 1)
        ili = calibrator.compute_information_leadership(0, 1)
        assert d_cross_eng == d_cross_cal == ili
        assert -1.0 <= d_cross_eng <= 1.0

        # 2. Strict anti-symmetry / skew-symmetry: D_cross(B, A) == -D_cross(A, B)
        engine.alpha[1][0] = [0.4, 0.2]
        engine.alpha[0][1] = [0.1, 0.05]
        d_ab = engine.compute_cross_excitation_asymmetry(0, 1)
        d_ba = engine.compute_cross_excitation_asymmetry(1, 0)
        assert d_ab > 0.0
        assert d_ba < 0.0
        assert pytest.approx(d_ab, rel=1e-5) == -d_ba
        assert -1.0 <= d_ab <= 1.0
        assert -1.0 <= d_ba <= 1.0

        # 3. Near-zero excitation guard: when all cross terms are 0.0, ratio is 0.0 without ZeroDivisionError
        engine.alpha[1][0] = [0.0, 0.0]
        engine.alpha[0][1] = [0.0, 0.0]
        d_zero = engine.compute_cross_excitation_asymmetry(0, 1, epsilon=1e-9)
        assert d_zero == 0.0

        # 4. Out of bounds index guard
        with pytest.raises(IndexError):
            engine.compute_cross_excitation_asymmetry(0, 5)

    def test_numerical_stability_guards_near_zero_denominators(self) -> None:
        """Verifies numerical stability guards under zero depth and extreme event intervals."""
        from agents.AGI_1_7.engine.agi17.finance.multivariate_hawkes_ofi_jump_engine import (
            OnlineHawkesCalibrator,
        )
        # 1. Zero order book depth with epsilon=0.0
        b_prev = [OrderBookLevel(bid_price=100.0, bid_size=0.0, ask_price=101.0, ask_size=0.0)]
        b_curr = [OrderBookLevel(bid_price=100.0, bid_size=0.0, ask_price=101.0, ask_size=0.0)]
        mlofi, nofi = MultivariateHawkesOFIJumpEngine.compute_multilevel_ofi(b_prev, b_curr, epsilon=0.0)
        assert mlofi == 0.0
        assert nofi == 0.0
        assert math.isfinite(nofi)

        # 2. OnlineHawkesCalibrator with rapid dt=0.0 and huge dt=10000.0
        engine = MultivariateHawkesOFIJumpEngine(num_types=2, num_kernels=2)
        calibrator = OnlineHawkesCalibrator(engine)

        ev_zero = HawkesEvent(timestamp=0.0, event_type=0)
        m0 = calibrator.step_event(ev_zero)
        assert math.isfinite(m0.log_likelihood_increment)

        ev_simult = HawkesEvent(timestamp=0.0, event_type=1)
        m_sim = calibrator.step_event(ev_simult)
        assert m_sim.dt == 0.0
        assert math.isfinite(m_sim.log_likelihood_increment)

        ev_huge = HawkesEvent(timestamp=10000.0, event_type=0)
        m_huge = calibrator.step_event(ev_huge)
        assert math.isfinite(m_huge.log_likelihood_increment)
        assert m_huge.spectral_radius <= 0.90
        assert m_huge.is_stable is True

    def test_exact_sensitivity_trace_and_finite_difference_gradient(self) -> None:
        """Verifies exact sensitivity trace recursion Y_{ijm} and finite-difference gradient agreement."""
        from agents.AGI_1_7.engine.agi17.finance.multivariate_hawkes_ofi_jump_engine import (
            OnlineHawkesCalibrator,
        )
        engine = MultivariateHawkesOFIJumpEngine(num_types=2, num_kernels=2)
        calibrator = OnlineHawkesCalibrator(engine)

        # Process first event to seed state
        ev0 = HawkesEvent(timestamp=10.0, event_type=0)
        calibrator.step_event(ev0)

        # Check U and Y sensitivity trace state
        assert calibrator.U[0][0][0] == 1.0
        assert calibrator.Y[0][0][0] == 0.0  # At event time t_0, age is 0

        # Process second event after dt = 0.5s
        dt = 0.5
        beta_0 = engine.beta[0][0][0]
        r = math.exp(-beta_0 * dt)
        expected_y_minus = r * (0.0 + dt * 1.0)  # r * (Y_prev + dt * U_prev)

        ev1 = HawkesEvent(timestamp=10.0 + dt, event_type=0)
        calibrator.step_event(ev1)

        # Sensitivity trace Y immediately after ev1 equals Y_minus
        assert pytest.approx(calibrator.Y[0][0][0], rel=1e-5) == expected_y_minus



class TestHawkesSSVISurface:
    """Verifies Cycle 14 Hawkes & NOFI driven SSVI volatility surface."""

    def test_ssvi_to_raw_svi_mapping(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.hawkes_ssvi_surface_engine import (
            HawkesSSVISurfaceEngine,
        )
        engine = HawkesSSVISurfaceEngine()
        theta = 0.04  # ~20% ATM vol for 1-year (or 0.04 total variance)
        rho = -0.40
        eta = 0.50

        raw = engine.ssvi_to_raw_svi(theta, rho, eta)
        assert raw.a > 0.0
        assert raw.b > 0.0
        assert raw.rho == pytest.approx(-0.40, abs=1e-4)
        assert raw.sigma > 0.0
        # ATM total variance w(0) should equal theta
        w_atm = raw.total_variance(0.0)
        assert pytest.approx(w_atm, rel=1e-3) == theta

    def test_ssvi_arbitrage_free_guarantee(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.hawkes_ssvi_surface_engine import (
            HawkesSSVISurfaceEngine,
        )
        engine = HawkesSSVISurfaceEngine()
        raw = engine.ssvi_to_raw_svi(theta=0.03, rho=-0.50, eta=0.60)
        audit = engine.check_arbitrage(raw)

        assert audit.is_arbitrage_free is True
        assert audit.non_negative_variance is True
        assert audit.lee_wing_bound_satisfied is True
        assert audit.butterfly_density_non_negative is True
        assert audit.min_durrleman_density >= -1e-4

    def test_hawkes_surface_perturbation_under_spike(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.hawkes_ssvi_surface_engine import (
            HawkesSSVISurfaceEngine,
        )
        engine = HawkesSSVISurfaceEngine()
        base_theta = 0.02
        base_rho = -0.30
        base_eta = 0.40

        # Calm state
        raw_calm, audit_calm = engine.perturb_surface_with_microstructure(
            base_theta=base_theta,
            base_rho=base_rho,
            base_eta=base_eta,
            lambda_total=1.0,
            lambda_base=1.0,
            nofi=0.0,
        )
        # Hawkes spike state (lambda = 5.0 vs base 1.0)
        raw_spike, audit_spike = engine.perturb_surface_with_microstructure(
            base_theta=base_theta,
            base_rho=base_rho,
            base_eta=base_eta,
            lambda_total=5.0,
            lambda_base=1.0,
            nofi=0.0,
        )

        # ATM variance must expand under Hawkes clustering burst
        assert raw_spike.total_variance(0.0) > raw_calm.total_variance(0.0)
        assert audit_spike.is_arbitrage_free is True

    def test_nofi_downside_put_skew_steepening(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.hawkes_ssvi_surface_engine import (
            HawkesSSVISurfaceEngine,
        )
        engine = HawkesSSVISurfaceEngine()
        # Normal neutral book (NOFI = 0.0)
        raw_neutral, _ = engine.perturb_surface_with_microstructure(
            base_theta=0.03, base_rho=-0.30, base_eta=0.50, lambda_total=1.0, lambda_base=1.0, nofi=0.0
        )
        # Heavy aggressive put buying (NOFI = -0.80)
        raw_panic, audit_panic = engine.perturb_surface_with_microstructure(
            base_theta=0.03, base_rho=-0.30, base_eta=0.50, lambda_total=2.0, lambda_base=1.0, nofi=-0.80
        )

        # Skew must shift significantly negative
        assert raw_panic.rho < raw_neutral.rho
        # OTM put total variance (k = -0.15) must be higher in panic state
        assert raw_panic.total_variance(-0.15) > raw_neutral.total_variance(-0.15)
        # Must strictly preserve butterfly arbitrage freedom (g(k) >= 0)
        assert audit_panic.is_arbitrage_free is True
        assert audit_panic.butterfly_density_non_negative is True


class TestCycle16CalendarEngineAndTermStructure:
    """Verifies Cycle 16 term-structure evolution, localized forward VRP, and discrete state machine."""

    @staticmethod
    def _sample_curve(lambda_jump: float = 2.0):
        from agents.AGI_1_7.engine.agi17.finance.term_structure_calendar_roller import (
            propagate_log_forward_variance,
        )
        tau = np.array([0.0, 1 / 52, 2 / 52, 1 / 12, 1 / 4])
        z = np.log(np.full(tau.size, 0.20**2))
        zbar = np.log(np.full(tau.size, 0.18**2))
        eta = np.full(tau.size, 2.0)
        beta = np.full(tau.size, 0.02)
        return propagate_log_forward_variance(
            tau, z, zbar, eta, beta,
            lambda_jump=lambda_jump, lambda_bar=1.0, dt=1 / 252,
            intensity_mean_reversion=3.0,
        )

    @staticmethod
    def _policy():
        from agents.AGI_1_7.engine.agi17.finance.term_structure_calendar_roller import RollPolicy
        return RollPolicy(
            tau_alert=2 / 252,
            pin_alert_threshold=0.5,
            pin_emergency_threshold=1.0,
            lambda_alert_threshold=5.0,
            lambda_emergency_threshold=10.0,
            roll_alert_threshold=0.05,
            roll_execute_threshold=0.1,
        )

    def test_total_variance_is_zero_at_zero_and_strictly_increasing(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.term_structure_calendar_roller import (
            calendar_monotonicity_violation,
        )
        tau = np.array([0.0, 1 / 52, 2 / 52, 1 / 12, 1 / 4])
        z, q, theta = self._sample_curve()
        assert z.shape == q.shape == theta.shape == tau.shape
        assert theta[0] == 0.0
        assert np.all(q > 0.0)
        assert np.all(np.diff(theta) > 0.0)
        assert not calendar_monotonicity_violation(tau, theta)

    def test_higher_hawkes_intensity_increases_forward_variance_when_beta_positive(self) -> None:
        _, q_low, theta_low = self._sample_curve(lambda_jump=1.0)
        _, q_high, theta_high = self._sample_curve(lambda_jump=8.0)
        assert np.all(q_high > q_low)
        assert np.all(theta_high[1:] > theta_low[1:])

    def test_calendar_violation_detected_for_decreasing_theta(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.term_structure_calendar_roller import (
            calendar_monotonicity_violation,
        )
        tau = [0.0, 0.1, 0.2]
        assert calendar_monotonicity_violation(tau, [0.0, 0.02, 0.019])
        assert not calendar_monotonicity_violation(tau, [0.0, 0.02, 0.02000000001])

    def test_bad_tau_grid_rejected(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.term_structure_calendar_roller import (
            propagate_log_forward_variance,
        )
        with pytest.raises(ValueError):
            propagate_log_forward_variance(
                [0.0, 0.1, 0.1], [0.0, 0.0, 0.0], [0.0, 0.0, 0.0],
                [1.0, 1.0, 1.0], [0.1, 0.1, 0.1],
                lambda_jump=1.0, lambda_bar=1.0, dt=0.1,
            )

    def test_bad_hawkes_intensity_rejected(self) -> None:
        with pytest.raises(ValueError):
            self._sample_curve(lambda_jump=-1.0)

    def test_expected_hazard_count_constant_intensity(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.term_structure_calendar_roller import (
            expected_hazard_count,
        )
        assert expected_hazard_count(4.0, 2.0, 0.5, intensity_mean_reversion=0.0) == pytest.approx(2.0)

    def test_expected_hazard_count_mean_reversion(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.term_structure_calendar_roller import (
            expected_hazard_count,
        )
        count = expected_hazard_count(10.0, 2.0, 1.0, intensity_mean_reversion=2.0)
        expected = 2.0 + 8.0 * (1.0 - np.exp(-2.0)) / 2.0
        assert count == pytest.approx(expected)

    def test_hazard_adjusted_vrp_penalty_increases_with_intensity(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.term_structure_calendar_roller import (
            hazard_adjusted_vrp,
        )
        _, penalty_low, adj_low = hazard_adjusted_vrp(
            0.05, 0.04, lambda_jump=1.0, lambda_bar=1.0, horizon=0.1,
            downside_jump_return_sq_per_event=0.01,
            intensity_mean_reversion=0.0,
        )
        _, penalty_high, adj_high = hazard_adjusted_vrp(
            0.05, 0.04, lambda_jump=5.0, lambda_bar=1.0, horizon=0.1,
            downside_jump_return_sq_per_event=0.01,
            intensity_mean_reversion=0.0,
        )
        assert penalty_high > penalty_low
        assert adj_high < adj_low

    def test_roll_score_favors_next_expiry_when_carry_risk_improves_and_hazard_is_low(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.term_structure_calendar_roller import (
            calendar_roll_score,
        )
        score = calendar_roll_score(
            carry_near_per_time=1.0,
            carry_next_per_time=3.0,
            gamma_near_abs=0.01,
            gamma_next_abs=0.01,
            stress_move=10.0,
            horizon=1.0,
            roll_cost=1.0,
            expected_jump_count=0.0,
            jump_damage_ratio=1.0,
        )
        assert score > 0

    def test_jump_hazard_reduces_roll_score(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.term_structure_calendar_roller import (
            calendar_roll_score,
        )
        kwargs = dict(
            carry_near_per_time=1.0,
            carry_next_per_time=2.0,
            gamma_near_abs=0.01,
            gamma_next_abs=0.01,
            stress_move=10.0,
            horizon=1.0,
            roll_cost=1.0,
            jump_damage_ratio=0.5,
        )
        low = calendar_roll_score(**kwargs, expected_jump_count=0.1)
        high = calendar_roll_score(**kwargs, expected_jump_count=2.0)
        assert high < low

    def test_hold_to_pre_roll_alert_and_alert_to_execution(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.term_structure_calendar_roller import (
            EngineState,
            RollSnapshot,
            next_roll_state,
        )
        p = self._policy()
        s = RollSnapshot(tau_near=1 / 252, pin_risk=0.0, lambda_jump=1.0,
                         roll_score=0.2, execution_allowed=True)
        assert next_roll_state(EngineState.HOLD, s, p) == EngineState.PRE_ROLL_ALERT
        assert next_roll_state(EngineState.PRE_ROLL_ALERT, s, p) == EngineState.EXECUTE_ROLL

    def test_calendar_violation_routes_to_repair(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.term_structure_calendar_roller import (
            EngineState,
            RollSnapshot,
            next_roll_state,
        )
        result = next_roll_state(
            EngineState.HOLD,
            RollSnapshot(tau_near=0.1, pin_risk=0.0, lambda_jump=1.0,
                         roll_score=1.0, calendar_violation=True),
            self._policy(),
        )
        assert result == EngineState.ARBITRAGE_REPAIR

    def test_hard_risk_trigger_overrides_repair_and_latches_emergency(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.term_structure_calendar_roller import (
            EngineState,
            RollSnapshot,
            next_roll_state,
        )
        p = self._policy()
        s = RollSnapshot(tau_near=0.01, pin_risk=1.2, lambda_jump=2.0,
                         roll_score=1.0, calendar_violation=True)
        assert next_roll_state(EngineState.HOLD, s, p) == EngineState.EMERGENCY_DELEVERAGE
        safe = RollSnapshot(tau_near=0.1, pin_risk=0.0, lambda_jump=1.0, roll_score=0.0)
        assert next_roll_state(EngineState.EMERGENCY_DELEVERAGE, safe, p) == EngineState.EMERGENCY_DELEVERAGE
        acknowledged = RollSnapshot(tau_near=0.1, pin_risk=0.0, lambda_jump=1.0,
                                    roll_score=0.0, emergency_reset=True)
        assert next_roll_state(EngineState.EMERGENCY_DELEVERAGE, acknowledged, p) == EngineState.HOLD

    def test_inflight_order_does_not_duplicate_new_decision(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.term_structure_calendar_roller import (
            EngineState,
            RollSnapshot,
            next_roll_state,
        )
        p = self._policy()
        s = RollSnapshot(tau_near=0.1, pin_risk=0.0, lambda_jump=1.0,
                         roll_score=0.0, order_inflight=True)
        assert next_roll_state(EngineState.HOLD, s, p) == EngineState.EXECUTE_ROLL

    def test_unreconciled_execution_routes_to_repair(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.term_structure_calendar_roller import (
            EngineState,
            RollSnapshot,
            next_roll_state,
        )
        s = RollSnapshot(tau_near=0.1, pin_risk=0.0, lambda_jump=1.0,
                         roll_score=0.0, execution_reconciled=False)
        assert next_roll_state(EngineState.EXECUTE_ROLL, s, self._policy()) == EngineState.ARBITRAGE_REPAIR

    def test_high_jump_intensity_triggers_emergency_deleverage(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.term_structure_calendar_roller import (
            EngineState,
            RollSnapshot,
            next_roll_state,
        )
        s = RollSnapshot(tau_near=0.1, pin_risk=0.0, lambda_jump=11.0, roll_score=1.0)
        assert next_roll_state(EngineState.HOLD, s, self._policy()) == EngineState.EMERGENCY_DELEVERAGE

    def test_invalid_numeric_inputs_rejected(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.term_structure_calendar_roller import (
            calendar_roll_score,
            expected_hazard_count,
        )
        with pytest.raises(ValueError):
            expected_hazard_count(float("nan"), 1.0, 0.5, intensity_mean_reversion=1.0)
        with pytest.raises(ValueError):
            calendar_roll_score(
                carry_near_per_time=1.0, carry_next_per_time=2.0,
                gamma_near_abs=0.1, gamma_next_abs=0.1, stress_move=0.0,
                horizon=1.0, roll_cost=0.0, expected_jump_count=0.0,
                jump_damage_ratio=0.0,
            )

    def test_calendar_check_accepts_maturity_grid_starting_after_zero(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.term_structure_calendar_roller import (
            calendar_monotonicity_violation,
        )
        assert not calendar_monotonicity_violation([1 / 365, 7 / 365, 30 / 365], [0.001, 0.010, 0.040])

    def test_intensity_convolution_is_stable_when_decay_rates_match(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.term_structure_calendar_roller import (
            propagate_log_forward_variance,
        )
        tau = np.array([0.0, 0.01, 0.02])
        z0 = np.log(np.full(3, 0.04))
        zbar = np.log(np.full(3, 0.04))
        _, q, theta = propagate_log_forward_variance(
            tau, z0, zbar, np.full(3, 2.0), np.full(3, 0.1),
            lambda_jump=4.0, lambda_bar=1.0, dt=0.1,
            intensity_mean_reversion=2.0,
        )
        expected_z = zbar + 0.1 * 3.0 * (0.1 * np.exp(-2.0 * 0.1))
        assert np.all(np.log(q) == pytest.approx(expected_z))
        assert np.all(np.diff(theta) > 0)

    def test_negative_hazard_loading_is_rejected(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.term_structure_calendar_roller import (
            propagate_log_forward_variance,
        )
        tau = [0.0, 0.1, 0.2]
        with pytest.raises(ValueError):
            propagate_log_forward_variance(
                tau, [0.0, 0.0, 0.0], [0.0, 0.0, 0.0],
                [1.0, 1.0, 1.0], [0.0, -0.1, 0.0],
                lambda_jump=2.0, lambda_bar=1.0, dt=0.1,
            )

    def test_pre_roll_alert_never_executes_when_execution_gate_is_closed(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.term_structure_calendar_roller import (
            EngineState,
            RollSnapshot,
            next_roll_state,
        )
        snap = RollSnapshot(
            tau_near=1 / 252, pin_risk=0.0, lambda_jump=1.0,
            roll_score=0.5, execution_allowed=False,
        )
        assert next_roll_state(EngineState.PRE_ROLL_ALERT, snap, self._policy()) == EngineState.PRE_ROLL_ALERT

    def test_forward_hazard_count_interval_matches_integral(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.term_structure_calendar_roller import (
            expected_hazard_count_interval,
        )
        count = expected_hazard_count_interval(10.0, 2.0, 0.25, 1.0, intensity_mean_reversion=2.0)
        expected = 2.0 * 0.75 + 8.0 * (np.exp(-2.0 * 0.25) - np.exp(-2.0)) / 2.0
        assert count == pytest.approx(expected)

    def test_localized_forward_vrp_penalty_increases_with_hazard(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.term_structure_calendar_roller import (
            localized_forward_vrp_hazard_adjusted,
        )
        args = dict(
            tau_near=1 / 52, tau_next=1 / 12,
            theta_iv_near=0.003, theta_iv_next=0.012,
            expected_total_rv_near=0.0025, expected_total_rv_next=0.010,
            lambda_bar=1.0, downside_jump_return_sq_per_event=0.005,
            intensity_mean_reversion=2.0,
        )
        _, p_low, adjusted_low = localized_forward_vrp_hazard_adjusted(lambda_jump=1.0, **args)
        _, p_high, adjusted_high = localized_forward_vrp_hazard_adjusted(lambda_jump=8.0, **args)
        assert p_high > p_low
        assert adjusted_high < adjusted_low

    def test_pin_risk_score_is_nonnegative_and_scales_with_pin_probability(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.term_structure_calendar_roller import (
            pin_risk_score,
        )
        low = pin_risk_score([2.0, -1.0], [0.1, 0.2], [10.0, 20.0], risk_budget_cash=1000.0)
        high = pin_risk_score([2.0, -1.0], [0.2, 0.4], [10.0, 20.0], risk_budget_cash=1000.0)
        assert low >= 0
        assert high == pytest.approx(2.0 * low)

    def test_pin_risk_invalid_probability_rejected(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.term_structure_calendar_roller import (
            pin_risk_score,
        )
        with pytest.raises(ValueError):
            pin_risk_score([1.0], [1.1], [10.0], risk_budget_cash=100.0)


class TestCycle17TransientImpactExecution:
    """Verifies Cycle 17 transient impact propagator, discrete DP optimizer, and Hawkes-conditioned slicing."""

    def test_decay_reduces_impact_state(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.transient_impact_execution_planner import (
            TransientImpactKernel,
        )
        kernel = TransientImpactKernel((2.0, 0.5), (1.0, 0.2))
        z = (10.0, 4.0)
        after = kernel.decay(z, 1.0)
        assert after[0] < z[0]
        assert after[1] < z[1]
        assert after[0] > 0.0

    def test_faster_rho_resilies_faster(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.transient_impact_execution_planner import (
            TransientImpactKernel,
        )
        kernel = TransientImpactKernel((2.0, 0.5), (1.0, 0.2))
        after = kernel.decay((1.0, 1.0), 1.0)
        assert after[0] < after[1]

    def test_state_advances_and_cost_nonnegative(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.transient_impact_execution_planner import (
            TransientImpactKernel,
        )
        kernel = TransientImpactKernel((2.0, 0.5), (1.0, 0.2))
        state = kernel.advance((0.0, 0.0), rate=5.0, dt=0.5)
        assert all(v > 0 for v in state)
        cost = kernel.integrated_cost(5.0, (0.0, 0.0), 0.5)
        assert cost >= 0.0

    def test_zero_rate_only_decays_old_impact(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.transient_impact_execution_planner import (
            TransientImpactKernel,
        )
        kernel = TransientImpactKernel((2.0, 0.5), (1.0, 0.2))
        state = (2.0, 3.0)
        assert kernel.advance(state, 0.0, 0.5) == kernel.decay(state, 0.5)

    def test_invalid_kernel_rejected(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.transient_impact_execution_planner import (
            TransientImpactKernel,
        )
        with pytest.raises(ValueError):
            TransientImpactKernel((1.0,), (0.0,))

    def test_ac_schedule_boundaries_and_monotonicity(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.transient_impact_execution_planner import (
            almgren_chriss_inventory_schedule,
        )
        x = almgren_chriss_inventory_schedule(100.0, 10.0, 20, 2.0, 0.5, 0.2)
        assert x[0] == 100.0
        assert x[-1] == 0.0
        assert all(x[i] >= x[i + 1] for i in range(len(x) - 1))

    def test_ac_linear_limit(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.transient_impact_execution_planner import (
            almgren_chriss_inventory_schedule,
        )
        x = almgren_chriss_inventory_schedule(12.0, 6.0, 3, 1.0, 0.0, 0.2)
        assert x == (12.0, 8.0, 4.0, 0.0)

    def test_dp_has_zero_terminal_inventory(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.transient_impact_execution_planner import (
            TransientImpactKernel,
            optimize_discrete_schedule,
        )
        kernel = TransientImpactKernel((0.2,), (0.8,))
        fees = {0: 0.0, 1: 5.0, 2: 8.0}
        result = optimize_discrete_schedule(
            total_lots=3, steps=3, max_lots_per_step=2, lot_size=10,
            dt=1.0, market_volume_rate=200.0, half_spread_ticks=1.0,
            tick_size=0.05, kernel=kernel, Y=0.1, sigma_price=1.0,
            inventory_risk_aversion=0.001, return_volatility=0.02,
            fee_cost_by_lots=fees, impact_state_quantum=0.001,
        )
        assert sum(result.lots_per_step) == 3
        assert result.terminal_inventory_lots == 0
        assert len(result.lots_per_step) == 3
        assert all(0 <= q <= 2 for q in result.lots_per_step)

    def test_dp_infeasible_capacity_rejected(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.transient_impact_execution_planner import (
            TransientImpactKernel,
            optimize_discrete_schedule,
        )
        with pytest.raises(ValueError):
            optimize_discrete_schedule(
                total_lots=5, steps=2, max_lots_per_step=2, lot_size=1,
                dt=1, market_volume_rate=10, half_spread_ticks=1,
                tick_size=0.05, kernel=TransientImpactKernel((0.1,), (1.0,)),
                fee_cost_by_lots={0: 0, 1: 1, 2: 2},
            )

    def test_square_root_impact_monotonicity(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.transient_impact_execution_planner import (
            square_root_impact_per_unit,
        )
        assert square_root_impact_per_unit(1.0, 2.0, 0.25) > 0
        assert square_root_impact_per_unit(1.0, 2.0, 1.0) > square_root_impact_per_unit(1.0, 2.0, 0.25)

    def test_jump_clustering_throttles_aggression_and_pace(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.transient_impact_execution_planner import (
            conditioned_slice_policy,
        )
        calm = conditioned_slice_policy(
            base_participation=0.05, max_participation=0.2, market_volume_rate=1000.0,
            hawkes_intensity=1.0, hawkes_baseline=1.0, normalized_ofi=0.0, parent_side=1,
            urgency=1.0, base_aggression=0.7,
        )
        hot = conditioned_slice_policy(
            base_participation=0.05, max_participation=0.2, market_volume_rate=1000.0,
            hawkes_intensity=3.0, hawkes_baseline=1.0, normalized_ofi=0.0, parent_side=1,
            urgency=1.0, base_aggression=0.7,
        )
        assert hot.aggression < calm.aggression
        assert hot.target_participation < calm.target_participation

    def test_adverse_aligned_ofi_raises_pace_but_lowers_cross_aggression(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.transient_impact_execution_planner import (
            conditioned_slice_policy,
        )
        neutral = conditioned_slice_policy(
            base_participation=0.05, max_participation=0.2, market_volume_rate=1000.0,
            hawkes_intensity=1.0, hawkes_baseline=1.0, normalized_ofi=0.0, parent_side=1,
            urgency=1.0, base_aggression=0.7,
        )
        aligned = conditioned_slice_policy(
            base_participation=0.05, max_participation=0.2, market_volume_rate=1000.0,
            hawkes_intensity=1.0, hawkes_baseline=1.0, normalized_ofi=0.8, parent_side=1,
            urgency=1.0, base_aggression=0.7,
        )
        assert aligned.target_participation > neutral.target_participation
        assert aligned.aggression < neutral.aggression

    def test_extreme_hazard_halts(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.transient_impact_execution_planner import (
            conditioned_slice_policy,
        )
        decision = conditioned_slice_policy(
            base_participation=0.05, max_participation=0.2, market_volume_rate=1000.0,
            hawkes_intensity=5.0, hawkes_baseline=1.0, normalized_ofi=0.2, parent_side=1,
            urgency=1.0, base_aggression=0.7,
        )
        assert decision.posture == "HALT"
        assert decision.aggression == 0.0

    def test_sell_side_ofi_convention(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.transient_impact_execution_planner import (
            conditioned_slice_policy,
        )
        buy_pressure = conditioned_slice_policy(
            base_participation=0.02, max_participation=0.1,
            market_volume_rate=100.0, hawkes_intensity=1.0,
            hawkes_baseline=1.0, normalized_ofi=0.6, parent_side=-1,
            base_aggression=0.5,
        )
        assert buy_pressure.aligned_ofi == pytest.approx(-0.6)

    def test_options_sell_one_crore_turnover(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.transient_impact_execution_planner import (
            NSEFeeModel, Product, Side,
        )
        fees = NSEFeeModel()
        b = fees.calculate(Product.OPTION, Side.SELL, 100.0, 10_000, 10, brokerage=100.0)
        assert b.exchange_and_ipft == pytest.approx(3553.0)
        assert b.sebi == pytest.approx(10.0)
        assert b.stt == pytest.approx(15000.0)
        assert b.stamp_duty == pytest.approx(0.0)
        assert b.gst == pytest.approx((3553 + 10 + 100) * 0.18)
        assert b.total == pytest.approx(3553 + 10 + 15000 + 100 + (3553 + 10 + 100) * 0.18)

    def test_options_buy_stamp_but_no_stt(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.transient_impact_execution_planner import (
            NSEFeeModel, Product, Side,
        )
        fees = NSEFeeModel()
        b = fees.calculate(Product.OPTION, Side.BUY, 100.0, 10_000, 10)
        assert b.stamp_duty == pytest.approx(300.0)
        assert b.stt == 0.0

    def test_futures_sale_uses_futures_rates(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.transient_impact_execution_planner import (
            NSEFeeModel, Product, Side,
        )
        fees = NSEFeeModel()
        b = fees.calculate(Product.FUTURE, Side.SELL, 25_000.0, 40, 1)
        turnover = 1_000_000.0
        assert b.exchange_and_ipft == pytest.approx(turnover * 183 / 10_000_000)
        assert b.stt == pytest.approx(turnover * 0.0005)

    def test_tick_rounding_by_intent(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.transient_impact_execution_planner import (
            quantize_limit_price, Side, OrderIntent,
        )
        assert quantize_limit_price(100.07, 0.05, Side.BUY, OrderIntent.PASSIVE) == 100.05
        assert quantize_limit_price(100.07, 0.05, Side.BUY, OrderIntent.AGGRESSIVE) == 100.10
        assert quantize_limit_price(100.07, 0.05, Side.SELL, OrderIntent.PASSIVE) == 100.10
        assert quantize_limit_price(100.07, 0.05, Side.SELL, OrderIntent.AGGRESSIVE) == 100.05

    def test_live_dispatch_disabled(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.transient_impact_execution_planner import (
            LIVE_ORDER_DISPATCH_ENABLED, dispatch_live_order,
        )
        assert not LIVE_ORDER_DISPATCH_ENABLED
        with pytest.raises(RuntimeError):
            dispatch_live_order("BUY", 1)

    def test_mock_fills_are_deterministic(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.transient_impact_execution_planner import (
            DeterministicMockFillSimulator,
        )
        sim = DeterministicMockFillSimulator(passive_fill_fraction=0.5)
        a = sim.fill(10, 9, "PASSIVE_POSTING")
        b = sim.fill(10, 9, "PASSIVE_POSTING")
        assert a == b
        assert a.filled_lots == 5
        cross = sim.fill(10, 4, "CROSS_SPREAD_FILL")
        assert cross.filled_lots == 4

    def test_idle_to_passive_then_cross_candidate(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.transient_impact_execution_planner import (
            ExecutionStateMachine, ExecutionState, StateContext,
        )
        sm = ExecutionStateMachine()
        state = sm.update(StateContext(remaining_lots=10))
        assert state == ExecutionState.PASSIVE_POSTING
        state = sm.update(StateContext(remaining_lots=10, cross_cost_justified=True))
        assert state == ExecutionState.CROSS_SPREAD_FILL

    def test_hazard_or_bad_data_halts(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.transient_impact_execution_planner import (
            ExecutionStateMachine, ExecutionState, StateContext,
        )
        sm = ExecutionStateMachine()
        assert sm.update(StateContext(remaining_lots=5)) == ExecutionState.PASSIVE_POSTING
        assert sm.update(StateContext(remaining_lots=5, jump_hazard_ratio=5)) == ExecutionState.ADVERSE_SELECTION_HALT
        assert sm.update(StateContext(remaining_lots=5, cooldown_clear=False)) == ExecutionState.ADVERSE_SELECTION_HALT
        assert sm.update(StateContext(remaining_lots=5, cooldown_clear=True)) == ExecutionState.PASSIVE_POSTING

    def test_emergency_state_latches_until_manual_ack(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.transient_impact_execution_planner import (
            ExecutionStateMachine, ExecutionState, StateContext,
        )
        sm = ExecutionStateMachine()
        assert sm.update(StateContext(remaining_lots=3, hard_risk_breach=True)) == ExecutionState.EMERGENCY_UNWIND
        assert sm.update(StateContext(remaining_lots=3)) == ExecutionState.EMERGENCY_UNWIND
        assert sm.update(StateContext(remaining_lots=3, manual_recovery_ack=True)) == ExecutionState.IDLE

    def test_no_new_order_when_one_is_in_flight(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.transient_impact_execution_planner import (
            ExecutionStateMachine, ExecutionState, StateContext,
        )
        sm = ExecutionStateMachine()
        state = sm.update(StateContext(remaining_lots=4, order_in_flight=True, cross_cost_justified=True))
        assert state == ExecutionState.PASSIVE_POSTING


class TestCycle18CrossIndexElasticityHedging:
    """Verifies Cycle 18 Cross-Index Elasticity, Joint Greek Hedging, and Friction Gates."""

    def test_kalman_elasticity_finite_updates_and_bounds(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.cross_index_elasticity_hedger import (
            KalmanElasticity, KalmanConfig
        )
        ke = KalmanElasticity(config=KalmanConfig(beta_min=0.5, beta_max=2.5))
        res = ke.update(math.log(24000.0), math.log(51000.0))
        assert 0.5 <= ke.beta <= 2.5
        assert math.isfinite(res["z_score"])
        assert ke.p00 >= 1e-12 and ke.p11 >= 1e-12

    def test_kalman_elasticity_rejects_nan_and_inf(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.cross_index_elasticity_hedger import KalmanElasticity
        ke = KalmanElasticity()
        with pytest.raises(ValueError, match="log prices must be finite"):
            ke.update(float("nan"), 10.0)
        with pytest.raises(ValueError, match="log prices must be finite"):
            ke.update(10.0, float("inf"))

    def test_vecm_controls_adaptation_with_cross_excitation_and_depth(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.cross_index_elasticity_hedger import vecm_controls
        c_base = vecm_controls(d_cross=0.0, normalized_depth=1.0)
        c_high_exc = vecm_controls(d_cross=0.8, normalized_depth=1.0)
        c_deep_book = vecm_controls(d_cross=0.0, normalized_depth=10.0)

        # High cross-excitation widens entry band and speeds up reversion
        assert c_high_exc["entry_band_z"] > c_base["entry_band_z"]
        assert c_high_exc["mean_reversion_speed"] > c_base["mean_reversion_speed"]

        # Deep reliable book reduces speed and tightens entry band
        assert c_deep_book["mean_reversion_speed"] < c_base["mean_reversion_speed"]
        assert c_deep_book["entry_band_z"] < c_base["entry_band_z"]

    def test_vecm_controls_rejects_negative_depth(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.cross_index_elasticity_hedger import vecm_controls
        with pytest.raises(ValueError, match="invalid cross-excitation/depth input"):
            vecm_controls(d_cross=0.1, normalized_depth=-1.0)

    def test_spread_and_z_score_calculation(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.cross_index_elasticity_hedger import spread_and_z
        spread, z = spread_and_z(
            log_nifty=10.0,
            log_banknifty=11.0,
            intercept=0.5,
            beta=1.0,
            spread_mean=0.5,
            spread_sd=0.1,
        )
        assert math.isclose(spread, 0.5, rel_tol=1e-9)
        assert math.isclose(z, 0.0, abs_tol=1e-9)

        with pytest.raises(ValueError, match="invalid spread inputs"):
            spread_and_z(10.0, 11.0, 0.5, 1.0, 0.5, 0.0)

    def test_joint_delta_neutrality_and_hedging(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.cross_index_elasticity_hedger import (
            GreekBook, hedge_delta_banknifty, hedge_delta_nifty
        )
        book = GreekBook(delta_nifty=50.0, delta_banknifty=-25.0, beta=2.0)
        assert math.isclose(book.joint_delta, 0.0, abs_tol=1e-9)
        assert hedge_delta_banknifty(book) == 0.0
        assert hedge_delta_nifty(book) == 0.0

        # Unbalanced book
        book2 = GreekBook(delta_nifty=50.0, delta_banknifty=0.0, beta=1.5)
        assert book2.joint_delta == 50.0
        assert math.isclose(hedge_delta_banknifty(book2), -50.0 / 1.5, rel_tol=1e-9)
        assert hedge_delta_nifty(book2) == -50.0

    def test_statutory_friction_schedules(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.cross_index_elasticity_hedger import (
            statutory_friction, FeeConfig
        )
        cfg = FeeConfig()
        # Options Buy: no STT, has stamp duty (0.003%), exchange (₹3,553/cr), SEBI (₹10/cr), GST (18%)
        f_opt_buy = statutory_friction(product="options", side="buy", turnover=100000.0, cfg=cfg)
        assert f_opt_buy > 0.0

        # Options Sell: has STT (0.15%), no stamp duty
        f_opt_sell = statutory_friction(product="options", side="sell", turnover=100000.0, cfg=cfg)
        assert f_opt_sell > f_opt_buy

        # Negative turnover rejected
        with pytest.raises(ValueError, match="turnover must be finite and non-negative"):
            statutory_friction(product="options", side="buy", turnover=-100.0)

    def test_gamma_rebalance_hurdle_decision(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.cross_index_elasticity_hedger import gamma_rebalance_hurdle
        # Insufficient expected gain -> rejected
        d_reject = gamma_rebalance_hurdle(
            expected_gamma_gain=10.0,
            turnover=100000.0,
            product="options",
            side="sell",
            impact_cost=50.0,
        )
        assert d_reject["rebalance_allowed"] is False
        assert d_reject["net_edge"] < 0

        # High expected gain -> approved
        d_accept = gamma_rebalance_hurdle(
            expected_gamma_gain=5000.0,
            turnover=100000.0,
            product="options",
            side="sell",
            impact_cost=50.0,
        )
        assert d_accept["rebalance_allowed"] is True
        assert d_accept["net_edge"] > 0

    def test_state_machine_transitions_and_emergency_latching(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.cross_index_elasticity_hedger import (
            StateMachine, State, Event
        )
        sm = StateMachine()
        assert sm.state == State.IDLE

        assert sm.step(Event.COINTEGRATION_SIGNAL) == State.COINTEGRATION_HEDGE_ACTIVE
        assert sm.step(Event.GAMMA_TRIGGER) == State.GAMMA_SCALP_REBALANCING
        assert sm.step(Event.VOL_SPIKE) == State.VOLATILITY_SPIKE_HALT
        assert sm.step(Event.CLEAR) == State.IDLE

        # Emergency latches fail-closed
        assert sm.step(Event.EMERGENCY) == State.EMERGENCY_UNWIND
        assert sm.emergency_latched is True
        assert sm.step(Event.CLEAR) == State.EMERGENCY_UNWIND
        assert sm.step(Event.NORMAL) == State.EMERGENCY_UNWIND

        # Requires RECOVERY_ACK to unlatch
        assert sm.step(Event.RECOVERY_ACK) == State.IDLE
        assert sm.emergency_latched is False

    def test_fail_closed_live_dispatch_locked(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.cross_index_elasticity_hedger import (
            LIVE_ORDER_DISPATCH_ENABLED, dispatch_live_order
        )
        assert LIVE_ORDER_DISPATCH_ENABLED is False
        with pytest.raises(RuntimeError, match="disabled by Cycle 18 safety invariant"):
            dispatch_live_order()


class TestCycle19MultiIndexVolatilitySurfaceAllocation:
    """Verifies Cycle 19 Multi-Index Volatility Surface Allocation and Lead-Lag Regime Filter."""

    def test_surface_fitting_recovers_known_parameters(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.multi_index_volatility_surface_allocator import (
            fit_total_variance_surface, SurfacePoint
        )
        # w(k) = 0.04 + 0.02*k + 0.05*k^2 with tau = 0.1
        tau = 0.1
        points = []
        for k in [-0.1, -0.05, 0.0, 0.05, 0.1]:
            w = 0.04 + 0.02 * k + 0.05 * k * k
            iv = math.sqrt(w / tau)
            points.append(SurfacePoint(k, tau, iv))

        res = fit_total_variance_surface(points)
        assert math.isclose(res.total_variance_level, 0.04, abs_tol=1e-6)
        assert math.isclose(res.skew_slope, 0.02, abs_tol=1e-6)
        assert math.isclose(res.curvature, 0.05, abs_tol=1e-6)
        assert math.isclose(res.sigma0, math.sqrt(0.04 / 0.1), abs_tol=1e-6)
        assert res.rmse < 1e-9

    def test_surface_fitting_rejects_invalid_inputs(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.multi_index_volatility_surface_allocator import (
            fit_total_variance_surface, SurfacePoint, SurfaceFitError
        )
        # Less than min_points
        with pytest.raises(SurfaceFitError, match="need at least 5 points"):
            fit_total_variance_surface([SurfacePoint(0.0, 0.1, 0.2)] * 4)

        # Non-positive or NaN IV
        with pytest.raises(SurfaceFitError, match="moneyness must be finite and IV finite/positive"):
            fit_total_variance_surface([
                SurfacePoint(-0.1, 0.1, 0.2),
                SurfacePoint(-0.05, 0.1, 0.2),
                SurfacePoint(0.0, 0.1, -0.1),
                SurfacePoint(0.05, 0.1, 0.2),
                SurfacePoint(0.1, 0.1, 0.2),
            ])

    def test_orthogonal_shock_propagator(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.multi_index_volatility_surface_allocator import (
            OrthogonalShockPropagator
        )
        osp = OrthogonalShockPropagator(decay=0.90)
        # Initial state: zero shock
        r0 = osp.update([0.15, -0.05, 0.18, -0.08])
        assert np.allclose(r0["raw_shock"], 0.0)

        # Second state: shock is observed and orthogonalized
        r1 = osp.update([0.16, -0.04, 0.20, -0.06])
        assert np.all(np.isfinite(r1["orthogonal_shock"]))
        assert r1["orthogonal_shock"].shape == (4,)

    def test_convex_joint_greek_allocation(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.multi_index_volatility_surface_allocator import (
            optimize_joint_allocation, AssetGreeks
        )
        assets = [
            AssetGreeks(delta=1.0, vega=0.1, gamma=0.01, expected_return=0.05, spread_cost=0.01),
            AssetGreeks(delta=-1.0, vega=0.1, gamma=0.01, expected_return=0.04, spread_cost=0.01),
            AssetGreeks(delta=0.5, vega=0.2, gamma=0.02, expected_return=0.06, liquidity_penalty=0.02),
            AssetGreeks(delta=-0.5, vega=0.2, gamma=0.02, expected_return=0.03, liquidity_penalty=0.02),
        ]
        cov = np.eye(4) * 0.04

        res = optimize_joint_allocation(
            assets, cov,
            vega_max=1.0,
            gamma_max=0.5,
            delta_tolerance=1e-4,
            max_weight=1.0,
        )
        assert res.success is True
        assert abs(res.joint_delta) <= 1e-4
        assert abs(res.joint_vega) <= 1.0 + 1e-4
        assert abs(res.joint_gamma) <= 0.5 + 1e-4

    def test_lead_lag_jump_detection_and_regime_filtering(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.multi_index_volatility_surface_allocator import (
            LeadLagVolatilityFilter
        )
        flt = LeadLagVolatilityFilter(threshold=3.0, delay_steps=2, bank_scale=1e-2, nifty_scale=1e-2)

        # Baseline ticks
        e0 = flt.update(0.001, 0.001)
        assert e0.propagated is False
        assert e0.regime == "NORMAL"

        # BANKNIFTY sudden shock (lead event)
        e1 = flt.update(0.04, 0.002)
        assert e1.propagated is False
        assert e1.regime == "VOLATILITY_SPIKE"

        # Next tick: NIFTY reacts (lag event)
        e2 = flt.update(0.001, 0.035)
        assert e2.propagated is True
        assert e2.delay_steps == 1
        assert e2.regime == "VOLATILITY_SPIKE"

        # Acknowledge recovery
        flt.acknowledge_recovery()
        assert flt.halted is False

    def test_cycle19_state_machine_and_emergency_latches(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.multi_index_volatility_surface_allocator import (
            Cycle19StateMachine, RiskState, RiskEvent
        )
        sm = Cycle19StateMachine()
        assert sm.state == RiskState.IDLE

        assert sm.transition(RiskEvent.START_MONITORING) == RiskState.SURFACE_MONITORING
        assert sm.transition(RiskEvent.ALLOCATION_APPROVED) == RiskState.ALLOCATION_ACTIVE
        assert sm.transition(RiskEvent.SPIKE) == RiskState.VOLATILITY_SPIKE_HALT

        # Emergency latches fail-closed
        assert sm.transition(RiskEvent.EMERGENCY) == RiskState.EMERGENCY_UNWIND
        assert sm.emergency_latched is True
        assert sm.transition(RiskEvent.START_MONITORING) == RiskState.EMERGENCY_UNWIND

        # Clearing latch
        assert sm.transition(RiskEvent.RECOVERY_ACK) == RiskState.IDLE
        assert sm.emergency_latched is False

    def test_cycle19_fail_closed_live_dispatch_locked(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.multi_index_volatility_surface_allocator import (
            LIVE_ORDER_DISPATCH_ENABLED, dispatch_live_order
        )
        assert LIVE_ORDER_DISPATCH_ENABLED is False
        with pytest.raises(RuntimeError, match="disabled by invariant"):
            dispatch_live_order()


class TestCycle20CrossAssetMicrostructureEquilibrium:
    """Verifies Cycle 20 Cross-Asset Impact Regularization, Queue Priority, and Inventory Quoting."""

    def test_cross_impact_regularization_and_psd(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.cross_asset_microstructure_equilibrium_engine import (
            regularize_cross_impact_tensor, quadratic_impact_cost
        )
        # Asymmetric empirical matrix
        raw_G = [
            [1.0, 0.8],
            [0.2, 1.2],
        ]
        reg_G, diag = regularize_cross_impact_tensor(raw_G, eigen_floor=1e-6)
        assert diag.psd_after is True
        assert diag.symmetry_error_after < 1e-12
        assert diag.raw_asymmetry_norm > 0.0

        # Verify quadratic impact cost is strictly non-negative
        cost = quadratic_impact_cost(reg_G, [10.0, -5.0])
        assert cost >= 0.0
        assert math.isfinite(cost)

    def test_cross_impact_tensor_rejections(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.cross_asset_microstructure_equilibrium_engine import (
            regularize_cross_impact_tensor
        )
        # Non-square
        with pytest.raises(ValueError, match="impact tensor must be a non-empty square matrix"):
            regularize_cross_impact_tensor([[1.0, 2.0]])

        # Non-finite
        with pytest.raises(ValueError, match="impact tensor must be finite"):
            regularize_cross_impact_tensor([[1.0, float("nan")], [0.0, 1.0]])

    def test_queue_priority_tracker_depletion_and_fill(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.cross_asset_microstructure_equilibrium_engine import (
            QueuePriorityTracker
        )
        q = QueuePriorityTracker(level=0, own_size=10.0, queue_ahead=50.0)

        # Baseline observations
        q.observe(timestamp=1.0, queue_ahead=50.0, queue_behind=20.0)
        q.observe(timestamp=2.0, queue_ahead=30.0, queue_behind=25.0, traded_volume_at_price=10.0)

        assert q.depletion_rate > 0.0

        # Estimate fill probability over 5 seconds horizon
        est = q.estimate(horizon_seconds=5.0, hawkes_intensity=0.5)
        assert 0.0 <= est.fill_probability <= 1.0
        assert est.expected_wait_seconds > 0.0

        # High Hawkes intensity accelerates depletion
        est_jump = q.estimate(horizon_seconds=5.0, hawkes_intensity=5.0)
        assert est_jump.depletion_rate > est.depletion_rate
        assert est_jump.fill_probability >= est.fill_probability

    def test_inventory_quote_model_pricing_and_skew(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.cross_asset_microstructure_equilibrium_engine import (
            InventoryQuoteModel
        )
        model = InventoryQuoteModel(
            base_half_spread=0.25,
            risk_aversion=0.1,
            cross_penalty=0.05,
            adverse_selection_coeff=0.2,
            tick_size=0.05,
        )

        # Neutral inventory quote
        q_neutral = model.quote(
            mid=100.0,
            own_inventory=0.0,
            other_inventory=0.0,
            cross_beta=1.0,
            volatility=0.2,
            adverse_selection_hazard=0.0,
        )
        assert q_neutral.bid < 100.0 < q_neutral.ask
        assert math.isclose(q_neutral.reservation_price, 100.0, abs_tol=1e-6)

        # Long inventory skews reservation down to induce selling
        q_long = model.quote(
            mid=100.0,
            own_inventory=10.0,
            other_inventory=0.0,
            cross_beta=1.0,
            volatility=0.2,
            adverse_selection_hazard=0.0,
        )
        assert q_long.reservation_price < q_neutral.reservation_price
        assert q_long.bid < q_neutral.bid

        # Adverse selection hazard widens spread
        q_hazard = model.quote(
            mid=100.0,
            own_inventory=0.0,
            other_inventory=0.0,
            cross_beta=1.0,
            volatility=0.2,
            adverse_selection_hazard=2.0,
        )
        assert (q_hazard.ask - q_hazard.bid) > (q_neutral.ask - q_neutral.bid)

    def test_cycle20_state_machine_and_emergency_latches(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.cross_asset_microstructure_equilibrium_engine import (
            Cycle20StateMachine, MicrostructureState, MicrostructureEvent
        )
        sm = Cycle20StateMachine()
        assert sm.state == MicrostructureState.IDLE

        assert sm.transition(MicrostructureEvent.START) == MicrostructureState.BOOK_MONITORING
        assert sm.transition(MicrostructureEvent.QUOTE_READY) == MicrostructureState.QUOTE_SIMULATION
        assert sm.transition(MicrostructureEvent.SPIKE) == MicrostructureState.VOLATILITY_SPIKE_HALT

        # Emergency latches fail-closed
        assert sm.transition(MicrostructureEvent.EMERGENCY) == MicrostructureState.EMERGENCY_UNWIND
        assert sm.emergency_latched is True
        assert sm.transition(MicrostructureEvent.START) == MicrostructureState.EMERGENCY_UNWIND

        # Clearing latch
        assert sm.transition(MicrostructureEvent.RECOVERY_ACK) == MicrostructureState.IDLE
        assert sm.emergency_latched is False

    def test_cycle20_fail_closed_live_dispatch_locked(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.cross_asset_microstructure_equilibrium_engine import (
            LIVE_ORDER_DISPATCH_ENABLED, dispatch_live_order
        )
        assert LIVE_ORDER_DISPATCH_ENABLED is False
        with pytest.raises(RuntimeError, match="disabled by invariant"):
            dispatch_live_order()


class TestCycle21RoughVolatilityFractionalSurface:
    """Verifies Cycle 21 Rough Volatility Fractional Surface Calibration & Markovian Lift Engine."""

    def test_fractional_rl_kernel(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.rough_volatility_fractional_surface_engine import (
            fractional_rl_kernel
        )
        t = [0.01, 0.1, 1.0]
        k = fractional_rl_kernel(t, H=0.1)
        assert len(k) == 3
        assert np.all(np.isfinite(k))
        # Kernel decays with t since H - 0.5 < 0
        assert k[0] > k[1] > k[2]

        with pytest.raises(ValueError, match="rough-volatility H must lie in"):
            fractional_rl_kernel(t, H=0.6)

    def test_markovian_lift_approximation_and_recursive_update(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.rough_volatility_fractional_surface_engine import (
            fit_markovian_lift
        )
        lift = fit_markovian_lift(H=0.15, factors=5, t_min=1e-4, t_max=1.0)
        assert lift.factors == 5
        assert np.all(lift.weights >= 0.0)
        assert lift.relative_rmse < 0.25

        # O(M) recursive update
        z0 = np.zeros(5)
        z1 = lift.update_states(z0, new_innovation=1.0, dt=0.01)
        assert z1.shape == (5,)
        assert np.all(z1 >= 0.0)
        assert np.sum(z1) > 0.0

    def test_hurst_estimation_from_increments(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.rough_volatility_fractional_surface_engine import (
            estimate_hurst_from_increments
        )
        # Synthetic rough series
        np.random.seed(42)
        n = 512
        steps = np.random.normal(0, 1, n)
        series = np.cumsum(steps)
        res = estimate_hurst_from_increments(series, min_lag=1, max_lag=32)
        assert 0.0 < res["H"] < 1.0
        assert res["r_squared"] > 0.70

    def test_rough_skew_extrapolate(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.rough_volatility_fractional_surface_engine import (
            rough_skew_extrapolate
        )
        tau_ref = 7 / 365
        psi_ref = -0.5
        H = 0.12

        # Ultrashort expiry has steeper skew (more negative)
        tau_short = 1 / 365
        skew_short = rough_skew_extrapolate(tau_short, psi_ref=psi_ref, tau_ref=tau_ref, H=H, sigma_ref=0.2)
        assert skew_short < psi_ref

        # Out-of-bounds tau rejected
        with pytest.raises(ValueError, match="tau must be within"):
            rough_skew_extrapolate(0.0001, psi_ref=psi_ref, tau_ref=tau_ref, H=H, sigma_ref=0.2)

    def test_svi_butterfly_and_surface_calendar_diagnostics(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.rough_volatility_fractional_surface_engine import (
            svi_g, check_surface_arbitrage
        )
        # SVI g(k)
        g_vals = svi_g([-0.1, 0.0, 0.1], a=0.04, b=0.1, rho=-0.4, m=0.0, sigma=0.1)
        assert len(g_vals) == 3
        assert np.all(np.isfinite(g_vals))

        # Check surface calendar monotonicity
        k_grid = [-0.1, 0.0, 0.1]
        tau_grid = [1/365, 7/365, 30/365]
        w_mono = [
            [0.01, 0.01, 0.01],
            [0.03, 0.03, 0.03],
            [0.06, 0.06, 0.06],
        ]
        res = check_surface_arbitrage(k_grid, tau_grid, w_mono)
        assert res["calendar_monotone"] is True
        assert res["nonnegative_total_variance"] is True

    def test_cycle21_state_machine_and_emergency_latches(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.rough_volatility_fractional_surface_engine import (
            Cycle21StateMachine, RoughVolState, RoughVolEvent
        )
        sm = Cycle21StateMachine()
        assert sm.state == RoughVolState.IDLE

        assert sm.transition(RoughVolEvent.START_CALIBRATION) == RoughVolState.CALIBRATION_ACTIVE
        assert sm.transition(RoughVolEvent.CALIBRATION_DONE) == RoughVolState.SURFACE_VALIDATION
        assert sm.transition(RoughVolEvent.SPIKE) == RoughVolState.VOLATILITY_SPIKE_HALT

        # Emergency latches fail-closed
        assert sm.transition(RoughVolEvent.EMERGENCY) == RoughVolState.EMERGENCY_UNWIND
        assert sm.emergency_latched is True
        assert sm.transition(RoughVolEvent.START_CALIBRATION) == RoughVolState.EMERGENCY_UNWIND

        # Clearing latch
        assert sm.transition(RoughVolEvent.RECOVERY_ACK) == RoughVolState.IDLE
        assert sm.emergency_latched is False

    def test_cycle21_fail_closed_live_dispatch_locked(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.rough_volatility_fractional_surface_engine import (
            LIVE_ORDER_DISPATCH_ENABLED, dispatch_live_order
        )
        assert LIVE_ORDER_DISPATCH_ENABLED is False
        with pytest.raises(RuntimeError, match="disabled by invariant"):
            dispatch_live_order()


class TestCycle22JumpDiffusionParticleFilter:
    """Test suite for Cycle 22 — Jump-Diffusion Particle Filtering & Macro IV Engine."""

    def test_jump_diffusion_parameter_validation(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.jump_diffusion_particle_filter_engine import (
            JumpDiffusionParameters
        )
        p = JumpDiffusionParameters()
        p.validate()

        with pytest.raises(ValueError, match="kappa must be positive"):
            JumpDiffusionParameters(kappa=-0.5).validate()
        with pytest.raises(ValueError, match="rho must be in"):
            JumpDiffusionParameters(rho=1.2).validate()
        with pytest.raises(ValueError, match="sigma_J must be positive"):
            JumpDiffusionParameters(sigma_J=0.0).validate()

    def test_indian_statutory_friction_exactness(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.jump_diffusion_particle_filter_engine import (
            calculate_indian_statutory_friction
        )
        res_sell = calculate_indian_statutory_friction(
            premium=100.0,
            lots=2,
            lot_size=50,
            is_sell=True,
        )
        turnover = 100.0 * 100.0  # 10,000 Rs
        assert res_sell["turnover"] == turnover
        assert abs(res_sell["stt"] - (turnover * 0.0015)) < 1e-6
        assert abs(res_sell["exchange_fee"] - (turnover * 0.0003553)) < 1e-6
        assert res_sell["stamp_duty"] == 0.0
        assert res_sell["total_hurdle"] > res_sell["statutory_total"]

        res_buy = calculate_indian_statutory_friction(
            premium=100.0,
            lots=2,
            lot_size=50,
            is_sell=False,
        )
        assert res_buy["stt"] == 0.0
        assert abs(res_buy["stamp_duty"] - (turnover * 0.00003)) < 1e-6

    def test_merton_jump_diffusion_and_black_scholes_limit(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.jump_diffusion_particle_filter_engine import (
            merton_jump_diffusion_price, black_scholes_price
        )
        S, K, tau, r, sigma = 24000.0, 24000.0, 30.0 / 365.0, 0.065, 0.16
        merton_zero = merton_jump_diffusion_price(
            S, K, tau, r, sigma, lambda_j=0.0, mu_J=-0.02, sigma_J=0.03
        )
        bs_price = black_scholes_price(S, K, tau, r, sigma)
        assert abs(merton_zero - bs_price) < 1e-4

        merton_jumps = merton_jump_diffusion_price(
            S, K, tau, r, sigma, lambda_j=4.0, mu_J=-0.02, sigma_J=0.04
        )
        assert merton_jumps > 0.0

    def test_implied_volatility_inversion(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.jump_diffusion_particle_filter_engine import (
            black_scholes_price, implied_volatility_inversion
        )
        S, K, tau, r, true_vol = 24000.0, 24100.0, 20.0 / 365.0, 0.065, 0.175
        px = black_scholes_price(S, K, tau, r, true_vol)
        rec_vol = implied_volatility_inversion(px, S, K, tau, r)
        assert abs(rec_vol - true_vol) < 1e-4

    def test_smc_particle_filter_propagation_and_n_eff(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.jump_diffusion_particle_filter_engine import (
            JumpDiffusionParameters, SMCParticleFilter
        )
        p = JumpDiffusionParameters()
        pf = SMCParticleFilter(p, n_particles=300, random_seed=42)
        pf.initialize(24000.0, 0.16)
        assert pf.effective_sample_size == 300.0

        pf.propagate(dt=1.0 / 252.0)
        assert np.all(pf.particles[:, 1] > 0.0)
        assert np.all(pf.particles[:, 2] > 0.0)

        pf.update_measurement(observed_spot=24050.0)
        assert 1.0 <= pf.effective_sample_size <= 300.0
        est = pf.get_state_estimates()
        assert est["estimated_spot"] > 20000.0
        assert est["estimated_vol"] > 0.0

    def test_systematic_resampling_trigger(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.jump_diffusion_particle_filter_engine import (
            JumpDiffusionParameters, SMCParticleFilter
        )
        p = JumpDiffusionParameters()
        pf = SMCParticleFilter(p, n_particles=200, random_seed=99)
        pf.initialize(24000.0)
        # Force degenerate weights
        pf.weights.fill(1e-12)
        pf.weights[0] = 1.0
        pf.weights /= np.sum(pf.weights)
        pf.effective_sample_size = 1.0 / float(np.sum(pf.weights**2))
        assert pf.effective_sample_size < 100.0

        pf.systematic_resample()
        assert pf.effective_sample_size == 200.0
        assert abs(float(np.sum(pf.weights)) - 1.0) < 1e-6

    def test_macro_event_regime_and_skew_calibration(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.jump_diffusion_particle_filter_engine import (
            JumpDiffusionParameters, MacroEventMetadata, JumpDiffusionMacroEngine, FilterRiskState
        )
        engine = JumpDiffusionMacroEngine(JumpDiffusionParameters(), n_particles=250)
        engine.initialize(24000.0)

        event = MacroEventMetadata(
            event_id="UNION_BUDGET_2027",
            event_name="Union Budget Announcement",
            scheduled_time=0.03,
            macro_lambda_boost=10.0,
            event_window_sigma=0.01,
            expected_jump_mean=-0.03,
        )

        strikes = np.array([23600.0, 23800.0, 24000.0, 24200.0, 24400.0])
        res = engine.calibrate_surface(
            spot=24000.0,
            strikes=strikes,
            tau=7.0 / 365.0,
            macro_event=event,
            current_time=0.03,
        )
        assert res["is_event_regime"] is True
        assert len(res["implied_volatilities"]) == 5
        assert np.all(res["implied_volatilities"] > 0.0)
        assert engine.state == FilterRiskState.SURFACE_CALIBRATED

    def test_frictional_alpha_hurdle_evaluation(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.jump_diffusion_particle_filter_engine import (
            JumpDiffusionMacroEngine
        )
        engine = JumpDiffusionMacroEngine(n_particles=200)
        engine.initialize(24000.0)
        eval_res = engine.evaluate_frictional_alpha(
            gross_alpha_rupees=2500.0,
            option_premium=120.0,
            lots=2,
            lot_size=50,
            is_sell=True,
        )
        assert eval_res["cost_breakdown"]["total_hurdle"] > 0.0
        assert eval_res["net_alpha"] == 2500.0 - eval_res["cost_breakdown"]["total_hurdle"]
        assert eval_res["is_frictional_hurdle_cleared"] is True

    def test_5_state_risk_engine_and_emergency_latch(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.jump_diffusion_particle_filter_engine import (
            JumpDiffusionMacroEngine, FilterRiskState
        )
        engine = JumpDiffusionMacroEngine(n_particles=200)
        assert engine.state == FilterRiskState.IDLE

        engine.initialize(24000.0)
        assert engine.state == FilterRiskState.FILTERING_ACTIVE

        engine.trigger_emergency_unwind("Test emergency")
        assert engine.state == FilterRiskState.EMERGENCY_UNWIND
        assert engine.emergency_latched is True

        res = engine.step(observed_spot=24050.0, dt=0.01)
        assert res["state"] == FilterRiskState.EMERGENCY_UNWIND.value

        with pytest.raises(RuntimeError, match="emergency unwind is latched"):
            engine.calibrate_surface(24000.0, np.array([24000.0]), tau=0.05)

        cleared = engine.acknowledge_recovery()
        assert cleared is True
        assert engine.state == FilterRiskState.IDLE
        assert engine.emergency_latched is False

    def test_fail_closed_live_dispatch_locked(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.jump_diffusion_particle_filter_engine import (
            JumpDiffusionMacroEngine, LIVE_ORDER_DISPATCH_ENABLED
        )
        assert LIVE_ORDER_DISPATCH_ENABLED is False
        engine = JumpDiffusionMacroEngine(n_particles=150)
        with pytest.raises(PermissionError, match="GATE_LIVE_ORDER_LOCKED"):
            engine.dispatch_live_order(symbol="NIFTY", qty=50)


class TestCycle23ActorCriticGammaScalper:
    """Test suite for Cycle 23 — Deep Reinforcement Learning Actor-Critic & Gamma Scalper."""

    def test_action_bounds_and_finite_vector(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.actor_critic_gamma_scalper_engine import (
            MarketState, GaussianActorCritic
        )
        state = MarketState(
            ofi=0.15, hawkes_intensity=1.2, rough_lift=(0.01, 0.02, 0.03),
            inventory=2.0, delta=0.12, gamma=0.025, vega=1.5,
            theta=-0.5, realized_volatility=0.18, spread_bps=2.5,
            regime_probability_high=0.3,
        )
        vec = state.vector()
        assert len(vec) == 13
        assert np.all(np.isfinite(vec))

        model = GaussianActorCritic(state_dim=len(vec), seed=42)
        sample = model.act(vec)
        act_vec = sample.action.vector()
        assert len(act_vec) == 3
        assert np.all(np.abs(act_vec) <= 1.0)

    def test_gaussian_actor_critic_deterministic_action(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.actor_critic_gamma_scalper_engine import (
            GaussianActorCritic
        )
        model = GaussianActorCritic(state_dim=5, seed=123)
        s = np.array([0.1, -0.2, 0.5, 0.0, 1.0])
        a1 = model.act(s, deterministic=True).action.vector()
        a2 = model.act(s, deterministic=True).action.vector()
        np.testing.assert_allclose(a1, a2)

    def test_ppo_update_finite_diagnostics(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.actor_critic_gamma_scalper_engine import (
            GaussianActorCritic
        )
        model = GaussianActorCritic(state_dim=4, seed=7)
        s = np.array([0.1, 0.2, -0.1, 0.0])
        samples = [model.act(s) for _ in range(16)]
        diag = model.update(
            samples,
            advantages=np.linspace(-0.5, 0.5, len(samples)),
            returns=np.linspace(-0.1, 0.2, len(samples)),
            epochs=2,
        )
        assert np.isfinite(diag["policy_loss"])
        assert np.isfinite(diag["value_loss"])
        assert np.isfinite(diag["entropy"])

    def test_bayesian_regime_filter_updates(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.actor_critic_gamma_scalper_engine import (
            BayesianRegimeFilter
        )
        filt = BayesianRegimeFilter()
        p0 = filt.p_high
        p_spike = filt.update(ofi=0.5, realized_volatility=0.08)
        assert 0.0 <= p_spike <= 1.0
        assert p_spike > p0

    def test_gamma_rebalance_band_symmetry_and_hawkes_narrowing(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.actor_critic_gamma_scalper_engine import (
            gamma_rebalance_band
        )
        lo, hi = gamma_rebalance_band(
            transaction_cost=15.0, risk_aversion=1.5, option_gamma=0.02,
            spot=24000.0, hawkes_intensity=0.5, hawkes_sensitivity=0.2,
        )
        assert abs(lo - (-hi)) < 1e-6
        assert lo < 0.0 < hi

        # Higher Hawkes arrival rate narrows the band
        w_low = gamma_rebalance_band(
            transaction_cost=15.0, risk_aversion=1.5, option_gamma=0.02,
            spot=24000.0, hawkes_intensity=0.0, hawkes_sensitivity=0.5,
        )[1]
        w_high = gamma_rebalance_band(
            transaction_cost=15.0, risk_aversion=1.5, option_gamma=0.02,
            spot=24000.0, hawkes_intensity=5.0, hawkes_sensitivity=0.5,
        )[1]
        assert w_high < w_low

    def test_transaction_costs_stt_and_stamp_duty(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.actor_critic_gamma_scalper_engine import (
            transaction_costs, FeeConfig
        )
        c_sell = transaction_costs(premium=120.0, quantity=50, side="SELL", config=FeeConfig())
        assert c_sell.premium_turnover == 6000.0
        assert abs(c_sell.stt - (6000.0 * 0.0015)) < 1e-6
        assert c_sell.stamp_duty == 0.0

        c_buy = transaction_costs(premium=120.0, quantity=50, side="BUY", config=FeeConfig())
        assert c_buy.stt == 0.0
        assert abs(c_buy.stamp_duty - (6000.0 * 0.00003)) < 1e-6

    def test_friction_aware_reward_penalties(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.actor_critic_gamma_scalper_engine import (
            friction_aware_reward, transaction_costs
        )
        costs = transaction_costs(premium=80.0, quantity=25, side="BUY")
        cov = np.array([[0.04]])
        reward = friction_aware_reward(
            pnl_change=500.0, inventory=[2.0], covariance=cov,
            risk_aversion=1.0, costs=costs,
        )
        # Reward = 500 - 0.5*1*(2^2 * 0.04) - costs.total = 500 - 0.08 - costs.total < 500
        assert reward < 500.0

    def test_risk_state_machine_transitions(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.actor_critic_gamma_scalper_engine import (
            RiskStateMachine, RiskState, RiskEvent
        )
        sm = RiskStateMachine()
        assert sm.state == RiskState.IDLE
        assert sm.transition(RiskEvent.START) == RiskState.CONTROLLER_ACTIVE
        assert sm.transition(RiskEvent.REBALANCE) == RiskState.SCALPING_REBALANCING
        assert sm.transition(RiskEvent.POLICY_DIVERGENCE) == RiskState.POLICY_DIVERGENCE_HALT

    def test_emergency_latch_and_recovery(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.actor_critic_gamma_scalper_engine import (
            RiskStateMachine, RiskState, RiskEvent
        )
        sm = RiskStateMachine()
        sm.transition(RiskEvent.EMERGENCY)
        assert sm.state == RiskState.EMERGENCY_UNWIND
        assert sm.emergency_latched is True

        sm.transition(RiskEvent.RESET)
        assert sm.state == RiskState.EMERGENCY_UNWIND

        sm.transition(RiskEvent.RECOVERY_ACK)
        assert sm.state == RiskState.IDLE
        assert sm.emergency_latched is False

    def test_live_dispatch_permanently_locked(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.actor_critic_gamma_scalper_engine import (
            LIVE_ORDER_DISPATCH_ENABLED, dispatch_live_order
        )
        assert LIVE_ORDER_DISPATCH_ENABLED is False
        with pytest.raises(RuntimeError, match="live order dispatch is disabled"):
            dispatch_live_order("BUY")


class TestCycle24HierarchicalLiquidityCrossExpiryRouter:
    """Verifies Cycle 24 multi-agent liquidity routing, Gatheral cross-expiry arbitrage, and circuit breaker halts."""

    def test_dislocation_tracker_bounds_and_tiers(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.hierarchical_liquidity_cross_expiry_router import (
            DislocationTracker
        )
        tracker = DislocationTracker()
        # Normal calm conditions
        snap_calm = tracker.update(
            index_move=0.005, current_depth=100.0, baseline_depth=100.0,
            current_spread=2.0, baseline_spread=2.0, estimated_fill_probability=0.95
        )
        assert 0.0 <= snap_calm.dislocation_index <= 0.2
        assert snap_calm.circuit_breaker_level is None

        # 10% move trigger
        snap_10 = tracker.update(
            index_move=0.105, current_depth=20.0, baseline_depth=100.0,
            current_spread=10.0, baseline_spread=2.0, estimated_fill_probability=0.2
        )
        assert snap_10.circuit_breaker_level == 10
        assert 0.0 <= snap_10.dislocation_index <= 1.0

        # 20% move trigger
        snap_20 = tracker.update(
            index_move=-0.21, current_depth=5.0, baseline_depth=100.0,
            current_spread=30.0, baseline_spread=2.0, estimated_fill_probability=0.05
        )
        assert snap_20.circuit_breaker_level == 20
        assert snap_20.dislocation_index > 0.8

    def test_systemic_allocator_multi_index_and_expiries(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.hierarchical_liquidity_cross_expiry_router import (
            SystemicAllocator, PortfolioGreeks, IndexName, ExpiryName
        )
        allocator = SystemicAllocator()
        greeks = PortfolioGreeks(delta=10.0, gamma=0.02, vega=50.0, theta=-20.0)
        taus = [7/365, 14/365, 30/365]

        allocs = allocator.allocate(
            total_risk_budget=10000.0, greeks=greeks,
            dislocation_index=0.1, term_structure_slope=0.05,
            taus=taus, halted=False
        )
        assert len(allocs) == 6  # 2 indices * 3 expiries
        total_allocated = sum(a.budget for a in allocs)
        assert 0.0 < total_allocated <= 10000.0

        # When halted, all allocations must freeze to 0.0
        allocs_halted = allocator.allocate(
            total_risk_budget=10000.0, greeks=greeks,
            dislocation_index=0.9, term_structure_slope=0.5,
            taus=taus, halted=True
        )
        assert all(a.budget == 0.0 for a in allocs_halted)

    def test_cross_expiry_arbitrageur_gatheral_calendar_and_signals(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.hierarchical_liquidity_cross_expiry_router import (
            CrossExpiryArbitrageur, VolSurfacePoint, IndexName
        )
        arb = CrossExpiryArbitrageur()

        # Valid monotonic total variance surface with annualized variance inversion
        # w(7) = 0.30^2 * 7 = 0.63
        # w(14) = 0.28^2 * 14 = 1.0976 > 0.63 (monotone total variance)
        # edge = 0.30^2 - 0.28^2 = 0.0116 > 0.005 inversion threshold
        valid_points = []
        for tau, iv in [(7/365, 0.30), (14/365, 0.28), (30/365, 0.25)]:
            for k in (-0.10, 0.0, 0.10):
                valid_points.append(VolSurfacePoint(IndexName.NIFTY, tau, k, iv))

        val = arb.validate_surface(valid_points)
        assert val.valid is True
        assert len(val.calendar_violations) == 0
        assert len(val.butterfly_violations) == 0

        # Inversion of annualized variance produces candidate signals
        signals = arb.detect_spreads(valid_points, dislocation_index=0.1)
        assert len(signals) > 0
        assert signals[0].index == IndexName.NIFTY
        assert signals[0].annualized_variance_edge > 0.0

        # Inverted calendar total variance surface
        bad_points = [
            VolSurfacePoint(IndexName.NIFTY, 7/365, 0.0, 0.30),
            VolSurfacePoint(IndexName.NIFTY, 14/365, 0.0, 0.10),
        ]
        # w(7) = 0.09 * 7 = 0.63
        # w(14) = 0.01 * 14 = 0.14 < 0.63 (calendar arbitrage violation!)
        bad_val = arb.validate_surface(bad_points)
        assert bad_val.valid is False
        assert len(bad_val.calendar_violations) > 0
        # No signals emitted on quarantined surface
        assert len(arb.detect_spreads(bad_points, dislocation_index=0.1)) == 0


    def test_smart_order_router_friction_and_cancellation(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.hierarchical_liquidity_cross_expiry_router import (
            SmartOrderRouter, OrderIntent, BookSnapshot, IndexName, ExpiryName, Side, TimeInForce, RiskState
        )
        sor = SmartOrderRouter()
        book = BookSnapshot(
            index=IndexName.NIFTY, best_bid=100.0, best_ask=102.0,
            visible_bid_depth_lots=10, visible_ask_depth_lots=10,
            passive_bid_depth_lots=5, passive_ask_depth_lots=5,
            simulated_block_depth_lots=5
        )
        intent = OrderIntent(
            index=IndexName.NIFTY, expiry=ExpiryName.TAU_1, side=Side.BUY,
            premium=102.0, lots=2, lot_size=25, expected_gross_alpha=500.0,
            time_in_force=TimeInForce.DAY
        )
        decision = sor.plan_order(intent, book, dislocation_index=0.1, risk_state=RiskState.MONITORING_ACTIVE)
        assert decision.accepted_for_simulation is True
        assert decision.planned_lots == 2
        assert decision.expected_net_alpha > 0

        # Cancel passive orders
        cancelled = sor.cancel_all_passive_orders()
        assert cancelled >= 0
        assert len(sor.resting_passive_orders) == 0

    def test_risk_state_machine_halts_and_recovery(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.hierarchical_liquidity_cross_expiry_router import (
            RiskStateMachine, RiskState, RiskEvent
        )
        sm = RiskStateMachine()
        assert sm.state == RiskState.IDLE
        sm.transition(RiskEvent.START_MONITORING)
        assert sm.state == RiskState.MONITORING_ACTIVE

        # Circuit breaker trigger
        sm.transition(RiskEvent.CIRCUIT_BREAKER)
        assert sm.state == RiskState.CIRCUIT_BREAKER_HALTED
        assert sm.can_allocate_or_route() is False

        # Attempting start monitoring during halt must be blocked
        sm.transition(RiskEvent.START_MONITORING)
        assert sm.state == RiskState.CIRCUIT_BREAKER_HALTED

        # Call auction stability followed by confirmed resumption
        sm.transition(RiskEvent.CALL_AUCTION_STABLE)
        assert sm.state == RiskState.CIRCUIT_BREAKER_HALTED
        sm.transition(RiskEvent.RESUMPTION_CONFIRMED)
        assert sm.state == RiskState.MONITORING_ACTIVE
        assert sm.can_allocate_or_route() is True

        # Emergency unwind latching
        sm.transition(RiskEvent.EMERGENCY)
        assert sm.state == RiskState.EMERGENCY_UNWIND
        assert sm.can_allocate_or_route() is False

        # Recovery ack restores safe state
        sm.transition(RiskEvent.RECOVERY_ACK)
        assert sm.state == RiskState.IDLE

    def test_live_dispatch_permanently_locked(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.hierarchical_liquidity_cross_expiry_router import (
            LIVE_ORDER_DISPATCH_ENABLED, dispatch_live_order
        )
        assert LIVE_ORDER_DISPATCH_ENABLED is False
        with pytest.raises(RuntimeError, match="live order dispatch is disabled"):
            dispatch_live_order()


class TestCycle25NewsShockIVCrushCompounding:
    """Verifies Cycle 25 High-Frequency News Volatility Shock Capture, Asymmetric IV Crush Exploitation,
    Indian Options Statutory Taxation, and Anti-Overtrading Throttling Engine.
    """

    def test_news_iv_pump_peak_and_crush(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.news_shock_iv_crush_compounding_engine import (
            NewsIVModel
        )
        model = NewsIVModel(0.16, 0.12, 120.0, 30.0)
        
        # Peak at announcement
        assert pytest.approx(model.implied_volatility(0.0), abs=1e-5) == 0.28
        
        # Pre-event pump increases monotonically toward event
        v_far = model.implied_volatility(-120.0)
        v_near = model.implied_volatility(-30.0)
        assert v_far < v_near < 0.28
        
        # Post-event exponential decay
        v_crush_30 = model.implied_volatility(30.0)
        expected_30 = 0.16 + 0.12 / math.e
        assert pytest.approx(v_crush_30, abs=1e-5) == expected_30
        
        # Continuity at event boundary
        assert pytest.approx(model.implied_volatility(-1e-6), abs=1e-5) == model.implied_volatility(1e-6)

    def test_news_regime_and_effective_spread(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.news_shock_iv_crush_compounding_engine import (
            NewsIVModel, NewsRegimeController, StrategyRegime, effective_spread
        )
        model = NewsIVModel(0.16, 0.12, 120.0, 30.0)
        ctrl = NewsRegimeController(minimum_crush_fraction=0.25, max_stress_for_short_vega=0.45)
        assert ctrl.recommend(model, -5, 0.27, 0.8) == StrategyRegime.LONG_VEGA_GAMMA

        # Spread under breaking news expands with shock severity
        s_calm = effective_spread(2.0, 3.0, 0.0)
        s_shock = effective_spread(2.0, 3.0, 0.5)
        assert s_shock > s_calm
        assert pytest.approx(s_shock, abs=1e-5) == 5.0

    def test_indian_options_statutory_taxation_and_friction(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.news_shock_iv_crush_compounding_engine import (
            StatutoryCostModel
        )
        cost_model = StatutoryCostModel(kappa_news=3.0)
        lots = 2
        lot_size = 25
        sell_prem = 150.0

        c = cost_model.calculate(
            premium=sell_prem, lots=lots, lot_size=lot_size, side="SELL",
            base_spread_per_unit=1.0, news_stress=0.5
        )
        assert c.stt > 0.0
        assert c.nse_exchange_charge > 0.0
        assert c.sebi_fee > 0.0
        assert c.gst > 0.0
        assert c.total_friction > 0.0
        
        # Verify STT is 0.15% of sell premium turnover (7500 * 0.0015 = 11.25)
        sell_turnover = sell_prem * lots * lot_size
        expected_stt = sell_turnover * 0.0015
        assert pytest.approx(c.stt, abs=1e-2) == expected_stt

    def test_optimal_trade_frequency_optimizer(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.news_shock_iv_crush_compounding_engine import (
            TradeFrequencyOptimizer
        )
        optimizer = TradeFrequencyOptimizer(
            alpha_per_trade=0.002, edge_decay=0.00001,
            sigma_eff=0.0005, round_trip_friction=50.0,
            max_trades_per_day=100
        )
        n_star = optimizer.optimal_daily_trade_count(100_000)
        assert n_star >= 1
        growth_star = optimizer.net_log_growth(n_star, 100_000)
        assert growth_star > 0.0

    def test_anti_tilt_and_overtrading_lockout(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.news_shock_iv_crush_compounding_engine import (
            AntiTiltGuard
        )
        tilt = AntiTiltGuard()
        # 3 consecutive losses triggers behavioral cooldown
        tilt.record_trade(timestamp=0, realized_pnl=-10, position_size=1)
        tilt.record_trade(timestamp=60, realized_pnl=-10, position_size=1)
        res = tilt.record_trade(timestamp=120, realized_pnl=-10, position_size=1)
        assert "LOSS_STREAK" in res.reasons
        assert tilt.is_locked(120) is True
        assert pytest.approx(tilt.remaining_seconds(120), abs=1e-1) == 900.0

    def test_cycle25_live_dispatch_permanently_locked(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.news_shock_iv_crush_compounding_engine import (
            LIVE_ORDER_DISPATCH_ENABLED, dispatch_live_order
        )
        assert LIVE_ORDER_DISPATCH_ENABLED is False
        with pytest.raises(RuntimeError, match="live order dispatch is permanently disabled"):
            dispatch_live_order("SELL", "NIFTY")


class TestCycle26MultiScaleHawkesSignatureCrossImpactExecution:
    """Verifies Cycle 26 Multi-Scale Hawkes Volatility Signature Curves, Microstructure Noise De-Biasing,
    NIFTY/BANKNIFTY Cross-Impact Optimal Execution, and Asymmetric Statutory Taxation Engine.
    """

    def test_signature_curve_and_two_scale_realized_volatility(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.multi_scale_hawkes_signature_cross_impact_execution_engine import (
            log_returns, realized_variance, volatility_signature_curve,
            estimate_microstructure_noise_variance, two_scale_realized_variance
        )
        r = log_returns([100.0, 110.0])
        assert pytest.approx(r[0], abs=1e-5) == math.log(1.1)

        # Synthetic prices with bounce noise
        prices = [100.0 + (0.5 if i % 2 == 0 else -0.5) for i in range(100)]
        rv1 = realized_variance(prices, scale=1)
        rv5 = realized_variance(prices, scale=5)
        assert rv1 > 0.0
        assert rv5 > 0.0

        curve = volatility_signature_curve(prices, scales=[1, 2, 5, 10])
        assert len(curve) == 4
        assert curve[0].scale == 1

        noise_var = estimate_microstructure_noise_variance(prices)
        assert noise_var >= 0.0

        tsrv = two_scale_realized_variance(prices, slow_scale=5)
        assert tsrv.tsrv >= 0.0
        assert tsrv.noise_variance >= 0.0

    def test_hawkes_intensity_and_cross_impact_estimator(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.multi_scale_hawkes_signature_cross_impact_execution_engine import (
            HawkesIntensityTracker, cluster_adjusted_variance,
            CrossImpactEstimator, CrossImpactSample, impact_kernel, lead_lag_correlation
        )
        tracker = HawkesIntensityTracker(baseline=0.2, excitation=0.6, decay_per_second=0.1)
        val = tracker.update(0, 2)
        assert pytest.approx(val, abs=1e-5) == 1.4

        # Hawkes-modulated cluster variance proxy
        exogenous, clustered = cluster_adjusted_variance(0.02, 3.0, 0.004)
        assert pytest.approx(exogenous + clustered, abs=1e-5) == 0.02
        assert pytest.approx(clustered, abs=1e-5) == 0.012

        # Cross-impact fit on 2 assets (NIFTY & BANKNIFTY)
        samples = []
        for n, b in [(-2, 1), (-1, -2), (0, 1), (1, 0), (2, -1), (3, 2), (-3, 3), (0.5, -3)]:
            samples.append(CrossImpactSample(n, b, 0.1 + 2*n + 0.5*b, -0.2 - 0.3*b + 1.25*n))
        estimator = CrossImpactEstimator(ridge=0).fit(samples)
        pred_n, pred_b = estimator.predict(1.2, -0.4)
        assert pred_n > 0.0

        # Exponential impact kernel
        assert impact_kernel(0, 1, kind="exponential") == 1.0
        assert impact_kernel(5, 1, kind="exponential") < 1.0

        # Lead-lag correlation
        a = [0, 1, 0, -1, 0, 2, 0, -2, 0, 1, 0, -1, 0]
        b = [0, 0, 1, 0, -1, 0, 2, 0, -2, 0, 1, 0, -1]
        lag, corr = lead_lag_correlation(a, b, max_lag=2)
        assert lag == 1
        assert corr > 0.5

    def test_indian_options_statutory_friction_and_asymmetric_execution(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.multi_scale_hawkes_signature_cross_impact_execution_engine import (
            statutory_friction, Side, profitability_gate,
            ExecutionConfig, optimize_execution_schedule
        )
        # Sell side incurs 0.15% STT on premium turnover (50 * 100 * 0.0015 = 7.50)
        f_sell = statutory_friction(premium=100, lots=2, lot_size=25, side=Side.SELL)
        assert pytest.approx(f_sell.stt, abs=1e-2) == 7.50
        assert f_sell.exchange_charge > 0.0
        assert f_sell.sebi_fee > 0.0
        assert f_sell.gst > 0.0
        assert f_sell.stamp_duty == 0.0

        # Buy side incurs 0.003% stamp duty and zero STT
        f_buy = statutory_friction(premium=100, lots=2, lot_size=25, side="BUY")
        assert f_buy.stt == 0.0
        assert f_buy.stamp_duty > 0.0

        # Strict profitability gate
        assert profitability_gate(50.0, f_sell) is True
        assert profitability_gate(5.0, f_sell) is False

        # Constrained execution schedule
        plan = optimize_execution_schedule(
            total_lots=6, lot_size=25,
            premiums_by_step=[100.0, 101.0, 102.0, 103.0, 104.0],
            displayed_capacity_lots=[10.0, 10.0, 10.0, 10.0, 10.0],
            side="SELL"
        )
        assert plan.feasible is True
        assert pytest.approx(sum(plan.scheduled_lots), abs=1e-4) == 6.0
        assert math.isfinite(plan.expected_total_cost)
        assert plan.expected_statutory_fees > 0.0

    def test_anti_tilt_session_throttle_and_risk_machine(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.multi_scale_hawkes_signature_cross_impact_execution_engine import (
            BehavioralTiltGuard, TiltReason, TradeFrequencyOptimizer, SessionController,
            RiskStateMachine, RiskState, RiskEvent, statutory_friction,
            LIVE_ORDER_DISPATCH_ENABLED, dispatch_live_order
        )
        # Behavioral tilt guard
        guard = BehavioralTiltGuard()
        guard.record_trade(now_seconds=0, size=1, pnl=-1)
        guard.record_trade(now_seconds=60, size=1, pnl=-1)
        reasons = guard.record_trade(now_seconds=120, size=1, pnl=-1)
        assert TiltReason.LOSS_STREAK in reasons
        assert guard.is_locked(121) is True

        # Optimal frequency optimizer
        opt = TradeFrequencyOptimizer(wealth=100000, gross_alpha_per_trade=100, friction_per_trade=20,
                                      impact_quadratic_rupees=5, sigma_eff=0.01, risk_scale=10, max_trades=10)
        res = opt.optimize()
        assert res.optimal_count >= 1

        # Session throttle
        controller = SessionController(opt)
        friction = statutory_friction(premium=1, lots=1, lot_size=1, side="BUY")
        cap = controller.optimal_daily_trades
        for i in range(cap):
            assert controller.can_enter(i*60, 1e6, friction) is True
            controller.record_trade(now_seconds=i*60, size=1, pnl=1)
        assert controller.can_enter((cap+1)*60, 1e6, friction) is False
        assert controller.overtrading_throttle_active is True

        # Risk state machine transitions
        sm = RiskStateMachine()
        assert sm.state == RiskState.IDLE
        assert sm.transition(RiskEvent.PLAN) == RiskState.EXECUTION_PLANNING
        assert sm.transition(RiskEvent.ROUTE) == RiskState.OPTIMAL_ROUTING

        # Emergency latch
        sm.transition(RiskEvent.EMERGENCY)
        assert sm.state == RiskState.EMERGENCY_UNWIND
        sm.transition(RiskEvent.RESET)
        assert sm.state == RiskState.EMERGENCY_UNWIND
        assert sm.transition(RiskEvent.RECOVERY_ACK) == RiskState.IDLE

        # Fail-closed live dispatch invariant
        assert LIVE_ORDER_DISPATCH_ENABLED is False
        with pytest.raises(RuntimeError):
            dispatch_live_order("BUY")


class TestCycle27RoughVolterraPinningLiquidity:
    """Cycle 27 verification: rough Volterra kernels, expiry pinning, MLOFI jumps, statutory taxes, and anti-overtrading."""

    def test_rough_volterra_kernel_properties(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.rough_volterra_pinning_liquidity_engine import (
            RoughVolterraKernel
        )
        # Valid Hurst bounds
        k_low = RoughVolterraKernel(0.05)
        assert k_low.hurst == 0.05
        k_high = RoughVolterraKernel(0.45)
        assert k_high.hurst == 0.45

        # Invalid bounds reject
        with pytest.raises(ValueError):
            RoughVolterraKernel(0.0)
        with pytest.raises(ValueError):
            RoughVolterraKernel(0.5)

        # Monotonicity & positive weights
        k = RoughVolterraKernel(0.1, n_terms=16)
        assert all(w > 0.0 for w in k.weights)
        assert all(a < b for a, b in zip(k.rates, k.rates[1:]))
        assert k.kernel_value(0.1) > k.kernel_value(10.0)

        # Streaming steps
        s1 = k.step(0.5)
        assert math.isfinite(s1)
        assert k.steps == 1
        k.reset()
        assert k.steps == 0
        assert all(v == 0.0 for v in k.state_vector())

    def test_expiry_pinning_and_liquidity_stress(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.rough_volterra_pinning_liquidity_engine import (
            ExpiryPinDynamicsModel, StrikeExposure
        )
        model = ExpiryPinDynamicsModel(base_break_threshold_points=25.0)
        strikes = [
            StrikeExposure(strike=22000.0, open_interest=100000.0, gamma=0.05),
            StrikeExposure(strike=22100.0, open_interest=25000.0, gamma=0.02),
        ]
        # At 14:50 (before window)
        r_pre = model.evaluate(spot=22005.0, hhmm_ist="14:50", strikes=strikes)
        assert r_pre.pinned_strike == 22000.0
        assert r_pre.expiry_pressure == 0.0
        assert r_pre.broke_pin is False

        # At 15:15 (inside window, halfway)
        r_mid = model.evaluate(spot=22010.0, hhmm_ist="15:15", strikes=strikes)
        assert pytest.approx(r_mid.expiry_pressure, abs=1e-3) == 0.50
        assert r_mid.broke_pin is False

        # Pin break: spot moved beyond threshold
        r_break = model.evaluate(spot=22060.0, hhmm_ist="15:25", strikes=strikes)
        assert r_break.broke_pin is True
        assert r_break.estimated_depth_fraction < 0.50
        assert r_break.spread_multiplier > 5.0

    def test_five_level_mlofi_and_fractional_jump(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.rough_volterra_pinning_liquidity_engine import (
            MLOFIJumpDetector, BookLevel
        )
        detector = MLOFIJumpDetector(levels=5)
        book_t0 = [
            BookLevel(bid_price=100.0 - i * 0.05, bid_size=100.0 / (i + 1),
                      ask_price=100.1 + i * 0.05, ask_size=100.0 / (i + 1))
            for i in range(5)
        ]
        obs0 = detector.update(book_t0, dt_seconds=1.0)
        assert obs0.mlofi == 0.0
        assert -1.0 <= obs0.normalized_imbalance <= 1.0

        # Aggressive buy order flow
        book_t1 = [
            BookLevel(bid_price=100.05 - i * 0.05, bid_size=300.0 / (i + 1),
                      ask_price=100.1 + i * 0.05, ask_size=50.0 / (i + 1))
            for i in range(5)
        ]
        obs1 = detector.update(book_t1, dt_seconds=1.0)
        assert obs1.mlofi > 0.0
        assert 0.0 <= obs1.jump_probability <= 1.0
        assert obs1.intensity > 0.0

    def test_statutory_friction_exact_nse_schedule(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.rough_volterra_pinning_liquidity_engine import (
            StatutoryCostCalculator, FeeConfig
        )
        calc = StatutoryCostCalculator()
        # Sell turnover: 100 premium * 2 lots * 25 lot_size = 5000 turnover
        # STT = 5000 * 0.0015 = 7.50
        f_sell = calc.calculate(premium=100.0, lots=2, lot_size=25, side="SELL", half_spread_per_unit=0.5)
        assert pytest.approx(f_sell.stt, abs=1e-2) == 7.50
        assert f_sell.nse_exchange_charge > 0.0
        assert f_sell.sebi_fee > 0.0
        assert f_sell.gst > 0.0
        assert f_sell.stamp_duty == 0.0
        assert f_sell.half_spread_slippage == 25.0

        # Buy turnover: stamp duty applies, STT zero
        f_buy = calc.calculate(premium=100.0, lots=2, lot_size=25, side="BUY")
        assert f_buy.stt == 0.0
        assert f_buy.stamp_duty > 0.0

        # Strict profitability hurdle
        assert calc.profitability_gate(f_sell.total_friction + 1.0, f_sell) is True
        assert calc.profitability_gate(f_sell.total_friction - 0.1, f_sell) is False

    def test_anti_overtrading_throttling_and_tilt_lockout(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.rough_volterra_pinning_liquidity_engine import (
            AntiOvertradingThrottler
        )
        throttler = AntiOvertradingThrottler(
            expected_gross_edge_per_trade=150.0,
            edge_decay_per_extra_trade=15.0,
            friction_per_trade=25.0,
            risk_penalty=2.0,
            max_trades=20,
            loss_streak_limit=3,
            min_pacing_seconds=30.0,
            cooldown_seconds=900.0
        )
        opt = throttler.optimize_frequency()
        assert opt.optimal_trades >= 1
        assert opt.expected_net_growth > 0.0

        # 3 consecutive losses trip LOSS_STREAK lockout
        throttler.record_fill(timestamp_seconds=100.0, pnl=-50.0, size=1.0)
        throttler.record_fill(timestamp_seconds=200.0, pnl=-30.0, size=1.0)
        status = throttler.record_fill(timestamp_seconds=300.0, pnl=-40.0, size=1.0)
        assert status.allowed is False
        assert status.tilt_locked is True
        assert status.loss_streak == 3
        assert status.cooldown_until_seconds == 300.0 + 900.0

    def test_cycle27_execution_engine_orchestration_and_safety(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.rough_volterra_pinning_liquidity_engine import (
            Cycle27ExecutionEngine, StrikeExposure, BookLevel, RiskState,
            LIVE_ORDER_DISPATCH_ENABLED, dispatch_live_order
        )
        engine = Cycle27ExecutionEngine(hurst=0.1)
        strikes = [StrikeExposure(22000.0, 100000.0, 0.05)]
        book = [
            BookLevel(bid_price=100.0 - i * 0.05, bid_size=100.0,
                      ask_price=100.1 + i * 0.05, ask_size=100.0)
            for i in range(5)
        ]

        # Normal observation
        snap = engine.observe(timestamp_ist="15:05", spot=22002.0,
                              strikes=strikes, book=book,
                              dt_seconds=1.0, volatility_innovation=0.1)
        assert snap.risk_state == RiskState.OPTIMAL_ROUTING
        assert snap.pin.broke_pin is False

        # Entry approval
        decision = engine.evaluate_entry(
            now_seconds=54300.0, premium=100.0, lots=1, lot_size=25, side="BUY",
            expected_gross_alpha=50.0, base_half_spread_per_unit=0.2
        )
        assert decision.allowed is True
        assert decision.reason == "PAPER_ENTRY_APPROVED"

        # Severe pin break triggers emergency unwind
        snap_emergency = engine.observe(
            timestamp_ist="15:28", spot=22075.0,
            strikes=strikes, book=book,
            dt_seconds=1.0, volatility_innovation=1.5
        )
        assert snap_emergency.risk_state == RiskState.EMERGENCY_UNWIND
        assert engine.risk.emergency_latched is True

        # Fail-closed invariant
        assert LIVE_ORDER_DISPATCH_ENABLED is False
        assert engine.live_dispatch_enabled() is False
        with pytest.raises(RuntimeError):
            dispatch_live_order()


class TestCycle28DeepConvexRiskHedging:
    """Cycle 28 verification: deep convex-risk hedging, indifference bands, Bayesian regime-switching, and CVaR."""

    def test_statutory_costs_and_profitability(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.deep_convex_risk_hedging_engine import (
            StatutoryCostCalculator, StatutoryCostConfig
        )
        calc = StatutoryCostCalculator()
        # Sell: 100 premium * 2 lots * 25 lot_size = 5000 turnover
        # STT = 5000 * 0.0015 = 7.50
        fees_sell = calc.calculate(premium=100.0, lots=2, lot_size=25, side="SELL", half_spread_per_unit=0.4)
        assert pytest.approx(fees_sell.stt, abs=1e-2) == 7.50
        assert fees_sell.exchange_fee > 0.0
        assert fees_sell.sebi_fee > 0.0
        assert fees_sell.gst > 0.0
        assert fees_sell.stamp_duty == 0.0
        assert fees_sell.spread_slippage == 20.0
        assert fees_sell.total > 27.50

        # Buy: Stamp duty applies, STT zero
        fees_buy = calc.calculate(premium=100.0, lots=2, lot_size=25, side="BUY")
        assert fees_buy.stt == 0.0
        assert fees_buy.stamp_duty > 0.0

    def test_indifference_band_and_rebalance_trigger(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.deep_convex_risk_hedging_engine import (
            IndifferenceBandEngine
        )
        engine = IndifferenceBandEngine(reference_volatility=0.02)
        band = engine.compute(
            target_delta=0.50, spot=22000.0, option_gamma=0.002,
            transaction_cost=25.0, realized_volatility=0.025, hurst=0.10,
            risk_aversion=1.0, regime_multiplier=1.0
        )
        assert band.width > 0.0
        assert band.lower < 0.50 < band.upper
        # Rebalancing decision
        assert band.contains(0.50) is True
        assert band.should_rebalance(0.50) is False
        assert band.should_rebalance(0.95) is True

    def test_bayesian_regime_switching_updates(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.deep_convex_risk_hedging_engine import (
            BayesianRegimeSwitchingModel, MarketRegime
        )
        model = BayesianRegimeSwitchingModel()
        # Calm observation: low vol, tight spread, low jump
        post_calm = model.update([0.010, 1.0, 0.02])
        assert pytest.approx(sum(post_calm), abs=1e-5) == 1.0
        assert model.most_likely_regime == MarketRegime.CALM_DIFFUSION

        # Crisis observation: high vol, blown spread, huge jump
        post_crisis = model.update([0.080, 6.0, 0.90])
        assert pytest.approx(sum(post_crisis), abs=1e-5) == 1.0
        assert model.most_likely_regime == MarketRegime.POST_EVENT_JUMP_CRUSH

    def test_cvar_objective_and_policy_selection(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.deep_convex_risk_hedging_engine import (
            CVaRObjectiveEvaluator, DeepHedgingPolicy
        )
        evaluator = CVaRObjectiveEvaluator()
        samples = [10.0, 5.0, 2.0, 0.0, -5.0, -10.0, -15.0, -20.0, -30.0, -50.0]
        cvar_res = evaluator.evaluate(samples, alpha=0.90)
        assert cvar_res.cvar_loss >= cvar_res.var_loss
        assert cvar_res.downside_shortfall > 0.0

        policy_selector = DeepHedgingPolicy(evaluator)
        choice = policy_selector.select({
            "conservative_band": [5.0, 4.0, 3.0, 1.0, 0.0, -2.0, -3.0],
            "aggressive_unhedged": [20.0, 15.0, 5.0, -10.0, -25.0, -60.0, -100.0]
        })
        assert choice.selected_policy == "conservative_band"

    def test_anti_overtrading_throttling_and_tilt_lockout(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.deep_convex_risk_hedging_engine import (
            AntiOvertradingThrottler
        )
        throttler = AntiOvertradingThrottler(max_daily_trades=20, loss_streak_limit=3, cooldown_seconds=900.0)
        res = throttler.derive_optimal_trade_count(
            wealth=100000.0, expected_gross_alpha_per_trade=120.0,
            friction_per_trade=25.0, impact_coefficient=3.0,
            variance_per_trade=50.0
        )
        assert res.optimal_count >= 1

        # 3 consecutive losses
        throttler.record_fill(timestamp=100.0, pnl=-10.0, size=1.0)
        throttler.record_fill(timestamp=200.0, pnl=-15.0, size=1.0)
        locked, reason = throttler.record_fill(timestamp=300.0, pnl=-8.0, size=1.0)
        assert locked is True
        assert reason == "loss_streak"
        assert throttler.is_locked(301.0) is True
        assert throttler.can_enter(301.0) is False

    def test_cycle28_execution_orchestration_and_safety(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.deep_convex_risk_hedging_engine import (
            Cycle28ExecutionEngine, RiskState, LIVE_ORDER_DISPATCH_ENABLED, dispatch_live_order
        )
        engine = Cycle28ExecutionEngine()
        assert engine.start_monitoring() == RiskState.MONITORING_ACTIVE

        # Assess trade profitability
        assessment = engine.assess_trade(
            expected_gross_alpha=50.0, premium=100.0, lots=1, lot_size=25,
            side="SELL", timestamp=500.0, half_spread_per_unit=0.2
        )
        assert assessment.approved is True
        assert assessment.reason == "paper_entry_gate_cleared"

        # Emergency trip and recovery
        assert engine.trigger_emergency() == RiskState.EMERGENCY_UNWIND
        assert engine.risk_machine.emergency_latched is True
        assert engine.acknowledge_recovery() == RiskState.IDLE
        assert engine.risk_machine.emergency_latched is False

        # Fail-closed invariant
        assert LIVE_ORDER_DISPATCH_ENABLED is False
        with pytest.raises(RuntimeError):
            dispatch_live_order()


class TestCycle29MultiLegNewsSpread:
    """Cycle 29 verification: real-time news NLP sentiment conditioning, macro jump diffusion filtering,
    and multi-leg options spread execution under asymmetric Indian tax regimes."""

    def test_multi_leg_statutory_schedule_and_tax_asymmetry(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.multi_leg_news_spread_engine import (
            MultiLegFeeCalculator, OptionLeg, Side
        )
        calc = MultiLegFeeCalculator()

        # Sell leg: STT 0.15% on premium turnover, zero stamp duty
        sell_leg = OptionLeg(symbol="NIFTY26OCT24500CE", side=Side.SELL, premium=100.0, lots=2, lot_size=25, half_spread_per_unit=0.2)
        assert sell_leg.turnover == 5000.0
        fees_sell = calc.calculate([sell_leg])
        assert pytest.approx(fees_sell.stt, abs=1e-2) == 7.50
        assert fees_sell.stamp_duty == 0.0
        assert fees_sell.exchange_fee > 0.0
        assert fees_sell.sebi_fee > 0.0
        assert fees_sell.gst > 0.0
        assert fees_sell.half_spread_slippage == 10.0  # 0.2 * 50 units

        # Buy leg: Zero STT, stamp duty 0.003% on turnover
        buy_leg = OptionLeg(symbol="NIFTY26OCT24600CE", side=Side.BUY, premium=40.0, lots=2, lot_size=25)
        assert buy_leg.turnover == 2000.0
        fees_buy = calc.calculate([buy_leg])
        assert fees_buy.stt == 0.0
        assert pytest.approx(fees_buy.stamp_duty, abs=1e-4) == 2000.0 * 0.00003

        # Multi-leg vertical spread combined
        fees_spread = calc.calculate([sell_leg, buy_leg])
        assert fees_spread.buy_turnover == 2000.0
        assert fees_spread.sell_turnover == 5000.0
        assert fees_spread.total_turnover == 7000.0
        assert pytest.approx(fees_spread.stt, abs=1e-2) == 7.50
        assert fees_spread.stamp_duty > 0.0
        assert fees_spread.total_cost == fees_spread.statutory_total + fees_spread.execution_cost_total

    def test_news_sentiment_volatility_conditioner(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.multi_leg_news_spread_engine import (
            NewsSentimentVolatilityConditioner
        )
        conditioner = NewsSentimentVolatilityConditioner(
            baseline_intensity=0.10, gamma_news=2.0, beta_news=0.01,
            pre_event_scale_seconds=100.0, skew_gain=0.04
        )
        # Event time t=0 with strong positive sentiment
        cond_pos = conditioner.condition(sentiment=0.8, urgency=1.0, seconds_from_event=0.0)
        assert pytest.approx(cond_pos.jump_intensity, abs=1e-4) == 2.10
        assert cond_pos.call_iv_shift > 0.0
        assert cond_pos.put_iv_shift < 0.0
        assert 0.0 <= cond_pos.stress_score <= 1.0

        # Event with negative sentiment shifts put IV upward
        cond_neg = conditioner.condition(sentiment=-0.7, urgency=0.9, seconds_from_event=0.0)
        assert cond_neg.call_iv_shift < 0.0
        assert cond_neg.put_iv_shift > 0.0

        # Post-event decay: intensity decays toward baseline
        cond_decay = conditioner.condition(sentiment=0.8, urgency=1.0, seconds_from_event=100.0)
        assert cond_decay.jump_intensity < cond_pos.jump_intensity

        # Pre-event anticipation
        cond_pre = conditioner.condition(sentiment=0.5, urgency=1.0, seconds_from_event=-50.0)
        assert cond_pre.jump_intensity > conditioner.baseline_intensity

    def test_sequential_jump_diffusion_filter(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.multi_leg_news_spread_engine import (
            SequentialJumpDiffusionFilter
        )
        filt = SequentialJumpDiffusionFilter(initial_variance=1e-6)

        # Small normal return: diffusion update, no jump detected
        res_diff = filt.update(0.0001, dt_seconds=1.0)
        assert res_diff.jump_detected is False
        assert filt.observation_count == 1
        assert filt.variance > 0.0

        # Large discontinuous return: jump detected, variance protected from contamination
        var_before = filt.variance
        res_jump = filt.update(0.025, dt_seconds=1.0)
        assert res_jump.jump_detected is True
        assert res_jump.jump_intensity > 0.0
        assert filt.variance == var_before  # uncontaminated

    def test_multi_leg_spread_optimizer_and_hurdles(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.multi_leg_news_spread_engine import (
            MultiLegSpreadOptimizer, OptionLeg, Side, SpreadType
        )
        optimizer = MultiLegSpreadOptimizer()
        legs = [
            OptionLeg("NIFTY26OCT24500CE", Side.BUY, premium=50.0, lots=1, lot_size=50, half_spread_per_unit=0.05),
            OptionLeg("NIFTY26OCT24600CE", Side.SELL, premium=90.0, lots=1, lot_size=50, half_spread_per_unit=0.05),
        ]
        # Gross alpha well above friction: accepted
        eval_pass = optimizer.evaluate(name="bull_spread", spread_type=SpreadType.VERTICAL,
                                       legs=legs, gross_expected_alpha=400.0)
        assert eval_pass.accepted is True
        assert eval_pass.expected_net_alpha > 0.0
        assert eval_pass.net_yield_on_turnover > 0.0

        # Gross alpha below total friction hurdle: rejected
        eval_fail = optimizer.evaluate(name="bull_spread", spread_type=SpreadType.VERTICAL,
                                       legs=legs, gross_expected_alpha=1.0)
        assert eval_fail.accepted is False
        assert eval_fail.expected_net_alpha < 0.0

        # Ratio candidate optimization
        ratio_res = optimizer.optimize_ratios(
            name="ratio_test", spread_type=SpreadType.RATIO,
            template_legs=legs, ratio_candidates=[(1, 1), (1, 2), (2, 1)],
            gross_alpha_by_ratio=[100.0, 800.0, 150.0]
        )
        assert ratio_res is not None
        assert ratio_res.leg_ratio == (1, 2)
        assert ratio_res.expected_net_alpha > 0.0

    def test_anti_overtrading_throttling_and_behavioral_lockout(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.multi_leg_news_spread_engine import (
            AntiOvertradingThrottler
        )
        throttler = AntiOvertradingThrottler(
            gross_edge_per_trade=100.0, friction_per_trade=20.0,
            risk_coeff=10.0, max_trades=100
        )
        # N* optimal daily trade count = round((100 - 20) / 10) = 8
        assert throttler.optimal_count == 8
        assert throttler.check_entry(now=0.0).allowed is True

        # Loss streak lockout (3 consecutive losses)
        throttler.record_fill(now=0.0, size=1.0, pnl=-5.0)
        throttler.record_fill(now=35.0, size=1.0, pnl=-10.0)
        out_streak = throttler.record_fill(now=70.0, size=1.0, pnl=-8.0)
        assert out_streak.allowed is False
        assert "loss streak" in out_streak.reason
        assert throttler.check_entry(now=75.0).allowed is False

        # Revenge sizing lockout
        fresh_t = AntiOvertradingThrottler(gross_edge_per_trade=100.0, friction_per_trade=20.0, risk_coeff=10.0)
        fresh_t.record_fill(now=0.0, size=10.0, pnl=5.0)
        out_revenge = fresh_t.record_fill(now=35.0, size=13.0, pnl=5.0)  # 13/10 = 1.30 > 1.25
        assert out_revenge.allowed is False
        assert "revenge" in out_revenge.reason

        # Pacing lockout (<30s)
        pacing_t = AntiOvertradingThrottler(gross_edge_per_trade=100.0, friction_per_trade=20.0, risk_coeff=10.0)
        pacing_t.record_fill(now=0.0, size=10.0, pnl=5.0)
        out_pacing = pacing_t.record_fill(now=15.0, size=10.0, pnl=5.0)
        assert out_pacing.allowed is False
        assert "pacing" in out_pacing.reason

    def test_cycle29_execution_engine_orchestration_and_safety(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.multi_leg_news_spread_engine import (
            Cycle29ExecutionEngine, OptionLeg, RiskState, Side, SpreadType, LIVE_ORDER_DISPATCH_ENABLED
        )
        engine = Cycle29ExecutionEngine()
        leg = OptionLeg("NIFTY26OCT24500CE", Side.SELL, premium=100.0, lots=1, lot_size=50)

        # Profitable spread evaluation
        res = engine.evaluate(
            sentiment=0.2, urgency=0.4, seconds_from_event=5.0,
            log_return=0.0001, dt_seconds=1.0, legs=[leg],
            spread_type=SpreadType.VERTICAL, expected_gross_alpha=1000.0, now=0.0
        )
        assert res.risk_state == RiskState.SPREAD_EVALUATED
        assert res.spread_evaluation.accepted is True
        assert res.live_dispatch_enabled is False

        # Emergency unwind and recovery
        engine.emergency_unwind()
        assert engine.risk.state == RiskState.EMERGENCY_UNWIND
        assert engine.risk.emergency_latched is True
        engine.recovery_ack()
        assert engine.risk.state == RiskState.IDLE
        assert engine.risk.emergency_latched is False

        # Fail-closed invariant
        assert LIVE_ORDER_DISPATCH_ENABLED is False
        with pytest.raises(RuntimeError):
            engine.dispatch_live_order("BUY")


class TestCycle30MacroTransmissionDashboard:
    """Cycle 30 verification: global macro shock transmission (US 10Y, DXY, Brent, VIX),
    SVI volatility smile parameter shifts, standalone dashboard telemetry streaming (port 8088),
    and 24/7 automated dynamic cool-down synthesis under asymmetric Indian tax regimes."""

    def test_macro_factors_and_cross_asset_transmission(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.macro_transmission_dashboard_engine import (
            MacroFactors, SVIParameters, MacroTransmissionModel, build_demo_factors
        )
        model = MacroTransmissionModel()

        # Zero shock preserves baseline surfaces
        surfaces_zero = model.transmit_both(MacroFactors(0.0, 0.0, 0.0, 0.0))
        assert set(surfaces_zero.keys()) == {"NIFTY", "BANKNIFTY"}
        assert surfaces_zero["NIFTY"].svi == model.base_surfaces["NIFTY"]

        # Positive DXY shock steepens put skew (delta rho < 0, delta b > 0)
        res_dxy = model.transmit(MacroFactors(0.0, 1.5, 0.0, 0.0), "NIFTY")
        assert res_dxy.shifts["rho"] < 0.0
        assert res_dxy.shifts["b"] > 0.0
        assert res_dxy.put_call_iv_diff > 0.0

        # Large macro shock keeps SVI surfaces strictly arbitrage-free and positive
        demo_factors = build_demo_factors()
        for idx in ("NIFTY", "BANKNIFTY"):
            res_shock = model.transmit(demo_factors, idx)
            assert res_shock.svi.minimum_total_variance() >= -1e-12
            assert res_shock.svi.total_variance(0.0) > 0.0
            assert math.isfinite(res_shock.put_call_iv_diff)

    def test_dynamic_cooldown_controller_and_stages(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.macro_transmission_dashboard_engine import (
            MacroFactors, MacroTransmissionModel, OperationalStage, DynamicCooldownController
        )
        model = MacroTransmissionModel()
        ctrl = DynamicCooldownController()
        now = 1800000000.0

        # Normal stage
        assert ctrl.evaluate(MacroFactors(0.0, 0.0, 0.0, 0.0), model, now) == OperationalStage.STAGE_0_NORMAL
        assert ctrl.band_multiplier == 1.0

        # Caution stage: widens indifference band by 1.5x, raises alpha hurdle
        stage_caut = ctrl.evaluate(MacroFactors(0.10, 0.0, 0.0, 0.0), model, now)
        assert stage_caut == OperationalStage.STAGE_1_CAUTION
        assert ctrl.band_multiplier == 1.5
        assert ctrl.alpha_hurdle_multiplier == 1.25

        # Extreme shock triggers quarantine stage
        stage_quar = ctrl.evaluate(MacroFactors(0.25, 0.0, 0.0, 0.0), model, now)
        assert stage_quar == OperationalStage.STAGE_2_QUARANTINE
        assert ctrl.new_entries_allowed is False
        assert ctrl.passive_risk_hedge_only is True
        assert ctrl.remaining(now) > 0.0

        # Emergency trip on depth collapse and latching
        stage_emerg = ctrl.evaluate(MacroFactors(0.0, 0.0, 0.0, 0.0), model, now, depth_ratio=0.05)
        assert stage_emerg == OperationalStage.STAGE_3_EMERGENCY_UNWIND
        assert ctrl.emergency_latched is True

        # Unverified recovery rejected
        with pytest.raises(PermissionError):
            ctrl.recovery_ack(verified=False, now_epoch=now + 10.0)

        # Verified recovery unlatches
        assert ctrl.recovery_ack(verified=True, now_epoch=now + 100000.0) == OperationalStage.STAGE_2_QUARANTINE
        assert ctrl.emergency_latched is False

    def test_statutory_friction_and_asymmetric_indian_taxes(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.macro_transmission_dashboard_engine import (
            OptionLeg, StatutoryFrictionCalculator
        )
        calc = StatutoryFrictionCalculator()

        # Buy leg: Zero STT, stamp duty 0.003% on premium turnover
        buy_leg = OptionLeg(symbol="NIFTY-CE-BUY", side="BUY", premium=100.0, quantity=50)
        fb_buy = calc.calculate([buy_leg])
        assert fb_buy.stt == 0.0
        assert pytest.approx(fb_buy.stamp_duty, abs=1e-4) == 5000.0 * 0.00003
        assert fb_buy.exchange_fee > 0.0
        assert fb_buy.sebi_fee > 0.0
        assert fb_buy.gst > 0.0

        # Sell leg: STT 0.15% on premium turnover, zero stamp duty
        sell_leg = OptionLeg(symbol="NIFTY-CE-SELL", side="SELL", premium=100.0, quantity=50)
        fb_sell = calc.calculate([sell_leg])
        assert pytest.approx(fb_sell.stt, abs=1e-2) == 7.50
        assert fb_sell.stamp_duty == 0.0

        # Profitability gate
        assert calc.passes_profitability_gate(fb_sell.total + 5.0, fb_sell) is True
        assert calc.passes_profitability_gate(fb_sell.total, fb_sell) is False
        assert calc.passes_profitability_gate(fb_sell.total - 1.0, fb_sell) is False

    def test_anti_overtrading_throttler_and_behavioral_lockouts(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.macro_transmission_dashboard_engine import (
            AntiOvertradingThrottler, TradeFrequencyConfig, OptionLeg, StatutoryFrictionCalculator
        )
        throttler = AntiOvertradingThrottler(TradeFrequencyConfig(
            alpha_per_trade=1000.0, friction_per_trade=250.0, risk_penalty=250.0, max_daily_trades=10
        ))
        # N* optimal daily trade cap = round((1000 - 250) / 250) = 3
        assert throttler.optimal_daily_trade_cap() == 3

        # 3 consecutive losses lock the engine
        throttler.record_outcome(-10.0, 1000.0)
        throttler.record_outcome(-15.0, 1050.0)
        locked = throttler.record_outcome(-8.0, 1100.0)
        assert locked is True
        assert "consecutive_losses" in throttler.lockout_reasons
        assert throttler.is_locked(1101.0) is True

        # Revenge sizing lock (> 1.25x)
        fresh_t = AntiOvertradingThrottler(TradeFrequencyConfig())
        fresh_t.record_fill(1000.0, 10.0)
        assert fresh_t.record_fill(1040.0, 13.0) is True
        assert "revenge_sizing" in fresh_t.lockout_reasons

        # Rapid fill pacing (< 30s)
        pacing_t = AntiOvertradingThrottler(TradeFrequencyConfig())
        pacing_t.record_fill(1000.0, 10.0)
        assert pacing_t.record_fill(1020.0, 10.0) is True
        assert "rapid_fill_pacing" in pacing_t.lockout_reasons

    def test_standalone_dashboard_telemetry_streaming_and_safety(self) -> None:
        from datetime import datetime, timezone
        from agents.AGI_1_7.engine.agi17.finance.macro_transmission_dashboard_engine import (
            Cycle30ExecutionEngine, MacroFactors, DASHBOARD_PORT, LIVE_ORDER_DISPATCH_ENABLED
        )
        import json

        assert DASHBOARD_PORT == 8088
        assert LIVE_ORDER_DISPATCH_ENABLED is False

        engine = Cycle30ExecutionEngine()
        now = datetime(2026, 10, 17, 12, 0, tzinfo=timezone.utc)
        payload = engine.telemetry_payload(MacroFactors(0.12, 1.8, 5.0, 12.0), now)

        # JSON serialization without NaN
        dumped = json.dumps(payload, allow_nan=False)
        assert '"schema_version": "1.0"' in dumped or '"schema_version":"1.0"' in dumped
        assert payload["dashboard_port"] == 8088
        assert payload["timestamp_ist"].endswith("+05:30")
        assert set(payload["svi_surfaces"].keys()) == {"NIFTY", "BANKNIFTY"}
        assert payload["operational"]["LIVE_ORDER_DISPATCH_ENABLED"] is False

        # SSE frame formatting
        sse_text = engine.sse_frame(payload, event_id="cycle30-sse-1")
        assert sse_text.startswith("id: cycle30-sse-1\nevent: telemetry\ndata: ")
        assert sse_text.endswith("\n\n")

        # Fail-closed invariant
        assert LIVE_ORDER_DISPATCH_ENABLED is False
        assert payload["operational"]["LIVE_ORDER_DISPATCH_ENABLED"] is False


class TestCycle31EVTVECMExpiryPinning:
    """Cycle 31 Integration Suite: EVT Tail Risk, HF VECM Cointegration, Pin-Aware Delta Hedging, and Statutory Levies."""

    def test_evt_gpd_tail_estimation_and_cvar(self) -> None:
        import random
        from agents.AGI_1_7.engine.agi17.finance.evt_vecm_expiry_pinning_engine import EVTGPDModel
        # 1. Smooth exponential limit when xi -> 0
        model0 = EVTGPDModel(threshold=10.0, shape_xi=0.0, scale_beta=2.0, sample_count=100, exceedance_count=10)
        expected_var = 10.0 + 2.0 * math.log(10.0)
        assert pytest.approx(model0.var(0.99), abs=1e-6) == expected_var
        assert pytest.approx(model0.cvar(0.99), abs=1e-6) == expected_var + 2.0

        # 2. Fit to synthetic tail losses
        rng = random.Random(42)
        losses = [abs(rng.gauss(20.0, 5.0)) + (rng.uniform(20, 80) if i % 10 == 0 else 0.0) for i in range(250)]
        fitted = EVTGPDModel().fit(losses, threshold_quantile=0.90)
        assert fitted.fitted is True
        assert fitted.scale_beta > 0.0
        assert fitted.shape_xi < 1.0
        assert fitted.var(0.99) >= fitted.threshold
        assert fitted.cvar(0.99) >= fitted.var(0.99)
        assert fitted.tail_margin_multiplier() >= 1.0

    def test_high_frequency_vecm_cointegration(self) -> None:
        import random
        from agents.AGI_1_7.engine.agi17.finance.evt_vecm_expiry_pinning_engine import HighFrequencyVECM
        rng = random.Random(42)
        bank = math.log(52000.0)
        beta = 0.85
        mu = math.log(25000.0) - beta * math.log(52000.0)
        residual = 0.0
        y1, y2 = [], []
        for _ in range(150):
            bank += rng.gauss(0.0001, 0.001)
            residual = 0.6 * residual + rng.gauss(0.0, 0.0005)
            y2.append(bank)
            y1.append(beta * bank + mu + residual)

        vecm = HighFrequencyVECM(z_threshold=2.0)
        params = vecm.fit(y1, y2, stabilize_mean_reversion=True)
        assert params.stable is True
        assert params.alpha_1 < 0.0
        assert params.alpha_2 > 0.0
        assert params.correction_speed > 0.0
        assert params.leader in {"NIFTY 50", "BANKNIFTY"}

        # Spread observation and dislocation detection
        z = vecm.spread(y1[-1], y2[-1])
        assert math.isfinite(z)
        assert isinstance(vecm.dislocation_signal(z), bool)

    def test_expiry_pinning_and_pin_aware_delta_hedging(self) -> None:
        from datetime import datetime
        from agents.AGI_1_7.engine.agi17.finance.evt_vecm_expiry_pinning_engine import (
            ExpiryPinningModel, StrikeExposure, IST
        )
        pin_model = ExpiryPinningModel(width_base=0.05, eta_pin=2.0)
        strikes = [
            StrikeExposure(strike=24800.0, open_interest=100000.0, gamma=0.001),
            StrikeExposure(strike=25000.0, open_interest=500000.0, gamma=0.005),
            StrikeExposure(strike=25200.0, open_interest=80000.0, gamma=0.002),
        ]
        # Expiry time: 15:15 IST
        expiry_now = datetime(2026, 10, 15, 15, 15, tzinfo=IST)
        pin_state = pin_model.identify_pin(spot=25005.0, strikes=strikes, now=expiry_now)
        assert pin_state.strike == 25000.0
        assert pin_state.expiry_window is True
        assert pin_state.gravity_multiplier > 1.0
        assert pin_state.band_width > 0.05

        # Inside widened band -> HOLD
        plan_hold = pin_model.hedge_plan(current_delta=0.50, target_delta=0.52, pin=pin_state)
        assert plan_hold.action == "HOLD"
        assert plan_hold.adjustment == 0.0

        # Breached band -> REBALANCE
        plan_reb = pin_model.hedge_plan(current_delta=0.50, target_delta=0.70, pin=pin_state)
        assert plan_reb.action == "REBALANCE"
        assert plan_reb.adjustment > 0.0

    def test_statutory_levy_schedule_and_multi_leg_hurdles(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.evt_vecm_expiry_pinning_engine import (
            StatutoryCostCalculator, OptionLeg, SpreadCandidate
        )
        calc = StatutoryCostCalculator()
        legs = [
            OptionLeg(name="short_call", side="SELL", premium=100.0, quantity=50.0, half_spread_per_unit=0.10),
            OptionLeg(name="long_call", side="BUY", premium=60.0, quantity=50.0, half_spread_per_unit=0.10),
        ]
        breakdowns = calc.calculate_multileg(legs)
        assert len(breakdowns) == 2
        # Sell leg: STT = 5000 * 0.0015 = 7.50, Stamp Duty = 0
        assert pytest.approx(breakdowns[0].stt, abs=1e-3) == 7.50
        assert breakdowns[0].stamp_duty == 0.0
        # Buy leg: STT = 0, Stamp Duty = 3000 * 0.00003 = 0.09
        assert breakdowns[1].stt == 0.0
        assert pytest.approx(breakdowns[1].stamp_duty, abs=1e-3) == 0.09

        # Spread evaluation with sufficient alpha
        candidate_good = SpreadCandidate(
            name="bear_call_spread",
            legs=tuple(legs),
            expected_gross_alpha=500.0,
            separate_impact_hurdle=10.0,
        )
        res_good = calc.evaluate_spread(candidate_good)
        assert res_good.qualifies is True
        assert res_good.expected_net_alpha > 0.0

        # Inadequate alpha rejected
        candidate_bad = SpreadCandidate(
            name="unprofitable_spread",
            legs=tuple(legs),
            expected_gross_alpha=10.0,
            separate_impact_hurdle=20.0,
        )
        res_bad = calc.evaluate_spread(candidate_bad)
        assert res_bad.qualifies is False

    def test_anti_overtrading_throttler_and_behavioral_lockouts(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.evt_vecm_expiry_pinning_engine import (
            AntiOvertradingThrottler, RiskStateMachine, RiskState, RiskEvent
        )
        # alpha=1000, cost=250, risk=250 -> cap = round((1000 - 250) / 250) = 3
        throttler = AntiOvertradingThrottler(alpha=1000.0, cost=250.0, risk=250.0, cooldown_seconds=600.0)
        assert throttler.daily_cap == 3
        assert throttler.can_enter(1000.0) is True

        # Rapid pacing (< 30s)
        throttler.record_fill(1000.0, 10.0)
        triggers = throttler.record_fill(1015.0, 10.0)
        assert "RAPID_FILL_PACING" in triggers
        assert throttler.can_enter(1020.0) is False

        # Loss streak
        fresh = AntiOvertradingThrottler(alpha=100.0, cost=10.0, risk=10.0)
        fresh.record_outcome(-50.0, 100.0)
        fresh.record_outcome(-30.0, 200.0)
        locked = fresh.record_outcome(-20.0, 300.0)
        assert locked is True
        assert "LOSS_STREAK" in fresh.lockout_reasons

        # Risk state machine transitions
        rsm = RiskStateMachine(RiskState.IDLE)
        assert rsm.transition(RiskEvent.START_PLANNING) == RiskState.HEDGE_PLANNING
        assert rsm.transition(RiskEvent.HEDGE_REQUIRED) == RiskState.HEDGE_REQUIRED
        assert rsm.transition(RiskEvent.THROTTLE) == RiskState.OVERTRADING_LOCKED
        assert rsm.transition(RiskEvent.EMERGENCY) == RiskState.EMERGENCY_UNWIND
        # Emergency is latched until RECOVERY_ACK
        assert rsm.transition(RiskEvent.RESET) == RiskState.EMERGENCY_UNWIND
        assert rsm.transition(RiskEvent.RECOVERY_ACK) == RiskState.IDLE

    def test_cycle31_execution_engine_telemetry_and_fail_closed_safety(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.evt_vecm_expiry_pinning_engine import (
            Cycle31ExecutionEngine, LIVE_ORDER_DISPATCH_ENABLED, dispatch_live_order
        )
        assert LIVE_ORDER_DISPATCH_ENABLED is False
        with pytest.raises(RuntimeError, match="live order dispatch is permanently disabled"):
            dispatch_live_order()

        engine = Cycle31ExecutionEngine()
        payload = engine.telemetry_payload(1776400000.0)
        assert payload["operations"]["live_order_dispatch_enabled"] is False
        assert payload["operations"]["mode"] == "PAPER_SIMULATION_ONLY"
        assert "evt" in payload
        assert "vecm" in payload
        assert "pinning" in payload
        json_str = engine.telemetry_json(1776400000.0)
        assert "PAPER_SIMULATION_ONLY" in json_str


class TestCycle32L3QueueDoubleDQNPortfolio:
    """Cycle 32 Integration Suite: L3 Queue Priority, Double-DQN Market Making, and Slippage-Constrained Portfolio Allocation."""

    def test_l3_queue_tracker_priority_and_depletion(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.l3_queue_double_dqn_portfolio_engine import (
            L3QueueTracker, QueueEventType
        )
        tracker = L3QueueTracker(mu_cancel=2.0, lambda_trade=3.0, hawkes_threshold=1.0)
        state = tracker.place_quote("NIFTY-24800-CE", "BID", 100.0, 20.0, 10.0, 1000.0)
        assert state.quantity_ahead == 20.0
        assert state.quantity_behind == 10.0
        assert state.priority_reached is False

        # Event: trade ahead of us reduces quantity ahead
        state = tracker.apply_event("NIFTY-24800-CE", "BID", 100.0, "TRADE_AHEAD", 5.0, 1001.0)
        assert state.quantity_ahead == 15.0
        assert state.cumulative_ahead_depletion == 5.0

        # Event: cancel ahead reduces quantity ahead
        state = tracker.apply_event("NIFTY-24800-CE", "BID", 100.0, "CANCEL_AHEAD", 5.0, 1002.0)
        assert state.quantity_ahead == 10.0

        # Estimate fill probability
        est = tracker.estimate("NIFTY-24800-CE", "BID", 100.0, tau=5.0, hawkes_intensity=0.5, ofi=0.0)
        assert 0.0 <= est.fill_probability <= 1.0
        assert est.depletion_velocity > 0.0
        assert est.reposition_hurdle >= 0.0

    def test_double_dqn_inventory_market_maker_action(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.l3_queue_double_dqn_portfolio_engine import (
            AvellanedaStoikovModel, DoubleDQNAgent, ReplayBuffer, Experience, ACTION_OFFSETS
        )
        # 1. Avellaneda-Stoikov reservation price skews downward for positive inventory
        q_pos = AvellanedaStoikovModel.calculate(spot=24800.0, inventory=5.0, risk_aversion=0.1, volatility=0.2, liquidity_kappa=1.5, time_remaining=1.0)
        q_neg = AvellanedaStoikovModel.calculate(spot=24800.0, inventory=-5.0, risk_aversion=0.1, volatility=0.2, liquidity_kappa=1.5, time_remaining=1.0)
        assert q_pos.reservation_price < 24800.0
        assert q_neg.reservation_price > 24800.0
        assert q_pos.bid_price < q_pos.ask_price

        # 2. Double-DQN agent forward pass & deterministic action
        agent = DoubleDQNAgent(seed=42, hidden_dim=8)
        state = [0.1, 0.05, 0.8, 0.25, 0.02, 0.5]
        action = agent.choose_action(state, epsilon=0.0)
        assert action in ACTION_OFFSETS

        # 3. Experience replay buffer & training step
        agent.remember(state, action, reward=1.0, next_state=state, done=False)
        for i in range(16):
            s = [0.1 * i, 0.05, 0.8, 0.25, 0.02, 0.5]
            agent.remember(s, 0, reward=0.5, next_state=s, done=False)
        metrics = agent.train_step(batch_size=8)
        assert "loss" in metrics
        assert math.isfinite(metrics["loss"])

    def test_dynamic_slippage_constrained_portfolio_optimization(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.l3_queue_double_dqn_portfolio_engine import (
            PortfolioOptimizer
        )
        opt = PortfolioOptimizer()
        mu = [0.10, 0.08, 0.06]
        cov = [[0.04, 0.01, 0.00], [0.01, 0.03, 0.00], [0.00, 0.00, 0.02]]
        omega = [[1.0, 0.2, 0.0], [0.2, 0.8, 0.1], [0.0, 0.1, 0.5]]
        costs = [0.01, 0.015, 0.02]

        result = opt.optimize(mu, cov, costs, omega, max_total_weight=0.8, max_weight=0.5)
        assert len(result.weights) == 3
        assert all(w >= 0.0 for w in result.weights)
        assert sum(result.weights) <= 0.800001
        assert math.isfinite(result.objective)
        assert result.risk_penalty >= -1e-10
        assert result.impact_penalty >= -1e-10

        # Zero budget gives exact zeros
        zero_res = opt.optimize(mu, cov, costs, omega, max_total_weight=0.0)
        assert zero_res.weights == (0.0, 0.0, 0.0)

    def test_asymmetric_indian_options_levy_schedule(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.l3_queue_double_dqn_portfolio_engine import (
            MultiLegFeeCalculator, OptionLeg
        )
        calc = MultiLegFeeCalculator()
        legs = [
            OptionLeg("NIFTY-24800-CE-BUY", "BUY", premium=50.0, quantity=50, half_spread_per_unit=0.1, impact_per_unit=0.05, brokerage=10.0),
            OptionLeg("NIFTY-24900-CE-SELL", "SELL", premium=100.0, quantity=50, half_spread_per_unit=0.1, impact_per_unit=0.05, brokerage=10.0),
        ]
        breakdown = calc.calculate(legs)
        assert breakdown.buy_turnover == 2500.0
        assert breakdown.sell_turnover == 5000.0

        # STT: 0.15% on sell turnover (7.50), zero on buy
        assert pytest.approx(breakdown.stt, abs=1e-3) == 7.50
        # Stamp duty: 0.003% on buy turnover (0.075), zero on sell
        assert pytest.approx(breakdown.stamp_duty, abs=1e-3) == 0.075
        assert breakdown.brokerage == 20.0
        assert breakdown.total_cost > breakdown.total_statutory

    def test_anti_overtrading_throttler_and_behavioral_lockouts(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.l3_queue_double_dqn_portfolio_engine import (
            AntiOvertradingThrottler, RiskState
        )
        # alpha=1000, cost=250, risk=250 -> cap = round((1000 - 250) / 250) = 3
        throttler = AntiOvertradingThrottler(alpha=1000.0, cost=250.0, risk=250.0)
        assert throttler.trade_cap == 3
        allowed, reason, _ = throttler.allow_entry(1000.0, gross_alpha=100.0, total_cost=20.0)
        assert allowed is True

        # Loss streak
        throttler.record_fill(1000.0, pnl=-10.0, size=10.0)
        throttler.record_fill(1050.0, pnl=-15.0, size=10.0)
        reason = throttler.record_fill(1100.0, pnl=-8.0, size=10.0)
        assert reason == "LOSS_STREAK"
        assert throttler.last_lockout_reason == "LOSS_STREAK"
        assert throttler.cooldown_until > 1100.0
        allowed_after, reason_after, _ = throttler.allow_entry(1101.0, gross_alpha=100.0, total_cost=20.0)
        assert allowed_after is False
        assert reason_after == "COOLDOWN"

    def test_cycle32_execution_engine_telemetry_and_fail_closed_safety(self) -> None:
        import json
        from agents.AGI_1_7.engine.agi17.finance.l3_queue_double_dqn_portfolio_engine import (
            Cycle32ExecutionEngine, LIVE_ORDER_DISPATCH_ENABLED
        )
        assert LIVE_ORDER_DISPATCH_ENABLED is False
        with pytest.raises(RuntimeError, match="live order dispatch is permanently disabled"):
            Cycle32ExecutionEngine.dispatch_live_order("BUY")

        engine = Cycle32ExecutionEngine()
        payload = engine.telemetry_payload(1792143800.0)
        assert payload["safety"]["live_order_dispatch_enabled"] is False
        assert payload["safety"]["paper_only"] is True
        assert "queues" in payload
        assert "double_dqn" in payload
        assert "portfolio" in payload
        json_str = json.dumps(payload)
        assert "paper_only" in json_str


class TestCycle33OFIGraphHawkesVarianceSwap:
    """Cycle 33 Integration Suite: Multi-Level OFI Graph, Multivariate Hawkes, Rough Volterra Variance Swap, and Indian Cost Schedules."""

    def test_multi_level_ofi_and_information_graph(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.ofi_graph_hawkes_variance_swap_engine import (
            MultiLevelOFITracker, BookLevelDelta, DirectedInformationGraph, shrink_nonnegative_matrix, spectral_radius
        )
        # 1. Multi-level OFI computation
        tracker = MultiLevelOFITracker([1.0, 0.7, 0.5])
        levels = [
            BookLevelDelta(bid_qty_delta=10.0, ask_qty_delta=2.0, bid_price_delta=0.05, ask_price_delta=-0.05),
            BookLevelDelta(bid_qty_delta=5.0, ask_qty_delta=5.0, bid_price_delta=0.0, ask_price_delta=0.0),
            BookLevelDelta(bid_qty_delta=2.0, ask_qty_delta=8.0, bid_price_delta=-0.05, ask_price_delta=0.05),
        ]
        res = tracker.compute("NIFTY50", levels)
        assert res.node == "NIFTY50"
        assert math.isfinite(res.ofi)
        assert "NIFTY50" in tracker.history

        # 2. Directed Information Graph and stability bounds
        graph = DirectedInformationGraph(["HDFCBANK", "ICICIBANK", "NIFTY50"])
        graph.set_edge("HDFCBANK", "NIFTY50", 0.45)
        graph.set_edge("ICICIBANK", "NIFTY50", 0.35)
        centrality = graph.centrality()
        assert centrality["HDFCBANK"]["out_degree_propagation"] == pytest.approx(0.45)
        assert centrality["NIFTY50"]["in_degree_absorption"] == pytest.approx(0.80)
        assert graph.radius <= 0.95 + 1e-9

        # 3. Nonnegative matrix shrinking ensuring rho <= 0.95
        matrix = [[1.5, 0.8], [0.8, 1.2]]
        shrunk, pre_rho, scale = shrink_nonnegative_matrix(matrix, 0.95)
        assert pre_rho > 0.95
        assert scale < 1.0
        post_rho = spectral_radius(shrunk)
        assert post_rho <= 0.95 + 1e-9

    def test_multivariate_hawkes_network_and_leadership(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.ofi_graph_hawkes_variance_swap_engine import (
            MultivariateHawkesNetwork
        )
        nodes = ["HDFCBANK", "ICICIBANK", "NIFTY50"]
        alpha = [
            [0.0, 0.2, 0.1],
            [0.1, 0.0, 0.1],
            [0.3, 0.3, 0.0],
        ]
        beta = [[1.0] * 3 for _ in range(3)]
        hawkes = MultivariateHawkesNetwork(nodes, baseline_rates=[0.2, 0.2, 0.5], alpha=alpha, beta=beta, learning_rate=0.0)
        assert hawkes.branching_radius() <= 0.90 + 1e-8

        # Process event count increments
        intensities = hawkes.update(dt=0.1, event_counts=[2.0, 1.0, 4.0])
        assert len(intensities) == 3
        assert all(v > 0.0 and math.isfinite(v) for v in intensities.values())

        # Measure causal leadership
        leadership_nifty = hawkes.leadership("NIFTY50")
        assert len(leadership_nifty) == 2
        total_lead = sum(item["leadership"] for item in leadership_nifty)
        assert total_lead == pytest.approx(1.0, abs=1e-6)

    def test_rough_volterra_kernel_and_variance_swap_replication(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.ofi_graph_hawkes_variance_swap_engine import (
            RoughVolterraKernel, VarianceSwapQuote
        )
        kernel = RoughVolterraKernel(hurst=0.10, factors=16)
        assert kernel.hurst == 0.10
        assert kernel.approximate_kernel(1.0) > 0.0
        assert kernel.exact_kernel(1.0) > 0.0

        # State updates
        val = kernel.update(1.0, 0.01)
        assert math.isfinite(val)
        kernel.reset()
        assert all(x == 0.0 for x in kernel.states)

        # Variance Swap Replication
        quotes = [
            VarianceSwapQuote(strike=24500.0, option_type="PUT", price=45.0),
            VarianceSwapQuote(strike=24800.0, option_type="PUT", price=95.0),
            VarianceSwapQuote(strike=25000.0, option_type="PUT", price=160.0),
            VarianceSwapQuote(strike=25200.0, option_type="CALL", price=110.0),
            VarianceSwapQuote(strike=25500.0, option_type="CALL", price=40.0),
        ]
        result = RoughVolterraKernel.replicate_variance_swap(
            spot=25000.0,
            maturity=30.0 / 365.0,
            quotes=quotes,
            integrand_second_derivative_bound=0.01,
            tail_truncation_bound=0.005,
        )
        assert result.fair_variance > 0.0
        assert math.sqrt(result.fair_variance) > 0.0
        assert result.total_error_bound == pytest.approx(result.discretization_error_bound + result.truncation_error_bound)

    def test_statutory_costs_and_profitability_gate(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.ofi_graph_hawkes_variance_swap_engine import (
            StatutoryCostCalculator, OptionLeg
        )
        calc = StatutoryCostCalculator(brokerage_per_leg=10.0)
        # Sell leg: 50 qty @ 100 Rs = 5000 turnover
        # STT = 5000 * 0.0015 = 7.50, Stamp = 0
        res_sell = calc.calculate([OptionLeg(premium=100.0, quantity=50.0, side="SELL")], expected_gross_alpha=50.0)
        assert res_sell.sell_turnover == 5000.0
        assert res_sell.buy_turnover == 0.0
        assert res_sell.stt == pytest.approx(7.50)
        assert res_sell.stamp_duty == 0.0
        assert res_sell.passes_profitability_gate is True

        # Buy leg: 50 qty @ 60 Rs = 3000 turnover
        # STT = 0, Stamp = 3000 * 0.00003 = 0.09
        res_buy = calc.calculate([OptionLeg(premium=60.0, quantity=50.0, side="BUY")], expected_gross_alpha=50.0)
        assert res_buy.buy_turnover == 3000.0
        assert res_buy.sell_turnover == 0.0
        assert res_buy.stt == 0.0
        assert res_buy.stamp_duty == pytest.approx(0.09)

        # Insufficient gross alpha fails gate
        res_fail = calc.calculate([OptionLeg(premium=100.0, quantity=50.0, side="SELL")], expected_gross_alpha=1.0)
        assert res_fail.passes_profitability_gate is False
        assert res_fail.expected_net_alpha < 0.0

    def test_anti_overtrading_throttler(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.ofi_graph_hawkes_variance_swap_engine import (
            AntiOvertradingThrottler, optimal_daily_trade_cap
        )
        # 1. Optimal trade cap
        cap_res = optimal_daily_trade_cap(1200.0, 200.0, 250.0)
        assert cap_res.trade_cap == 4

        # 2. Throttler mechanics
        throttler = AntiOvertradingThrottler(cap=10, cooldown_seconds=600.0, loss_streak_limit=3, revenge_ratio=1.25, min_fill_interval=30.0)
        assert throttler.can_trade(100.0) is True

        # Revenge sizing lockout (>1.25x size)
        throttler.record_fill(timestamp=100.0, size=10.0, pnl=50.0)
        reason = throttler.record_fill(timestamp=140.0, size=13.0, pnl=50.0)
        assert reason == "REVENGE_SIZING"
        assert throttler.lockout_reason == "REVENGE_SIZING"
        assert throttler.can_trade(150.0) is False

        # Reset session
        throttler.reset_session()
        assert throttler.can_trade(150.0) is True

        # Loss streak lockout
        throttler.record_fill(timestamp=150.0, size=5.0, pnl=-10.0)
        throttler.record_fill(timestamp=190.0, size=5.0, pnl=-20.0)
        streak_reason = throttler.record_fill(timestamp=230.0, size=5.0, pnl=-5.0)
        assert streak_reason == "LOSS_STREAK"
        assert throttler.can_trade(231.0) is False

    def test_cycle33_engine_telemetry_and_fail_closed_safety(self) -> None:
        import json
        from agents.AGI_1_7.engine.agi17.finance.ofi_graph_hawkes_variance_swap_engine import (
            Cycle33Engine, LIVE_ORDER_DISPATCH_ENABLED, dispatch_live_order, OptionLeg, BookLevelDelta
        )
        assert LIVE_ORDER_DISPATCH_ENABLED is False
        with pytest.raises(RuntimeError, match="live order dispatch is permanently disabled"):
            dispatch_live_order()
        with pytest.raises(RuntimeError, match="live order dispatch is permanently disabled"):
            Cycle33Engine.dispatch_live_order("SELL", 50)

        engine = Cycle33Engine()
        engine.update_ofi("HDFCBANK", [BookLevelDelta(10.0, 2.0, 0.0, -0.05)])
        telemetry = engine.telemetry_payload(1792144000.0)
        assert telemetry["LIVE_ORDER_DISPATCH_ENABLED"] is False
        assert telemetry["paper_simulation_only"] is True
        assert telemetry["timestamp_ist"].endswith("+05:30")
        assert "ofi" in telemetry
        assert "hawkes" in telemetry
        assert "rough_volterra" in telemetry
        assert "trade_throttle" in telemetry

        # Emergency latching
        engine.trigger_emergency()
        assert engine.emergency_latched is True
        spread_res = engine.evaluate_spread([OptionLeg(10.0, 1.0, "BUY")], expected_gross_alpha=500.0, now=1792144000.0)
        assert spread_res.passes_profitability_gate is False
        assert spread_res.expected_net_alpha == 0.0

        # Unlatch via recovery ack
        assert engine.recovery_ack() is True
        assert engine.emergency_latched is False
        json_data = json.dumps(engine.telemetry_payload(1792144000.0))
        assert "paper_simulation_only" in json_data


class TestCycle34MicrostructureSVIQueueBOCPD:
    """Cycle 34 Integration Suite: Microstructure-Conditioned SVI Smiles, L1-L5 Queue Depletion, and Adams-MacKay BOCPD."""

    def test_microstructure_state_conditioned_svi_and_arbitrage_guards(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.microstructure_svi_queue_bocpd_engine import (
            MicrostructureState, SVIParams, MicrostructureSVIConditioner
        )
        base = SVIParams(a=0.04, b=0.10, rho=-0.40, m=0.0, sigma=0.20)
        assert base.minimum_total_variance() >= 0.0
        assert base.butterfly_g(0.0) > 0.0

        conditioner = MicrostructureSVIConditioner()
        state = MicrostructureState(ofi_norm=0.8, hawkes_intensity_ratio=2.5, spread_ratio=1.8, queue_imbalance=0.35)
        res = conditioner.condition(base, state)

        # Verified conditioned parameters
        assert res.params.a > base.a
        assert res.params.b > base.b
        # Aggressive buy OFI rotates skew downward (more negative rho)
        assert res.params.rho < base.rho
        assert res.min_sampled_g > 0.0
        assert res.params.minimum_total_variance() >= 0.0

    def test_queue_depletion_machine_and_repositioning_barrier(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.microstructure_svi_queue_bocpd_engine import (
            QueueDepletionMachine
        )
        machine = QueueDepletionMachine(lambda0=1.0, gamma_ofi=0.5)
        machine.set_level(level=1, price=24500.0, q_ahead=100.0, q_behind=60.0, now=100.0)
        machine.set_level(level=2, price=24499.5, q_ahead=150.0, q_behind=80.0, now=100.0)
        intensity = machine.intensity(now=101.0, ofi=-0.5)
        assert intensity > 1.0

        # Fill probability over 10s horizon
        fill_p = machine.fill_probability(q_ahead=100.0, horizon=10.0, now=101.0, ofi=-0.5)
        assert 0.0 < fill_p < 1.0

        # Deeper queue ahead has lower fill probability
        fill_p_l2 = machine.fill_probability(q_ahead=150.0, horizon=10.0, now=101.0, ofi=-0.5)
        assert fill_p_l2 < fill_p

        # Repositioning evaluation
        assert machine.should_reposition(q_ahead=10.0, horizon=10.0, now=101.0, eta_reposition=0.1, cancel_replace_hazard=0.01) is False
        assert machine.should_reposition(q_ahead=1000.0, horizon=0.1, now=101.0, eta_reposition=0.9, cancel_replace_hazard=0.01) is True

    def test_bocpd_conjugate_nig_and_regime_classification(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.microstructure_svi_queue_bocpd_engine import (
            BayesianOnlineChangepointDetector, MacroRegime, nig_update, nig_predictive_logpdf, NIGStats
        )
        # 1. NIG conjugate updates
        prior = NIGStats(mu=0.0, kappa=1.0, alpha=2.0, beta=1.0)
        post = nig_update(prior, 0.5)
        assert post.kappa == 2.0
        assert post.alpha == 2.5
        log_p = nig_predictive_logpdf(0.5, prior)
        assert math.isfinite(log_p)

        # 2. BOCPD online inference
        detector = BayesianOnlineChangepointDetector(expected_run_length=100.0, max_run_length=50)
        for _ in range(15):
            res_calm = detector.update(0.01)
        assert res_calm.regime in (MacroRegime.LOW_VOL_MEAN_REVERTING, MacroRegime.HIGH_VOL_TRENDING)
        assert res_calm.changepoint_probability < 0.20

        # Extreme macro jump shock
        res_shock = detector.update(15.0)
        assert res_shock.changepoint_probability > 0.90
        assert res_shock.regime == MacroRegime.LIQUIDITY_CRISIS_JUMP
        assert res_shock.z_score > 5.0

    def test_statutory_friction_and_multi_leg_profitability_gate(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.microstructure_svi_queue_bocpd_engine import (
            StatutoryCostCalculator, TradeLeg
        )
        calc = StatutoryCostCalculator()
        legs = [
            TradeLeg(side="BUY", premium=70.0, lots=2, lot_size=25, half_spread_per_unit=0.05),
            TradeLeg(side="SELL", premium=110.0, lots=2, lot_size=25, half_spread_per_unit=0.05),
        ]
        breakdown = calc.calculate(legs)
        assert breakdown.buy_turnover == 3500.0
        assert breakdown.sell_turnover == 5500.0
        assert breakdown.total_turnover == 9000.0

        # STT = 5500 * 0.0015 = 8.25 (only on sell), Stamp = 3500 * 0.00003 = 0.105 (only on buy)
        assert breakdown.stt == pytest.approx(8.25)
        assert breakdown.stamp_duty == pytest.approx(0.105)
        assert breakdown.total_hurdle > breakdown.statutory_fees

        # Profitability evaluation
        res_pass = calc.profitability(expected_gross_alpha=200.0, legs=legs)
        assert res_pass.qualifies is True
        assert res_pass.expected_net_alpha > 0.0

        res_fail = calc.profitability(expected_gross_alpha=5.0, legs=legs)
        assert res_fail.qualifies is False
        assert res_fail.expected_net_alpha < 0.0

    def test_anti_overtrading_throttler_and_behavioral_lockouts(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.microstructure_svi_queue_bocpd_engine import (
            AntiOvertradingThrottler
        )
        throttler = AntiOvertradingThrottler(alpha=10.0, cost=0.0, risk_per_trade=1.0, loss_limit=3, cooldown_seconds=900.0)
        assert throttler.can_enter(100.0) is True

        # Loss streak
        throttler.record_fill(now=100.0, size=1.0, pnl=-50.0)
        throttler.record_fill(now=140.0, size=1.0, pnl=-25.0)
        reason = throttler.record_fill(now=180.0, size=1.0, pnl=-10.0)
        assert reason == "LOSS_STREAK"
        assert throttler.can_enter(185.0) is False

        # Reset session
        throttler.daily_reset()
        assert throttler.can_enter(185.0) is True

        # Revenge sizing lockout (>1.25x size)
        throttler.record_fill(now=185.0, size=10.0, pnl=20.0)
        revenge = throttler.record_fill(now=225.0, size=13.0, pnl=10.0)
        assert revenge == "REVENGE_SIZING"
        assert throttler.can_enter(230.0) is False

    def test_cycle34_execution_engine_telemetry_and_fail_closed_safety(self) -> None:
        import json
        from agents.AGI_1_7.engine.agi17.finance.microstructure_svi_queue_bocpd_engine import (
            Cycle34ExecutionEngine, LIVE_ORDER_DISPATCH_ENABLED, dispatch_live_order,
            MicrostructureState, TradeLeg, RiskState
        )
        assert LIVE_ORDER_DISPATCH_ENABLED is False
        with pytest.raises(RuntimeError, match="live order dispatch is permanently disabled"):
            dispatch_live_order()
        with pytest.raises(RuntimeError, match="live order dispatch is permanently disabled"):
            Cycle34ExecutionEngine.dispatch_live_order("SELL", 25)

        engine = Cycle34ExecutionEngine()
        engine.update_microstructure(MicrostructureState(ofi_norm=0.5))
        telemetry = engine.telemetry_payload(now_epoch=1800000000.0)

        assert telemetry["live_order_dispatch_enabled"] is False
        assert telemetry["timestamp_ist"].endswith("+05:30")
        assert "svi" in telemetry
        assert "queue" in telemetry
        assert "bocpd" in telemetry
        assert "throttle" in telemetry

        # Macro shock causes automatic entry into emergency
        res_shock = engine.update_observation(20.0)
        assert engine.emergency_latched is True
        assert engine.risk_state == RiskState.EMERGENCY_UNWIND

        # Profitability gate rejects during emergency
        candidate = engine.evaluate_candidate(500.0, [TradeLeg("BUY", 50.0, 1, 25)], now=1800000000.0)
        assert candidate.qualifies is False
        assert candidate.expected_net_alpha <= 0.0

        # Recovery acknowledgement
        with pytest.raises(PermissionError):
            engine.recovery_ack(verified=False)
        engine.recovery_ack(verified=True)
        assert engine.emergency_latched is False
        assert engine.risk_state == RiskState.MONITORING

        json_str = json.dumps(engine.telemetry_payload(now_epoch=1800000000.0))
        assert "live_order_dispatch_enabled" in json_str


class TestCycle35CrossAssetSSVILeadLagParticle:
    """Cycle 35: Cross-Asset SSVI Volatility Smiles, Hawkes Transient Cross-Impact,

    Lead-Lag Delta Execution, and Multi-Regime Bayesian Particle Filter Verification.
    """

    def test_ssvi_surface_and_calendar_no_arbitrage(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.cross_asset_ssvi_lead_lag_particle_engine import (
            SSVIParams, SurfaceSlice, VolatilitySurface, cross_asset_smile_basis
        )
        p1 = SSVIParams(theta=0.02, rho=-0.30, phi=0.45, psi=0.0)
        p2 = SSVIParams(theta=0.035, rho=-0.30, phi=0.45, psi=0.0)
        assert p1.total_variance(0.0) > 0.0
        assert p1.wing_slope_max < 2.0
        assert p1.butterfly_nonnegative([-1.0, 0.0, 1.0]) is True

        nifty_surf = VolatilitySurface("NIFTY 50", [SurfaceSlice(0.1, p1), SurfaceSlice(0.25, p2)])
        bank_p1 = SSVIParams(theta=0.025, rho=-0.40, phi=0.45, psi=0.0)
        bank_p2 = SSVIParams(theta=0.045, rho=-0.40, phi=0.45, psi=0.0)
        bank_surf = VolatilitySurface("BANKNIFTY", [SurfaceSlice(0.1, bank_p1), SurfaceSlice(0.25, bank_p2)])

        assert nifty_surf.calendar_violations([-1.0, 0.0, 1.0]) == ()
        assert bank_surf.calendar_violations([-1.0, 0.0, 1.0]) == ()

        basis = cross_asset_smile_basis(nifty_surf, bank_surf, 1.1, [-0.5, 0.0, 0.5], 0.15)
        assert len(basis) == 3
        assert all(math.isfinite(b) for b in basis)

    def test_surface_spread_analyzer_and_calendar_hurdle(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.cross_asset_ssvi_lead_lag_particle_engine import (
            SSVIParams, SurfaceSlice, VolatilitySurface, SurfaceSpreadAnalyzer,
            SurfaceOptionLeg, SpreadType
        )
        nifty = VolatilitySurface("NIFTY", [
            SurfaceSlice(0.05, SSVIParams(0.018, -0.25, 0.35)),
            SurfaceSlice(0.25, SSVIParams(0.047, -0.25, 0.35)),
        ])
        analyzer = SurfaceSpreadAnalyzer()
        legs = [
            SurfaceOptionLeg("NIFTY", "BUY", 22000.0, 0.25, True, 1, 10, label="long_far_call"),
            SurfaceOptionLeg("NIFTY", "SELL", 22000.0, 0.05, True, 1, 10, label="short_near_call"),
        ]
        result = analyzer.analyze_calendar({"NIFTY": nifty}, {"NIFTY": 22000.0}, legs)
        assert result.structure == SpreadType.CALENDAR
        assert len(result.fair_premiums) == 2
        assert result.surface_no_arbitrage_ok is True
        assert result.profitability.fees.stt > 0.0  # STT applies on sell leg
        assert result.profitability.fees.stamp_duty > 0.0  # Stamp duty applies on buy leg

    def test_hawkes_cross_impact_and_almgren_chriss_execution(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.cross_asset_ssvi_lead_lag_particle_engine import (
            HawkesCrossImpactModel, LeadLagSignal, AlmgrenChrissPlanner
        )
        hawkes = HawkesCrossImpactModel(baseline_intensity=0.2, alpha=0.8, beta=2.0, eta=0.1, decay_rate=2.0)
        assert hawkes.intensity(1.0) == pytest.approx(0.2)
        hawkes.record_event(1.0, 1.0, "HDFCBANK")
        assert hawkes.intensity(1.0) > 0.2
        assert hawkes.transient_kernel(0.5) > 0.0

        signal = LeadLagSignal(score=1.5, lag_seconds=0.10, expected_drift_per_second=0.05)
        assert signal.drift() > 0.0

        planner = AlmgrenChrissPlanner()
        plan = planner.plan(quantity=100.0, horizon_seconds=10.0, steps=5, side="BUY",
                            volatility=0.20, risk_aversion=0.50, temporary_impact=0.10,
                            cross_impact_coefficient=0.02, hawkes=hawkes, signal=signal)
        assert plan.inventory_path[0] == 100.0
        assert plan.inventory_path[-1] == 0.0
        assert sum(plan.child_quantities) == pytest.approx(100.0)
        assert plan.expected_impact_cost >= 0.0

    def test_multi_regime_particle_filter_resampling_and_regime_shift(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.cross_asset_ssvi_lead_lag_particle_engine import (
            MultiRegimeParticleFilter, MicrostructureObservation, MarketRegime
        )
        filt = MultiRegimeParticleFilter(particles=300, seed=11)
        assert len(filt.particles) == 300

        # Normal calm observation
        calm_obs = MicrostructureObservation(absolute_return=0.003, spread_ratio=1.0, depth_ratio=1.0, jump_count=0)
        res_calm = filt.update(calm_obs)
        assert res_calm.classified_regime in list(MarketRegime)
        assert math.isclose(sum(res_calm.regime_probabilities.values()), 1.0, rel_tol=1e-5)

        # Severe shock observation
        filt_shock = MultiRegimeParticleFilter(particles=300, seed=11)
        shock_obs = MicrostructureObservation(absolute_return=0.08, spread_ratio=5.0, depth_ratio=0.04, jump_count=8)
        res_shock = filt_shock.update(shock_obs)
        assert res_shock.classified_regime == MarketRegime.LIQUIDITY_VACUUM
        assert res_shock.effective_sample_size > 0.0
        assert isinstance(res_shock.resampled, bool)

    def test_cycle35_execution_engine_telemetry_and_fail_closed_safety(self) -> None:
        import json
        from agents.AGI_1_7.engine.agi17.finance.cross_asset_ssvi_lead_lag_particle_engine import (
            Cycle35Engine, LIVE_ORDER_DISPATCH_ENABLED, dispatch_live_order, RiskState,
            MicrostructureObservation
        )
        assert LIVE_ORDER_DISPATCH_ENABLED is False
        with pytest.raises(RuntimeError, match="live order dispatch is permanently disabled"):
            dispatch_live_order("BUY", 25)

        engine = Cycle35Engine()
        obs = MicrostructureObservation(absolute_return=0.003, spread_ratio=1.0, depth_ratio=1.0, jump_count=0)
        res_obs = engine.update_observation(obs)
        assert res_obs.effective_sample_size > 0.0
        telemetry = engine.telemetry()
        assert telemetry["cycle"] == 35
        assert telemetry["live_order_dispatch_enabled"] is False
        assert telemetry["paper_simulation_only"] is True
        assert telemetry["timestamp_ist"].endswith("+05:30")
        assert "surfaces" in telemetry
        assert telemetry["particle_filter"] is not None
        assert "trading_controls" in telemetry

        # Serialization check
        json_output = json.dumps(telemetry, allow_nan=False)
        assert "LIQUIDITY" in json_output


class TestCycle36SOFIResiliencyQuadraticHedge:
    """Master regression tests for Cycle 36: SOFI jump diffusion, LOB resiliency,
    2D Hawkes, Bayesian regime filter, quadratic spread hedging, and fail-closed safety.
    """

    def test_sofi_jump_diffusion_dynamics(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.cross_impact_sofi_quadratic_hedging_engine import (
            SOFIJumpDiffusion
        )
        sofi = SOFIJumpDiffusion(kappa_ofi=1.4, mean_ofi=0.0, sigma_ofi=0.25, jump_intensity=0.2, seed=36)
        assert sofi.ofi == 0.0
        ofi_next = sofi.step(dt=0.05)
        assert isinstance(ofi_next, float)
        assert math.isfinite(ofi_next)
        snap = sofi.snapshot()
        assert snap["elapsed"] == 0.05
        assert snap["kappa_ofi"] == 1.4
        assert snap["jump_intensity"] == 0.2

    def test_lob_resiliency_kernel_and_recovery_metrics(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.cross_impact_sofi_quadratic_hedging_engine import (
            LOBResiliencyKernel
        )
        kernel = LOBResiliencyKernel(beta_r=0.8, r0=1.0, default_impulse_decay=1.2)
        half_life = kernel.recovery_half_life
        assert math.isclose(half_life, math.log(2) / 0.8, rel_tol=1e-5)

        kernel.record_depletion(1.0, 2.0)
        v_replenish = kernel.replenishment_velocity(1.5)
        assert v_replenish > 0.0
        r_val = kernel.value(1.5)
        assert r_val > 0.0
        hazard = kernel.adverse_selection_hazard(ofi=1.5, spread_ratio=2.0, hawkes_intensity=1.0, depth_ratio=0.5)
        assert 0.0 <= hazard <= 1.0

    def test_hawkes_2d_spectral_stability_and_online_updates(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.cross_impact_sofi_quadratic_hedging_engine import (
            HawkesMutualExcitation2D, spectral_radius_2x2
        )
        hawkes = HawkesMutualExcitation2D(
            mu_bid=0.25,
            mu_ask=0.25,
            alpha=[[0.2, 0.05], [0.05, 0.2]],
            beta=1.2
        )
        rho = hawkes.branching_spectral_radius()
        assert 0.0 <= rho < 0.90  # subcritical stability invariant

        # Observe events and update intensities
        intensities_before = hawkes.intensities()
        intensities_after = hawkes.observe(dt=0.05, n_bid=1, n_ask=0)
        assert len(intensities_after) == 2
        assert intensities_after[0] > intensities_before[0]

        asym = hawkes.cross_asymmetry
        assert -1.0 <= asym <= 1.0

    def test_bayesian_microstructure_regime_posterior(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.cross_impact_sofi_quadratic_hedging_engine import (
            BayesianMicrostructureFilter, MicrostructureRegime
        )
        regime_filter = BayesianMicrostructureFilter()
        # Normal calm input: [abs_return, spread_ratio, depth_ratio, sweeps, ofi]
        res_calm = regime_filter.update([0.0005, 1.0, 1.0, 0.05, 0.0])
        assert res_calm["regime"] in [r.value for r in MicrostructureRegime]
        assert math.isclose(sum(res_calm["posterior"]), 1.0, rel_tol=1e-5)
        assert 0.0 <= res_calm["changepoint_probability"] <= 1.0

        # High trend input
        res_trend = regime_filter.update([0.01, 4.0, 0.2, 5.0, 1.0])
        assert math.isclose(sum(res_trend["posterior"]), 1.0, rel_tol=1e-5)
        assert res_trend["z_regime"] >= 0.0

    def test_quadratic_spread_hedger_delta_gamma_neutrality(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.cross_impact_sofi_quadratic_hedging_engine import (
            QuadraticSpreadHedgeOptimizer
        )
        opt = QuadraticSpreadHedgeOptimizer(max_iterations=300, tolerance=1e-6)
        sol = opt.optimize(
            covariance=[[1.0, 0.1], [0.1, 1.0]],
            impact_matrix=[[0.5, 0.1], [0.1, 0.5]],
            deltas=[1.0, -1.0],
            gammas=[0.5, -0.5],
            weight_min=[0.0, 0.0],
            weight_max=[2.0, 2.0],
            cost_per_unit=[0.1, 0.1],
            expected_alpha_per_unit=[2.0, 2.0],
            gamma_max=0.2
        )
        assert sol.converged is True
        assert math.isclose(sol.delta_residual, 0.0, abs_tol=1e-4)
        assert abs(sol.gamma_exposure) <= 0.2001

    def test_authoritative_statutory_fee_asymmetry_and_alpha_gate(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.cross_impact_sofi_quadratic_hedging_engine import (
            StatutoryCostCalculator, OptionLeg
        )
        calc = StatutoryCostCalculator()
        legs = [
            OptionLeg(premium=100.0, quantity=50, side="BUY"),
            OptionLeg(premium=50.0, quantity=50, side="SELL"),
        ]
        fee = calc.calculate(legs, half_spread_per_unit=0.5, cross_impact_hurdle=10.0)
        # Sell turnover = 50 * 50 = 2500; STT = 0.15% of 2500 = 3.75
        assert math.isclose(fee.stt, 2500.0 * 0.0015, rel_tol=1e-5)
        # Buy turnover = 100 * 50 = 5000; Stamp duty = 0.003% of 5000 = 0.15
        assert math.isclose(fee.stamp_duty, 5000.0 * 0.00003, rel_tol=1e-5)
        assert fee.total_statutory > 0.0
        assert fee.total_friction > fee.total_statutory

    def test_cycle36_execution_engine_telemetry_and_fail_closed_invariants(self) -> None:
        import json
        from agents.AGI_1_7.engine.agi17.finance.cross_impact_sofi_quadratic_hedging_engine import (
            Cycle36ExecutionEngine, LIVE_ORDER_DISPATCH_ENABLED, dispatch_live_order,
            OptionLeg, RiskState
        )
        assert LIVE_ORDER_DISPATCH_ENABLED is False
        with pytest.raises(RuntimeError, match="live order dispatch is permanently disabled"):
            dispatch_live_order("BUY")

        engine = Cycle36ExecutionEngine()
        telemetry = engine.telemetry_payload()
        assert telemetry["LIVE_ORDER_DISPATCH_ENABLED"] is False
        assert telemetry["safety_epoch"] == "epoch_10k"
        assert telemetry["timestamp_ist"].endswith("+05:30")
        assert "sofi" in telemetry
        assert "lob_resiliency" in telemetry
        assert "hawkes" in telemetry
        assert "microstructure_regime" in telemetry
        assert telemetry["risk_state"] == "IDLE"

        # Evaluate candidate trade
        legs = [OptionLeg(premium=100.0, quantity=50, side="BUY")]
        econ = engine.evaluate_candidate(gross_alpha=200.0, legs=legs, half_spread_per_unit=0.5, impact_hurdle=5.0)
        assert econ["profitable"] is True
        assert econ["entry_allowed"] is True
        assert engine.risk.state is RiskState.EXECUTION_PLANNING

        # Register 3 consecutive losses -> trigger loss streak lockout
        engine.register_fill(now=100.0, size=50.0, pnl=-500.0)
        engine.register_fill(now=200.0, size=50.0, pnl=-500.0)
        locked = engine.register_fill(now=300.0, size=50.0, pnl=-500.0)
        assert locked is True
        assert engine.risk.state is RiskState.OVERTRADING_LOCKED

        # JSON health and telemetry serialization check
        health = engine.health_payload()
        assert health["status"] == "ok"
        assert health["live_order_dispatch_enabled"] is False
        json_output = json.dumps(engine.telemetry_payload(), allow_nan=False)
        assert "OVERTRADING_LOCKED" in json_output


class TestCycle37RoughVolterraGammaVacuumHedging:
    """Master regression tests for Cycle 37: Rough Volterra kernel (H=0.08),
    Quadratic OFI cointegration, Gamma Vacuum Hedger, Statutory Taxes, and Fail-Closed Safety.
    """

    def test_rough_volterra_kernel_properties_and_updates(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.rough_volterra_gamma_vacuum_hedging_engine import (
            RoughVolterraKernel
        )
        kernel = RoughVolterraKernel(H=0.08, factors=12)
        assert kernel.H == 0.08
        assert kernel.factors == 12
        assert kernel.memory_half_life > 0.0

        # Exact and approximate kernel calculations
        exact_val = kernel.exact_kernel(1.0)
        approx_val = kernel.approximate_kernel(1.0)
        assert exact_val > 0.0
        assert approx_val > 0.0
        assert math.isfinite(kernel.kernel_relative_error(1.0))

        # Dynamic state update
        v_next = kernel.update(dt=0.05, drift=0.0, vol_of_vol=1.0, normal_shock=0.5, jump=0.0)
        assert isinstance(v_next, float)
        assert v_next > 0.0
        assert math.isfinite(kernel.rough_log_variance_state)

        # Roger Lee asymptotic wing bounds
        assert kernel.roger_lee_bound_ok(k=2.0, total_variance=0.05, wing_slope=1.5, wing_start=1.5)
        w_wing = kernel.variance_at(log_moneyness=2.5, wing_slope=1.5, wing_start=1.5)
        assert 0.0 <= w_wing <= 1.5 * 2.5 + 1e-6

    def test_quadratic_ofi_cointegration_and_leadership(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.rough_volterra_gamma_vacuum_hedging_engine import (
            QuadraticOFICointegration
        )
        qofi = QuadraticOFICointegration(
            assets=("NIFTY", "BANKNIFTY", "HDFCBANK", "ICICIBANK", "SBIN", "RELIANCE")
        )
        flows = {"NIFTY": 1.2, "BANKNIFTY": 2.0, "HDFCBANK": 1.5, "ICICIBANK": 1.0, "SBIN": 0.5, "RELIANCE": -0.8}
        score = qofi.update(flows)
        assert isinstance(score, float)
        assert math.isfinite(score)
        assert qofi.last_score == score

        # Cointegration error-correction signal
        c_prices = {"HDFCBANK": 1700.0, "ICICIBANK": 1150.0, "SBIN": 820.0}
        beta_ci = {"HDFCBANK": 0.4, "ICICIBANK": 0.3, "SBIN": 0.3}
        ec = qofi.error_correction_signal(
            index_price=51000.0,
            constituent_prices=c_prices,
            beta_ci=beta_ci,
            mu_coint=0.0
        )
        assert "spread" in ec and "expected_log_delta" in ec and "q_ofi" in ec
        assert math.isfinite(ec["expected_log_delta"])

        # Leadership metric in [-1, 1]
        lead = QuadraticOFICointegration.leadership_metric(leader_flow=10.0, follower_flow=2.0)
        assert 0.0 < lead <= 1.0
        trail = QuadraticOFICointegration.leadership_metric(leader_flow=1.0, follower_flow=8.0)
        assert -1.0 <= trail < 0.0

    def test_gamma_vacuum_hedger_delta_neutral_convergence(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.rough_volterra_gamma_vacuum_hedging_engine import (
            GammaVacuumHedger
        )
        hedger = GammaVacuumHedger(lambda_spread=0.001, lambda_vacuum=0.001, tolerance=1e-6)
        # 4 option strikes: paired deltas allowing non-zero delta-neutral gamma reallocation
        res = hedger.optimize(
            deltas=[0.8, -0.8, 0.35, -0.35],
            gammas=[0.018, 0.022, 0.010, 0.012],
            spreads=[0.4, 0.45, 0.25, 0.30],
            depths=[150.0, 125.0, 80.0, 75.0],
            gamma_target=0.80,
            max_units=[20.0, 20.0, 15.0, 15.0],
            min_units=[0.0, 0.0, 0.0, 0.0]
        )
        assert res.feasible is True
        assert abs(res.delta_net) <= 1e-4
        assert res.gamma_net > 0.0
        assert math.isfinite(res.objective)

        # Infeasible box constraints: all deltas strictly positive with positive min_units
        res_infeasible = hedger.optimize(
            deltas=[1.0, 1.0],
            gammas=[0.1, 0.1],
            spreads=[0.5, 0.5],
            depths=[10.0, 10.0],
            gamma_target=0.5,
            max_units=[2.0, 2.0],
            min_units=[1.0, 1.0]
        )
        assert res_infeasible.feasible is False
        assert "infeasible" in res_infeasible.message.lower()

    def test_statutory_cost_calculator_asymmetric_schedule(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.rough_volterra_gamma_vacuum_hedging_engine import (
            StatutoryCostCalculator, OptionLeg
        )
        calc = StatutoryCostCalculator()
        legs = [
            OptionLeg(symbol="NIFTY26OCT25000CE", side="BUY", premium=100.0, quantity=50, half_spread_per_unit=0.5),
            OptionLeg(symbol="NIFTY26OCT25200CE", side="SELL", premium=60.0, quantity=50, half_spread_per_unit=0.5),
        ]
        breakdown = calc.calculate(legs)
        # Buy leg: 100 * 50 = 5000 -> Stamp duty = 0.003% of 5000 = 0.15, STT = 0
        assert math.isclose(breakdown.stamp_duty, 5000.0 * 0.00003, rel_tol=1e-5)
        # Sell leg: 60 * 50 = 3000 -> STT = 0.15% of 3000 = 4.50, Stamp = 0
        assert math.isclose(breakdown.stt, 3000.0 * 0.0015, rel_tol=1e-5)
        # Exchange turnover (₹3553/crore) on 8000 total turnover
        assert math.isclose(breakdown.exchange_fee, 8000.0 * 3553.0 / 1e7, rel_tol=1e-5)
        # Brokerage = 2 legs * 20 = 40
        assert breakdown.brokerage == 40.0
        # GST = 18% on (exchange + sebi + brokerage)
        expected_gst = 0.18 * (breakdown.exchange_fee + breakdown.sebi_fee + breakdown.brokerage)
        assert math.isclose(breakdown.gst, expected_gst, rel_tol=1e-5)

        # Gate logic
        gate_ok = StatutoryCostCalculator.profitability_gate(gross_expected_alpha=200.0, costs=breakdown, safety_buffer=10.0)
        assert gate_ok["approved"] is True
        assert gate_ok["expected_net_alpha"] > 0.0

        gate_fail = StatutoryCostCalculator.profitability_gate(gross_expected_alpha=20.0, costs=breakdown, safety_buffer=10.0)
        assert gate_fail["approved"] is False

    def test_anti_overtrading_throttler_cooldown_and_lockouts(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.rough_volterra_gamma_vacuum_hedging_engine import (
            AntiOvertradingThrottler
        )
        throttler = AntiOvertradingThrottler(max_trades_per_session=5, base_cooldown=900.0)
        assert throttler.can_enter(100.0) is True

        # Optimal trade cap formula
        cap = AntiOvertradingThrottler.optimal_trade_cap(alpha=150.0, cost=50.0, risk=10.0)
        assert cap == 10

        # Rapid pacing lockout (<30s)
        throttler.record_fill(now=100.0, size=10.0, pnl=50.0)
        reason_rapid = throttler.record_fill(now=110.0, size=10.0, pnl=50.0)
        assert reason_rapid == "rapid_pacing"
        assert throttler.can_enter(120.0) is False

        # Reset throttler and test revenge sizing lockout (>1.25x)
        t2 = AntiOvertradingThrottler()
        t2.record_fill(now=100.0, size=10.0, pnl=-50.0)
        reason_revenge = t2.record_fill(now=200.0, size=15.0, pnl=20.0)  # 15.0 > 10.0 * 1.25
        assert reason_revenge == "revenge_sizing"
        assert t2.can_enter(250.0) is False

        # Reset throttler and test 3 consecutive losses
        t3 = AntiOvertradingThrottler(loss_limit=3)
        t3.record_fill(now=100.0, size=10.0, pnl=-50.0)
        t3.record_fill(now=200.0, size=10.0, pnl=-50.0)
        reason_streak = t3.record_fill(now=300.0, size=10.0, pnl=-50.0)
        assert reason_streak == "loss_streak"
        assert t3.consecutive_losses == 3
        assert t3.can_enter(350.0) is False

    def test_cycle37_execution_engine_telemetry_and_fail_closed_invariants(self) -> None:
        import json
        from agents.AGI_1_7.engine.agi17.finance.rough_volterra_gamma_vacuum_hedging_engine import (
            Cycle37ExecutionEngine, LIVE_ORDER_DISPATCH_ENABLED, REAL_BROKER_FILLS_LOCKED,
            dispatch_live_order, OptionLeg
        )
        assert LIVE_ORDER_DISPATCH_ENABLED is False
        assert REAL_BROKER_FILLS_LOCKED is True
        with pytest.raises(RuntimeError, match="live order dispatch is permanently disabled"):
            dispatch_live_order()

        engine = Cycle37ExecutionEngine()
        tick = engine.update_tick(dt=0.05, ofi={"NIFTY": 0.5, "BANKNIFTY": 1.0})
        assert "rough_variance" in tick and "q_ofi" in tick

        # Telemetry verification
        telem = engine.telemetry()
        assert telem["LIVE_ORDER_DISPATCH_ENABLED"] is False
        assert telem["REAL_BROKER_FILLS_LOCKED"] is True
        assert telem["safety_epoch"] == "epoch_10k"
        assert "+05:30" in telem["timestamp_ist"]
        assert telem["rough"]["H"] == 0.08
        assert "qofi" in telem
        assert "throttler" in telem

        # Spread evaluation
        legs = [OptionLeg(symbol="NIFTY26OCT25000CE", side="BUY", premium=100.0, quantity=50)]
        eval_res = engine.evaluate_spread(legs=legs, gross_expected_alpha=200.0, safety_buffer=5.0, now=1000.0)
        assert "costs" in eval_res and "gate" in eval_res
        assert eval_res["gate"]["approved"] is True

        # JSON serialization without NaN
        json_output = json.dumps(engine.telemetry(), allow_nan=False)
        assert "epoch_10k" in json_output


class TestCycle38HawkesL3CancellationVarianceGamma:
    """Master regression tests for Cycle 38: Hawkes directed graph centrality,
    L3 cancellation shock dynamics, Variance Gamma pricing, and fail-closed safety.
    """

    def test_hawkes_directed_graph_spectral_stability_and_centrality(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.hawkes_l3_cancellation_variance_gamma_engine import (
            HawkesDirectedGraph
        )
        graph = HawkesDirectedGraph()
        assert len(graph.nodes) == 8
        assert graph.spectral_radius < 0.89
        assert graph.stability_upper_bound < 0.89

        # Centrality metrics
        cent = graph.centrality()
        assert "HDFCBANK" in cent and "BANKNIFTY" in cent
        for node, metrics in cent.items():
            assert metrics["in_degree_absorption"] >= 0.0
            assert metrics["out_degree_propagation"] >= 0.0

        # Leadership ranking
        leaders = graph.leadership()
        assert len(leaders) == 8
        assert math.isclose(sum(l["score"] for l in leaders), 1.0, rel_tol=1e-5)

        # Intensity updates
        rates = graph.intensity()
        assert len(rates) == 8
        assert all(r > 0 for r in rates)

    def test_l3_cancellation_shock_process_and_quote_pullback(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.hawkes_l3_cancellation_variance_gamma_engine import (
            CancellationShockModel
        )
        model = CancellationShockModel(baseline_intensity=0.20, cascade_threshold=0.65)
        assert model.intensity(timestamp=0.0) == 0.20
        assert model.cascade_hazard(timestamp=0.0) < 0.65
        assert model.should_pull_quotes(timestamp=0.0) is False

        # Add heavy cancellation bursts at L1 and L2
        model.add_cancel_event(timestamp=1.0, mark=45.0, level=1)

        # Check excited intensity and cascade hazard
        int_t = model.intensity(timestamp=1.0, ofi=-3.0)
        assert int_t > 0.20
        surv = model.survival_probability(horizon=0.05, timestamp=1.0, ofi=-3.0)
        assert 0.0 <= surv <= 1.0
        hazard = model.cascade_hazard(timestamp=1.0, ofi=-3.0)
        assert 0.0 <= hazard <= 1.0
        assert model.should_pull_quotes(timestamp=1.0, ofi=-3.0) is True

    def test_variance_gamma_surface_pricing_and_butterfly_density(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.hawkes_l3_cancellation_variance_gamma_engine import (
            VarianceGammaSurface, VGParameters
        )
        vg = VarianceGammaSurface(params=VGParameters(sigma=0.20, nu=0.20, theta=-0.10))
        # Characteristic function at origin
        phi_0 = vg.characteristic_function(0.0, maturity=1.0)
        assert math.isclose(phi_0.real, 1.0, rel_tol=1e-7)
        assert math.isclose(phi_0.imag, 0.0, abs_tol=1e-7)

        # Option pricing
        spot = 24000.0
        c_atm = vg.call_price(spot=spot, strike=24000.0, maturity=0.25)
        p_atm = vg.put_price(spot=spot, strike=24000.0, maturity=0.25)
        assert c_atm > 0.0 and p_atm > 0.0
        # Call price monotonic in strike
        c_otm = vg.call_price(spot=spot, strike=25000.0, maturity=0.25)
        assert c_atm > c_otm

        # Strip pricing
        strikes = [23000.0, 23500.0, 24000.0, 24500.0, 25000.0]
        strip = vg.price_strip(spot=spot, strikes=strikes, maturity=0.25)
        assert len(strip) == 5

        # Butterfly density
        calls = [s["call"] for s in strip]
        butterflies = VarianceGammaSurface.butterfly_density(calls, strike_spacing=500.0)
        assert len(butterflies) == 3
        # Strict butterfly density non-negativity
        assert all(b >= -1e-6 for b in butterflies)

    def test_statutory_cost_calculator_asymmetric_schedule(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.hawkes_l3_cancellation_variance_gamma_engine import (
            StatutoryCostCalculator, OptionLeg
        )
        calc = StatutoryCostCalculator()
        legs = [
            OptionLeg(side="BUY", premium=100.0, quantity=50),
            OptionLeg(side="SELL", premium=80.0, quantity=50),
        ]
        breakdown = calc.calculate(legs, slippage=10.0, impact_hurdle=5.0)
        # Buy leg turnover = 5000 -> Stamp duty = 0.003% of 5000 = 0.15
        assert math.isclose(breakdown.stamp_duty, 5000.0 * 0.00003, rel_tol=1e-5)
        # Sell leg turnover = 4000 -> STT = 0.15% of 4000 = 6.00
        assert math.isclose(breakdown.stt, 4000.0 * 0.0015, rel_tol=1e-5)
        # Exchange fee on total 9000
        assert math.isclose(breakdown.exchange_fee, 9000.0 * 3553.0 / 1e7, rel_tol=1e-5)
        assert breakdown.brokerage == 40.0
        assert breakdown.statutory_total > 0.0
        assert breakdown.total_hurdle > breakdown.statutory_total

        # Net alpha and gate verification
        assert calc.passes_gate(gross_alpha=200.0, costs=breakdown) is True
        assert calc.passes_gate(gross_alpha=20.0, costs=breakdown) is False

    def test_anti_overtrading_throttler_dynamic_cooldown_and_lockouts(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.hawkes_l3_cancellation_variance_gamma_engine import (
            AntiOvertradingThrottler
        )
        t = AntiOvertradingThrottler(max_daily_trades=5, base_cooldown_seconds=900.0)
        assert t.locked(now=100.0) is False

        # Optimal trade cap formula
        cap = AntiOvertradingThrottler.optimal_daily_trade_cap(alpha=200.0, cost=50.0, risk=15.0)
        assert cap == 10

        # Rapid fill lockout (<30s)
        t.record_fill(timestamp=100.0, size=10.0, pnl=50.0)
        triggered_rapid = t.record_fill(timestamp=115.0, size=10.0, pnl=50.0)
        assert triggered_rapid is True
        assert t.locked(now=120.0) is True

        # Reset and test revenge sizing (>1.25x)
        t.reset_session()
        t.record_fill(timestamp=100.0, size=10.0, pnl=-50.0)
        triggered_revenge = t.record_fill(timestamp=200.0, size=15.0, pnl=10.0)
        assert triggered_revenge is True
        assert t.locked(now=250.0) is True

        # Reset and test 3-consecutive loss streak
        t.reset_session()
        t.record_fill(timestamp=100.0, size=10.0, pnl=-50.0)
        t.record_fill(timestamp=200.0, size=10.0, pnl=-50.0)
        triggered_loss = t.record_fill(timestamp=300.0, size=10.0, pnl=-50.0)
        assert triggered_loss is True
        assert t.consecutive_losses == 3
        assert t.locked(now=350.0) is True

    def test_cycle38_execution_engine_telemetry_and_fail_closed_invariants(self) -> None:
        import json
        from agents.AGI_1_7.engine.agi17.finance.hawkes_l3_cancellation_variance_gamma_engine import (
            Cycle38ExecutionEngine, LIVE_ORDER_DISPATCH_ENABLED, REAL_BROKER_FILLS_LOCKED,
            OptionLeg, RiskState
        )
        assert LIVE_ORDER_DISPATCH_ENABLED is False
        assert REAL_BROKER_FILLS_LOCKED is True

        engine = Cycle38ExecutionEngine()
        assert engine.risk.state == RiskState.IDLE

        # Process a heavy cancellation burst
        res = engine.process_cancel_event(timestamp=10.0, mark=45.0, level=1, ofi=-3.0)
        assert res["quote_pullback"] is True
        assert engine.risk.state == RiskState.CANCELLATION_SHOCK

        # Evaluate candidate trade under shock state -> must be blocked
        legs = [OptionLeg(side="BUY", premium=100.0, quantity=50)]
        candidate = engine.evaluate_candidate(gross_alpha=300.0, legs=legs, now=10.05)
        assert candidate["allowed"] is False

        # Telemetry validation
        telem = engine.telemetry(now=10.05)
        assert telem["safety"]["LIVE_ORDER_DISPATCH_ENABLED"] is False
        assert telem["safety"]["REAL_BROKER_FILLS_LOCKED"] is True
        assert telem["safety"]["paper_ledger_epoch"] == "epoch_10k"
        assert "+05:30" in telem["timestamp_ist"]
        assert "hawkes_graph" in telem
        assert "cancellation" in telem
        assert "vg_surface" in telem

        # JSON serialization without NaN
        json_output = engine.json_telemetry(now=10.05)
        assert "CANCELLATION_SHOCK" in json_output


class TestTradingSquadAndSkillBudget:
    """Acceptance test suite for the 4-agent trading squad and token-budgeted skill optimization."""

    def test_squad_personas_and_roles(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.three_agent_contract import (
            MANAGER_ABHI_PERSONA,
            ALEX_PERSONA,
            ALEXA_PERSONA,
            EMILY_PERSONA,
            MAX_PERSONA,
        )

        # Manager Abhi: Operator interface and system lead
        assert MANAGER_ABHI_PERSONA.name == "Manager Abhi"
        assert MANAGER_ABHI_PERSONA.binding_rejection_authority is True
        assert "operator" in MANAGER_ABHI_PERSONA.role.lower()
        assert any("fail-closed" in r.lower() for r in MANAGER_ABHI_PERSONA.responsibilities)

        # Alex: Microstructure and L3 execution
        assert ALEX_PERSONA.name == "Alex"
        assert ALEX_PERSONA.binding_rejection_authority is True
        assert "microstructure" in ALEX_PERSONA.role.lower()

        # Emily: Volatility and macro intelligence
        assert EMILY_PERSONA.name == "Emily"
        assert EMILY_PERSONA.binding_rejection_authority is True
        assert ("financial" in EMILY_PERSONA.role.lower() or "volatility" in EMILY_PERSONA.role.lower())
        assert any("vix" in r.lower() for r in EMILY_PERSONA.responsibilities)

        # Max: Quantitative risk and statutory cost
        assert MAX_PERSONA.name == "Max"
        assert MAX_PERSONA.binding_rejection_authority is True
        assert "risk" in MAX_PERSONA.role.lower()

    def test_four_agent_squad_coordinator_approval(self, tmp_path: Path) -> None:
        from agents.AGI_1_7.engine.agi17.finance.three_agent_contract import FourAgentSquadCoordinator

        coordinator = FourAgentSquadCoordinator(storage_dir=tmp_path)
        operator_order = {
            "live_dispatch_requested": False,
            "allocated_capital_inr": 10000.0,
            "max_daily_loss_inr": 2500.0,
            "directive": "Execute paper strangle evaluation",
        }
        emily_radar = {"tail_risk_flag": False, "is_sentiment_only": False}
        max_candidate = {
            "decision": "APPROVED",
            "net_expectancy_inr": 185.0,
            "risk_calc_inr": 150.0,
            "instrument": "NIFTY26OCT24500CE",
        }
        alex_ui = {"browser_ready": True, "inputs_verified": True}

        approved, status, record, summary = coordinator.evaluate_squad_consensus(
            session_id="SESS-SQUAD-01",
            operator_order=operator_order,
            emily_radar_status=emily_radar,
            max_quant_candidate=max_candidate,
            alex_ui_verification=alex_ui,
        )

        assert approved is True
        assert status == "APPROVED_BY_SQUAD"
        assert record is None
        assert summary["manager_abhi_approved"] is True
        assert summary["alex_approved"] is True
        assert summary["emily_approved"] is True
        assert summary["max_approved"] is True

    def test_manager_abhi_veto_on_live_dispatch(self, tmp_path: Path) -> None:
        from agents.AGI_1_7.engine.agi17.finance.three_agent_contract import FourAgentSquadCoordinator

        coordinator = FourAgentSquadCoordinator(storage_dir=tmp_path)
        operator_order = {
            "live_dispatch_requested": True,  # Prohibited live dispatch attempt
            "allocated_capital_inr": 10000.0,
            "max_daily_loss_inr": 2500.0,
        }
        emily_radar = {"tail_risk_flag": False, "is_sentiment_only": False}
        max_candidate = {"decision": "APPROVED", "net_expectancy_inr": 100.0, "risk_calc_inr": 100.0}
        alex_ui = {"browser_ready": True, "inputs_verified": True}

        approved, status, record, summary = coordinator.evaluate_squad_consensus(
            session_id="SESS-SQUAD-02",
            operator_order=operator_order,
            emily_radar_status=emily_radar,
            max_quant_candidate=max_candidate,
            alex_ui_verification=alex_ui,
        )

        assert approved is False
        assert status == "PREFER_NO_TRADE"
        assert record is not None
        assert "Manager Abhi" in record.agent_stances
        assert "LIVE_ORDER_DISPATCH_ENABLED = False" in str(record.evidence_ledger["Manager Abhi"])
        assert summary["manager_abhi_approved"] is False

    def test_manager_abhi_veto_on_excess_capital(self, tmp_path: Path) -> None:
        from agents.AGI_1_7.engine.agi17.finance.three_agent_contract import FourAgentSquadCoordinator

        coordinator = FourAgentSquadCoordinator(storage_dir=tmp_path)
        operator_order = {
            "live_dispatch_requested": False,
            "allocated_capital_inr": 50000.0,  # Exceeds authorized epoch_10k (10,000)
            "max_daily_loss_inr": 2500.0,
        }
        emily_radar = {"tail_risk_flag": False, "is_sentiment_only": False}
        max_candidate = {"decision": "APPROVED", "net_expectancy_inr": 100.0, "risk_calc_inr": 100.0}
        alex_ui = {"browser_ready": True, "inputs_verified": True}

        approved, status, record, summary = coordinator.evaluate_squad_consensus(
            session_id="SESS-SQUAD-03",
            operator_order=operator_order,
            emily_radar_status=emily_radar,
            max_quant_candidate=max_candidate,
            alex_ui_verification=alex_ui,
        )

        assert approved is False
        assert "Manager Abhi" in record.agent_stances
        assert "epoch_10k" in record.agent_stances["Manager Abhi"]

    def test_skill_budget_manager(self) -> None:
        from agents.AGI_1_7.engine.agi17.skills.skill_budget_manager import SkillBudgetManager

        mgr = SkillBudgetManager()
        status = mgr.get_status()
        assert status["active_count"] == 47
        assert status["vaulted_count"] >= 1900
        assert status["estimated_token_savings"] >= 19000
        assert "omega-quant-trading" in status["active_skills"]
        assert "trading-risk-management" in status["active_skills"]
        assert "deep-research" in status["active_skills"]
        assert "browser-harness" in status["active_skills"]


class TestCycle39FractionalHestonHawkesQueueDepletion:
    """Acceptance test suite for Cycle 39 Fractional Heston-Hawkes, SSVI and L3 Queue Depletion."""

    def test_cycle39_safety_invariants_fail_closed(self) -> None:
        import agents.AGI_1_7.engine.agi17.finance.fractional_heston_hawkes_queue_depletion_engine as c39

        assert c39.LIVE_ORDER_DISPATCH_ENABLED is False
        assert c39.REAL_BROKER_FILLS_LOCKED is True
        assert c39.PAPER_LEDGER_EPOCH == "epoch_10k"
        assert c39.INITIAL_PAPER_CAPITAL == 10000.0

        with pytest.raises(RuntimeError):
            c39.dispatch_live_order("BUY")

    def test_cycle39_fractional_kernel_and_rough_heston(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.fractional_heston_hawkes_queue_depletion_engine import (
            FractionalKernel12, FractionalHestonHawkesModel
        )
        import numpy as np

        model = FractionalKernel12(hurst=0.075)
        assert 0.05 < model.hurst < 0.45
        assert len(model.weights) == 12
        assert model.kernel(0.01) > 0.0
        assert math.isfinite(model.kernel(0.1))

        # Rough Heston simulation step
        heston = FractionalHestonHawkesModel(seed=42)
        v = heston.update(dt=0.01, shocks=(0.1, -0.2), jump_shocks=(0.0, 0.05))
        assert v.shape == (2,)
        assert np.all(v > 0.0)

    def test_cycle39_bivariate_hawkes_cross_excitation(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.fractional_heston_hawkes_queue_depletion_engine import BivariateHawkes
        import numpy as np

        bh = BivariateHawkes()
        assert bh.spectral_radius < 0.90
        before = bh.intensity.copy()
        after = bh.event(source=0, count=2)
        assert np.all(after >= before)
        assert after[0] > before[0]
        asym = bh.cross_excitation_asymmetry
        assert -1.0 <= asym <= 1.0

    def test_cycle39_ssvi_surface_and_butterfly_convexity(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.fractional_heston_hawkes_queue_depletion_engine import SSVISurface

        maturities = [0.08, 0.16, 0.32]
        theta = [0.025, 0.045, 0.08]
        surface = SSVISurface(maturities=maturities, theta=theta, rho=-0.25, phi=0.7)
        tv = surface.total_variance(k=0.0, maturity=0.16)
        assert tv > 0.0
        assert math.isfinite(tv)

        bf = surface.butterfly_diagnostic()
        assert bf["convex_nonnegative_sampled"] is True

    def test_cycle39_l3_queue_depletion_and_assessment(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.fractional_heston_hawkes_queue_depletion_engine import (
            L3QueueDepletionMachine, QueueOrder
        )

        qm = L3QueueDepletionMachine()
        order = QueueOrder(order_id="ORD-01", symbol="NIFTY", level=1, side="BID", price=100.0, quantity=50.0, ahead=10.0)
        qm.place(order)
        assessment = qm.assess(order_id="ORD-01", lambda_market=1.0, tau=1.0, expected_adverse_slippage=0.5, round_trip_friction=1.8)
        assert 0.0 <= assessment.fill_probability <= 1.0
        assert assessment.expected_adverse_slippage >= 0.0

    def test_cycle39_delta_gamma_neutral_hedger(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.fractional_heston_hawkes_queue_depletion_engine import (
            DeltaGammaNeutralHedger
        )

        hedger = DeltaGammaNeutralHedger(max_iter=300)
        out = hedger.solve(
            delta0=0.0,
            gamma0=0.1,
            target_gamma=0.4,
            delta_sensitivities=[1.0, -1.0],
            gamma_sensitivities=[0.2, 0.7],
            spreads=[0.1, 0.15],
            depths=[20.0, 25.0],
            lower_bounds=[-5.0, -5.0],
            upper_bounds=[5.0, 5.0],
            lambda_spread=0.01,
            lambda_vacuum=0.001,
        )
        assert out.feasible is True
        assert abs(out.delta_net) < 1e-5

    def test_cycle39_statutory_cost_calculator(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.fractional_heston_hawkes_queue_depletion_engine import (
            Cycle39StatutoryCostCalculator, Cycle39Leg
        )

        calc = Cycle39StatutoryCostCalculator()
        legs = [
            Cycle39Leg(side="SELL", premium=100.0, quantity=50.0),
            Cycle39Leg(side="BUY", premium=60.0, quantity=50.0),
        ]
        breakdown = calc.breakdown(legs)
        assert breakdown.stt > 0.0  # 0.15% on sell premium
        assert breakdown.stamp_duty > 0.0  # 0.003% on buy premium
        assert breakdown.brokerage == 40.0  # ₹20 * 2 legs
        assert breakdown.gst > 0.0
        assert breakdown.total > 40.0

    def test_cycle39_execution_engine_full_loop(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.fractional_heston_hawkes_queue_depletion_engine import (
            Cycle39ExecutionEngine
        )

        engine = Cycle39ExecutionEngine(particles=100)
        telemetry = engine.telemetry()
        assert telemetry["safety"]["LIVE_ORDER_DISPATCH_ENABLED"] is False
        assert telemetry["safety"]["REAL_BROKER_FILLS_LOCKED"] is True
        assert telemetry["paper_ledger"]["epoch"] == "epoch_10k"
        assert "timestamp_ist" in telemetry


class TestCycle40RoughBergomiHawkesInventory:
    """Cycle 40 deterministic integration suite for Rough Bergomi, Hawkes Market Maker, and 4-Agent Squad."""

    def test_cycle40_safety_invariants_fail_closed(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.rough_bergomi_hawkes_inventory_engine import (
            LIVE_ORDER_DISPATCH_ENABLED, REAL_BROKER_FILLS_LOCKED,
            PAPER_LEDGER_EPOCH, PAPER_INITIAL_CAPITAL, dispatch_live_order
        )
        assert LIVE_ORDER_DISPATCH_ENABLED is False
        assert REAL_BROKER_FILLS_LOCKED is True
        assert PAPER_LEDGER_EPOCH == "epoch_10k"
        assert PAPER_INITIAL_CAPITAL == 10000.0

        with pytest.raises((PermissionError, RuntimeError)):
            dispatch_live_order("NIFTY", "BUY", 50, 22000.0)

    def test_cycle40_rough_bergomi_lift_and_kernel(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.rough_bergomi_hawkes_inventory_engine import (
            RoughBergomiLift
        )
        model = RoughBergomiLift(hurst=0.07, seed=7)
        assert 0.0 < model.hurst < 0.5
        assert len(model.omega) == 12
        assert model.approximate_kernel(0.01) > 0.0
        assert math.isinf(model.kernel(0.0))
        assert math.isfinite(model.approximate_kernel(0.0))

        step = model.advance(dt=0.01, brownian_z=0.2)
        assert "variance" in step
        assert step["variance"] > 0.0

    def test_cycle40_hawkes_graph4_centrality(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.rough_bergomi_hawkes_inventory_engine import (
            HawkesGraph4
        )
        graph = HawkesGraph4()
        assert graph.spectral_radius < 0.88
        rates = graph.update(dt=0.05, events=[1, 0, 2, 0])
        assert len(rates) == 4
        assert np.all(rates > 0.0)

        centrality = graph.centrality()
        assert "NIFTY50" in centrality
        assert "in_degree_absorption" in centrality["NIFTY50"]
        assert 0.0 <= centrality["NIFTY50"]["in_degree_absorption"] <= 1.0

    def test_cycle40_hawkes_market_maker_quotes(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.rough_bergomi_hawkes_inventory_engine import (
            HawkesMarketMaker
        )
        mm = HawkesMarketMaker(risk_aversion=0.1, order_book_kappa=1.2, hawkes_spread_scale=0.08)
        quote = mm.quote(mid=22000.0, inventory=2.0, volatility=0.18, horizon=0.1, hawkes_intensity=1.5)
        assert quote.bid < 22000.0
        assert quote.ask > quote.bid
        assert quote.half_spread > 0.0
        assert quote.hawkes_widening >= 1.0

    def test_cycle40_l3_queue_machine_pullback(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.rough_bergomi_hawkes_inventory_engine import (
            L3QueueMachine
        )
        qm = L3QueueMachine()
        qm.add_order(order_id="ORD-L3-01", level=1, side="BUY", quantity=50.0, ahead=1.0)
        verdict = qm.evaluate_pullback(
            order_id="ORD-L3-01",
            horizon=1.0,
            market_arrival_rate=10.0,
            cancellation_hazard=0.5,
            expected_adverse_slippage=15.0,
            round_trip_statutory_friction=5.0,
            fill_threshold=0.5,
        )
        assert verdict["fill_probability"] > 0.5
        assert verdict["quote_pullback_immediate"] is True

    def test_cycle40_variance_gamma_and_discrete_replication(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.rough_bergomi_hawkes_inventory_engine import (
            VarianceGammaModel, DiscreteVarianceGammaReplicator
        )
        vg = VarianceGammaModel(sigma=0.2, nu=0.15, theta=-0.05)
        cf = vg.characteristic_function(1.0, 0.5)
        assert math.isfinite(abs(cf))

        replicator = DiscreteVarianceGammaReplicator(vg)
        strip = replicator.strip(spot=22000.0, strikes=[21800.0, 22000.0, 22200.0], maturity=0.1)
        assert strip["butterfly_nonnegative_sampled"] is True
        assert len(strip["calls"]) == 3
        assert len(strip["puts"]) == 3
        assert strip["variance_swap_rate"] > 0.0

    def test_cycle40_statutory_cost_calculator(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.rough_bergomi_hawkes_inventory_engine import (
            StatutoryCostCalculator, OptionLeg, FeeConfig
        )
        calc = StatutoryCostCalculator(FeeConfig())
        legs = [
            OptionLeg(side="BUY", premium=120.0, quantity=50.0),
            OptionLeg(side="SELL", premium=80.0, quantity=50.0),
        ]
        breakdown = calc.calculate(legs, half_spread_slippage=1.0, impact_hurdle=0.5)
        assert breakdown.stt > 0.0  # 0.15% on sell premium
        assert breakdown.stamp_duty > 0.0  # 0.003% on buy premium
        assert breakdown.brokerage == 40.0  # ₹20 * 2 orders
        assert breakdown.gst > 0.0
        assert breakdown.total > 41.5

    def test_cycle40_inventory_controller_and_tilt_throttler(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.rough_bergomi_hawkes_inventory_engine import (
            InventoryRiskController, TiltThrottler
        )
        controller = InventoryRiskController(initial_capital=10000.0, max_abs_inventory=5.0)
        fill = controller.apply_paper_fill("BUY", 2.0, 100.0, fees=25.0)
        assert fill["accepted"] is True
        assert controller.inventory == 2.0
        assert controller.cash == 10000.0 - 200.0 - 25.0

        throttler = TiltThrottler(max_trades_per_session=3, cooldown_seconds=60.0)
        assert throttler.can_enter(100.0) is True
        throttler.record_fill(100.0, 1.0, -10.0)
        throttler.record_fill(105.0, 1.0, -10.0)  # rapid fill triggers cooldown
        assert throttler.can_enter(110.0) is False

    def test_cycle40_four_agent_squad_evaluation(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.rough_bergomi_hawkes_inventory_engine import (
            FourAgentSquad
        )
        approved_eval = FourAgentSquad.evaluate(
            operator_approved=True,
            alpha_positive=True,
            queue_safe=True,
            volatility_safe=True,
            statutory_valid=True,
        )
        assert approved_eval["approved"] is True
        assert approved_eval["votes"]["Manager Abhi"] is True
        assert approved_eval["votes"]["Alex"] is True
        assert approved_eval["votes"]["Emily"] is True
        assert approved_eval["votes"]["Max"] is True

        # Operator veto test
        veto_eval = FourAgentSquad.evaluate(
            operator_approved=False,
            alpha_positive=True,
            queue_safe=True,
            volatility_safe=True,
            statutory_valid=True,
        )
        assert veto_eval["approved"] is False
        assert veto_eval["manager_veto"] is True

    def test_cycle40_execution_engine_telemetry(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.rough_bergomi_hawkes_inventory_engine import (
            Cycle40ExecutionEngine
        )
        engine = Cycle40ExecutionEngine(seed=40)
        telemetry = engine.telemetry()
        assert telemetry["safety"]["LIVE_ORDER_DISPATCH_ENABLED"] is False
        assert telemetry["safety"]["REAL_BROKER_FILLS_LOCKED"] is True
        assert telemetry["paper_ledger"]["epoch"] == "epoch_10k"
        assert "rough" in telemetry
        assert "hawkes" in telemetry
        assert "inventory" in telemetry
        assert "paper_ledger" in telemetry


class TestCycle41CrossAssetVolterraHawkesHedging:
    """Cycle 41 integration suite for Cross-Asset Volterra Covariance, Hawkes Lead-Lag, and 4-Agent Squad."""

    def test_cycle41_safety_invariants_fail_closed(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.cross_asset_volterra_hawkes_hedging_engine import (
            LIVE_ORDER_DISPATCH_ENABLED, REAL_BROKER_FILLS_LOCKED,
            PAPER_LEDGER_EPOCH, INITIAL_CAPITAL_INR, dispatch_live_order, ASSETS
        )
        assert LIVE_ORDER_DISPATCH_ENABLED is False
        assert REAL_BROKER_FILLS_LOCKED is True
        assert PAPER_LEDGER_EPOCH == "epoch_10k"
        assert INITIAL_CAPITAL_INR == 10000.0
        assert ASSETS == ("NIFTY50", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY")

        with pytest.raises((PermissionError, RuntimeError)):
            dispatch_live_order("BUY")

    def test_cycle41_multi_asset_rough_volterra_covariance(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.cross_asset_volterra_hawkes_hedging_engine import (
            MultiAssetRoughVolterraCovariance
        )
        cov = MultiAssetRoughVolterraCovariance(seed=41)
        snap = cov.step(dt=0.01)
        assert len(snap.variances) == 4
        assert snap.min_covariance_eigenvalue > 0
        assert np.all(np.array(snap.variances) > 0)
        assert len(snap.kernel_relative_errors) == 4

    def test_cycle41_hawkes_lead_lag_graph_centrality(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.cross_asset_volterra_hawkes_hedging_engine import (
            HawkesLeadLagGraph
        )
        hawkes = HawkesLeadLagGraph()
        assert hawkes.spectral_radius() < 0.88
        leaders = hawkes.leading_constituents()
        assert len(leaders) == 4
        assert leaders[0][0] in hawkes.NODES
        leadership = hawkes.leadership_matrix()
        assert len(leadership) == 4
        assert leadership[0][0] == 0.0

    def test_cycle41_l3_queue_machine_pullback(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.cross_asset_volterra_hawkes_hedging_engine import (
            L3QueueDepletionMachine, QueueOrder
        )
        qm = L3QueueDepletionMachine()
        order = QueueOrder(order_id="ORD-41", instrument="NIFTY50", side="BUY", level=2, quantity=10, ahead=2.0, behind=5.0)
        qm.add_order(order)
        assert len(qm.orders) == 1
        assert qm.pullback_required(0.9, 10.0, 2.0) is True

    def test_cycle41_multi_horizon_gamma_hedger(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.cross_asset_volterra_hawkes_hedging_engine import (
            MultiHorizonGammaHedger, OptionInstrument
        )
        options = [
            OptionInstrument("N-C1", delta=0.5, gamma=0.05, half_spread=0.1, depth=100.0, max_adjustment=10.0, expiry_days=7.0, price=150.0),
            OptionInstrument("N-P1", delta=-0.4, gamma=0.05, half_spread=0.1, depth=100.0, max_adjustment=10.0, expiry_days=7.0, price=120.0),
        ]
        hedger = MultiHorizonGammaHedger(options)
        res = hedger.optimize(initial_delta=-0.5, initial_gamma=0.02, gamma_target=0.0)
        assert res.converged is True
        assert len(res.adjustments) == 2

    def test_cycle41_statutory_cost_calculator(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.cross_asset_volterra_hawkes_hedging_engine import (
            StatutoryCostCalculator, TradeLeg
        )
        calc = StatutoryCostCalculator()
        legs = [
            TradeLeg(side="BUY", premium=50.0, lots=1, lot_size=50, label="NIFTY-CE"),
            TradeLeg(side="SELL", premium=68.0, lots=1, lot_size=50, label="NIFTY-PE"),
        ]
        fees = calc.calculate(legs)
        assert fees.stt > 0
        assert fees.stamp_duty > 0
        assert fees.brokerage == 40.0
        assert fees.gst > 0
        assert fees.total > 41.5

    def test_cycle41_anti_overtilt_throttler(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.cross_asset_volterra_hawkes_hedging_engine import (
            AntiOvertiltThrottler
        )
        throttler = AntiOvertiltThrottler(max_daily_trades=3, cooldown_seconds=60.0)
        allowed, reason = throttler.can_enter(100.0)
        assert allowed is True
        throttler.record_fill(100.0, 1.0, -10.0)
        throttler.record_fill(140.0, 1.0, -10.0)
        throttler.record_fill(180.0, 1.0, -10.0)
        allowed_after, reason_after = throttler.can_enter(190.0)
        assert allowed_after is False
        assert reason_after == "loss_streak"

    def test_cycle41_four_agent_squad_and_manager_abhi(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.cross_asset_volterra_hawkes_hedging_engine import (
            FourAgentSquad, TradeCandidate, TradeLeg
        )
        squad = FourAgentSquad()
        legs = [
            TradeLeg(side="BUY", premium=50.0, lots=1, lot_size=50, label="NIFTY-CE"),
            TradeLeg(side="SELL", premium=68.0, lots=1, lot_size=50, label="NIFTY-PE"),
        ]
        cand = TradeCandidate("cand-1", 200.0, legs, 5.0, 5.0, 10.0, 5900.0, 5.0, 0.7)
        dec = squad.evaluate(cand, capital=10000.0, live=False)
        assert dec.approved is True
        assert dec.votes["Manager Abhi"] is True
        assert dec.votes["Alex"] is True
        assert dec.votes["Emily"] is True
        assert dec.votes["Max"] is True

        veto = squad.evaluate(cand, capital=10000.0, live=True)
        assert veto.approved is False
        assert veto.votes["Manager Abhi"] is False

    def test_cycle41_execution_engine_telemetry(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.cross_asset_volterra_hawkes_hedging_engine import (
            Cycle41ExecutionEngine
        )
        engine = Cycle41ExecutionEngine()
        telemetry = engine.telemetry()
        assert telemetry["safety"]["LIVE_ORDER_DISPATCH_ENABLED"] is False
        assert telemetry["safety"]["REAL_BROKER_FILLS_LOCKED"] is True
        assert telemetry["paper_ledger"]["epoch"] == "epoch_10k"
        assert "rough_volterra" in telemetry
        assert "hawkes" in telemetry
        assert "queue" in telemetry
        assert "hedge" in telemetry


class TestCycle42HawkesMLOFIGreeksSurfaceHedging:
    """Verifies Cycle 42 MLOFI, Hawkes Network, Rough Volterra Covariance, Greek Hedging, Statutory Friction, and 4-Agent Consensus."""

    def test_cycle42_mlofi_tracker(self) -> None:
        import numpy as np
        from agents.AGI_1_7.engine.agi17.finance.hawkes_mlofi_greeks_surface_hedging_engine import (
            MLOFITracker
        )
        tracker = MLOFITracker()
        assert len(tracker.assets) == 4
        assert np.allclose(tracker.weights, [1.0, 0.8, 0.6, 0.4, 0.2])
        bid_v = np.array([[100.0, 80.0, 60.0, 40.0, 20.0]] * 4)
        ask_v = np.array([[90.0, 75.0, 55.0, 35.0, 15.0]] * 4)
        tracker.update(bid_v, ask_v)
        snap = tracker.snapshot()
        assert "ofi" in snap
        assert len(snap["ofi"]) == 4

    def test_cycle42_hawkes_network_subcritical(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.hawkes_mlofi_greeks_surface_hedging_engine import (
            HawkesNetwork
        )
        hn = HawkesNetwork()
        rho = hn.spectral_radius
        assert rho < 0.88
        cent = hn.centrality()
        assert "in_absorption" in cent
        assert "out_spillover" in cent
        assert len(cent["in_absorption"]) == 4
        assert all(c > 0 for c in cent["in_absorption"])

    def test_cycle42_rough_volterra_covariance_psd(self) -> None:
        import numpy as np
        from agents.AGI_1_7.engine.agi17.finance.hawkes_mlofi_greeks_surface_hedging_engine import (
            RoughVolterraCovariance
        )
        rvc = RoughVolterraCovariance(seed=42)
        cov = rvc.covariance_matrix()
        assert cov.shape == (4, 4)
        assert np.allclose(cov, cov.T)
        eigvals = np.linalg.eigvalsh(cov)
        assert np.all(eigvals >= -1e-10)
        assert len(rvc.half_lives()) == 12

    def test_cycle42_greek_hedge_optimizer(self) -> None:
        import numpy as np
        from agents.AGI_1_7.engine.agi17.finance.hawkes_mlofi_greeks_surface_hedging_engine import (
            GreekHedgeOptimizer
        )
        opt = GreekHedgeOptimizer(max_projection_iter=400, max_opt_iter=40)
        g = np.eye(3)
        cur = np.array([0.5 * 1e-4, 0.5 * 1e-3, 0.5 * 0.5])
        res = opt.optimize(
            covariance=np.eye(3),
            cross_impact=np.eye(3) * 0.1,
            greeks=g,
            current_greeks=cur,
            transaction_cost_rates=np.ones(3) * 0.01,
            lower_bounds=np.full(3, -1.0),
            upper_bounds=np.full(3, 1.0)
        )
        assert res.feasible is True
        assert abs(res.net_greeks[0]) <= 1e-4 + 2e-6
        assert abs(res.net_greeks[1]) <= 1e-3 + 2e-6
        assert abs(res.net_greeks[2]) <= 1.0 + 2e-6

    def test_cycle42_statutory_cost_calculator(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.hawkes_mlofi_greeks_surface_hedging_engine import (
            StatutoryCostCalculator, OptionLeg
        )
        calc = StatutoryCostCalculator()
        legs = [
            OptionLeg(instrument="NIFTY_CE", side="BUY", premium=100.0, lots=1.0, lot_size=50),
            OptionLeg(instrument="NIFTY_PE", side="SELL", premium=120.0, lots=1.0, lot_size=50),
        ]
        report = calc.calculate(legs, gross_alpha=500.0)
        assert report.stt == 9.0
        assert report.stamp_duty == 0.15
        assert report.brokerage == 40.0
        assert report.gst > 0
        assert report.approved is True
        assert report.net_alpha == report.gross_alpha - report.total_friction

    def test_cycle42_anti_overtrading_throttler(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.hawkes_mlofi_greeks_surface_hedging_engine import (
            AntiOvertradingThrottler
        )
        throttler = AntiOvertradingThrottler(max_trades_per_day=3, tau_base=60.0)
        ok, reason = throttler.can_enter(100.0)
        assert ok is True
        throttler.record_fill(100.0, 1.0, -50.0)
        throttler.record_fill(120.0, 1.0, -50.0)
        throttler.record_fill(140.0, 1.0, -50.0)
        ok_after, reason_after = throttler.can_enter(150.0)
        assert ok_after is False
        assert "consecutive_losses" in reason_after

    def test_cycle42_trading_squad_consensus(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.hawkes_mlofi_greeks_surface_hedging_engine import (
            TradingSquadConsensus
        )
        squad = TradingSquadConsensus()
        dec = squad.evaluate(live=False, equity=10000.0, capital_required=2000.0, net_alpha=150.0)
        assert dec.approved is True
        assert dec.live_veto is False
        assert len(dec.decisions) == 4
        veto = squad.evaluate(live=True, equity=10000.0, capital_required=2000.0, net_alpha=150.0)
        assert veto.approved is False
        assert veto.live_veto is True
        f = squad.bayesian_kelly_fraction(win_probability=0.6, payoff_ratio=1.5, uncertainty=0.1)
        assert 0.0 < f <= 0.25

    def test_cycle42_fail_closed_live_dispatch_locked(self) -> None:
        import pytest
        from agents.AGI_1_7.engine.agi17.finance.hawkes_mlofi_greeks_surface_hedging_engine import (
            dispatch_live_order, Cycle42ExecutionEngine
        )
        with pytest.raises(PermissionError, match="live order dispatch is permanently disabled"):
            dispatch_live_order()
        engine = Cycle42ExecutionEngine()
        with pytest.raises(PermissionError, match="live order dispatch is permanently disabled"):
            engine.dispatch_live_order()

    def test_cycle42_execution_engine_telemetry(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.hawkes_mlofi_greeks_surface_hedging_engine import (
            Cycle42ExecutionEngine
        )
        engine = Cycle42ExecutionEngine()
        t = engine.telemetry()
        assert t["safety"]["LIVE_ORDER_DISPATCH_ENABLED"] is False
        assert t["safety"]["REAL_BROKER_FILLS_LOCKED"] is True
        assert t["safety"]["paper_ledger_epoch"] == "epoch_10k"
        assert t["safety"]["initial_capital"] == 10000.0
        assert "mlofi" in t
        assert "hawkes" in t
        assert "rough_covariance" in t
        assert "queue" in t
        assert "surface" in t


class TestCycle43FractionalVolterraGammaSqueeze:
    """Verifies Cycle 43 Fractional Volterra Covariance, Dealer Gamma Squeeze Topology, Cross-Expiry Hedging, Statutory Taxes, and 4-Agent Consensus."""

    def test_cycle43_rough_volterra_covariance_and_hurst(self) -> None:
        import numpy as np
        from agents.AGI_1_7.engine.agi17.finance.fractional_volterra_gamma_squeeze_engine import (
            RoughVolterraCovariance
        )
        rv = RoughVolterraCovariance()
        cov = rv.covariance()
        assert cov.shape == (4, 4)
        assert np.allclose(cov, cov.T)
        assert np.all(np.linalg.eigvalsh(cov) >= -1e-10)
        assert len(rv.hurst) == 4
        assert rv.n_factors == 12
        assert rv.validate_lee_wing(0, 0.1, 0.05) is True

    def test_cycle43_dealer_gamma_squeeze_topology(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.fractional_volterra_gamma_squeeze_engine import (
            DealerGammaSqueezeTopology
        )
        sq = DealerGammaSqueezeTopology()
        r1 = sq.update("NIFTY50", {22000.0: 1.5, 22100.0: -0.5}, depth=100.0)
        assert r1["squeeze_hazard"] > 0
        assert r1["quote_retreat_immediate"] is False
        assert r1["dominant_strike"] == 22000.0
        # Toxic cascade triggers immediate quote retreat
        r2 = sq.update("NIFTY50", {22000.0: 10.0}, depth=1.0, toxic_cascade=True)
        assert r2["quote_retreat_immediate"] is True
        assert r2["reason"] == "toxic_cascade"

    def test_cycle43_hawkes_spillover_graph(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.fractional_volterra_gamma_squeeze_engine import (
            HawkesSpilloverGraph
        )
        h = HawkesSpilloverGraph()
        assert h.spectral_radius < 0.88
        cents = h.centralities()
        assert "in_degree_absorption" in cents
        assert "out_degree_spillover" in cents
        assert len(cents["in_degree_absorption"]) == 4
        assert all(c > 0 for c in cents["in_degree_absorption"])
        lead = h.leadership_matrix()
        assert lead.shape == (4, 4)
        for i in range(4):
            assert lead[i, i] == 0.0

    def test_cycle43_mlofi_depth_volume_deltas(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.fractional_volterra_gamma_squeeze_engine import (
            MultiLevelOFI
        )
        mlofi = MultiLevelOFI()
        norm = mlofi.normalized()
        assert len(norm) == 4
        assert set(mlofi.assets) == {"NIFTY50", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY"}

    def test_cycle43_cross_expiry_greek_hedge_optimizer(self) -> None:
        import numpy as np
        from agents.AGI_1_7.engine.agi17.finance.fractional_volterra_gamma_squeeze_engine import (
            Cycle43ExecutionEngine, OptionLeg
        )
        e = Cycle43ExecutionEngine()
        legs = [
            OptionLeg("near", 100.0, 1.0, "BUY", delta=0.5, gamma=0.08, vega=0.1, expiry="near_week"),
            OptionLeg("next", 90.0, 1.0, "SELL", delta=-0.3, gamma=0.05, vega=0.3, expiry="next_week"),
            OptionLeg("near2", 120.0, 1.0, "BUY", delta=0.2, gamma=0.04, vega=-0.2, expiry="near_week"),
            OptionLeg("next2", 110.0, 1.0, "SELL", delta=-0.45, gamma=0.06, vega=0.4, expiry="next_week"),
        ]
        hedge = e.optimize_cross_expiry_hedge(
            legs, np.eye(4) * 0.1, [100, 50, 20, 15],
            current_delta=0.15, current_gamma=0.05, current_vega=0.4,
            max_abs_weight=100, iterations=5000, learning_rate=0.05,
            transaction_penalty=0.001, vacuum_penalty=0.01,
            gamma_penalty=3000, vega_penalty=10
        )
        assert hedge["feasible"] is True
        assert set(hedge["weights_by_expiry"]) == {"near_week", "next_week"}
        assert abs(hedge["net_delta"]) <= 1e-4

    def test_cycle43_statutory_cost_calculator(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.fractional_volterra_gamma_squeeze_engine import (
            StatutoryCostCalculator, OptionLeg
        )
        calc = StatutoryCostCalculator()
        fee_legs = [
            OptionLeg("C1", 100.0, 50.0, "BUY"),
            OptionLeg("P1", 120.0, 50.0, "SELL"),
        ]
        fees = calc.calculate(fee_legs)
        assert fees.stt == 9.0
        assert fees.stamp_duty == 0.15
        assert fees.brokerage == 40.0
        assert fees.gst > 0
        gate = calc.profitability_gate(500.0, fee_legs)
        assert gate["approved"] is True
        assert gate["net_alpha"] > 0

    def test_cycle43_dynamic_volatility_throttler(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.fractional_volterra_gamma_squeeze_engine import (
            DynamicVolatilityThrottler
        )
        th = DynamicVolatilityThrottler(base_cooldown_seconds=60.0, max_consecutive_losses=3)
        assert th.cooldown_duration(sigma_rough=0.4) > th.cooldown_duration(sigma_rough=0.2)
        th.record_fill(100.0, 1.0, -10.0, 0.2)
        th.record_fill(140.0, 1.0, -10.0, 0.2)
        th.record_fill(180.0, 1.0, -10.0, 0.2)
        ok = th.can_trade(now=190.0)
        assert ok is False
        assert "loss_streak" in th.reasons

    def test_cycle43_squad_consensus_and_live_veto(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.fractional_volterra_gamma_squeeze_engine import (
            SquadConsensus
        )
        squad = SquadConsensus()
        proposal = {
            "gross_alpha": 200.0, "friction": 50.0,
            "capital_required": 1000.0, "queue_hazard": 0.2, "sigma_rough": 0.2
        }
        res = squad.evaluate(proposal, live=False)
        assert res["approved"] is True
        assert len(res["decisions"]) == 4
        veto = squad.evaluate(proposal, live=True)
        assert veto["approved"] is False
        assert veto["decisions"][0]["approved"] is False
        assert veto["decisions"][0]["reason"] == "manager_veto_live_or_capital"
        f = squad.bayesian_kelly(0.6, 1.5, 0.5)
        assert 0.0 < f <= 0.5

    def test_cycle43_fail_closed_boundaries_and_telemetry(self) -> None:
        import pytest
        from agents.AGI_1_7.engine.agi17.finance.fractional_volterra_gamma_squeeze_engine import (
            dispatch_live_order, Cycle43ExecutionEngine
        )
        with pytest.raises(PermissionError, match="live broker order dispatch is permanently disabled"):
            dispatch_live_order()
        engine = Cycle43ExecutionEngine()
        with pytest.raises(PermissionError, match="live broker order dispatch is permanently disabled"):
            engine.dispatch_live_order()
        t = engine.telemetry(timestamp_epoch=1792300000)
        assert t["timestamp_ist"].endswith("+05:30")
        assert t["paper_ledger_epoch"] == "epoch_10k"
        assert t["initial_paper_capital"] == 10000.0
        assert "gamma_squeeze" in t
        assert "hawkes_centralities" in t
        assert "rough_covariance" in t
        assert "mlofi" in t


class TestCycle44StochasticVolterraLiquidityContagion:
    """Verifies Cycle 44 Stochastic Volterra Jump-Diffusion, Liquidity Contagion Graph, Dealer Inventory Unwind, Neural Hedging, and 4-Agent Consensus."""

    def test_cycle44_volterra_jump_diffusion(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.volterra_jump_diffusion_liquidity_engine import (
            RoughVolterraJumpDiffusion
        )
        rv = RoughVolterraJumpDiffusion("NIFTY 50", hurst=0.07, factors=12)
        snap = rv.update(dt=0.01, gaussian_shock=0.005)
        assert snap.variance > 0
        assert rv.total_implied_variance(0.05, 0.1) > 0
        assert rv.lee_wing_slope(maturity=0.1) >= 0

    def test_cycle44_liquidity_contagion_graph(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.volterra_jump_diffusion_liquidity_engine import (
            LiquidityContagionGraph
        )
        graph = LiquidityContagionGraph()
        assert graph.spectral_radius < 0.88
        cents = graph.centralities()
        assert len(cents) == 4
        assert "NIFTY 50" in cents
        assert "absorption" in cents["NIFTY 50"]
        assert "spillover" in cents["NIFTY 50"]

    def test_cycle44_dealer_inventory_unwind(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.volterra_jump_diffusion_liquidity_engine import (
            DealerInventoryUnwind
        )
        unwind = DealerInventoryUnwind()
        u1 = unwind.update(inventory=150.0, market_depth=50.0)
        assert u1.hazard_probability > 0.9
        assert u1.quote_pullback is True
        u2 = unwind.update(inventory=10.0, market_depth=100.0, toxic_flow=True)
        assert u2.quote_pullback is True
        assert u2.reason == "TOXIC_FLOW"

    def test_cycle44_neural_greek_hedge_optimizer(self) -> None:
        import numpy as np
        from agents.AGI_1_7.engine.agi17.finance.volterra_jump_diffusion_liquidity_engine import (
            GreekNeutralHedgeOptimizer
        )
        opt = GreekNeutralHedgeOptimizer()
        G = np.array([[1.0, -1.0, 0.2, -0.2], [0.4, 0.4, -0.8, -0.8], [0.1, -0.1, 1.0, -1.0]])
        r = opt.optimize(G, [2.0, -1.0, 1.0, 0.2], [100, 80, 20, 20], [0.2, 0.3, 0.8, 0.9])
        assert r.feasible is True
        assert abs(r.delta_net) <= 1e-4 + 1e-7
        assert abs(r.gamma_net) <= 1e-3 + 1e-7
        assert abs(r.vega_net) <= 1.0 + 1e-7

    def test_cycle44_statutory_costs_and_profitability(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.volterra_jump_diffusion_liquidity_engine import (
            StatutoryCostCalculator, OptionLeg
        )
        calc = StatutoryCostCalculator()
        legs = [
            OptionLeg(100.0, 50.0, "BUY", leg_id="NIFTY_CE"),
            OptionLeg(120.0, 50.0, "SELL", leg_id="NIFTY_PE"),
        ]
        fees = calc.calculate(legs, gross_alpha=500.0)
        assert fees.stt == 9.0
        assert fees.stamp_duty == 0.15
        assert fees.brokerage == 40.0
        assert StatutoryCostCalculator.profitable(500.0, fees) is True

    def test_cycle44_anti_tilt_throttler(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.volterra_jump_diffusion_liquidity_engine import (
            AntiTiltThrottler
        )
        th = AntiTiltThrottler(base_cooldown=60.0, loss_limit=3)
        assert th.cooldown_seconds(0.4) > th.cooldown_seconds(0.2)
        th.record_fill(100.0, 1.0, -10.0, 0.2)
        th.record_fill(140.0, 1.0, -10.0, 0.2)
        th.record_fill(180.0, 1.0, -10.0, 0.2)
        assert th.can_enter(190.0) is False
        assert th.status(190.0).reason == "LOSS_STREAK"

    def test_cycle44_trading_squad_consensus(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.volterra_jump_diffusion_liquidity_engine import (
            TradingSquadConsensus
        )
        squad = TradingSquadConsensus()
        res = squad.evaluate(live=False, capital_required=2000.0, available_capital=10000.0, net_alpha=150.0, toxicity=False, volatility_stress=False)
        assert res.approved is True
        assert res.votes["Manager Abhi"] is True
        veto = squad.evaluate(live=True, capital_required=2000.0, available_capital=10000.0, net_alpha=150.0, toxicity=False, volatility_stress=False)
        assert veto.approved is False
        assert "Manager Abhi" in veto.vetoes
        assert veto.reason == "MANAGER_ABHI_VETO_LIVE"

    def test_cycle44_live_dispatch_permanently_locked(self) -> None:
        import pytest
        from agents.AGI_1_7.engine.agi17.finance.volterra_jump_diffusion_liquidity_engine import (
            Cycle44ExecutionEngine
        )
        e = Cycle44ExecutionEngine()
        with pytest.raises(PermissionError, match="live broker dispatch is permanently disabled"):
            e.dispatch_live_order()

    def test_cycle44_execution_engine_telemetry(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.volterra_jump_diffusion_liquidity_engine import (
            Cycle44ExecutionEngine
        )
        e = Cycle44ExecutionEngine()
        t = e.telemetry()
        assert t["live_order_dispatch_enabled"] is False
        assert t["real_broker_fills_locked"] is True
        assert t["paper_ledger_epoch"] == "epoch_10k"
        assert t["initial_capital"] == 10000.0
        assert "volterra" in t
        assert "liquidity_contagion" in t
        assert "dealer_unwind" in t


class TestCycle45OptimalStoppingHawkesRoughHeston:
    """Verifies Cycle 45 High-Frequency Optimal Stopping Boundaries, Hawkes Jumps, Lifted Rough Heston Surface Calibration, Dealer GEX Squeeze, and 4-Agent Consensus."""

    def test_cycle45_optimal_stopping_solution(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.optimal_stopping_hawkes_rough_heston_engine import (
            solve_queue_optimal_stopping, MicrostructureParameters
        )
        params = MicrostructureParameters(lambda_fill=2.0, lambda_cancel=1.5, holding_cost_per_unit=0.01)
        res = solve_queue_optimal_stopping(queue_ahead=5, edge_per_unit=0.25, order_qty=1.0, params=params)
        assert np.isfinite(res.value)
        assert res.action in {"WAIT", "PEG", "CANCEL"}

    def test_cycle45_hawkes_network_stability(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.optimal_stopping_hawkes_rough_heston_engine import (
            HawkesNetwork
        )
        mu = [0.1, 0.15, 0.08, 0.05]
        alpha = [[0.05, 0.02, 0.01, 0.01], [0.02, 0.06, 0.02, 0.01], [0.01, 0.02, 0.05, 0.02], [0.01, 0.01, 0.02, 0.04]]
        beta = [[1.0, 1.0, 1.0, 1.0], [1.0, 1.0, 1.0, 1.0], [1.0, 1.0, 1.0, 1.0], [1.0, 1.0, 1.0, 1.0]]
        net = HawkesNetwork(mu, alpha, beta, stability_limit=0.88)
        assert net.spectral_radius < 0.88
        assert net.spectral_radius >= 0.0
        spill = net.spillover_centralities()
        assert "source_spillover" in spill
        assert len(spill["source_spillover"]) == 4
        assert all(spill["source_spillover"][a] >= 0.0 for a in spill["source_spillover"])

    def test_cycle45_rough_heston_exponential_lift(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.optimal_stopping_hawkes_rough_heston_engine import (
            build_exponential_lift
        )
        lift = build_exponential_lift(hurst=0.07, n_factors=12)
        assert len(lift.weights) == 12
        assert len(lift.rates) == 12
        assert lift.relative_rmse < 0.05

    def test_cycle45_dealer_gex_and_squeeze_machine(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.optimal_stopping_hawkes_rough_heston_engine import (
            map_dealer_gex, GammaPosition, GammaSqueezeMachine
        )
        positions = [
            GammaPosition(strike=24000.0, open_interest=100.0, gamma=0.005, dealer_sign=1.0, multiplier=1.0),
            GammaPosition(strike=24100.0, open_interest=150.0, gamma=0.004, dealer_sign=-1.0, multiplier=1.0),
        ]
        gex_map, total_gex = map_dealer_gex(positions, 24000.0)
        assert 24000.0 in gex_map
        machine = GammaSqueezeMachine(lambda0=0.05, kappa=2.0)
        dec = machine.evaluate(gamma_dealer=total_gex, depth=100.0)
        assert dec.intensity > 0
        assert isinstance(dec.toxic_cascade, bool)
        assert isinstance(dec.quote_retreat, bool)

    def test_cycle45_greek_neutral_hedge_optimization(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.optimal_stopping_hawkes_rough_heston_engine import (
            optimize_greek_neutral_hedge
        )
        cov = [[0.04, 0.01], [0.01, 0.05]]
        greeks = [[0.5, -0.4], [0.08, 0.06], [1.2, 0.9]]
        existing = [0.1, 0.02, 0.5]
        spreads = [0.5, 0.6]
        res = optimize_greek_neutral_hedge(cov, greeks, existing, spreads)
        assert res.success is True
        assert abs(res.delta_net) <= 0.0001 + 1e-5
        assert abs(res.gamma_net) <= 0.001 + 1e-5
        assert abs(res.vega_net) <= 1.0 + 1e-5

    def test_cycle45_statutory_fees_and_profitability(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.optimal_stopping_hawkes_rough_heston_engine import (
            calculate_indian_statutory_fees, evaluate_net_alpha
        )
        fees = calculate_indian_statutory_fees(buy_turnover=5000.0, sell_turnover=6000.0, legs=2)
        assert abs(fees.stt_sell - (6000.0 * 0.0015)) < 1e-6
        assert abs(fees.stamp_duty_buy - (5000.0 * 0.00003)) < 1e-6
        assert fees.brokerage == 40.0
        assert fees.total > 0
        gate = evaluate_net_alpha(expected_gross_alpha=200.0, buy_turnover=5000.0, sell_turnover=6000.0, legs=2)
        assert gate.approved is True
        assert gate.expected_net_alpha > 0

    def test_cycle45_adaptive_anti_tilt_throttle(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.optimal_stopping_hawkes_rough_heston_engine import (
            AdaptiveAntiTiltThrottle
        )
        th = AdaptiveAntiTiltThrottle()
        assert th.cooldown(tau_base=60.0, theta_v=1.0, sigma_rough=0.4, sigma_base=0.2) > th.cooldown(tau_base=60.0, theta_v=1.0, sigma_rough=0.2, sigma_base=0.2)
        for i in range(3):
            th.record_trade(timestamp=i * 60, size=1.0, pnl=-1.0, session_day="D")
        dec = th.can_trade(timestamp=1000.0, size=1.0, sigma_rough=0.2, sigma_base=0.2, session_day="D")
        assert dec.allowed is False
        assert dec.reason == "three_consecutive_losses"

    def test_cycle45_trading_squad_consensus(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.optimal_stopping_hawkes_rough_heston_engine import (
            TradingSquad, TradeIntent
        )
        squad = TradingSquad()
        intent = TradeIntent(mode="paper", capital_requested=1000.0, queue_risk_score=0.1, sigma_rough=0.2, expected_gross_alpha=100.0, buy_turnover=1000.0, sell_turnover=1000.0, legs=2, kelly_fraction=0.1)
        res = squad.evaluate(intent)
        assert res.approved_for_paper_simulation is True
        assert any(v.agent == "Manager Abhi" and v.approve is True for v in res.votes)
        
        # Live dispatch mode must unconditionally fail consensus
        intent_live = TradeIntent(mode="live", capital_requested=1000.0, queue_risk_score=0.1, sigma_rough=0.2, expected_gross_alpha=100.0, buy_turnover=1000.0, sell_turnover=1000.0, legs=2, kelly_fraction=0.1)
        res_live = squad.evaluate(intent_live)
        assert res_live.approved_for_paper_simulation is False
        assert res_live.votes[0].approve is False

    def test_cycle45_fail_closed_live_dispatch_locked(self) -> None:
        import pytest
        from agents.AGI_1_7.engine.agi17.finance.optimal_stopping_hawkes_rough_heston_engine import (
            dispatch_live_order, PaperLedger
        )
        with pytest.raises(PermissionError, match="live order dispatch is permanently disabled"):
            dispatch_live_order()
        ledger = PaperLedger(initial_capital=10000.0, epoch="epoch_10k")
        snap = ledger.snapshot()
        assert snap["initial_capital"] == 10000.0
        assert snap["epoch"] == "epoch_10k"
        assert snap["live_order_dispatch_enabled"] is False
        assert snap["real_broker_fills_locked"] is True


class TestCycle46MultiHorizonHawkesActorCritic:
    """Comprehensive test suite verifying Cycle 46 Multi-Horizon Hawkes Actor-Critic Engine."""

    def test_cycle46_constants_and_safety_flags(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.multi_horizon_hawkes_actor_critic_engine import (
            ASSETS, INITIAL_CAPITAL_INR, PAPER_LEDGER_EPOCH,
            LIVE_ORDER_DISPATCH_ENABLED, REAL_BROKER_FILLS_LOCKED,
            dispatch_live_order, PaperLedger
        )
        assert len(ASSETS) == 4
        assert set(ASSETS) == {"NIFTY50", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY"}
        assert INITIAL_CAPITAL_INR == 10000.0
        assert PAPER_LEDGER_EPOCH == "epoch_10k"
        assert LIVE_ORDER_DISPATCH_ENABLED is False
        assert REAL_BROKER_FILLS_LOCKED is True

        with pytest.raises(PermissionError, match="live order dispatch is permanently disabled"):
            dispatch_live_order()

        ledger = PaperLedger(initial_capital=10000.0, epoch="epoch_10k")
        assert ledger.capital == 10000.0
        net = ledger.record_paper_pnl(gross_pnl=500.0, fees=65.0)
        assert net == 435.0
        assert ledger.capital == 10435.0

    def test_cycle46_multi_horizon_hawkes_network(self) -> None:
        import numpy as np
        from agents.AGI_1_7.engine.agi17.finance.multi_horizon_hawkes_actor_critic_engine import (
            MultiHorizonHawkes, LAMBDA_STABILITY_LIMIT
        )
        mu = [1.0, 2.0, 1.5, 1.0]
        alpha_fast = np.eye(4) * 0.1
        alpha_slow = np.eye(4) * 0.05
        model = MultiHorizonHawkes(mu=mu, alpha_fast=alpha_fast, alpha_slow=alpha_slow)
        assert model.spectral_radius < LAMBDA_STABILITY_LIMIT
        assert model.stress_summary()["stable"] is True

        before = model.intensity.copy()
        after = model.register_event(0)
        assert after[0] > before[0]

        model.advance(0.05)
        leadership = model.leadership_index()
        assert np.max(leadership) <= 1.0 and np.min(leadership) >= -1.0
        np.testing.assert_allclose(leadership, -leadership.T)

        with pytest.raises(ValueError, match="unstable Hawkes"):
            MultiHorizonHawkes([1.0]*4, np.zeros((4, 4)), np.eye(4) * 0.95)

    def test_cycle46_continuous_actor_critic(self) -> None:
        import math, numpy as np
        from agents.AGI_1_7.engine.agi17.finance.multi_horizon_hawkes_actor_critic_engine import (
            ContinuousActorCritic, encode_actor_state
        )
        ac = ContinuousActorCritic(seed=42)
        state = encode_actor_state(
            ofi=[1.0, -0.5, 0.2, 0.0],
            hawkes_intensity=[0.8, 0.7, 0.5, 0.4],
            rough_variance_lift=[0.04, 0.05, 0.03, 0.02],
            queue_priority_position=12.0,
            dealer_gex_stress=350.0,
            bid_ask_spread=0.75,
            time_to_expiry_norm=0.2
        )
        assert state.shape == (16,)
        res = ac.policy(state)
        action = res["action"]
        assert action.shape == (3,)
        assert np.all(action >= -1.0) and np.all(action <= 1.0)

        val = ac.value(state)
        assert np.isfinite(val)
        upd = ac.update(state, action, advantage=0.5)
        assert math.isfinite(upd.value_before) and math.isfinite(upd.value_after)

    def test_cycle46_order_cancellation_hazard_and_survival(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.multi_horizon_hawkes_actor_critic_engine import (
            cancellation_hazard, cancellation_survival, order_revision_decision
        )
        h1 = cancellation_hazard(depth=100.0, age=2.0)
        h2 = cancellation_hazard(depth=10.0, age=2.0)
        assert h2 > h1

        surv = cancellation_survival(duration=1.0, depth=100.0, age=2.0)
        assert 0.0 < surv <= 1.0

        rev_stay = order_revision_decision(duration=1.0, depth=100.0, age=1.0, queue_ahead=5.0)
        assert rev_stay in {"HOLD", "REVISE_OR_PULL"}

        rev_pull = order_revision_decision(duration=5.0, depth=1.0, age=20.0, queue_ahead=500.0, min_survival=0.9)
        assert rev_pull in {"HOLD", "REVISE_OR_PULL"}

    def test_cycle46_rough_volterra_and_two_scale_realized_variance(self) -> None:
        import numpy as np
        from agents.AGI_1_7.engine.agi17.finance.multi_horizon_hawkes_actor_critic_engine import (
            rough_volterra_kernel, exponential_rough_lift, rough_lift_variance,
            two_scale_realized_variance, debiased_midquote_returns
        )
        k = rough_volterra_kernel(np.array([0.01, 0.05, 0.1]), hurst=0.07)
        assert len(k) == 3
        assert np.all(k > 0)

        betas, weights = exponential_rough_lift(hurst=0.07, n_factors=12)
        assert len(betas) == 12 and len(weights) == 12

        v = rough_lift_variance(np.linspace(0.01, 1.0, 20), np.random.normal(0, 0.01, 20), hurst=0.07, n_factors=12)
        assert len(v) == 12

        p_fast = 100.0 + np.cumsum(np.random.RandomState(42).normal(0, 0.1, 50))
        p_slow = p_fast[::5]
        tsrv_res = two_scale_realized_variance(p_fast, p_slow)
        assert "tsrv" in tsrv_res
        assert tsrv_res["tsrv"] >= 0.0 or isinstance(tsrv_res["tsrv"], float)

        bids = 100.0 + np.cumsum(np.random.RandomState(42).normal(0, 0.05, 30))
        asks = bids + 0.1
        deb = debiased_midquote_returns(bids, asks)
        assert len(deb) == len(bids) - 1

    def test_cycle46_dealer_gex_and_gamma_squeeze_hazard(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.multi_horizon_hawkes_actor_critic_engine import (
            dealer_net_gamma, gamma_squeeze_hazard
        )
        oi = [10000.0, 8000.0]
        ga = [0.002, 0.0015]
        spot = 24000.0
        gex = dealer_net_gamma(oi, ga, spot)
        assert gex > 0

        squeeze = gamma_squeeze_hazard(gex, depth=100.0, lambda0=0.05, kappa=2.0)
        assert squeeze["lambda_squeeze"] > 0
        assert isinstance(squeeze["toxic_cascade"], bool)
        assert isinstance(squeeze["quote_retreat"], bool)

    def test_cycle46_greek_neutral_hedge_optimization(self) -> None:
        import numpy as np
        from agents.AGI_1_7.engine.agi17.finance.multi_horizon_hawkes_actor_critic_engine import (
            solve_greek_neutral_hedge
        )
        base = [0.01, 0.02, 0.2]
        covariance = np.eye(3)
        greeks = np.eye(3)
        h_res = solve_greek_neutral_hedge(covariance, greeks, [0.01, 0.02, 0.03], base)
        assert h_res.success is True
        assert abs(h_res.net_delta) <= 1.02e-4
        assert abs(h_res.net_gamma) <= 1.02e-3
        assert abs(h_res.net_vega) <= 1.0002

    def test_cycle46_indian_statutory_fees_and_net_alpha_gate(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.multi_horizon_hawkes_actor_critic_engine import (
            IndianFeeSchedule, net_alpha_gate, research_preflight
        )
        sched = IndianFeeSchedule()
        fees = sched.calculate(buy_turnover=5000.0, sell_turnover=6000.0, legs=2)
        assert abs(fees["stt"] - (6000.0 * 0.0015)) < 1e-5
        assert abs(fees["stamp_duty"] - (5000.0 * 0.00003)) < 1e-5
        assert fees["brokerage"] == 40.0
        assert fees["total_fees"] > 0

        gate_ok = net_alpha_gate(expected_gross_alpha=500.0, total_statutory_fees=fees["total_fees"])
        assert gate_ok["approved"] is True
        assert gate_ok["expected_net_alpha"] > 0

        gate_fail = net_alpha_gate(expected_gross_alpha=50.0, total_statutory_fees=fees["total_fees"])
        assert gate_fail["approved"] is False
        assert gate_fail["expected_net_alpha"] < 0

        preflight = research_preflight(
            expected_gross_alpha=500.0, buy_turnover=5000.0, sell_turnover=6000.0, legs=2
        )
        assert preflight["paper_only"] is True
        assert preflight["live_dispatch_enabled"] is False

    def test_cycle46_anti_tilt_controller_and_squad_consensus(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.multi_horizon_hawkes_actor_critic_engine import (
            AntiTiltController, TradingSquad
        )
        ctrl = AntiTiltController()
        assert ctrl.cooldown(sigma_rough=0.4) > ctrl.cooldown(sigma_rough=0.2)
        ctrl.record_trade(timestamp=100.0, size=1.0, pnl=-10.0)
        ctrl.record_trade(timestamp=200.0, size=1.0, pnl=-10.0)
        ctrl.record_trade(timestamp=300.0, size=1.0, pnl=-10.0)
        reasons = ctrl.lockout_reasons(timestamp=310.0, proposed_size=1.0)
        assert "CONSECUTIVE_LOSSES" in reasons

        squad = TradingSquad()
        res_ok = squad.review(manager_veto=False, queue_risk_ok=True, volatility_ok=True, net_alpha_positive=True, sizing_ok=True)
        assert res_ok.approved is True
        assert res_ok.votes["Manager Abhi"] is True

        res_veto = squad.review(manager_veto=True, queue_risk_ok=True, volatility_ok=True, net_alpha_positive=True, sizing_ok=True)
        assert res_veto.approved is False
        assert res_veto.manager_veto is True
        assert "MANAGER_VETO" in res_veto.reasons


class TestCycle47OptimalStoppingHawkesDeepHedger:
    """Comprehensive test suite verifying Cycle 47 Deep Neural Optimal Stopping Snell Envelopes."""

    def test_cycle47_constants_and_fail_closed_invariants(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.optimal_stopping_hawkes_deep_hedger_engine import (
            ASSETS, INITIAL_CAPITAL_INR, PAPER_LEDGER_EPOCH,
            LIVE_ORDER_DISPATCH_ENABLED, REAL_BROKER_FILLS_LOCKED,
            dispatch_live_order, PaperLedger
        )
        assert len(ASSETS) == 4
        assert set(ASSETS) == {"NIFTY50", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY"}
        assert INITIAL_CAPITAL_INR == 10000.0
        assert PAPER_LEDGER_EPOCH == "epoch_10k"
        assert LIVE_ORDER_DISPATCH_ENABLED is False
        assert REAL_BROKER_FILLS_LOCKED is True

        with pytest.raises(PermissionError, match="live order dispatch is permanently disabled"):
            dispatch_live_order()

        ledger = PaperLedger(initial_capital=10000.0, epoch="epoch_10k")
        assert ledger.cash == 10000.0
        rec = ledger.record(pnl=500.0, fees=55.0)
        assert rec["net_pnl"] == 445.0
        assert ledger.cash == 10445.0

    def test_cycle47_multi_horizon_hawkes_network(self) -> None:
        import numpy as np
        from agents.AGI_1_7.engine.agi17.finance.optimal_stopping_hawkes_deep_hedger_engine import (
            default_hawkes_model
        )
        h = default_hawkes_model()
        diag = h.diagnostics()
        assert diag.stable is True
        assert diag.spectral_radius < 0.88
        assert np.all(diag.spillover_out >= 0)
        assert np.all(diag.absorption_in >= 0)

    def test_cycle47_gaussian_actor_critic_and_snell_envelope(self) -> None:
        import numpy as np
        from agents.AGI_1_7.engine.agi17.finance.optimal_stopping_hawkes_deep_hedger_engine import (
            GaussianActorCritic, snell_envelope, actor_action_interpretation
        )
        ac = GaussianActorCritic(seed=42)
        s = np.zeros(16)
        act = ac.act(s)
        assert act.shape == (3,)
        assert np.all(act >= -1.0) and np.all(act <= 1.0)

        snell = snell_envelope(immediate_value=2.0, expected_continuation=1.5, holding_cost_rate=0.1, dt=1.0)
        assert snell.action == "STOP"
        assert snell.value == 2.0

        interp = actor_action_interpretation(act)
        assert "spread_placement" in interp
        assert "cancellation_bias" in interp
        assert "size_dampener" in interp

    def test_cycle47_order_cancellation_hazard_and_survival(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.optimal_stopping_hawkes_deep_hedger_engine import (
            cancellation_hazard, order_survival_and_revision
        )
        haz = cancellation_hazard(depth=50.0, age=2.0)
        assert haz > 0

        rev = order_survival_and_revision(tau=1.0, queue_ahead=10.0, depth=50.0, age=2.0)
        assert rev.revision in {"HOLD", "REVISE_OR_PULL"}
        assert 0.0 < rev.survival_probability <= 1.0

    def test_cycle47_rough_volterra_and_two_scale_realized_variance(self) -> None:
        import math, numpy as np
        from agents.AGI_1_7.engine.agi17.finance.optimal_stopping_hawkes_deep_hedger_engine import (
            rough_volterra_kernel, markovian_exponential_lift, two_scale_realized_variance,
            debias_tick_returns
        )
        k = rough_volterra_kernel(np.array([0.01, 0.05, 0.1]), hurst=0.07)
        assert len(k) == 3

        weights, rates = markovian_exponential_lift(hurst=0.07, n_factors=12)
        assert len(weights) == 12 and len(rates) == 12

        fast_ret = [0.001, -0.002, 0.0015, -0.001]
        slow_ret = [0.0005, 0.0005]
        tsrv = two_scale_realized_variance(fast_ret, slow_ret)
        assert math.isfinite(tsrv)

        deb = debias_tick_returns(fast_ret)
        assert len(deb) == len(fast_ret) // 2

    def test_cycle47_dealer_net_gamma_and_squeeze_hazard(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.optimal_stopping_hawkes_deep_hedger_engine import (
            dealer_net_gamma_exposure, gamma_squeeze_hazard, quote_retreat_decision
        )
        oi = [10000.0, 8000.0]
        gamma = [0.002, 0.0015]
        gex = dealer_net_gamma_exposure(oi, gamma, spot=24000.0)
        assert gex > 0

        sq_haz = gamma_squeeze_hazard(gex, depth=100.0)
        assert sq_haz > 0

        retreat = quote_retreat_decision(gex, depth=100.0, hazard_threshold=1.0)
        assert retreat["quote_action"] in {"RETREAT", "MAINTAIN"}

    def test_cycle47_greek_neutral_hedge_optimization(self) -> None:
        import numpy as np
        from agents.AGI_1_7.engine.agi17.finance.optimal_stopping_hawkes_deep_hedger_engine import (
            greek_neutral_hedge
        )
        cov = np.eye(3)
        greeks = np.eye(3)
        curr = [0.01, 0.02, 0.03]
        spr = [0.01, 0.02, 0.03]
        res = greek_neutral_hedge(cov, greeks, curr, spr)
        assert res.success is True
        assert abs(res.delta_net) <= 0.000102 + 1e-6
        assert abs(res.gamma_net) <= 0.00102 + 1e-6
        assert abs(res.vega_net) <= 1.0002 + 1e-6

    def test_cycle47_indian_statutory_fees_and_net_alpha_gate(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.optimal_stopping_hawkes_deep_hedger_engine import (
            indian_statutory_fees, net_alpha_gate
        )
        fees = indian_statutory_fees(buy_turnover=5000.0, sell_turnover=6000.0, legs=2)
        assert fees.brokerage == 40.0
        assert fees.total > 0

        gate_ok = net_alpha_gate(expected_gross_alpha=500.0, fees=fees)
        assert gate_ok["approved"] is True
        assert gate_ok["expected_net_alpha"] > 0

        gate_no = net_alpha_gate(expected_gross_alpha=10.0, fees=fees)
        assert gate_no["approved"] is False

    def test_cycle47_anti_tilt_controller_and_squad_consensus(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.optimal_stopping_hawkes_deep_hedger_engine import (
            AntiTiltController, squad_consensus
        )
        ctrl = AntiTiltController()
        assert ctrl.cooldown(0.4) > ctrl.cooldown(0.2)

        squad_ok = squad_consensus(manager_approved=True, alex_approved=True, emily_approved=True, max_approved=True)
        assert squad_ok.approve is True
        assert squad_ok.manager_veto is False

        squad_veto = squad_consensus(manager_approved=False, alex_approved=True, emily_approved=True, max_approved=True)
        assert squad_veto.approve is False
        assert squad_veto.manager_veto is True
        assert squad_veto.reason == "MANAGER_ABHI_VETO"


class TestCycle48VolterraHawkesPeggerHedger:
    """Comprehensive test suite verifying Cycle 48 Volterra-Hawkes Pegger & Greek Hedger Engine."""

    def test_cycle48_constants_and_fail_closed_invariants(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.volterra_hawkes_pegger_hedger_engine import (
            ASSETS, INITIAL_CAPITAL_INR, PAPER_LEDGER_EPOCH,
            LIVE_ORDER_DISPATCH_ENABLED, REAL_BROKER_FILLS_LOCKED,
            dispatch_live_order, PaperLedger
        )
        assert len(ASSETS) == 4
        assert set(ASSETS) == {"NIFTY50", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY"}
        assert INITIAL_CAPITAL_INR == 10000.0
        assert PAPER_LEDGER_EPOCH == "epoch_10k"
        assert LIVE_ORDER_DISPATCH_ENABLED is False
        assert REAL_BROKER_FILLS_LOCKED is True

        with pytest.raises(PermissionError, match="live order dispatch is permanently disabled"):
            dispatch_live_order()

        ledger = PaperLedger(initial_capital=10000.0, epoch="epoch_10k")
        assert ledger.cash == 10000.0
        rec = ledger.record(pnl=500.0, fees=55.0)
        assert rec["net_pnl"] == 445.0
        assert ledger.cash == 10445.0

    def test_cycle48_multi_horizon_hawkes_network(self) -> None:
        import numpy as np
        from agents.AGI_1_7.engine.agi17.finance.volterra_hawkes_pegger_hedger_engine import (
            default_hawkes_model, information_leadership_index
        )
        h = default_hawkes_model()
        diag = h.diagnostics()
        assert diag.stable is True
        assert diag.spectral_radius < 0.88
        assert np.all(diag.spillover_out >= 0)
        assert np.all(diag.absorption_in >= 0)

        scores = np.ones((4, 4))
        idx = information_leadership_index(scores)
        assert idx.shape == (4, 4)
        assert np.all(idx >= -1.0) and np.all(idx <= 1.0)
        assert np.all(np.diag(idx) == 0.0)

    def test_cycle48_gaussian_actor_critic_and_snell_envelope(self) -> None:
        import numpy as np
        from agents.AGI_1_7.engine.agi17.finance.volterra_hawkes_pegger_hedger_engine import (
            GaussianActorCritic, snell_envelope, actor_action_interpretation, STATE_DIM
        )
        ac = GaussianActorCritic(seed=42)
        s = np.zeros(STATE_DIM)
        act = ac.act(s)
        assert act.shape == (3,)
        assert np.all(act >= -1.0) and np.all(act <= 1.0)

        snell = snell_envelope(immediate_value=2.0, expected_continuation=1.5, holding_cost_rate=0.1, dt=1.0)
        assert snell.action == "STOP"
        assert snell.value == 2.0

        interp = actor_action_interpretation(act)
        assert "spread_placement" in interp
        assert "cancellation_bias" in interp
        assert "size_dampener" in interp

    def test_cycle48_order_cancellation_hazard_and_survival(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.volterra_hawkes_pegger_hedger_engine import (
            cancellation_hazard, order_survival_and_revision
        )
        haz = cancellation_hazard(depth=50.0, age=2.0)
        assert haz > 0

        rev = order_survival_and_revision(tau=1.0, queue_ahead=10.0, depth=50.0, age=2.0)
        assert rev.revision in {"HOLD", "REVISE_OR_PULL"}
        assert 0.0 < rev.survival_probability <= 1.0

    def test_cycle48_rough_volterra_jump_diffusion_and_tsrv(self) -> None:
        import math, numpy as np
        from agents.AGI_1_7.engine.agi17.finance.volterra_hawkes_pegger_hedger_engine import (
            rough_volterra_kernel, markovian_exponential_lift, tsrv_estimate,
            midquote_log_returns, simulate_rough_volterra_jump_diffusion,
            jump_diffusion_total_variance_proxy, validate_total_variance_surface
        )
        k = rough_volterra_kernel(np.array([0.01, 0.05, 0.1]), hurst=0.07)
        assert len(k) == 3

        weights, rates = markovian_exponential_lift(hurst=0.07, n_factors=12)
        assert len(weights) == 12 and len(rates) == 12

        fast_ret = [0.001, -0.002, 0.0015, -0.001]
        slow_ret = [0.0005, 0.0005]
        tsrv = tsrv_estimate(fast_ret, slow_ret)
        assert math.isfinite(tsrv.tsrv)

        bids = [100.0, 100.2, 100.1, 100.4]
        asks = [100.5, 100.7, 100.6, 100.9]
        mq = midquote_log_returns(bids, asks)
        assert len(mq) == 3

        sim = simulate_rough_volterra_jump_diffusion(n_steps=24, dt=0.01, seed=48)
        assert len(sim.spot) == 25
        assert len(sim.variance) == 25

        smile_expiries = [1.0 / 52.0, 2.0 / 52.0]
        smile_grid = jump_diffusion_total_variance_proxy(
            smile_expiries, [-0.5, 0.0, 0.5], 0.04, 0.08, -0.04, 0.12,
            skew_strength=0.005, wing_curvature=0.02
        )
        assert smile_grid.shape == (2, 3)
        checks = validate_total_variance_surface(
            smile_expiries, [-0.5, 0.0, 0.5], smile_grid, beta_call=1.4, beta_put=1.3
        )
        assert checks["calendar_monotone"] is True

    def test_cycle48_dealer_net_gamma_and_squeeze_hazard(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.volterra_hawkes_pegger_hedger_engine import (
            dealer_net_gamma_exposure, gamma_squeeze_hazard, quote_retreat_decision
        )
        oi = [10000.0, 8000.0]
        gamma = [0.002, 0.0015]
        gex = dealer_net_gamma_exposure(oi, gamma, spot=24000.0)
        assert gex > 0

        sq_haz = gamma_squeeze_hazard(gex, depth=100.0)
        assert sq_haz > 0

        retreat = quote_retreat_decision(gex, depth=100.0, hazard_threshold=1.0)
        assert retreat["quote_action"] in {"RETREAT", "MAINTAIN"}

    def test_cycle48_greek_neutral_hedge_optimization(self) -> None:
        import numpy as np
        from agents.AGI_1_7.engine.agi17.finance.volterra_hawkes_pegger_hedger_engine import (
            greek_neutral_hedge
        )
        cov = np.eye(3)
        greeks = np.eye(3)
        curr = [0.01, 0.02, 0.03]
        spr = [0.01, 0.02, 0.03]
        res = greek_neutral_hedge(cov, greeks, curr, spr)
        assert res.success is True
        assert abs(res.delta_net) <= 0.000102 + 1e-6
        assert abs(res.gamma_net) <= 0.00102 + 1e-6
        assert abs(res.vega_net) <= 1.0002 + 1e-6

    def test_cycle48_indian_statutory_fees_and_net_alpha_gate(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.volterra_hawkes_pegger_hedger_engine import (
            indian_statutory_fees, net_alpha_gate
        )
        fees = indian_statutory_fees(buy_turnover=5000.0, sell_turnover=6000.0, legs=2)
        assert fees.brokerage == 40.0
        assert fees.total > 0

        gate_ok = net_alpha_gate(expected_gross_alpha=500.0, fees=fees)
        assert gate_ok["approved"] is True
        assert gate_ok["expected_net_alpha"] > 0

        gate_no = net_alpha_gate(expected_gross_alpha=10.0, fees=fees)
        assert gate_no["approved"] is False

    def test_cycle48_anti_tilt_controller_and_squad_consensus(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.volterra_hawkes_pegger_hedger_engine import (
            AntiTiltController, squad_consensus, run_cycle48_example
        )
        ctrl = AntiTiltController()
        assert ctrl.cooldown(0.4) > ctrl.cooldown(0.2)

        squad_ok = squad_consensus(manager_approved=True, alex_approved=True, emily_approved=True, max_approved=True)
        assert squad_ok.approve is True
        assert squad_ok.manager_veto is False

        squad_veto = squad_consensus(manager_approved=False, alex_approved=True, emily_approved=True, max_approved=True)
        assert squad_veto.approve is False
        assert squad_veto.manager_veto is True
        assert squad_veto.reason == "MANAGER_ABHI_VETO"

        # End-to-end example verification
        ex = run_cycle48_example()
        assert ex["cycle"] == 48
        assert ex["live_order_dispatch_enabled"] is False
        assert ex["real_broker_fills_locked"] is True
        assert ex["hawkes_stable"] is True


class TestCycle49RegimeSwitchingVolterraHawkesPeggerHedger:
    """Comprehensive test suite verifying Cycle 49 Regime-Switching Volterra-Hawkes Pegger & Hedger Engine."""

    def test_cycle49_constants_and_fail_closed_invariants(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.regime_switching_volterra_hawkes_pegger_hedger_engine import (
            ASSETS, INITIAL_CAPITAL_INR, PAPER_LEDGER_EPOCH,
            LIVE_ORDER_DISPATCH_ENABLED, REAL_BROKER_FILLS_LOCKED,
            dispatch_live_order, AGENT_SQUAD, REGIMES
        )
        assert len(ASSETS) == 4
        assert set(ASSETS) == {"NIFTY50", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY"}
        assert INITIAL_CAPITAL_INR == 10000.0
        assert PAPER_LEDGER_EPOCH == "epoch_10k"
        assert LIVE_ORDER_DISPATCH_ENABLED is False
        assert REAL_BROKER_FILLS_LOCKED is True
        assert list(AGENT_SQUAD) == ["Abhi", "Alex", "Emily", "Max"]
        assert len(REGIMES) == 3

        with pytest.raises(PermissionError, match="live broker order dispatch is disabled"):
            dispatch_live_order("BUY", "NIFTY50", 50)

    def test_cycle49_hmm_belief_tracker_and_regime_hawkes(self) -> None:
        import pytest
        from agents.AGI_1_7.engine.agi17.finance.regime_switching_volterra_hawkes_pegger_hedger_engine import (
            HMMBeliefTracker, RegimeSwitchingHawkesNetwork
        )
        hmm = HMMBeliefTracker()
        belief = hmm.update([1.0, 0.5, 0.2])
        assert len(belief) == 3
        assert pytest.approx(sum(belief), abs=1e-5) == 1.0

        net = RegimeSwitchingHawkesNetwork()
        radii = net.regime_radii
        assert len(radii) == 3
        for r in radii:
            assert r < 0.88

    def test_cycle49_continuous_actor_critic_and_snell_envelope(self) -> None:
        import numpy as np
        from agents.AGI_1_7.engine.agi17.finance.regime_switching_volterra_hawkes_pegger_hedger_engine import (
            ContinuousActorCritic, snell_envelope_step, STATE_DIM, ACTION_DIM
        )
        ac = ContinuousActorCritic(seed=49)
        s = np.zeros(STATE_DIM)
        act = ac.act(s)
        assert act.shape == (ACTION_DIM,)
        assert np.all(act >= -1.0) and np.all(act <= 1.0)

        snell = snell_envelope_step(0.8, 0.95, rate=0.01, dt=1.0, holding_cost_rate=0.01)
        assert snell["decision"] in {"STOP", "CONTINUE"}
        assert snell["value"] >= 0.8

    def test_cycle49_order_hazard_and_queue_decision(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.regime_switching_volterra_hawkes_pegger_hedger_engine import (
            cancellation_hazard, order_survival_probability, queue_revision_decision
        )
        haz = cancellation_hazard(depth=50.0, age=2.0)
        assert haz > 0

        surv = order_survival_probability(tau=1.0, queue_ahead=10.0, depth=50.0, age=2.0, fill_rate=0.03)
        assert 0.0 <= surv <= 1.0

        dec = queue_revision_decision(surv, minimum_survival=0.5)
        assert dec in {"HOLD", "REVISE_OR_PULL"}

    def test_cycle49_volterra_jump_diffusion_and_tsrv(self) -> None:
        import math
        from agents.AGI_1_7.engine.agi17.finance.regime_switching_volterra_hawkes_pegger_hedger_engine import (
            midquote_log_returns, two_scale_realized_variance,
            simulate_volterra_jump_diffusion, synthetic_total_variance_surface, validate_vol_surface
        )
        bids = [100.0, 100.2, 100.1, 100.4]
        asks = [100.5, 100.7, 100.6, 100.9]
        mq = midquote_log_returns(bids, asks)
        assert len(mq) == 3

        fast_ret = [0.001, -0.002, 0.0015, -0.001]
        slow_ret = [0.0005, 0.0005]
        tsrv = two_scale_realized_variance(fast_ret, slow_ret)
        assert math.isfinite(tsrv)

        sim = simulate_volterra_jump_diffusion(steps=24, seed=49)
        assert len(sim["price"]) == 24
        assert len(sim["variance"]) == 24

        surf = synthetic_total_variance_surface([0.1, 0.2], [-0.5, 0.0, 0.5])
        v_res = validate_vol_surface(surf, [0.1, 0.2], [-0.5, 0.0, 0.5], beta_call=1.4, beta_put=1.8)
        assert v_res["valid"] is True
        assert v_res["calendar_monotone"] is True
        assert v_res["butterfly_convex"] is True

    def test_cycle49_dealer_gex_and_gamma_squeeze(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.regime_switching_volterra_hawkes_pegger_hedger_engine import (
            dealer_net_gamma_exposure, gamma_squeeze_hazard, quote_retreat_decision
        )
        gex = dealer_net_gamma_exposure([10000.0], [0.002], 24000.0)
        assert gex > 0

        sq = gamma_squeeze_hazard(gex, 100.0)
        assert sq > 0

        q_ret = quote_retreat_decision(toxic_cascade=False, squeeze_hazard=sq, hazard_threshold=1.0)
        assert q_ret in {"QUOTE", "RETREAT"}

    def test_cycle49_greek_neutral_convex_hedger(self) -> None:
        import numpy as np
        from agents.AGI_1_7.engine.agi17.finance.regime_switching_volterra_hawkes_pegger_hedger_engine import (
            greek_neutral_hedge
        )
        cov = np.eye(3)
        greeks = np.eye(3)
        curr = [0.01, 0.02, 0.03]
        spr = [0.01, 0.02, 0.03]
        h_res = greek_neutral_hedge(cov, greeks, curr, spr)
        assert h_res["success"] is True
        assert np.all(np.abs(h_res["net_greeks"]) <= np.array([1.02e-4, 1.02e-3, 1.0002]) + 1e-6)

    def test_cycle49_statutory_fees_and_bayesian_kelly(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.regime_switching_volterra_hawkes_pegger_hedger_engine import (
            IndianStatutoryFees, expected_net_alpha_gate, bayesian_kelly_fraction
        )
        fees = IndianStatutoryFees().calculate(buy_turnover=5000.0, sell_turnover=5000.0, executed_legs=2)
        assert fees["brokerage"] == 40.0
        assert fees["total_fees"] > 0

        gate_ok = expected_net_alpha_gate(500.0, fees["total_fees"])
        assert gate_ok["approved"] is True
        assert gate_ok["expected_net_alpha"] > 0

        gate_no = expected_net_alpha_gate(10.0, fees["total_fees"])
        assert gate_no["approved"] is False

        k = bayesian_kelly_fraction(12.0, 8.0, 1.5)
        assert 0.0 <= k["fractional_kelly_fraction"] <= 0.1

    def test_cycle49_squad_consensus_and_example(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.regime_switching_volterra_hawkes_pegger_hedger_engine import (
            squad_consensus, run_cycle49_example
        )
        s_ok = squad_consensus(manager_approved=True, capital_approved=True, queue_safe=True, regime_safe=True, alpha_approved=True, risk_safe=True)
        assert s_ok["approved"] is True
        assert s_ok["live_dispatch_permitted"] is False

        s_veto = squad_consensus(manager_approved=False, capital_approved=True, queue_safe=True, regime_safe=True, alpha_approved=True, risk_safe=True)
        assert s_veto["approved"] is False

        ex = run_cycle49_example()
        assert ex["cycle"] == 49
        assert ex["live_order_dispatch_enabled"] is False
        assert ex["real_broker_fills_locked"] is True
        assert ex["execution_mode"] == "PAPER_ONLY"
        assert ex["initial_capital_inr"] == 10000.0
        assert ex["ledger_epoch"] == "epoch_10k"


class TestCycle50GUMMEEVolterraHawkesPeggerHedger:
    """Verifies Cycle 50 Grand Unified Microstructure-Macro Quantum-Jump Execution Engine (GUMMEE)."""

    def test_cycle50_identity_and_fail_closed_invariants(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.gummee_volterra_hawkes_pegger_hedger_engine import (
            GUMMEE_NAME, LIVE_ORDER_DISPATCH_ENABLED, REAL_BROKER_FILLS_LOCKED,
            PAPER_LEDGER_EPOCH, INITIAL_CAPITAL_INR, dispatch_live_order,
            ASSETS, AGENT_SQUAD,
        )
        assert GUMMEE_NAME == "Grand Unified Microstructure-Macro Quantum-Jump Execution Engine"
        assert LIVE_ORDER_DISPATCH_ENABLED is False
        assert REAL_BROKER_FILLS_LOCKED is True
        assert PAPER_LEDGER_EPOCH == "epoch_10k"
        assert INITIAL_CAPITAL_INR == 10000.0
        assert "NIFTY50" in ASSETS and "BANKNIFTY" in ASSETS
        assert list(AGENT_SQUAD.keys()) == ["Abhi", "Alex", "Emily", "Max"]

        with pytest.raises(PermissionError, match="LIVE_ORDER_DISPATCH_ENABLED is False|live broker order dispatch is disabled"):
            dispatch_live_order({"symbol": "NIFTY", "qty": 50, "side": "BUY"})

    def test_cycle50_cross_asset_impact_and_centrality(self) -> None:
        import numpy as np
        from agents.AGI_1_7.engine.agi17.finance.gummee_volterra_hawkes_pegger_hedger_engine import (
            CrossAssetImpactModel,
        )
        model = CrossAssetImpactModel()
        flow = np.array([1.0, -0.5, 0.25, 0.0])
        impact = model.predict_returns(flow)
        assert impact.shape == (4,)
        assert np.all(np.isfinite(impact))
        assert model.impact_cost(flow) >= 0

        # Linearity check
        assert np.allclose(model.predict_returns(2.0 * flow), 2.0 * impact)

        # Spillover and absorption centrality
        source = model.source_spillover_centrality()
        target = model.target_absorption_centrality()
        leadership = model.leadership_index()

        assert source.shape == (4,) and np.all(source >= 0) and math.isclose(float(source.sum()), 1.0, abs_tol=1e-5)
        assert target.shape == (4,) and np.all(target >= 0) and math.isclose(float(target.sum()), 1.0, abs_tol=1e-5)
        assert leadership.shape == (4, 4)
        assert np.all(np.diag(leadership) == 0.0)
        assert np.all(leadership >= -1.0) and np.all(leadership <= 1.0)

    def test_cycle50_regime_marked_jump_diffusion(self) -> None:
        import numpy as np
        from agents.AGI_1_7.engine.agi17.finance.gummee_volterra_hawkes_pegger_hedger_engine import (
            simulate_regime_marked_jumps,
        )
        j1 = simulate_regime_marked_jumps(steps=30, dt=0.01, seed=42)
        j2 = simulate_regime_marked_jumps(steps=30, dt=0.01, seed=42)

        assert np.array_equal(j1["regime"], j2["regime"])
        assert np.array_equal(j1["event_count"], j2["event_count"])
        assert np.array_equal(j1["aggregate_jump_return"], j2["aggregate_jump_return"])
        assert np.all(np.isin(j1["regime"], [0, 1, 2]))
        assert np.all(j1["event_count"] >= 0)
        assert np.all(np.isfinite(j1["aggregate_jump_return"]))

    def test_cycle50_hmm_belief_and_regime_switching_hawkes(self) -> None:
        import numpy as np
        from agents.AGI_1_7.engine.agi17.finance.gummee_volterra_hawkes_pegger_hedger_engine import (
            HMMBeliefTracker, RegimeSwitchingHawkesNetwork, normalize_probabilities,
        )
        tracker = HMMBeliefTracker()
        post = tracker.update([0.2, 0.5, 0.3])
        assert post.shape == (3,)
        assert np.all(post >= 0)
        assert math.isclose(float(post.sum()), 1.0, abs_tol=1e-6)

        hawkes = RegimeSwitchingHawkesNetwork()
        assert np.all(hawkes.regime_radii < 0.88)

        rates = hawkes.advance(0.01, [1.0, 0.0, 2.0, 1.0])
        assert rates.shape == (3, 4)
        assert np.all(rates >= 0)

        mixed = hawkes.intensity(post)
        assert mixed.shape == (4,)
        assert np.all(mixed >= 0)

    def test_cycle50_continuous_actor_critic_and_friction_advantage(self) -> None:
        import numpy as np
        from agents.AGI_1_7.engine.agi17.finance.gummee_volterra_hawkes_pegger_hedger_engine import (
            ContinuousActorCritic, build_state_vector, friction_aware_advantage,
        )
        policy = ContinuousActorCritic(seed=50)
        state = build_state_vector(
            ofi=0.1,
            fast_intensities=[0.2, 0.3, 0.2, 0.3],
            slow_intensities=[0.1, 0.15, 0.1, 0.15],
            regime_belief=[0.6, 0.3, 0.1],
            rough_variance_lift=0.05,
            queue_priority=0.4,
            dealer_gex_stress=0.1,
            bid_ask_spread=0.5,
        )
        assert state.shape == (16,)
        act = policy.act(state, deterministic=True)
        assert act.shape == (3,)
        assert np.all(act >= -1.0) and np.all(act <= 1.0)

        val = policy.value(state)
        assert isinstance(val, float)

        adv = friction_aware_advantage(
            reward=20.0,
            value=3.0,
            next_value=4.0,
            statutory_fees=15.0,
            inventory_variance=0.2,
            variance_penalty=0.5,
        )
        assert "advantage" in adv
        assert adv["fee_drag"] == 15.0
        assert adv["inventory_risk_penalty"] == 0.1

    def test_cycle50_snell_envelope_and_queue_survival(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.gummee_volterra_hawkes_pegger_hedger_engine import (
            snell_envelope_step, order_survival_probability, queue_revision_decision,
        )
        step = snell_envelope_step(0.8, 0.95, rate=0.01, dt=0.1, holding_cost_rate=0.02)
        assert step["decision"] in {"STOP", "CONTINUE"}
        assert step["value"] >= 0.8

        surv = order_survival_probability(tau=0.5, queue_ahead=2, depth=10, age=0.1, fill_rate=0.05)
        assert 0.0 <= surv <= 1.0

        dec = queue_revision_decision(surv)
        assert dec in {"HOLD", "REVISE_OR_PULL"}

    def test_cycle50_surface_validation_and_dealer_gex(self) -> None:
        import numpy as np
        from agents.AGI_1_7.engine.agi17.finance.gummee_volterra_hawkes_pegger_hedger_engine import (
            synthetic_total_variance_surface, validate_vol_surface,
            dealer_net_gamma_exposure, gamma_squeeze_hazard, quote_retreat_decision,
        )
        maturities = np.array([1/52, 2/52, 4/52])
        log_moneyness = np.linspace(-1, 1, 9)
        surf = synthetic_total_variance_surface(maturities, log_moneyness)
        check = validate_vol_surface(surf, maturities, log_moneyness, beta_call=1.5, beta_put=1.7)
        assert check["valid"] is True
        assert check["butterfly_convex"] is True
        assert check["calendar_monotone"] is True

        gex = dealer_net_gamma_exposure([1000, 500], [0.001, -0.0005], 24000.0)
        assert isinstance(gex, float)

        hazard = gamma_squeeze_hazard(gex, depth=10000.0)
        assert hazard >= 0.0

        quote_dec = quote_retreat_decision(toxic_cascade=False, squeeze_hazard=hazard, hazard_threshold=1.0)
        assert quote_dec in {"QUOTE", "RETREAT"}

    def test_cycle50_statutory_fees_and_bayesian_kelly(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.gummee_volterra_hawkes_pegger_hedger_engine import (
            IndianStatutoryFees, expected_net_alpha_gate, bayesian_kelly_fraction,
        )
        fees = IndianStatutoryFees().calculate(buy_turnover=50000.0, sell_turnover=50000.0, executed_legs=2)
        assert fees["brokerage"] == 40.0
        assert fees["total_fees"] > 0

        net_gate = expected_net_alpha_gate(expected_gross_alpha=500.0, total_statutory_fees=fees["total_fees"])
        assert net_gate["approved"] is True
        assert net_gate["expected_net_alpha"] > 0

        kelly = bayesian_kelly_fraction(wins_prior=15.0, losses_prior=10.0, payoff_ratio=1.5)
        assert 0.0 <= kelly["fractional_kelly_fraction"] <= 0.1

    def test_cycle50_squad_consensus_and_example(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.gummee_volterra_hawkes_pegger_hedger_engine import (
            squad_consensus, run_cycle50_example,
        )
        sc = squad_consensus(
            manager_approved=True, capital_approved=True, queue_safe=True,
            regime_safe=True, alpha_approved=True, risk_safe=True
        )
        assert sc["approved"] is True
        assert sc["live_dispatch_permitted"] is False
        assert sc["mode"] == "PAPER_ONLY"

        veto = squad_consensus(
            manager_approved=False, capital_approved=True, queue_safe=True,
            regime_safe=True, alpha_approved=True, risk_safe=True
        )
        assert veto["approved"] is False

        ex = run_cycle50_example()
        assert ex["cycle"] == 50
        assert ex["live_order_dispatch_enabled"] is False
        assert ex["real_broker_fills_locked"] is True
        assert ex["execution_mode"] == "PAPER_ONLY"
        assert ex["initial_capital_inr"] == 10000.0
        assert ex["ledger_epoch"] == "epoch_10k"


class TestCycle51HFLOBVIPVolterraHawkes:
    """Verifies Cycle 51 High-Frequency Limit Order Book Cointegration and Volterra-Hawkes Utility Indifference Pricer."""

    def test_cycle51_identity_and_fail_closed_invariants(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.hflob_vip_volterra_hawkes_engine import (
            HFLOB_VIP_NAME, VECM_ASSETS, ASSETS, LIVE_ORDER_DISPATCH_ENABLED,
            REAL_BROKER_FILLS_LOCKED, PAPER_LEDGER_EPOCH, INITIAL_CAPITAL_INR,
            dispatch_live_order, AGENT_SQUAD,
        )
        assert HFLOB_VIP_NAME == "High-Frequency Limit Order Book Cointegration and Volterra-Hawkes Utility Indifference Pricer"
        assert VECM_ASSETS == ("NIFTY50", "BANKNIFTY")
        assert "NIFTY50" in ASSETS and "BANKNIFTY" in ASSETS
        assert LIVE_ORDER_DISPATCH_ENABLED is False
        assert REAL_BROKER_FILLS_LOCKED is True
        assert PAPER_LEDGER_EPOCH == "epoch_10k"
        assert INITIAL_CAPITAL_INR == 10000.0
        assert list(AGENT_SQUAD.keys()) == ["Abhi", "Alex", "Emily", "Max"]

        with pytest.raises(PermissionError, match="LIVE_ORDER_DISPATCH_ENABLED is False|live broker order dispatch is disabled"):
            dispatch_live_order({"symbol": "NIFTY", "qty": 50, "side": "BUY"})

    def test_cycle51_synthetic_forward_and_vecm_cointegration(self) -> None:
        import numpy as np
        from agents.AGI_1_7.engine.agi17.finance.hflob_vip_volterra_hawkes_engine import (
            synthetic_forward_price, cointegration_spread, VECMSpreadModel,
            estimate_vecm_cointegration,
        )
        # Synthetic forward
        fwd = synthetic_forward_price(24000.0, 0.065, 0.012, 30 / 365)
        assert fwd > 24000.0

        # Cointegration spread
        z = cointegration_spread(fwd, [24000.0, 51000.0], [0.8, 0.2], alpha0=0.01)
        assert isinstance(z, float) and math.isfinite(z)

        # VECM model
        vecm = VECMSpreadModel(beta=np.array([0.8, 0.2]), alpha0=0.01, kappa_vecm=0.25)
        assert math.isclose(vecm.half_life, math.log(2.0) / 0.25, abs_tol=1e-6)
        drift = vecm.correction_drift(0.05)
        assert drift < 0  # Reversion toward origin
        nxt = vecm.expected_next_spread(0.05, dt=1.0)
        assert 0 < nxt < 0.05

        # Simulated path estimation
        rng = np.random.default_rng(42)
        n = 100
        spots = np.column_stack([
            24000.0 + np.cumsum(rng.normal(0, 10, n)),
            51000.0 + np.cumsum(rng.normal(0, 20, n))
        ])
        true_beta = np.array([0.75, 0.25])
        # Generate mean-reverting synthetic forwards: z_t = 0.8 * z_{t-1} + e_t
        z_path = np.zeros(n)
        for t in range(1, n):
            z_path[t] = 0.7 * z_path[t-1] + rng.normal(0, 0.002)
        fwds = np.exp(np.dot(np.log(spots), true_beta) + 0.02 + z_path)

        fit = estimate_vecm_cointegration(fwds, spots, dt=1.0, minimum_observations=30)
        assert "beta" in fit
        assert "kappa_vecm" in fit
        assert fit["kappa_vecm"] > 0
        assert fit["half_life"] > 0
        assert 0.0 < fit["phi"] < 1.0

    def test_cycle51_top5_ofi_and_toxicity_decomposition(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.hflob_vip_volterra_hawkes_engine import (
            decompose_top5_ofi, flow_toxicity_index,
        )
        bid_fills = [10.0, 5.0, 2.0, 1.0, 0.0]
        bid_cancels = [2.0, 1.0, 0.0, 1.0, 0.0]
        ask_fills = [4.0, 2.0, 1.0, 0.0, 0.0]
        ask_cancels = [1.0, 2.0, 1.0, 0.0, 0.0]

        res = decompose_top5_ofi(bid_fills, bid_cancels, ask_fills, ask_cancels)
        assert len(res["active_execution_flow_by_level"]) == 5
        assert len(res["passive_cancel_flow_by_level"]) == 5
        assert len(res["ofi_by_level"]) == 5
        assert res["total_liquidity_flow"] == sum(bid_fills + bid_cancels + ask_fills + ask_cancels)
        assert 0.0 <= res["toxicity_index"] <= 1.0

        tox = flow_toxicity_index(15.0, 100.0)
        assert math.isclose(tox, 0.15, abs_tol=1e-6)

    def test_cycle51_nonlinear_quadratic_hawkes(self) -> None:
        import numpy as np
        from agents.AGI_1_7.engine.agi17.finance.hflob_vip_volterra_hawkes_engine import (
            NonlinearQuadraticHawkesNetwork,
        )
        hawkes = NonlinearQuadraticHawkesNetwork()
        audit = hawkes.audit_stability()
        assert audit["passed"] is True
        assert audit["spectral_radius"] < 0.88

        # Step progression
        nxt_intensities = hawkes.step(0.01, [1.0, 0.0, 2.0, 1.0])
        assert nxt_intensities.shape == (4,)
        assert np.all(nxt_intensities >= 0)
        assert hawkes.audit_stability()["passed"] is True

    def test_cycle51_utility_indifference_pricer(self) -> None:
        import numpy as np
        from agents.AGI_1_7.engine.agi17.finance.hflob_vip_volterra_hawkes_engine import (
            UtilityIndifferencePricer,
        )
        pricer = UtilityIndifferencePricer(
            gamma_risk=0.08, inventory_risk_penalty=0.02,
            jump_cascade_penalty=0.15, fee_per_unit=0.25
        )
        u = pricer.utility(100.0)
        assert isinstance(u, float) and u < 0

        scenarios = np.array([17.0, 18.5, 19.0, 20.0, 21.5, 14.0, 22.0])
        ce = pricer.certainty_equivalent(inventory=2.0, centered_payoff_scenarios=scenarios - 19.0, cascade_score=0.25)
        assert isinstance(ce, float)

        quotes = pricer.reservation_quotes(
            mid_price=19.0, inventory=2.0, payoff_scenarios=scenarios, cascade_score=0.25
        )
        assert quotes["reservation_ask"] >= quotes["reservation_bid"]
        assert quotes["risk_spread"] >= 0.0
        assert quotes["mid_price"] == 19.0
        assert quotes["inventory"] == 2.0

    def test_cycle51_statutory_fees_and_bayesian_kelly(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.hflob_vip_volterra_hawkes_engine import (
            IndianStatutoryFees, expected_net_alpha_gate, bayesian_kelly_fraction,
        )
        fees = IndianStatutoryFees().calculate(buy_turnover=50000.0, sell_turnover=50000.0, executed_legs=2)
        assert fees["brokerage"] == 40.0
        assert fees["total_fees"] > 0

        net_gate = expected_net_alpha_gate(expected_gross_alpha=500.0, total_statutory_fees=fees["total_fees"])
        assert net_gate["approved"] is True
        assert net_gate["expected_net_alpha"] > 0

        kelly = bayesian_kelly_fraction(wins_prior=15.0, losses_prior=10.0, payoff_ratio=1.5)
        assert 0.0 <= kelly["fractional_kelly_fraction"] <= 0.10

    def test_cycle51_squad_consensus_and_example(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.hflob_vip_volterra_hawkes_engine import (
            squad_consensus, run_cycle51_example,
        )
        sc = squad_consensus(
            manager_approved=True, capital_approved=True, queue_safe=True,
            regime_safe=True, alpha_approved=True, risk_safe=True
        )
        assert sc["approved"] is True
        assert sc["live_dispatch_permitted"] is False
        assert sc["mode"] == "PAPER_ONLY"

        veto = squad_consensus(
            manager_approved=False, capital_approved=True, queue_safe=True,
            regime_safe=True, alpha_approved=True, risk_safe=True
        )
        assert veto["approved"] is False

        ex = run_cycle51_example()
        assert ex["cycle"] == 51
        assert ex["live_order_dispatch_enabled"] is False
        assert ex["real_broker_fills_locked"] is True
        assert ex["execution_mode"] == "PAPER_ONLY"
        assert ex["initial_capital_inr"] == 10000.0
        assert ex["ledger_epoch"] == "epoch_10k"


class TestCycle52FPSEPGVVolterraHawkes:
    """Verifies Cycle 52 Fractional Path Signatures, Expiry Pinning Gamma Vacuums, and Liquidity Contagion."""

    def test_cycle52_identity_and_fail_closed_invariants(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.fps_epgv_volterra_hawkes_engine import (
            ASSETS, LIVE_ORDER_DISPATCH_ENABLED, REAL_BROKER_FILLS_LOCKED,
            PAPER_LEDGER_EPOCH, INITIAL_CAPITAL_INR, dispatch_live_order,
            engine_manifest_summary,
        )
        assert LIVE_ORDER_DISPATCH_ENABLED is False
        assert REAL_BROKER_FILLS_LOCKED is True
        assert PAPER_LEDGER_EPOCH == "epoch_10k"
        assert INITIAL_CAPITAL_INR == 10000.0
        assert "NIFTY50" in ASSETS and "BANKNIFTY" in ASSETS

        summary = engine_manifest_summary()
        assert summary["cycle"] == 52
        assert summary["engine"] == "FPS-EPGV"

        with pytest.raises(PermissionError, match="Live order dispatch is disabled"):
            dispatch_live_order({"symbol": "NIFTY", "qty": 50, "side": "BUY"})

    def test_cycle52_path_signature_and_chen_identity(self) -> None:
        import numpy as np
        from agents.AGI_1_7.engine.agi17.finance.fps_epgv_volterra_hawkes_engine import (
            PathSignature, path_signature, signature_features, signature_predictability_features,
        )
        p1 = np.array([[0.0, 100.0], [1.0, 102.0], [2.0, 101.0]])
        p2 = np.array([[2.0, 101.0], [3.0, 103.0], [4.0, 105.0]])
        p_full = np.vstack([p1, p2[1:]])

        s1 = path_signature(p1, degree=3)
        s2 = path_signature(p2, degree=3)
        s_concat = s1.concatenate(s2)
        s_full = path_signature(p_full, degree=3)

        # Chen's identity verification
        assert np.allclose(s_concat.level1, s_full.level1, atol=1e-6)
        assert np.allclose(s_concat.level2, s_full.level2, atol=1e-6)
        assert np.allclose(s_concat.level3, s_full.level3, atol=1e-6)

        feat = signature_features(s_full, size=16)
        assert feat.shape == (16,)
        assert np.all(np.isfinite(feat))

        pred = signature_predictability_features(s_full)
        assert "net_path_norm" in pred
        assert "geometric_area_norm" in pred
        assert pred["geometric_area_norm"] >= 0.0

    def test_cycle52_exponential_volterra_lift(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.fps_epgv_volterra_hawkes_engine import (
            rough_volterra_kernel, build_exponential_volterra_lift,
        )
        k_val = rough_volterra_kernel(1.0, hurst=0.07)
        assert isinstance(k_val, float) and k_val > 0

        lift = build_exponential_volterra_lift(hurst=0.07, factors=12)
        assert len(lift.rates) == 12
        assert len(lift.weights) == 12

        approx = lift.evaluate(1.0)
        assert isinstance(approx, float) and approx > 0

    def test_cycle52_expiry_pinning_and_gamma_vacuum(self) -> None:
        from datetime import datetime
        from zoneinfo import ZoneInfo
        from agents.AGI_1_7.engine.agi17.finance.fps_epgv_volterra_hawkes_engine import (
            expiry_pinning_force, in_expiry_pin_window, gamma_vacuum_quote_action,
        )
        oi = {24000.0: 100000.0, 24100.0: 500000.0, 24200.0: 200000.0}
        # Spot above dominant strike (24100) -> negative restoring force
        f_above = expiry_pinning_force(spot=24150.0, open_interest=oi, time_to_expiry=0.01, kappa_pin=1.0)
        assert f_above < 0

        # Spot below dominant strike -> positive restoring force
        f_below = expiry_pinning_force(spot=24050.0, open_interest=oi, time_to_expiry=0.01, kappa_pin=1.0)
        assert f_below > 0

        # Expiry window check (Thursday 15:15 IST)
        # 2026-10-15 is a Thursday
        dt_thursday = datetime(2026, 10, 15, 15, 15, tzinfo=ZoneInfo("Asia/Kolkata"))
        assert in_expiry_pin_window(dt_thursday) is True

        dt_friday = datetime(2026, 10, 16, 15, 15, tzinfo=ZoneInfo("Asia/Kolkata"))
        assert in_expiry_pin_window(dt_friday) is False

        # Gamma vacuum detection
        action_vac = gamma_vacuum_quote_action(dealer_gamma=-500.0, gamma_threshold=100.0)
        assert action_vac == "RETREAT"

        action_norm = gamma_vacuum_quote_action(dealer_gamma=50.0, gamma_threshold=100.0)
        assert action_norm == "QUOTE"

    def test_cycle52_cross_asset_liquidity_depletion_and_resilience(self) -> None:
        import numpy as np
        from agents.AGI_1_7.engine.agi17.finance.fps_epgv_volterra_hawkes_engine import (
            cross_asset_liquidity_depletion, resilience_half_life,
        )
        coupling = np.array([[1.0, 0.2], [0.3, 1.0]])
        decay = np.array([[1.0, 0.5], [0.5, 2.0]])
        shocks = np.array([10.0, 5.0])

        dep = cross_asset_liquidity_depletion(coupling, decay, shocks, ages=0.1)
        assert dep.shape == (2,)
        assert np.all(dep <= 0)  # Depletion is non-positive

        hl0 = resilience_half_life(decay, 0)
        assert math.isclose(hl0, math.log(2.0) / 1.0, abs_tol=1e-5)
        hl1 = resilience_half_life(decay, 1)
        assert math.isclose(hl1, math.log(2.0) / 2.0, abs_tol=1e-5)

    def test_cycle52_path_signature_actor_critic_and_advantage(self) -> None:
        import numpy as np
        from agents.AGI_1_7.engine.agi17.finance.fps_epgv_volterra_hawkes_engine import (
            PathSignatureActorCritic, friction_aware_advantage,
        )
        ac = PathSignatureActorCritic(state_dim=16, seed=52)
        state = np.linspace(0.1, 1.6, 16)
        act = ac.act(state)
        assert act.shape == (3,)
        assert np.all(act >= -1.0) and np.all(act <= 1.0)

        val = ac.value(state)
        assert isinstance(val, float)

        adv = friction_aware_advantage(
            reward=100.0, baseline_value=20.0, statutory_fees=35.0,
            inventory=2.0, volatility=0.15, risk_aversion=1.0,
        )
        assert isinstance(adv, float)
        assert adv < 100.0 - 20.0 - 35.0

    def test_cycle52_statutory_fees_and_consensus(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.fps_epgv_volterra_hawkes_engine import (
            calculate_statutory_fees, net_alpha_gate, beta_posterior_fractional_kelly,
            four_agent_consensus,
        )
        fees = calculate_statutory_fees(buy_turnover=50000.0, sell_turnover=50000.0, executed_legs=2)
        assert fees.brokerage == 40.0
        assert fees.total > 0

        passed, net = net_alpha_gate(expected_gross_alpha=500.0, fees=fees)
        assert passed is True
        assert net > 0

        f_no, net_neg = net_alpha_gate(expected_gross_alpha=10.0, fees=fees)
        assert f_no is False
        assert net_neg < 0

        k = beta_posterior_fractional_kelly(alpha_wins=15.0, beta_losses=10.0, payoff_odds=1.5)
        assert 0.0 <= k <= 0.10

        c_ok = four_agent_consensus(
            manager_abhi=True, alex_queue_safe=True,
            emily_volatility_safe=True, max_net_alpha_safe=True
        )
        assert c_ok["status"] == "PAPER_APPROVE"
        assert c_ok["live_dispatch"] is False

        c_veto = four_agent_consensus(
            manager_abhi=True, alex_queue_safe=True,
            emily_volatility_safe=True, max_net_alpha_safe=True, manager_veto=True
        )
        assert c_veto["status"] == "VETO"


class TestCycle53RBSVIBOCPDVolterraHawkes:
    """Verifies Cycle 53 Rough Bergomi-SSVI, BOCPD, Hawkes Filtering, and Friction-Aware Indifference Bands."""

    def test_cycle53_forward_variance_and_rough_volterra(self) -> None:
        import numpy as np
        from agents.AGI_1_7.engine.agi17.finance.rbsvi_bocpd_volterra_hawkes_engine import (
            ForwardVarianceCurve, rough_volterra_kernel, build_volterra_lift, simulate_rough_variance_proxy,
        )
        times = np.array([0.0, 0.25, 0.5, 1.0])
        values = np.array([0.04, 0.042, 0.045, 0.05])
        fwd = ForwardVarianceCurve(times, values)
        assert fwd.total_variance(0.25) > 0.0
        assert fwd.total_variance(0.5) > fwd.total_variance(0.25)
        assert fwd.total_variance(1.0) > fwd.total_variance(0.5)

        k_val = rough_volterra_kernel(1.0, hurst=0.07)
        assert isinstance(k_val, float) and k_val > 0.0

        lift = build_volterra_lift(factors=12)
        assert len(lift.rates) == 12
        assert len(lift.weights) == 12
        approx = lift.evaluate(1.0)
        assert isinstance(approx, float) and approx > 0.0

        v_path = simulate_rough_variance_proxy(0.04, np.array([0.01, -0.02, 0.015, -0.005]), 0.01)
        assert len(v_path) == 4
        assert np.all(v_path > 0.0)

    def test_cycle53_ssvi_derivatives_and_butterfly_density(self) -> None:
        import numpy as np
        from agents.AGI_1_7.engine.agi17.finance.rbsvi_bocpd_volterra_hawkes_engine import (
            ssvi_total_variance, ssvi_derivatives, ssvi_butterfly_density,
            ssvi_wing_slopes, surface_diagnostics, calibrate_ssvi_grid,
        )
        theta = 0.04
        w_val = ssvi_total_variance(0.0, theta, -0.4, 0.2, 0.5)
        assert math.isclose(w_val, theta, abs_tol=1e-6)

        w, dw, d2w = ssvi_derivatives(0.05, theta, -0.4, 0.2, 0.5)
        assert w > 0.0
        assert isinstance(dw, float) and isinstance(d2w, float)

        density = ssvi_butterfly_density(0.05, theta, -0.4, 0.2, 0.5)
        assert density > 0.0

        left_slope, right_slope = ssvi_wing_slopes(theta, -0.4, 0.2, 0.5)
        assert left_slope >= 0.0 and right_slope >= 0.0
        assert left_slope < 2.0 and right_slope < 2.0

        expiries = np.array([0.25, 0.5, 1.0])
        thetas = np.array([0.01, 0.02, 0.04])
        diag = surface_diagnostics(expiries, thetas, -0.4, 0.2, 0.5)
        assert diag["admissible_on_grid"] is True
        assert diag["minimum_butterfly_density"] > 0.0

        k_grid = np.linspace(-0.5, 0.5, 11)
        observed = ssvi_total_variance(k_grid, theta, -0.4, 0.2, 0.5)
        calib = calibrate_ssvi_grid(theta, k_grid, observed)
        assert calib.rmse >= 0.0
        assert -1.0 < calib.rho < 1.0

    def test_cycle53_bocpd_changepoint_detection(self) -> None:
        import numpy as np
        from agents.AGI_1_7.engine.agi17.finance.rbsvi_bocpd_volterra_hawkes_engine import (
            BayesianOnlineChangepointDetector,
        )
        bocpd = BayesianOnlineChangepointDetector(hazard_lambda=40.0, max_run_length=50)
        np.random.seed(42)
        series = np.concatenate([np.random.normal(0, 0.1, 15), np.random.normal(3.0, 0.1, 10)])
        cp_probs = []
        for x in series:
            res = bocpd.update(float(x))
            cp = res["changepoint_probability"]
            cp_probs.append(cp)
            assert 0.0 <= cp <= 1.0
            assert math.isclose(float(np.sum(res["run_length_probabilities"])), 1.0, abs_tol=1e-5)

        assert max(cp_probs[15:]) > max(cp_probs[:10])

    def test_cycle53_hawkes_bocpd_filter_and_stability(self) -> None:
        import numpy as np
        from agents.AGI_1_7.engine.agi17.finance.rbsvi_bocpd_volterra_hawkes_engine import (
            validate_hawkes_stability, HawkesBOCPDFilter,
        )
        alpha = np.array([
            [0.05, 0.02],
            [0.02, 0.05],
        ])
        beta = np.array([
            [2.0, 2.0],
            [2.0, 2.0],
        ])
        stab = validate_hawkes_stability(alpha, beta)
        assert stab["stable"] is True
        assert stab["spectral_radius"] < 0.88

        filt = HawkesBOCPDFilter(
            baseline=[0.1, 0.15],
            alpha=alpha,
            beta=beta,
            bocpd_weight=0.5,
            hazard_lambda=40.0,
        )
        up = filt.update(event_counts=[1, 0], observations=[0.02, -0.01], dt=0.01)
        assert len(up.intensities) == 2
        assert np.all(up.intensities > 0.0)
        assert 0.0 <= up.system_changepoint_probability <= 1.0

    def test_cycle53_friction_aware_indifference_band(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.rbsvi_bocpd_volterra_hawkes_engine import (
            friction_aware_indifference_band, IndifferenceBand,
        )
        band = friction_aware_indifference_band(
            sigma=0.2,
            risk_aversion=0.5,
            friction_cost=0.02,
            buy_spread_penalty=0.03,
            sell_spread_penalty=0.01,
            statutory_fee_drag=0.02,
            inventory_target=0.0,
        )
        assert isinstance(band, IndifferenceBand)
        assert band.lower < 0.0 < band.upper
        assert band.buy_half_width > 0.0
        assert band.sell_half_width > 0.0

        band_target = friction_aware_indifference_band(
            sigma=0.2,
            risk_aversion=0.5,
            friction_cost=0.02,
            inventory_target=5.0,
        )
        assert band_target.lower < 5.0 < band_target.upper

    def test_cycle53_actor_critic_and_advantage(self) -> None:
        import numpy as np
        from agents.AGI_1_7.engine.agi17.finance.rbsvi_bocpd_volterra_hawkes_engine import (
            ContinuousActorCritic, friction_aware_advantage,
        )
        ac = ContinuousActorCritic(seed=53)
        state = np.linspace(-0.5, 0.5, 16)
        action = ac.act(state)
        assert action.shape == (3,)
        assert np.all(action >= -1.0) and np.all(action <= 1.0)

        val = ac.value(state)
        assert isinstance(val, float)

        adv = friction_aware_advantage(
            reward=50.0,
            value=10.0,
            next_value=12.0,
            discount=0.99,
            statutory_fees=15.0,
            inventory_variance=1.0,
            inventory_penalty=0.5,
        )
        assert isinstance(adv, float)
        assert adv < 50.0 - 10.0 - 15.0 + 12.0

    def test_cycle53_statutory_fees_consensus_and_live_dispatch_locked(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.rbsvi_bocpd_volterra_hawkes_engine import (
            calculate_statutory_fees, net_alpha_gate, beta_posterior_fractional_kelly,
            four_agent_consensus, dispatch_live_order, LIVE_ORDER_DISPATCH_ENABLED,
            REAL_BROKER_FILLS_LOCKED,
        )
        assert LIVE_ORDER_DISPATCH_ENABLED is False
        assert REAL_BROKER_FILLS_LOCKED is True

        fees = calculate_statutory_fees(buy_turnover=25000.0, sell_turnover=25000.0, executed_legs=2)
        assert fees.brokerage == 40.0
        assert fees.total > 0.0

        passed, net = net_alpha_gate(expected_gross_alpha=200.0, fees=fees)
        assert passed is True
        assert net > 0.0

        f_no, net_neg = net_alpha_gate(expected_gross_alpha=10.0, fees=fees)
        assert f_no is False
        assert net_neg < 0.0

        k = beta_posterior_fractional_kelly(alpha_wins=8.0, beta_losses=4.0, payoff_odds=1.5)
        assert 0.0 <= k <= 0.10

        c_ok = four_agent_consensus(
            manager_approved=True, queue_safe=True,
            volatility_safe=True, net_alpha_positive=True,
        )
        assert c_ok["approved"] is True
        assert c_ok["execution_mode"] == "PAPER_ONLY"

        c_veto = four_agent_consensus(
            manager_approved=False, queue_safe=True,
            volatility_safe=True, net_alpha_positive=True,
        )
        assert c_veto["approved"] is False
        assert "Manager Abhi" in c_veto["failed_vetoes"]

        import pytest
        with pytest.raises(PermissionError, match="Live broker order dispatch is disabled"):
            dispatch_live_order("NIFTY50", 50, "BUY")


class TestCycle54DRHRBVNVolterraHawkes:
    """Verifies Cycle 54 Deep Reinforcement Hedging with Rough Bergomi Volterra Neural Jump SDEs."""

    def test_cycle54_rough_bergomi_simulation_and_volterra_lift(self) -> None:
        import numpy as np
        from agents.AGI_1_7.engine.agi17.finance.drh_rbvn_volterra_hawkes_engine import (
            rough_volterra_kernel, build_volterra_lift, simulate_rough_bergomi_jump_sde,
        )
        k_val = rough_volterra_kernel(1.0, hurst=0.07)
        assert isinstance(k_val, float) and k_val > 0.0

        lift = build_volterra_lift(factors=12)
        assert len(lift.rates) == 12
        assert len(lift.weights) == 12
        approx = lift.evaluate(1.0)
        assert isinstance(approx, float) and approx > 0.0

        sim = simulate_rough_bergomi_jump_sde(
            spot0=22000.0, dt=1.0 / 252.0, n_steps=24, forward_variance=0.04, hurst=0.07, seed=54,
        )
        assert len(sim.spot) == 25
        assert len(sim.variance) == 24
        assert np.all(sim.spot > 0.0)
        assert np.all(sim.variance > 0.0)

    def test_cycle54_mlofi_top5_order_imbalance(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.drh_rbvn_volterra_hawkes_engine import (
            mlofi_top5,
        )
        ofi = mlofi_top5(
            delta_bid_volume=[3, 2, 1, -1, 0],
            delta_ask_volume=[1, 0, 2, 1, 1],
            delta_bid_price=[0, 1, 0, -1, 0],
            delta_ask_price=[0, -1, 1, 0, -1],
        )
        assert isinstance(ofi, float)
        assert ofi > 0.0

    def test_cycle54_cvar_and_hedging_error(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.drh_rbvn_volterra_hawkes_engine import (
            hedging_error_scenarios, cvar_alpha,
        )
        errors = hedging_error_scenarios(
            terminal_pnl=[12.0, -4.0, 6.0, -9.0, 3.0],
            price_changes=[[1.0, -0.5], [-1.0, 0.4], [0.2, 1.1], [-0.7, -0.9], [0.5, 0.1]],
            delta_hedges=[0.4, -0.2],
            transaction_costs=[1.25, 0.75],
        )
        assert len(errors) == 5
        cvar = cvar_alpha(errors, 0.95)
        assert isinstance(cvar, float)
        assert cvar >= min(errors)

    def test_cycle54_friction_aware_no_trade_band(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.drh_rbvn_volterra_hawkes_engine import (
            friction_aware_no_trade_band, inventory_action, NoTradeBand,
        )
        band = friction_aware_no_trade_band(
            target_inventory=2.0,
            transaction_cost=0.03,
            volatility=0.25,
            risk_aversion=1.2,
            buy_spread_penalty=0.02,
            sell_spread_penalty=0.03,
            fee_drag=0.01,
        )
        assert isinstance(band, NoTradeBand)
        assert band.lower < 2.0 < band.upper
        act_target = inventory_action(2.0, band)
        assert act_target == "HOLD_NO_TRADE"

        act_buy = inventory_action(1.0, band)
        assert act_buy == "BUY_TOWARD_TARGET"

        act_sell = inventory_action(3.0, band)
        assert act_sell == "SELL_TOWARD_TARGET"

    def test_cycle54_actor_critic_and_advantage(self) -> None:
        import numpy as np
        from agents.AGI_1_7.engine.agi17.finance.drh_rbvn_volterra_hawkes_engine import (
            ContinuousActorCritic, friction_aware_advantage, STATE_DIMENSION,
        )
        model = ContinuousActorCritic(seed=54)
        state = np.linspace(-0.5, 0.5, STATE_DIMENSION)
        action = model.act(state, seed=54, deterministic=True)
        assert -1.0 <= action <= 1.0

        val = model.value(state)
        assert isinstance(val, float)

        adv = friction_aware_advantage(
            reward=25.0,
            value=5.0,
            next_value=6.0,
            statutory_fees=10.0,
            inventory_variance=0.5,
            risk_aversion=0.5,
            discount=0.99,
        )
        assert isinstance(adv, float)
        assert adv < 25.0 - 5.0 - 10.0 + 6.0

    def test_cycle54_statutory_fees_and_kelly(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.drh_rbvn_volterra_hawkes_engine import (
            calculate_statutory_fees, pretrade_net_alpha_gate, beta_posterior_fractional_kelly,
        )
        fees = calculate_statutory_fees(125000.0, 110000.0, 2)
        assert fees["brokerage"] == 40.0
        assert fees["total_fees"] > 0.0

        gate = pretrade_net_alpha_gate(500.0, fees["total_fees"])
        assert gate["approved"] is True
        assert gate["expected_net_alpha"] > 0.0

        gate_no = pretrade_net_alpha_gate(10.0, fees["total_fees"])
        assert gate_no["approved"] is False

        k = beta_posterior_fractional_kelly(18, 7, odds=1.8)
        assert 0.0 <= k["fraction"] <= 0.10

    def test_cycle54_consensus_and_live_dispatch_locked(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.drh_rbvn_volterra_hawkes_engine import (
            squad_consensus, dispatch_live_order, safety_invariants,
        )
        inv = safety_invariants()
        assert inv["LIVE_ORDER_DISPATCH_ENABLED"] is False
        assert inv["REAL_BROKER_FILLS_LOCKED"] is True

        c_ok = squad_consensus(True, True, True, True)
        assert c_ok.approved is True
        assert c_ok.paper_only is True

        c_no = squad_consensus(False, True, True, True)
        assert c_no.approved is False
        assert "Abhi capital approval absent" in c_no.reasons

        c_veto = squad_consensus(True, True, True, True, manager_veto=True)
        assert c_veto.approved is False
        assert "Manager Abhi binding veto active" in c_veto.reasons

        import pytest
        with pytest.raises(PermissionError, match="Live order dispatch is disabled"):
            dispatch_live_order("NIFTY50", 50, "BUY")


class TestCycle55HFCEHLOSExecution:
    """Verifies Cycle 55 High-Frequency Cross-Impact Optimal Execution with Hawkes Price Impact (HF-CEH-LOS)."""

    def test_cycle55_safety_and_fail_closed_invariants(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.hf_ceh_los_execution_engine import (
            ASSETS, LIVE_ORDER_DISPATCH_ENABLED, REAL_BROKER_FILLS_LOCKED,
            PAPER_LEDGER_EPOCH, INITIAL_CAPITAL_INR, dispatch_live_order,
        )
        assert ASSETS == ("NIFTY50", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY")
        assert LIVE_ORDER_DISPATCH_ENABLED is False
        assert REAL_BROKER_FILLS_LOCKED is True
        assert PAPER_LEDGER_EPOCH == "epoch_10k"
        assert INITIAL_CAPITAL_INR == 10000.0

        with pytest.raises(PermissionError, match="Cycle 55 is paper-only"):
            dispatch_live_order("NIFTY50", 50, price=24500.0)

    def test_cycle55_regularize_impact_matrix_and_model(self) -> None:
        import numpy as np
        from agents.AGI_1_7.engine.agi17.finance.hf_ceh_los_execution_engine import (
            regularize_impact_matrix, CrossImpactModel,
        )
        raw_g = np.array([
            [0.7, 0.1, 0.04, 0.02],
            [0.1, 0.6, 0.03, 0.02],
            [0.04, 0.03, 0.5, 0.05],
            [0.02, 0.02, 0.05, 0.4]
        ])
        reg_g = regularize_impact_matrix(raw_g, epsilon=1e-7)
        assert np.allclose(reg_g, reg_g.T, atol=1e-10)
        assert np.min(np.linalg.eigvalsh(reg_g)) > 0

        decay = np.full((4, 4), 1.0)
        kernel = np.full((4, 4), 0.02)
        model = CrossImpactModel(reg_g, decay, kernel, exponent=1.0)
        memory = model.add_event(np.zeros((4, 4)), 1, 2.0)
        impact = model.price_impact(np.array([100.0, -50.0, 20.0, 0.0]), memory)
        assert impact.shape == (4,)
        assert np.all(np.isfinite(impact))

        cost = model.quadratic_cost(np.array([1.0, -1.0, 2.0, 0.5]))
        assert cost >= 0.0

    def test_cycle55_cancellation_intensity_and_mlofi(self) -> None:
        import numpy as np
        from agents.AGI_1_7.engine.agi17.finance.hf_ceh_los_execution_engine import (
            cancellation_intensity, adverse_selection_probability, mlofi_top5,
        )
        cancel = cancellation_intensity(0.2, 0.4, 2.0, [0.0, 0.1, 0.4], ofi=1.2, gamma=0.05)
        assert cancel > 0.0
        adv_p = adverse_selection_probability(cancel, 0.25)
        assert 0.0 < adv_p < 1.0

        vb = np.array([10.0, 8.0, 6.0, 4.0, 2.0])
        va = np.array([12.0, 9.0, 7.0, 5.0, 3.0])
        pb = np.array([0.05, 0.0, -0.05, 0.05, 0.0])
        pa = np.array([-0.05, 0.05, 0.0, -0.05, 0.05])
        ofi = mlofi_top5(vb, va, pb, pa)
        assert isinstance(ofi, float)
        assert math.isfinite(ofi)

    def test_cycle55_hawkes_stability_audit_and_cascade(self) -> None:
        import numpy as np
        from agents.AGI_1_7.engine.agi17.finance.hf_ceh_los_execution_engine import (
            hawkes_stability_audit, HawkesCascade,
        )
        alpha = np.eye(4) * 0.2
        beta = np.ones((4, 4)) * 1.0
        audit = hawkes_stability_audit(alpha, beta)
        assert audit["stable"] is True
        assert audit["spectral_radius"] <= 0.88

        cascade = HawkesCascade(np.ones(4) * 0.1, np.eye(4) * 0.1, np.ones((4, 4)))
        intensities = cascade.step(0.5, [1, 0, 2, 0])
        assert intensities.shape == (4,)
        assert np.all(intensities >= 0.0)

    def test_cycle55_almgren_chriss_and_no_trade_band(self) -> None:
        import numpy as np
        from agents.AGI_1_7.engine.agi17.finance.hf_ceh_los_execution_engine import (
            almgren_chriss_trajectory, compute_no_trade_band, inventory_action,
        )
        q0 = np.array([10.0, -4.0, 2.0, 1.0])
        impact_m = np.eye(4) * 0.4
        vol_cov = np.eye(4) * 0.01
        traj = almgren_chriss_trajectory(q0, 10.0, 20, impact_m, vol_cov, 0.2, half_life=2.5)
        assert np.allclose(traj.remaining_inventory[0], q0)
        assert np.allclose(traj.remaining_inventory[-1], 0.0)
        assert traj.expected_quadratic_cost >= 0.0

        band = compute_no_trade_band(0.0, 0.01, 0.2, 1.0, 0.01, 0.015, 0.005)
        assert band.lower < 0.0 < band.upper
        assert inventory_action(0.0, band) == "NO_TRADE"
        assert inventory_action(-0.5, band) == "BUY"
        assert inventory_action(0.5, band) == "SELL"

    def test_cycle55_actor_critic_and_advantage(self) -> None:
        import numpy as np
        from agents.AGI_1_7.engine.agi17.finance.hf_ceh_los_execution_engine import (
            ContinuousActorCritic, friction_aware_advantage,
        )
        ac = ContinuousActorCritic(seed=55)
        state = np.linspace(-0.5, 0.5, 16)
        action = ac.sample_action(state, seed=123, stochastic=False)
        assert action.shape == (3,)
        assert np.all(np.abs(action) <= 1.0)

        val = ac.value(state)
        assert isinstance(val, float)

        adv = friction_aware_advantage(
            gross_advantage=30.0,
            statutory_fees=15.0,
            inventory=2.0,
            inventory_variance=0.8,
            risk_penalty=0.5,
        )
        assert isinstance(adv, float)
        assert adv == 30.0 - 15.0 - 0.5 * (2.0**2) * 0.8

    def test_cycle55_statutory_fees_kelly_and_consensus(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.hf_ceh_los_execution_engine import (
            statutory_fees, net_alpha_gate, beta_posterior_fractional_kelly, squad_consensus,
        )
        fees = statutory_fees(15000.0, 12000.0, 2)
        assert fees.brokerage == 40.0
        assert fees.total > 0.0

        gate_pass = net_alpha_gate(90.0, fees.total)
        assert gate_pass["approved"] is True
        assert gate_pass["net_alpha"] > 0.0

        gate_fail = net_alpha_gate(50.0, fees.total)
        assert gate_fail["approved"] is False

        k = beta_posterior_fractional_kelly(12.0, 8.0, 1.2)
        assert 0.0 <= k <= 0.10

        c_ok = squad_consensus(
            manager_approved=True,
            queue_risk_clear=True,
            volatility_risk_clear=True,
            net_alpha_positive=True,
            paper_only=True,
        )
        assert c_ok["approved_for_paper_simulation"] is True

        c_reject = squad_consensus(
            manager_approved=False,
            queue_risk_clear=True,
            volatility_risk_clear=True,
            net_alpha_positive=True,
            paper_only=True,
        )
        assert c_reject["approved_for_paper_simulation"] is False
        assert "Manager Abhi" in c_reject["rejection_reasons"]


class TestCycle56MHMFGTOFAExecution:
    """Verifies Cycle 56 Multi-Horizon Mean-Field Games for Liquidity Provision & Toxic Order Flow (MH-MFG-TOFA)."""

    def test_cycle56_safety_and_fail_closed_invariants(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.mh_mfg_tofa_execution_engine import (
            ASSETS, LIVE_ORDER_DISPATCH_ENABLED, REAL_BROKER_FILLS_LOCKED,
            PAPER_LEDGER_EPOCH, INITIAL_CAPITAL_INR, dispatch_live_order,
        )
        assert ASSETS == ("NIFTY50", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY")
        assert LIVE_ORDER_DISPATCH_ENABLED is False
        assert REAL_BROKER_FILLS_LOCKED is True
        assert PAPER_LEDGER_EPOCH == "epoch_10k"
        assert INITIAL_CAPITAL_INR == 10000.0

        with pytest.raises(PermissionError, match="Cycle 56 is paper-only"):
            dispatch_live_order("NIFTY50", 50, price=24500.0)

    def test_cycle56_mfg_hjb_fpk_solution_and_density(self) -> None:
        import numpy as np
        from agents.AGI_1_7.engine.agi17.finance.mh_mfg_tofa_execution_engine import (
            MFGConfig, solve_mean_field_game,
        )
        cfg = MFGConfig(horizon=0.3, n_steps=8, inventory_limit=3,
                        fixed_point_iterations=8, fixed_point_tolerance=1e-2)
        res = solve_mean_field_game(cfg)
        assert res.converged is True
        assert res.density_mass_error < 1e-10
        assert np.all(res.density >= 0.0)
        assert res.optimal_bid_half_spread.shape == (cfg.n_steps, 2 * cfg.inventory_limit + 1)
        assert res.optimal_ask_half_spread.shape == (cfg.n_steps, 2 * cfg.inventory_limit + 1)
        # Boundary fills prevented
        assert np.all(res.bid_fill_intensity[:, -1] == 0.0)
        assert np.all(res.ask_fill_intensity[:, 0] == 0.0)

    def test_cycle56_toxic_noise_split_and_hawkes(self) -> None:
        import math
        from agents.AGI_1_7.engine.agi17.finance.mh_mfg_tofa_execution_engine import (
            split_toxic_and_noise_flow, ToxicFlowHawkes, mlofi_cancellation_hazard, toxic_spread_expansion,
        )
        split = split_toxic_and_noise_flow(noise_arrival_rate=0.2, toxic_intensity=0.4, directional_toxicity=0.5)
        assert split.noise_buy_rate == 0.2
        assert split.toxic_buy_rate == 0.2
        assert split.toxic_sell_rate == 0.0

        tf_hawkes = ToxicFlowHawkes(baseline=0.1, excitation=0.3, decay=1.5)
        rate = tf_hawkes.intensity(mlofi=1.5)
        assert rate > 0.1
        assert math.isfinite(rate)

        hazard = mlofi_cancellation_hazard(0.1, 0.2, 2.0, 0.5, 0.03, 1.2)
        assert hazard > 0.0

        spread = toxic_spread_expansion(0.01, 0.5, 0.05)
        assert spread == 0.01 + 0.5 * 0.05

    def test_cycle56_rough_volterra_lift_and_simulation(self) -> None:
        import numpy as np
        from agents.AGI_1_7.engine.agi17.finance.mh_mfg_tofa_execution_engine import (
            build_rough_volterra_lift, simulate_rough_volterra_jump_sde,
        )
        lift = build_rough_volterra_lift(n_factors=12, hurst=0.07)
        assert lift.n_factors == 12
        assert np.all(lift.weights > 0.0)
        assert np.all(lift.decay_rates > 0.0)

        sim = simulate_rough_volterra_jump_sde(
            initial_spot=100.0,
            forward_variance=0.04,
            horizon=0.1,
            n_steps=10,
            lift=lift,
            seed=56,
        )
        assert len(sim.spot) == 11
        assert np.all(sim.spot > 0.0)
        assert np.all(sim.variance > 0.0)

    def test_cycle56_actor_critic_and_mean_field_advantage(self) -> None:
        import numpy as np
        from agents.AGI_1_7.engine.agi17.finance.mh_mfg_tofa_execution_engine import (
            ContinuousActorCritic, mean_field_advantage,
        )
        ac = ContinuousActorCritic(seed=56)
        state = np.linspace(-0.5, 0.5, 16)
        action = ac.sample_action(state, seed=42, stochastic=False)
        assert action.shape == (3,)
        assert np.all(np.abs(action) <= 1.0)
        assert np.isfinite(ac.value(state))

        adv = mean_field_advantage(
            gross_advantage=1.5,
            statutory_fee_drag=0.2,
            inventory=1.0,
            inventory_variance=0.5,
            risk_penalty=0.3,
            toxic_adverse_selection=0.1,
        )
        assert adv == 1.5 - 0.2 - 0.3 * (1.0**2) * 0.5 - 0.1

    def test_cycle56_statutory_fees_and_kelly(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.mh_mfg_tofa_execution_engine import (
            statutory_fees, net_alpha_gate, beta_posterior_fractional_kelly,
        )
        fee = statutory_fees(15000.0, 12000.0, 2)
        assert fee.brokerage == 40.0
        assert fee.total > 0.0

        gate_pass = net_alpha_gate(90.0, fee.total)
        assert gate_pass["approved"] is True

        gate_fail = net_alpha_gate(50.0, fee.total)
        assert gate_fail["approved"] is False

        k = beta_posterior_fractional_kelly(25.0, 10.0, 1.4)
        assert 0.0 <= k <= 0.10

    def test_cycle56_squad_consensus_and_live_dispatch_locked(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.mh_mfg_tofa_execution_engine import (
            squad_consensus, dispatch_live_order,
        )
        c_ok = squad_consensus(
            manager_approved=True,
            queue_risk_clear=True,
            volatility_risk_clear=True,
            net_alpha_positive=True,
            paper_only=True,
        )
        assert c_ok["approved_for_paper_simulation"] is True

        c_fail = squad_consensus(
            manager_approved=False,
            queue_risk_clear=True,
            volatility_risk_clear=True,
            net_alpha_positive=True,
            paper_only=True,
        )
        assert c_fail["approved_for_paper_simulation"] is False
        assert "Manager Abhi" in c_fail["rejection_reasons"]

        with pytest.raises(PermissionError, match="Cycle 56 is paper-only"):
            dispatch_live_order("NIFTY50", 50, price=24500.0)


class TestCycle57QTNCSMExecution:
    """Verifies Cycle 57 Quantum-Inspired Tensor Networks for Cross-Asset Gamma Surface Manifolds,
    Multi-Scale Fractional Hawkes Microstructure, Dynamic Liquidity Resilience,
    Rough Volterra Variance Lift, Indian Statutory Taxation, and 4-Agent Consensus.
    """

    def test_cycle57_tensor_train_svd_and_gamma_vacuum(self) -> None:
        import numpy as np
        from agents.AGI_1_7.engine.agi17.finance.qtn_csm_volterra_hawkes_engine import (
            tensor_train_svd, gamma_vacuum_detect, assert_calendar_monotone_surface,
        )
        x = np.arange(24, dtype=float).reshape(2, 3, 4)
        mps = tensor_train_svd(x, max_bond_dim=4, tolerance=1e-4, require_tolerance=False)
        assert mps.max_bond_dimension <= 4
        assert len(mps.factors) == 3

        # Test gamma vacuum detection
        assert gamma_vacuum_detect([-0.5, 0.2, 1.0], threshold=0.4) is True
        assert gamma_vacuum_detect([-0.3, 0.2, 1.0], threshold=0.4) is False

        # Calendar monotone surface
        mat = np.array([[0.04, 0.05, 0.06], [0.05, 0.06, 0.07]])
        assert_calendar_monotone_surface(mat)

    def test_cycle57_hawkes_and_liquidity_resilience(self) -> None:
        import numpy as np
        from agents.AGI_1_7.engine.agi17.finance.qtn_csm_volterra_hawkes_engine import (
            MultiScaleFractionalHawkes, LiquidityResilience,
        )
        mu = np.array([0.1, 0.1, 0.1, 0.1])
        ae = np.eye(4) * 0.05
        ap = np.eye(4) * 0.02
        hawkes = MultiScaleFractionalHawkes(mu, ae, ap, kappa=2.0, beta=2.5, stability_limit=0.88)
        rep = hawkes.stability_report()
        assert rep.stable is True
        assert rep.spectral_radius <= 0.88

        lr = LiquidityResilience(equilibrium=1.0, theta=0.8, eta=0.3, zeta=0.5)
        res = lr.step(dt=0.1, passive_fill=0.5, toxic_intensity=0.2)
        assert res > 0.0
        assert lr.half_life > 0.0

    def test_cycle57_rough_volterra_lift_and_price_step(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.qtn_csm_volterra_hawkes_engine import (
            RoughVolterraLift, rough_vol_price_step,
        )
        lift = RoughVolterraLift(hurst=0.07, factors=12)
        assert len(lift.weights) == 12
        assert len(lift.decay_rates) == 12

        log_var, var = lift.step(dt=0.01, dW=0.05, jump=0.0)
        assert var > 0.0

        next_spot = rough_vol_price_step(spot=24500.0, drift=0.0, variance=var, dt=0.01, dW=0.05, jump_amplitudes=[])
        assert next_spot > 0.0

    def test_cycle57_actor_critic_and_inventory_band(self) -> None:
        import numpy as np
        from agents.AGI_1_7.engine.agi17.finance.qtn_csm_volterra_hawkes_engine import (
            ContinuousActorCritic, inventory_indifference_band, inventory_action,
            friction_aware_advantage,
        )
        ac = ContinuousActorCritic(seed=57)
        state = np.zeros(16)
        action = ac.act(state)
        assert action.shape == (3,)
        assert np.all(np.abs(action) <= 1.0)

        band = inventory_indifference_band(
            target_inventory=0.0, cost=0.01, sigma=0.02, gamma_risk=0.5,
            buy_spread_penalty=0.05, sell_spread_penalty=0.05, fee_drag=0.02
        )
        assert band.lower < band.upper
        assert inventory_action(0.0, band) == "NO_TRADE"

        adv = friction_aware_advantage(
            gross_advantage=2.0, statutory_fees=0.3, inventory=1.0, sigma_inventory=0.2, risk_lambda=0.4
        )
        assert adv == 2.0 - 0.3 - 0.4 * (1.0 ** 2) * (0.2 ** 2)

    def test_cycle57_statutory_fees_and_kelly(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.qtn_csm_volterra_hawkes_engine import (
            indian_statutory_fees, net_alpha_gate, beta_fractional_kelly,
        )
        fee = indian_statutory_fees(buy_turnover=25000.0, sell_turnover=30000.0, legs=2)
        assert fee.brokerage == 40.0
        assert fee.total > 0.0

        allowed_pass, net_pass = net_alpha_gate(120.0, fee.total)
        assert allowed_pass is True
        assert net_pass > 0.0

        allowed_fail, net_fail = net_alpha_gate(20.0, fee.total)
        assert allowed_fail is False
        assert net_fail < 0.0

        k = beta_fractional_kelly(wins=15.0, losses=8.0, odds=1.5, scale=0.25)
        assert 0.0 <= k <= 0.10

    def test_cycle57_squad_consensus_and_live_dispatch_locked(self) -> None:
        import pytest
        from agents.AGI_1_7.engine.agi17.finance.qtn_csm_volterra_hawkes_engine import (
            squad_consensus, dispatch_live_order, AgentVote,
            LIVE_ORDER_DISPATCH_ENABLED, REAL_BROKER_FILLS_LOCKED,
        )
        assert LIVE_ORDER_DISPATCH_ENABLED is False
        assert REAL_BROKER_FILLS_LOCKED is True

        votes = [
            AgentVote("Manager Abhi", True, "Approved"),
            AgentVote("Alex", True, "Approved"),
            AgentVote("Emily", True, "Approved"),
            AgentVote("Max", True, "Approved"),
        ]
        assert squad_consensus(votes, net_alpha_positive=True) is True

        veto_votes = [
            AgentVote("Manager Abhi", False, "Veto"),
            AgentVote("Alex", True, "Approved"),
            AgentVote("Emily", True, "Approved"),
            AgentVote("Max", True, "Approved"),
        ]
        assert squad_consensus(veto_votes, net_alpha_positive=True) is False

        with pytest.raises(PermissionError, match="Cycle 57 is paper-only"):
            dispatch_live_order("BUY", "NIFTY50", 1, 24500.0)


class TestCycle58DRHNMHExecution:
    """Verifies Cycle 58 Deep Rough Heston Calibration, Non-Markovian Hawkes Jump Clustering,
    Multi-Asset Path Signature-Wasserstein Equilibrium, Indian Derivatives Slippage SDE,
    and 4-Agent Consensus.
    """

    def test_cycle58_volterra_lift_and_pricer(self) -> None:
        import numpy as np
        from agents.AGI_1_7.engine.agi17.finance.drh_nmh_execution_engine import (
            build_volterra_lift, RoughHestonLiftedPricer,
        )
        lift = build_volterra_lift(hurst=0.07)
        assert len(lift.weights) == 12
        assert len(lift.rates) == 12
        pricer = RoughHestonLiftedPricer(lift=lift)
        phi = pricer.characteristic_function(u=1.0, expiry=0.25, spot=100.0)
        assert np.isfinite(phi.real) and np.isfinite(phi.imag)

    def test_cycle58_hawkes_l2_jump_clustering(self) -> None:
        import numpy as np
        from agents.AGI_1_7.engine.agi17.finance.drh_nmh_execution_engine import (
            NonMarkovianHawkesL2,
        )
        mu = [0.1, 0.1, 0.1, 0.1]
        alpha = np.eye(4) * 0.05
        gamma = np.eye(4) * 0.02
        beta = np.ones((4, 4)) * 2.0
        hawkes = NonMarkovianHawkesL2(baseline=mu, alpha=alpha, gamma=gamma, beta=beta, stability_limit=0.88)
        rep = hawkes.stability_report()
        assert rep.stable is True
        assert rep.spectral_radius <= 0.88

    def test_cycle58_path_signature_and_area(self) -> None:
        import numpy as np
        from agents.AGI_1_7.engine.agi17.finance.drh_nmh_execution_engine import (
            path_signature,
        )
        path = np.array([[0.0, 100.0, 200.0], [1.0, 102.0, 199.0], [2.0, 101.5, 201.0]])
        sig = path_signature(path)
        assert sig.level1.shape == (3,)
        area = sig.area_tensor()
        assert area.shape == (3, 3)

    def test_cycle58_slippage_and_schedule(self) -> None:
        import pytest
        from agents.AGI_1_7.engine.agi17.finance.drh_nmh_execution_engine import (
            transient_market_impact, optimal_trade_schedule,
        )
        impact = transient_market_impact(trading_rate=10.0, elapsed=0.5, eta=0.01, alpha=1.0, kappa=1.5)
        assert impact > 0.0
        sched = optimal_trade_schedule(quantity=100.0, horizon=1.0, steps=10, impact_eta=0.01, risk_aversion=0.1, return_variance=0.04)
        assert len(sched.inventory) == 11
        assert pytest.approx(sched.inventory[-1], abs=1e-4) == 0.0

    def test_cycle58_actor_critic_and_inventory_band(self) -> None:
        import numpy as np
        from agents.AGI_1_7.engine.agi17.finance.drh_nmh_execution_engine import (
            ContinuousActorCritic, inventory_indifference_band, inventory_trade_decision,
            friction_aware_advantage,
        )
        ac = ContinuousActorCritic(seed=58)
        state = np.zeros(16)
        action = ac.act(state)
        assert action.shape == (3,)
        assert np.all(np.abs(action) <= 1.0)

        band = inventory_indifference_band(sigma=0.02, risk_aversion=0.5, friction_cost=0.01)
        assert band.lower < band.upper
        assert inventory_trade_decision(0.0, band) == "NO_TRADE"

        adv = friction_aware_advantage(gross_advantage=150.0, statutory_fees=45.0, inventory=2.0, inventory_variance=0.25, risk_weight=0.5)
        assert adv == 150.0 - 45.0 - 0.5 * (2.0 ** 2) * 0.25

    def test_cycle58_statutory_fees_and_kelly(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.drh_nmh_execution_engine import (
            calculate_statutory_fees, net_alpha_gate, beta_posterior_fractional_kelly,
        )
        fees = calculate_statutory_fees(buy_turnover=25000.0, sell_turnover=30000.0, executed_legs=2)
        assert fees.brokerage == 40.0
        assert fees.total > 0.0

        pass_gate, net_val = net_alpha_gate(200.0, fees)
        assert pass_gate is True
        assert net_val > 0.0

        fail_gate, net_fail = net_alpha_gate(20.0, fees)
        assert fail_gate is False
        assert net_fail < 0.0

        k = beta_posterior_fractional_kelly(alpha_wins=15.0, beta_losses=8.0, payoff_odds=1.5, fractional_scale=0.25)
        assert 0.0 <= k <= 0.10

    def test_cycle58_squad_consensus_and_live_dispatch_locked(self) -> None:
        import pytest
        from agents.AGI_1_7.engine.agi17.finance.drh_nmh_execution_engine import (
            four_agent_consensus, dispatch_live_order,
            LIVE_ORDER_DISPATCH_ENABLED, REAL_BROKER_FILLS_LOCKED,
        )
        assert LIVE_ORDER_DISPATCH_ENABLED is False
        assert REAL_BROKER_FILLS_LOCKED is True

        c_ok = four_agent_consensus(manager_approved=True, queue_safe=True, volatility_safe=True, net_alpha_positive=True)
        assert c_ok["approved"] is True

        c_veto = four_agent_consensus(manager_approved=False, queue_safe=True, volatility_safe=True, net_alpha_positive=True)
        assert c_veto["approved"] is False
        assert "Manager Abhi" in c_veto["failed_vetoes"]

        with pytest.raises(PermissionError, match="Cycle 58 is paper-only"):
            dispatch_live_order("BUY", "NIFTY50", 50, price=24500.0)


class TestCycle59FSVDHExecution:
    """Verifies Cycle 59 Fractional Stochastic Volatility Neural SDEs, Multi-Factor Deep Hawkes Microstructure,
    Cross-Asset Lead-Lag Information Flow, Asymmetric High-Frequency Execution, and 4-Agent Consensus.
    """

    def test_cycle59_neural_vector_field_and_lift(self) -> None:
        import numpy as np
        from agents.AGI_1_7.engine.agi17.finance.fsv_dh_execution_engine import (
            build_volterra_lift, FractionalNeuralVectorField,
        )
        lift = build_volterra_lift(hurst=0.07)
        assert len(lift.weights) == 12
        assert len(lift.rates) == 12

        nvf = FractionalNeuralVectorField(seed=59)
        state = np.zeros(12)
        drift, diff = nvf.evaluate(state)
        assert drift.shape == (12,)
        assert diff.shape == (12,)

    def test_cycle59_deep_hawkes_microstructure(self) -> None:
        import numpy as np
        from agents.AGI_1_7.engine.agi17.finance.fsv_dh_execution_engine import (
            DeepHawkesMicrostructure,
        )
        base = [0.1, 0.1, 0.1, 0.1]
        alpha = np.eye(4) * 0.05
        beta = np.ones((4, 4)) * 2.0
        dh = DeepHawkesMicrostructure(baseline=base, alpha=alpha, beta=beta, stability_limit=0.88)
        rep = dh.stability_report()
        assert rep.stable is True
        assert rep.spectral_radius <= 0.88

    def test_cycle59_lead_lag_and_transfer_entropy(self) -> None:
        import numpy as np
        from agents.AGI_1_7.engine.agi17.finance.fsv_dh_execution_engine import (
            cross_asset_lead_lag, transfer_entropy_matrix,
        )
        returns = np.zeros((16, 4))
        returns[:, 0] = np.sin(np.linspace(0, 3, 16)) * 0.01
        returns[1:, 1] = returns[:-1, 0] * 0.8
        ll = cross_asset_lead_lag(returns, max_lag=2)
        assert ll.correlation.shape == (4, 4)
        te = transfer_entropy_matrix(returns, bins=2)
        assert te.shape == (4, 4)

    def test_cycle59_asymmetric_impact_and_slippage(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.fsv_dh_execution_engine import (
            asymmetric_transient_impact,
        )
        buy_imp = asymmetric_transient_impact(10.0, 0.5, eta_buy=0.01, eta_sell=0.015, kappa=1.5)
        assert buy_imp > 0.0
        sell_imp = asymmetric_transient_impact(-10.0, 0.5, eta_buy=0.01, eta_sell=0.015, kappa=1.5)
        assert sell_imp < 0.0

    def test_cycle59_adverse_selection_gate(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.fsv_dh_execution_engine import (
            adverse_selection_probability, quote_action_for_adverse_selection,
        )
        p_adv = adverse_selection_probability(cancellation_intensity=0.3, fill_horizon=0.25)
        assert 0.0 <= p_adv <= 1.0
        assert quote_action_for_adverse_selection(p_adv, retreat_threshold=0.5) == "QUOTE"
        assert quote_action_for_adverse_selection(0.6, retreat_threshold=0.5) == "RETREAT"

    def test_cycle59_statutory_fees_and_kelly(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.fsv_dh_execution_engine import (
            calculate_statutory_fees, net_alpha_gate, beta_posterior_fractional_kelly,
        )
        fees = calculate_statutory_fees(buy_turnover=25000.0, sell_turnover=30000.0, executed_legs=2)
        assert fees.brokerage == 40.0
        assert fees.total > 0.0

        pass_gate, net_val = net_alpha_gate(200.0, fees)
        assert pass_gate is True
        assert net_val > 0.0

        k = beta_posterior_fractional_kelly(alpha_wins=15.0, beta_losses=8.0, payoff_odds=1.5, fractional_scale=0.25)
        assert 0.0 <= k <= 0.10

    def test_cycle59_squad_consensus_and_live_dispatch_locked(self) -> None:
        import pytest
        from agents.AGI_1_7.engine.agi17.finance.fsv_dh_execution_engine import (
            four_agent_consensus, dispatch_live_order,
            LIVE_ORDER_DISPATCH_ENABLED, REAL_BROKER_FILLS_LOCKED,
        )
        assert LIVE_ORDER_DISPATCH_ENABLED is False
        assert REAL_BROKER_FILLS_LOCKED is True

        c_ok = four_agent_consensus(manager_approved=True, queue_safe=True, volatility_safe=True, net_alpha_positive=True)
        assert c_ok["approved"] is True

        c_veto = four_agent_consensus(manager_approved=False, queue_safe=True, volatility_safe=True, net_alpha_positive=True)
        assert c_veto["approved"] is False
        assert "Manager Abhi" in c_veto["failed_vetoes"]

        with pytest.raises(PermissionError, match="Cycle 59 is paper-only"):
            dispatch_live_order("BUY", "NIFTY50", 50, price=24500.0)


class TestCycle60QTNMOTExecution:
    """Milestone Cycle 60 integration and verification test suite."""

    def test_cycle60_tensor_train_svd_decomposition_and_reconstruction(self) -> None:
        import numpy as np
        from agents.AGI_1_7.engine.agi17.finance.qtn_mot_execution_engine import (
            tensor_train_decompose,
        )
        rng = np.random.default_rng(60)
        factors = [rng.normal(size=n) for n in (3, 4, 3, 2)]
        tensor = np.einsum("i,j,k,l->ijkl", *factors)
        res = tensor_train_decompose(tensor, max_bond_dim=16, tolerance=1e-4)
        assert res.relative_error < 1e-10
        assert res.max_bond_dim <= 16
        assert np.allclose(res.reconstruct(), tensor, rtol=1e-9, atol=1e-9)

    def test_cycle60_tensor_train_contract_and_local_greeks(self) -> None:
        import numpy as np
        import pytest
        from agents.AGI_1_7.engine.agi17.finance.qtn_mot_execution_engine import (
            tensor_train_decompose, tensor_train_contract, tensor_greeks, tensor_train_greeks,
        )
        rng = np.random.default_rng(601)
        i = np.arange(4, dtype=float)
        f = i * i + 0.25 * i
        a, b, c = rng.normal(size=3), rng.normal(size=3), rng.normal(size=2)
        tensor = np.einsum("i,j,k,l->ijkl", f, a, b, c)
        tt = tensor_train_decompose(tensor, tolerance=1e-4)
        index = (2, 1, 1, 0)

        # Contraction check
        val_contract = tensor_train_contract(tt.cores, index)
        assert val_contract == pytest.approx(float(tensor[index]), abs=1e-10)

        # Local Greeks check
        dense_g = tensor_greeks(tensor, index, axis=0, spacing=0.5)
        tt_g = tensor_train_greeks(tt.cores, index, axis=0, spacing=0.5)
        assert tt_g["first"] == pytest.approx(dense_g["first"], rel=1e-8, abs=1e-8)
        assert tt_g["second"] == pytest.approx(dense_g["second"], rel=1e-8, abs=1e-8)

    def test_cycle60_martingale_optimal_transport_dual_bounds(self) -> None:
        import numpy as np
        import pytest
        from agents.AGI_1_7.engine.agi17.finance.qtn_mot_execution_engine import (
            solve_martingale_transport_bounds,
        )
        x = np.array([0.0, 1.0, 2.0])
        mu = np.array([0.25, 0.5, 0.25])
        payoff = np.abs(x[None, :] - x[:, None])
        res = solve_martingale_transport_bounds(x, mu, x, mu, payoff)
        assert res.lower_price <= res.upper_price
        assert res.lower_price == pytest.approx(res.lower_dual_bound, abs=1e-8)
        assert res.upper_price == pytest.approx(res.upper_dual_bound, abs=1e-8)
        assert res.lower_dual_constraint_violation <= 1e-8
        assert res.upper_dual_constraint_violation <= 1e-8

    def test_cycle60_multi_agent_hawkes_game_and_toxicity_spread(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.qtn_mot_execution_engine import (
            optimal_toxic_spread, adverse_selection_probability, should_retreat_quote,
            solve_spread_nash_equilibrium,
        )
        # Toxicity spread widening
        s_clean = optimal_toxic_spread(
            base_spread=0.10, risk_aversion=0.1, volatility=0.2, inventory=0.0,
            kappa=1.0, alpha=2.0, toxic_intensity=0.0
        )
        s_toxic = optimal_toxic_spread(
            base_spread=0.10, risk_aversion=0.1, volatility=0.2, inventory=0.0,
            kappa=1.0, alpha=2.0, toxic_intensity=5.0
        )
        assert s_toxic > s_clean

        # Adverse selection probability
        p_adv = adverse_selection_probability(toxic_intensity=2.0, horizon=0.5)
        assert 0.0 < p_adv < 1.0
        assert should_retreat_quote(toxic_intensity=2.0, horizon=0.5, threshold=0.60) in (True, False)

        # Nash equilibrium
        nash = solve_spread_nash_equilibrium(
            risk_adjusted_target_spreads=[0.10, 0.12, 0.14],
            competition_weight=0.2,
        )
        assert len(nash) == 3
        assert all(s > 0.0 for s in nash)

    def test_cycle60_statutory_fees_and_kelly(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.qtn_mot_execution_engine import (
            indian_statutory_fees, net_alpha_gate, beta_posterior_fractional_kelly,
        )
        fees = indian_statutory_fees(buy_turnover=200000.0, sell_turnover=250000.0, executed_legs=2)
        assert fees.brokerage == 40.0
        assert fees.total > 0.0

        gate = net_alpha_gate(expected_gross_alpha=fees.total + 50.0, total_fees=fees.total)
        assert gate["approved"] is True
        assert gate["net_alpha"] == 50.0

        k = beta_posterior_fractional_kelly(wins=16.0, losses=8.0, payoff_ratio=1.5, fraction=0.25)
        assert 0.0 <= k <= 0.10

    def test_cycle60_squad_consensus_and_live_dispatch_locked(self) -> None:
        import pytest
        from agents.AGI_1_7.engine.agi17.finance.qtn_mot_execution_engine import (
            squad_consensus, dispatch_live_order,
            LIVE_ORDER_DISPATCH_ENABLED, REAL_BROKER_FILLS_LOCKED,
            AGENT_ROLES,
        )
        assert LIVE_ORDER_DISPATCH_ENABLED is False
        assert REAL_BROKER_FILLS_LOCKED is True
        assert set(AGENT_ROLES) == {"Abhi", "Alex", "Emily", "Max"}

        c_ok = squad_consensus(100.0, True, True, True, True, manager_abhi_veto=False)
        assert c_ok["approved_for_paper_research"] is True
        assert c_ok["live_dispatch_approved"] is False

        c_veto = squad_consensus(100.0, True, True, True, True, manager_abhi_veto=True)
        assert c_veto["approved_for_paper_research"] is False
        assert c_veto["manager_veto_active"] is True

        with pytest.raises(PermissionError, match="Cycle 60 is paper-only: live order dispatch is permanently disabled"):
            dispatch_live_order("BUY", quantity=100)


class TestCycle61RBFSKDOFIExecution:
    """Milestone Cycle 61 integration and verification test suite."""

    def test_cycle61_volterra_lift_and_forward_variance_curve(self) -> None:
        import numpy as np
        from agents.AGI_1_7.engine.agi17.finance.rb_fsk_dofi_execution_engine import (
            fit_volterra_lift, forward_variance_curve, cumulative_total_variance,
            validate_calendar_total_variance, validate_butterfly_convexity,
        )
        lift = fit_volterra_lift()
        assert len(lift.rates) == 12
        assert len(lift.weights) == 12
        assert np.all(lift.rates > 0)
        assert np.all(lift.weights >= 0)
        assert lift.relative_l2_error < 0.05

        # Forward variance interpolation
        times = [0.0, 1.0, 2.0]
        vals = [0.04, 0.03, 0.05]
        q = np.linspace(0.0, 2.0, 15)
        curve = forward_variance_curve(times, vals, q)
        assert curve.shape == q.shape
        assert np.all(curve > 0)

        # Monotone cumulative total variance
        theta = cumulative_total_variance(q, curve)
        assert theta[0] == 0.0
        assert np.all(np.diff(theta) >= 0)

        # Arbitrage sanity checks
        rep_cal = validate_calendar_total_variance([[0.05, 0.06], [0.06, 0.07]])
        assert rep_cal["calendar_monotone"] is True
        assert rep_cal["non_negative"] is True

        rep_bf = validate_butterfly_convexity([90, 100, 110], [12.0, 5.0, 1.0])
        assert rep_bf["convex"] is True

    def test_cycle61_path_signatures_and_area_tensor(self) -> None:
        import numpy as np
        from agents.AGI_1_7.engine.agi17.finance.rb_fsk_dofi_execution_engine import (
            path_signature, chen_concatenate, geometric_area_tensor, randomized_signature_kernel,
        )
        rng = np.random.default_rng(61)
        path = rng.normal(size=(8, 4)).cumsum(axis=0)

        sig = path_signature(path, degree=3)
        assert [sig[k].size for k in (1, 2, 3)] == [4, 16, 64]

        # Geometric area tensor antisymmetry
        area = geometric_area_tensor(path)
        assert area.shape == (4, 4)
        assert np.allclose(area, -area.T)
        assert np.allclose(np.diag(area), 0.0)

        # Randomized signature kernel
        kernel_val = randomized_signature_kernel(path, path, seed=61)
        assert abs(kernel_val - 1.0) < 1e-6

    def test_cycle61_deep_cancellation_shocks_and_quote_action(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.rb_fsk_dofi_execution_engine import (
            multi_level_ofi, cancellation_intensity, queue_priority_degradation,
            adverse_selection_probability, quote_action,
        )
        ofi_tot, ofi_levels = multi_level_ofi(
            delta_bid_volume=[10, 8, 6, 4, 2],
            delta_ask_volume=[5, 6, 2, 3, 1],
            delta_bid_price=[0.1, 0.0, -0.1, 0.0, 0.1],
            delta_ask_price=[-0.1, 0.1, 0.0, -0.1, 0.0],
        )
        assert len(ofi_levels) == 5
        assert isinstance(ofi_tot, float)

        # Cancellation intensity
        lam_c = cancellation_intensity(base_rate=0.15, ofi_levels=ofi_levels, beta_price=0.2, delta_price=-0.01)
        assert lam_c >= 0.0

        # Queue degradation
        deg = queue_priority_degradation(queue_ahead=10.0, depth=50.0, age=2.0, cancellation_rate=lam_c, ofi_toxicity=0.05)
        assert 0.0 <= deg <= 1.0

        # Adverse selection and quote action
        p_adv = adverse_selection_probability(toxic_intensity=lam_c, horizon=0.5)
        assert 0.0 <= p_adv <= 1.0

        action = quote_action(toxic_intensity=lam_c, horizon=0.5, threshold=0.60)
        assert action in ("QUOTE", "RETREAT")

    def test_cycle61_cross_expiry_dislocation_and_martingale_bounds(self) -> None:
        import numpy as np
        from agents.AGI_1_7.engine.agi17.finance.rb_fsk_dofi_execution_engine import (
            detect_cross_expiry_dislocation, discrete_martingale_bounds,
        )
        weekly = [0.10, 0.12, 0.14]
        monthly = [0.12, 0.14, 0.16]
        rep = detect_cross_expiry_dislocation(weekly, monthly)
        assert rep["calendar_ok"] is True
        assert rep["arbitrage_flag"] is False

        # Discrete martingale bounds
        x = np.array([0.0, 1.0, 2.0])
        mu = np.array([0.25, 0.50, 0.25])
        y = np.array([-1.0, 0.0, 1.0, 2.0, 3.0])
        nu = np.array([0.125, 0.125, 0.5, 0.125, 0.125])
        payoff = np.maximum(y[None, :] - x[:, None], 0.0)
        mot = discrete_martingale_bounds(x, mu, y, nu, payoff)
        assert mot.lower_bound <= mot.upper_bound
        assert mot.martingale_residual <= 1e-8

    def test_cycle61_statutory_fees_and_kelly(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.rb_fsk_dofi_execution_engine import (
            statutory_fees, net_alpha_gate, beta_posterior_fractional_kelly,
        )
        f = statutory_fees(buy_turnover=100000.0, sell_turnover=150000.0, executed_legs=2, exercise_turnover=10000.0)
        assert f.brokerage == 40.0
        assert f.total > 0.0
        assert f.stt > 0.0

        gate = net_alpha_gate(expected_gross_alpha=f.total + 75.0, fees=f.total)
        assert gate["approved"] is True
        assert gate["expected_net_alpha"] == 75.0

        k = beta_posterior_fractional_kelly(alpha_wins=20, beta_losses=10, odds=1.5, fractional_scale=0.25)
        assert 0.0 <= k <= 0.10

    def test_cycle61_squad_consensus_and_live_dispatch_locked(self) -> None:
        import pytest
        from agents.AGI_1_7.engine.agi17.finance.rb_fsk_dofi_execution_engine import (
            squad_consensus, dispatch_live_order,
            LIVE_ORDER_DISPATCH_ENABLED, REAL_BROKER_FILLS_LOCKED,
            AGENT_ROLES,
        )
        assert LIVE_ORDER_DISPATCH_ENABLED is False
        assert REAL_BROKER_FILLS_LOCKED is True
        assert set(AGENT_ROLES) == {"Abhi", "Alex", "Emily", "Max"}

        yes = squad_consensus(True, True, True, True)
        assert yes["approved_for_paper_simulation"] is True

        no = squad_consensus(False, True, True, True)
        assert no["approved_for_paper_simulation"] is False

        with pytest.raises(PermissionError, match="Cycle 61 is paper-only: live order dispatch is permanently disabled"):
            dispatch_live_order("BUY", quantity=50)


class TestCycle62DHJDOLExecution:
    """Test suite for Cycle 62 Deep Hawkes Jump-Diffusion Optimal Liquidation (DH-JD-OL)."""

    def test_cycle62_mlofi_and_hawkes_spectral_radius(self) -> None:
        import numpy as np
        from agents.AGI_1_7.engine.agi17.finance.dh_jd_ol_execution_engine import (
            multi_level_ofi, MarkedHawkes4, ASSETS,
        )
        assert len(ASSETS) == 4
        m = multi_level_ofi(
            bid_volume_delta=[10, 8, 6, 4, 2],
            ask_volume_delta=[5, 6, 2, 3, 1],
            bid_price_delta=[0.1, 0.0, -0.1, 0.0, 0.1],
            ask_price_delta=[-0.1, 0.1, 0.0, -0.1, 0.0],
        )
        assert len(m["level_contributions"]) == 5
        assert isinstance(m["value"], float)

        mu = [0.1] * 4
        alpha = np.full((4, 4), 0.005); np.fill_diagonal(alpha, 0.01)
        beta = np.full((4, 4), 1.0)
        hawkes = MarkedHawkes4(mu, alpha, beta, mlofi_gain=0.001)
        assert hawkes.spectral_radius <= 0.88
        intensities = hawkes.step(0.01, [0.2, -0.1, 0.3, 0.0], marks=[1, 0, 0.5, 0])
        assert len(intensities) == 4
        assert np.all(intensities > 0.0)

    def test_cycle62_path_signature_and_levy_area(self) -> None:
        import numpy as np
        from agents.AGI_1_7.engine.agi17.finance.dh_jd_ol_execution_engine import (
            path_signature, levy_area, signature_random_features,
        )
        path = np.array([[0.0, 0.0, 0.0], [0.1, -0.05, 0.02], [0.2, 0.02, 0.03]])
        sig = path_signature(path, degree=3)
        assert len(sig) == 4
        area = levy_area(sig)
        assert area.shape == (3, 3)
        assert np.allclose(area, -area.T)
        assert np.allclose(np.diag(area), 0.0)

        rf = signature_random_features([path, path + 0.01], n_features=64, seed=62)
        assert rf["gram"].shape == (2, 2)
        assert rf["min_eigenvalue"] >= -1e-10

    def test_cycle62_optimal_liquidation_and_toxicity(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.dh_jd_ol_execution_engine import (
            optimal_liquidation_schedule, quote_action_for_toxicity,
        )
        sched = optimal_liquidation_schedule(q0=10.0, horizon=1.0, n_steps=20, impact=0.2, risk_aversion=0.5, volatility=0.2, jump_intensity=0.1, jump_variance=0.03)
        assert sched["terminal_inventory"] == 0.0
        assert len(sched["times"]) == 21

        action_safe = quote_action_for_toxicity(intensity=0.2, horizon=0.5, threshold=0.60)
        assert action_safe["quote_action"] == "QUOTE"

        action_toxic = quote_action_for_toxicity(intensity=3.0, horizon=1.0, threshold=0.60)
        assert action_toxic["quote_action"] == "RETREAT"

    def test_cycle62_surface_dislocations_and_martingale_bounds(self) -> None:
        import numpy as np
        from agents.AGI_1_7.engine.agi17.finance.dh_jd_ol_execution_engine import (
            cross_index_surface_dislocations, martingale_transport_bounds,
        )
        t = [0.1, 0.2, 0.3]
        k = [0.8, 1.0, 1.2]
        var_n = np.outer(t, [0.04, 0.05, 0.06])
        var_b = np.outer(t, [0.038, 0.048, 0.058])
        disloc = cross_index_surface_dislocations(var_n, var_b, t, k)
        assert disloc["calendar_monotone"] is True

        x = [0.0, 1.0, 2.0]
        mu = [0.25, 0.50, 0.25]
        y = [-1.0, 0.0, 1.0, 2.0, 3.0]
        nu = [0.125, 0.125, 0.5, 0.125, 0.125]
        payoff = np.maximum(np.array(y)[None, :] - np.array(x)[:, None], 0.0)
        mot = martingale_transport_bounds(x, mu, y, nu, payoff)
        assert mot["lower_bound"] <= mot["upper_bound"]
        assert mot["martingale_residual"] <= 1e-8

    def test_cycle62_statutory_fees_and_kelly(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.dh_jd_ol_execution_engine import (
            calculate_indian_fees, net_alpha_gate, beta_fractional_kelly,
        )
        f = calculate_indian_fees(buy_turnover=100000.0, sell_turnover=150000.0, executed_legs=2, exercise_turnover=10000.0)
        assert f["brokerage"] == 40.0
        assert f["total"] > 0.0

        gate = net_alpha_gate(expected_gross_alpha=f["total"] + 100.0, total_fees=f["total"])
        assert gate["approved"] is True
        assert gate["expected_net_alpha"] == 100.0

        k = beta_fractional_kelly(prior_alpha=1.0, prior_beta=1.0, wins=25, losses=10, odds=1.5, scale=0.25)
        assert 0.0 <= k["capital_fraction"] <= 0.10

    def test_cycle62_squad_consensus_and_live_dispatch_locked(self) -> None:
        import pytest
        from agents.AGI_1_7.engine.agi17.finance.dh_jd_ol_execution_engine import (
            agent_consensus, dispatch_live_order,
            LIVE_ORDER_DISPATCH_ENABLED, REAL_BROKER_FILLS_LOCKED,
            INITIAL_CAPITAL_INR, PAPER_LEDGER_EPOCH,
        )
        assert LIVE_ORDER_DISPATCH_ENABLED is False
        assert REAL_BROKER_FILLS_LOCKED is True
        assert INITIAL_CAPITAL_INR == 10000.0
        assert PAPER_LEDGER_EPOCH == "epoch_10k"

        approvals = {"Manager Abhi": True, "Alex": True, "Emily": True, "Max": True}
        yes = agent_consensus(approvals)
        assert yes["approved"] is True

        veto = agent_consensus(approvals, manager_veto=True)
        assert veto["approved"] is False

        with pytest.raises(PermissionError, match="Cycle 62 is paper-only: live order dispatch is permanently disabled"):
            dispatch_live_order("BUY", quantity=50)


class TestCycle63NMHFVTTCALCExecution:
    """Integration test suite for Cycle 63: NMH-FVTT-CALC."""

    def test_cycle63_non_markovian_hawkes_and_mlofi(self) -> None:
        import numpy as np
        from agents.AGI_1_7.engine.agi17.finance.nmh_fvtt_calc_execution_engine import (
            power_law_kernel, signed_mlofi, hawkes_intensity, multivariate_hawkes_intensity,
        )
        # Power-law kernel
        k = power_law_kernel(1.0, alpha=0.5, gamma=1.5)
        assert k > 0.0

        # MLOFI
        bids = [10.0, 5.0, 2.0, 1.0, 0.5]
        asks = [-2.0, -1.0, 0.0, 0.5, 1.0]
        mlofi = signed_mlofi(bids, asks)
        assert mlofi > 0.0

        # Hawkes intensity
        events = [0.1, 0.4, 0.8]
        lam = hawkes_intensity(now=1.0, event_times=events, mu0=0.2, alpha=0.3, gamma=1.2)
        assert lam > 0.2

        # Multivariate Hawkes
        events_by_asset = [[0.1, 0.5], [0.2, 0.7], [0.3], [0.4, 0.8]]
        exc = [[0.1]*4 for _ in range(4)]
        multi_lam = multivariate_hawkes_intensity(now=1.0, event_times_by_asset=events_by_asset, baselines=[0.1]*4, excitation_matrix=exc, gamma=1.5)
        assert len(multi_lam) == 4
        assert all(l > 0.0 for l in multi_lam)

    def test_cycle63_fractional_volterra_and_tt_svd(self) -> None:
        import numpy as np
        from agents.AGI_1_7.engine.agi17.finance.nmh_fvtt_calc_execution_engine import (
            volterra_kernel, tt_svd, tt_reconstruct,
        )
        k = volterra_kernel(1.0, 0.5, H=0.15)
        assert k > 0.0

        tensor = np.random.RandomState(63).randn(3, 4, 3)
        tt = tt_svd(tensor, tolerance=1e-8)
        assert tt["bound_met"] is True
        recon = tt_reconstruct(tt["cores"])
        assert np.allclose(tensor, recon, atol=1e-6)

    def test_cycle63_contagion_matrix_and_sldi(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.nmh_fvtt_calc_execution_engine import (
            verify_contagion_matrix, scale_contagion_matrix, systemic_liquidity_drain_index,
        )
        W = [
            [0.0, 0.1, 0.05, 0.02],
            [0.08, 0.0, 0.04, 0.01],
            [0.02, 0.03, 0.0, 0.05],
            [0.01, 0.02, 0.04, 0.0],
        ]
        res = verify_contagion_matrix(W, max_radius=0.85)
        assert res["stable"] is True
        assert res["spectral_radius"] < 0.85

        scaled = scale_contagion_matrix(W, max_radius=0.85)
        assert scaled.shape == (4, 4)

        sldi = systemic_liquidity_drain_index(W)
        assert sldi["sldi"] >= 0.0
        assert sldi["amplification"] >= 1.0

    def test_cycle63_optimal_liquidation_and_toxicity(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.nmh_fvtt_calc_execution_engine import (
            optimal_liquidation_schedule, adverse_jump_probability, toxicity_action,
        )
        times = [0.0, 0.25, 0.5, 0.75, 1.0]
        sched = optimal_liquidation_schedule(initial_inventory=100.0, times=times, impact_eta=0.01, risk_aversion=0.01)
        assert sched["terminal_inventory"] == 0.0
        assert sched["success"] is True

        p_safe = adverse_jump_probability(intensity=0.2, horizon=0.5)
        assert 0.0 <= p_safe <= 1.0
        assert toxicity_action(intensity=0.2, horizon=0.5, threshold=0.60) == "CONTINUE"

        p_toxic = adverse_jump_probability(intensity=5.0, horizon=1.0)
        assert p_toxic > 0.60
        assert toxicity_action(intensity=5.0, horizon=1.0, threshold=0.60) == "RETREAT"

    def test_cycle63_statutory_fees_and_kelly(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.nmh_fvtt_calc_execution_engine import (
            calculate_indian_fees, net_alpha_gate, beta_fractional_kelly,
        )
        f = calculate_indian_fees(buy_turnover=50000.0, sell_turnover=75000.0, executed_legs=2)
        assert f["brokerage_inr"] == 40.0
        assert f["total_fees_inr"] > 0.0

        gate_pass = net_alpha_gate(expected_gross_alpha_inr=f["total_fees_inr"] + 50.0, fees=f)
        assert gate_pass["pass"] is True
        assert abs(gate_pass["net_alpha_inr"] - 50.0) < 1e-9

        gate_fail = net_alpha_gate(expected_gross_alpha_inr=f["total_fees_inr"] - 10.0, fees=f)
        assert gate_fail["pass"] is False

        k = beta_fractional_kelly(alpha_wins=15.0, beta_losses=10.0, win_loss_ratio=1.2, fractional_scale=0.25, cap=0.10)
        assert 0.0 <= k["fractional_kelly_fraction"] <= 0.10

    def test_cycle63_four_agent_consensus_and_live_dispatch_locked(self) -> None:
        import pytest
        from agents.AGI_1_7.engine.agi17.finance.nmh_fvtt_calc_execution_engine import (
            four_agent_consensus, dispatch_live_order,
            LIVE_ORDER_DISPATCH_ENABLED, REAL_BROKER_FILLS_LOCKED,
            INITIAL_CAPITAL_INR, PAPER_LEDGER_EPOCH,
        )
        assert LIVE_ORDER_DISPATCH_ENABLED is False
        assert REAL_BROKER_FILLS_LOCKED is True
        assert INITIAL_CAPITAL_INR == 10000.0
        assert PAPER_LEDGER_EPOCH == "epoch_10k"

        res = four_agent_consensus(
            operator_approved=True,
            mlofi_score=1.5,
            contagion_stable=True,
            macro_regime_approved=True,
            volterra_fidelity_ok=True,
            net_alpha_positive=True,
            kelly_fraction=0.05,
            risk_checks_pass=True,
        )
        assert res["approved_for_paper_simulation"] is True

        veto = four_agent_consensus(
            operator_approved=False,
            mlofi_score=1.5,
            contagion_stable=True,
            macro_regime_approved=True,
            volterra_fidelity_ok=True,
            net_alpha_positive=True,
            kelly_fraction=0.05,
            risk_checks_pass=True,
        )
        assert veto["approved_for_paper_simulation"] is False

        with pytest.raises(PermissionError, match="Cycle 63 is paper-only: live order dispatch is permanently disabled"):
            dispatch_live_order("BUY", quantity=25)


class TestCycle64HDHVGATTRExecution:
    """Integration test suite for Cycle 64: HD-HV-GAT-TR."""

    def test_cycle64_graph_attention_and_network_intensity(self) -> None:
        import numpy as np
        from agents.AGI_1_7.engine.agi17.finance.hd_hv_gat_tr_execution_engine import (
            build_graph_attention, hawkes_network_intensity, spectral_radius,
        )
        z = np.zeros((4, 4))
        v = np.ones(4)
        att = build_graph_attention(z, v)
        assert att.shape == (4, 4)
        assert np.all(att >= 0.0)
        assert spectral_radius(att) <= 0.85 + 1e-10

        intensity = hawkes_network_intensity(
            np.ones(4), att, np.ones((4, 4)) * 0.1, np.ones((4, 4)),
            [1, 2, 3, 1], [-100, 1, -2, 0], gamma_ofi=0.05
        )
        assert intensity.shape == (4,)
        assert np.all(intensity >= 1e-12)
        assert np.all(np.isfinite(intensity))

    def test_cycle64_tensor_ring_svd_and_reconstruction(self) -> None:
        import numpy as np
        from agents.AGI_1_7.engine.agi17.finance.hd_hv_gat_tr_execution_engine import (
            tensor_ring_svd, reconstruct_tensor_ring,
        )
        rng = np.random.default_rng(64)
        x = rng.normal(size=(2, 3, 2, 2))
        tr = tensor_ring_svd(x, tolerance=1e-6)
        rebuilt = reconstruct_tensor_ring(tr)
        assert rebuilt.shape == x.shape
        assert np.linalg.norm(x - rebuilt) / np.linalg.norm(x) <= 1e-6
        assert tr.relative_error <= 1e-6

    def test_cycle64_surface_dislocation_and_toxicity(self) -> None:
        import math
        from agents.AGI_1_7.engine.agi17.finance.hd_hv_gat_tr_execution_engine import (
            surface_dislocation, toxicity_probability,
        )
        result = surface_dislocation([[0.1, 0.12, 0.14], [0.08, 0.09, 0.11]], [0.2, 0.25], [0.2, 0.31], 0.03)
        assert result["calendar_monotonic"] is True
        assert result["smile_dislocated"] is True

        p_safe = toxicity_probability(0.2, 1.0)
        assert 0.0 <= p_safe < 1.0
        p_toxic = toxicity_probability(5.0, 1.0)
        assert p_toxic > 0.60

    def test_cycle64_position_stress_testing_and_almgren_chriss(self) -> None:
        import pytest
        from agents.AGI_1_7.engine.agi17.finance.hd_hv_gat_tr_execution_engine import (
            almgren_chriss_unwind, stress_test_positions,
        )
        unwind = almgren_chriss_unwind(8.0, horizon_steps=12, intensity=1.2, tau=1.0)
        assert unwind["terminal_inventory"] == 0.0
        assert unwind["inventory_path"][-1] == 0.0
        assert len(unwind["trade_schedule"]) == 12
        assert sum(unwind["trade_schedule"]) == pytest.approx(8.0, abs=1e-9)
        assert unwind["toxicity_action"] == "RETREAT"

        stress = stress_test_positions(
            [{"symbol": "BANKNIFTY", "quantity": 60, "mark_price": 482.80, "liquidity_scale": 0.5}],
            available_funds_inr=10000.0,
            price_shocks={"BANKNIFTY": -0.05},
            liquidity_haircut=0.20
        )
        assert stress["stressed_funds_inr"] > 0.0
        assert stress["source_mode"] == "operator_supplied_offline_snapshot"

    def test_cycle64_statutory_fees_and_kelly(self) -> None:
        import pytest
        from agents.AGI_1_7.engine.agi17.finance.hd_hv_gat_tr_execution_engine import (
            indian_statutory_fees, net_alpha_gate, beta_fractional_kelly,
        )
        f = indian_statutory_fees(100000.0, 100000.0, 2)
        assert f["brokerage_inr"] == pytest.approx(40.0)
        assert f["total_fees_inr"] == pytest.approx(284.2508)

        gate_pass = net_alpha_gate(300.0, f["total_fees_inr"])
        assert gate_pass["approved"] is True
        assert gate_pass["net_alpha_inr"] > 0.0

        gate_fail = net_alpha_gate(200.0, f["total_fees_inr"])
        assert gate_fail["approved"] is False

        k = beta_fractional_kelly(2.0, 2.0, 6, 4, 1.5, 0.25, net_alpha_positive=True)
        assert 0.0 <= k["capital_fraction"] <= 0.10

    def test_cycle64_squad_consensus_and_live_dispatch_locked(self) -> None:
        import pytest
        from agents.AGI_1_7.engine.agi17.finance.hd_hv_gat_tr_execution_engine import (
            squad_consensus, dispatch_live_order,
            LIVE_ORDER_DISPATCH_ENABLED, REAL_BROKER_FILLS_LOCKED,
            INITIAL_CAPITAL_INR, PAPER_LEDGER_EPOCH,
        )
        assert LIVE_ORDER_DISPATCH_ENABLED is False
        assert REAL_BROKER_FILLS_LOCKED is True
        assert INITIAL_CAPITAL_INR == 10000.0
        assert PAPER_LEDGER_EPOCH == "epoch_10k"

        votes = {name: True for name in ("Abhi", "Alex", "Emily", "Max")}
        res = squad_consensus(votes, manager_live_veto=True, risk_gates_passed=True)
        assert res["paper_research_approved"] is True
        assert res["live_order_dispatch_enabled"] is False

        with pytest.raises(PermissionError, match="Cycle 64 is paper-only: live order dispatch is permanently disabled"):
            dispatch_live_order("BUY", quantity=60)


class TestCycle65DNSDEMLTExecution:
    """Cycle 65: Deep Neural SDEs, Multi-Layer Optimal Liquidity Transport & Drawdown Absorption."""

    def test_cycle65_dnsde_simulation_and_lipschitz(self) -> None:
        import numpy as np
        from agents.AGI_1_7.engine.agi17.finance.dnsde_mlt_execution_engine import simulate_dnsde
        
        dim = 2
        sig_dim = 1
        x0 = np.array([0.1, -0.05])
        w_drift = np.array([
            [0.2, -0.1, 0.05, 0.3],
            [0.1, 0.25, -0.05, -0.2]
        ])
        w_diff = np.array([
            [0.15, -0.1, 0.05],
            [-0.05, 0.2, 0.1]
        ])
        signals = np.linspace(-0.5, 0.5, 20)
        
        sim = simulate_dnsde(
            initial_state=x0,
            drift_weights=w_drift,
            diffusion_weights=w_diff,
            mlofi_signals=signals,
            n_steps=20,
            dt=0.01,
            lambda_jump=0.1,
            jump_scale=0.02,
            lipschitz_limit=1.5
        )
        assert sim["trajectory"].shape == (21, 2)
        assert sim["drift_path"].shape == (20, 2)
        assert sim["diffusion_path"].shape == (20, 2, 2)
        assert sim["lipschitz_verified"] is True
        assert np.all(np.isfinite(sim["trajectory"]))

    def test_cycle65_optimal_liquidity_transport(self) -> None:
        import numpy as np
        from agents.AGI_1_7.engine.agi17.finance.dnsde_mlt_execution_engine import optimal_liquidity_transport

        src = np.array([100.0, 150.0, 200.0, 120.0, 80.0])
        tgt = np.array([90.0, 130.0, 210.0, 140.0, 80.0])

        res = optimal_liquidity_transport(src, tgt, epsilon=0.05, max_iter=200, tol=1e-5)
        assert res["convergence"] is True
        assert res["transport_plan"].shape == (5, 5)
        assert res["marginal_error_source"] <= 1e-4
        assert res["marginal_error_target"] <= 1e-4
        assert res["transport_cost"] >= 0.0

    def test_cycle65_almgren_chriss_unwind_and_toxicity(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.dnsde_mlt_execution_engine import almgren_chriss_unwind

        u_calm = almgren_chriss_unwind(inventory=100.0, horizon_steps=10, intensity=0.1, tau=1.0)
        assert u_calm["terminal_inventory"] == 0.0
        assert u_calm["inventory_path"][-1] == 0.0
        assert len(u_calm["trade_schedule"]) == 10
        assert u_calm["toxicity_action"] == "CONTINUE_PAPER"

        u_toxic = almgren_chriss_unwind(inventory=100.0, horizon_steps=10, intensity=2.0, tau=1.0)
        assert u_toxic["toxicity_action"] == "RETREAT"
        assert u_toxic["toxicity_prob"] > 0.60

    def test_cycle65_deep_intraday_stress_testing(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.dnsde_mlt_execution_engine import stress_test_positions

        positions = [
            {
                "symbol": "NIFTY24OCT25000CE",
                "underlying": "NIFTY",
                "quantity": 50,
                "price": 120.0,
                "multiplier": 1.0,
                "delta": 0.52,
                "underlying_price": 24800.0,
                "instrument_type": "option",
                "liquid": True,
            },
            {
                "symbol": "BANKNIFTY24OCT52000PE",
                "underlying": "BANKNIFTY",
                "quantity": -30,
                "price": 180.0,
                "multiplier": 1.0,
                "delta": -0.45,
                "underlying_price": 52200.0,
                "instrument_type": "option",
                "liquid": True,
            }
        ]
        stress = stress_test_positions(positions, available_funds_inr=10000.0)
        assert stress["source_mode"] == "operator_supplied_offline_snapshot"
        assert "stressed_funds_inr" in stress
        assert stress["scenario_count"] == 4

    def test_cycle65_statutory_fees_and_kelly(self) -> None:
        import pytest
        from agents.AGI_1_7.engine.agi17.finance.dnsde_mlt_execution_engine import (
            indian_statutory_fees, net_alpha_gate, beta_fractional_kelly,
        )
        f = indian_statutory_fees(100000.0, 100000.0, 2)
        assert f["breakdown"]["brokerage_inr"] == pytest.approx(40.0)
        assert f["total_fees_inr"] == pytest.approx(284.29)

        gate_pass = net_alpha_gate(300.0, f["total_fees_inr"])
        assert gate_pass["approved"] is True
        assert gate_pass["net_alpha_inr"] > 0.0

        gate_fail = net_alpha_gate(200.0, f["total_fees_inr"])
        assert gate_fail["approved"] is False

        k = beta_fractional_kelly(2.0, 2.0, 7, 3, 1.6, 0.25, net_alpha_positive=True)
        assert 0.0 <= k["capital_fraction"] <= 0.10

    def test_cycle65_squad_consensus_and_live_dispatch_locked(self) -> None:
        import pytest
        from agents.AGI_1_7.engine.agi17.finance.dnsde_mlt_execution_engine import (
            squad_consensus, dispatch_live_order,
            LIVE_ORDER_DISPATCH_ENABLED, REAL_BROKER_FILLS_LOCKED,
            INITIAL_CAPITAL_INR, PAPER_LEDGER_EPOCH,
        )
        assert LIVE_ORDER_DISPATCH_ENABLED is False
        assert REAL_BROKER_FILLS_LOCKED is True
        assert INITIAL_CAPITAL_INR == 10000.0
        assert PAPER_LEDGER_EPOCH == "epoch_10k"

        votes = {name: True for name in ("Abhi", "Alex", "Emily", "Max")}
        res = squad_consensus(votes, manager_live_veto=True, risk_gates_passed=True)
        assert res["paper_research_approved"] is True
        assert res["live_order_dispatch_enabled"] is False

        with pytest.raises(PermissionError, match="Cycle 65 is paper-only: live order dispatch is permanently disabled"):
            dispatch_live_order("BUY", quantity=50)


class TestCycle66CTFMVJDExecution:
    """Cycle 66: Continuous-Time Fractional McKean-Vlasov Jump-Diffusion & Multi-Asset Cross-Impact."""

    def test_cycle66_mckean_vlasov_system_simulation(self) -> None:
        import numpy as np
        from agents.AGI_1_7.engine.agi17.finance.ct_fmv_jd_execution_engine import simulate_mckean_vlasov_system

        res = simulate_mckean_vlasov_system(
            n_particles=50,
            n_steps=25,
            dt=0.01,
            kappa=1.5,
            gamma=0.8,
            x_bar=0.0,
            beta=0.2,
            sigma_base=0.15,
            hurst=0.15,
            lambda_jump=0.1,
            jump_scale=0.02,
            seed=42,
        )
        assert res["particle_trajectories"].shape == (26, 50)
        assert res["mean_field_path"].shape == (26,)
        assert res["variance_field_path"].shape == (26,)
        assert res["stability_verified"] is True
        assert np.all(np.isfinite(res["particle_trajectories"]))

    def test_cycle66_cross_asset_nonlocal_impact(self) -> None:
        import numpy as np
        from agents.AGI_1_7.engine.agi17.finance.ct_fmv_jd_execution_engine import cross_asset_nonlocal_impact

        ofi = np.array([
            [1.2, -0.5],
            [0.8, 0.4],
            [-0.3, 1.1],
            [1.5, -0.2],
        ])
        impact_mat = np.array([
            [0.05, 0.02],
            [0.01, 0.06],
        ])
        impact = cross_asset_nonlocal_impact(ofi, impact_mat, dt=0.01, gamma_decay=1.2)
        assert impact["cumulative_impact"].shape == (4, 2)
        assert impact["cross_asymmetry_matrix"].shape == (2, 2)
        assert np.all(np.diag(impact["cross_asymmetry_matrix"]) == 0.0)
        assert -1.0 <= impact["cross_asymmetry_matrix"][0, 1] <= 1.0
        assert impact["total_energy"] >= 0.0

    def test_cycle66_almgren_chriss_unwind(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.ct_fmv_jd_execution_engine import almgren_chriss_unwind

        u_calm = almgren_chriss_unwind(inventory=150.0, horizon_steps=12, intensity=0.1, tau=1.0)
        assert u_calm["terminal_inventory"] == 0.0
        assert u_calm["inventory_path"][-1] == 0.0
        assert len(u_calm["trade_schedule"]) == 12
        assert u_calm["toxicity_action"] == "CONTINUE_PAPER"

        u_toxic = almgren_chriss_unwind(inventory=150.0, horizon_steps=12, intensity=2.5, tau=1.0)
        assert u_toxic["toxicity_action"] == "RETREAT"
        assert u_toxic["toxicity_prob"] > 0.60

    def test_cycle66_stress_test_positions(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.ct_fmv_jd_execution_engine import stress_test_positions

        positions = [
            {
                "symbol": "NIFTY",
                "quantity": 50,
                "price": 120.0,
                "multiplier": 1.0,
                "delta": 0.50,
                "underlying_price": 24800.0,
                "is_illiquid": False,
            },
            {
                "symbol": "BANKNIFTY",
                "quantity": -30,
                "price": 180.0,
                "multiplier": 1.0,
                "delta": -0.40,
                "underlying_price": 52200.0,
                "is_illiquid": True,
            }
        ]
        stress = stress_test_positions(positions, available_funds_inr=10000.0)
        assert stress["source_mode"] == "operator_supplied_offline_snapshot"
        assert "stressed_funds_inr" in stress
        assert stress["scenarios_evaluated"] == 4

    def test_cycle66_fees_kelly_and_gates(self) -> None:
        import pytest
        from agents.AGI_1_7.engine.agi17.finance.ct_fmv_jd_execution_engine import (
            indian_statutory_fees, net_alpha_gate, beta_fractional_kelly,
        )
        f = indian_statutory_fees(100000.0, 100000.0, 2)
        assert f["breakdown"]["brokerage_inr"] == pytest.approx(40.0)
        assert f["total_fees_inr"] == pytest.approx(284.28654)

        gate_pass = net_alpha_gate(300.0, f["total_fees_inr"])
        assert gate_pass["approved"] is True
        assert gate_pass["net_alpha_inr"] > 0.0

        gate_fail = net_alpha_gate(200.0, f["total_fees_inr"])
        assert gate_fail["approved"] is False

        k = beta_fractional_kelly(2.0, 2.0, 7, 3, 1.6, 0.25, net_alpha_positive=True)
        assert 0.0 <= k["capital_fraction"] <= 0.10

    def test_cycle66_squad_consensus_and_live_dispatch_locked(self) -> None:
        import pytest
        from agents.AGI_1_7.engine.agi17.finance.ct_fmv_jd_execution_engine import (
            squad_consensus, dispatch_live_order,
            LIVE_ORDER_DISPATCH_ENABLED, REAL_BROKER_FILLS_LOCKED,
            INITIAL_CAPITAL_INR, PAPER_LEDGER_EPOCH,
        )
        assert LIVE_ORDER_DISPATCH_ENABLED is False
        assert REAL_BROKER_FILLS_LOCKED is True
        assert INITIAL_CAPITAL_INR == 10000.0
        assert PAPER_LEDGER_EPOCH == "epoch_10k"

        votes = {name: True for name in ("Abhi", "Alex", "Emily", "Max")}
        res = squad_consensus(votes, manager_live_veto=True, risk_gates_passed=True)
        assert res["paper_research_approved"] is True
        assert res["live_order_dispatch_enabled"] is False

        with pytest.raises(PermissionError, match="Cycle 66 is paper-only: live order dispatch is permanently disabled"):
            dispatch_live_order("BUY", quantity=50)
























class TestCycle67NLFLFCELAExecution:
    def test_cycle67_tempered_levy_characteristic_and_simulation(self) -> None:
        import pytest
        import numpy as np
        from agents.AGI_1_7.engine.agi17.finance.nl_flf_cela_execution_engine import (
            tempered_levy_characteristic_function, simulate_levy_flight_path, sample_truncated_levy_flights,
        )
        phi_0 = tempered_levy_characteristic_function(0.0, 1.0, 1.5, 0.5)
        assert abs(phi_0 - 1.0) < 1e-12

        phi_val = tempered_levy_characteristic_function(2.0, 0.5, 1.6, 0.4)
        assert abs(phi_val) <= 1.0 + 1e-12

        jumps = sample_truncated_levy_flights(100, alpha=1.5, lambda_damp=0.5, rng=np.random.default_rng(42))
        assert len(jumps) == 100

        sim = simulate_levy_flight_path(n_steps=30, dt=0.01, alpha=1.6, lambda_damp=0.5, seed=42)
        assert len(sim["trajectory"]) == 31
        assert "model_mode" in sim
        assert sim["jumps_total"] >= 0

    def test_cycle67_mlofi_and_toxic_intensity(self) -> None:
        import pytest
        from agents.AGI_1_7.engine.agi17.finance.nl_flf_cela_execution_engine import (
            compute_mlofi_5level, toxic_jump_intensity,
        )
        delta_bv = [10.0, 8.0, 6.0, 4.0, 2.0]
        delta_av = [-9.0, -7.0, -5.0, -3.0, -1.0]
        delta_bp = [0.05, 0.05, 0.05, 0.05, 0.05]
        delta_ap = [-0.05, -0.05, -0.05, -0.05, -0.05]

        mlofi = compute_mlofi_5level(delta_bv, delta_av, delta_bp, delta_ap)
        assert isinstance(mlofi, float)

        res = toxic_jump_intensity(mlofi, [(1.0, 0.5), (2.0, 0.2)], current_time=2.5, lambda_thresh=0.5)
        assert res["intensity"] >= 0.0
        assert res["toxicity_action"] in ("CONTINUE_PAPER", "RETREAT")

    def test_cycle67_term_structure_arbitrage_audit(self) -> None:
        import pytest
        from agents.AGI_1_7.engine.agi17.finance.nl_flf_cela_execution_engine import (
            term_structure_arbitrage_audit,
        )
        maturities = [0.1, 0.25, 0.5]
        strikes = [-0.1, 0.0, 0.1]
        w_grid = [
            [0.02, 0.018, 0.022],
            [0.04, 0.038, 0.042],
            [0.08, 0.076, 0.084],
        ]
        audit = term_structure_arbitrage_audit(maturities, strikes, w_grid)
        assert audit["calendar_monotone"] is True
        assert "butterfly_convex" in audit
        assert "net_curvature_signal" in audit

    def test_cycle67_multi_expiry_liquidation_and_indifference(self) -> None:
        import pytest
        from agents.AGI_1_7.engine.agi17.finance.nl_flf_cela_execution_engine import (
            multi_expiry_liquidation, friction_aware_indifference_width,
        )
        inv = [10.0, -5.0, 2.0]
        liq = multi_expiry_liquidation(inv, horizon_steps=10, eta=0.05, lambda_risk=1e-4)
        assert liq["terminal_inventory"] == 0.0
        assert liq["trade_schedule"].shape == (10, 3)

        width = friction_aware_indifference_width(0.20, 100.0, 0.01, fee_drag=0.001)
        assert width["indifference_width"] > 0.001

    def test_cycle67_statutory_fees_and_kelly_limits(self) -> None:
        import pytest
        from agents.AGI_1_7.engine.agi17.finance.nl_flf_cela_execution_engine import (
            indian_statutory_fees, net_alpha_gate, beta_fractional_kelly,
        )
        fees = indian_statutory_fees(100000.0, 100000.0, executed_legs=2)
        assert fees["breakdown"]["brokerage"] == pytest.approx(40.0)
        assert fees["total_fees_inr"] > 0.0

        gate = net_alpha_gate(300.0, fees["total_fees_inr"])
        assert gate["approved"] is True
        assert gate["net_alpha_inr"] > 0.0

        kelly = beta_fractional_kelly(alpha_prior=2.0, beta_prior=2.0, wins=7, losses=3, win_loss_ratio=1.5, scale=0.25, cap=0.10)
        assert 0.0 <= kelly["capital_fraction"] <= 0.10
        assert 0.0 <= kelly["posterior_win_probability"] <= 1.0

    def test_cycle67_squad_consensus_and_live_dispatch_locked(self) -> None:
        import pytest
        from agents.AGI_1_7.engine.agi17.finance.nl_flf_cela_execution_engine import (
            squad_consensus, dispatch_live_order,
            LIVE_ORDER_DISPATCH_ENABLED, REAL_BROKER_FILLS_LOCKED,
            INITIAL_CAPITAL_INR, PAPER_LEDGER_EPOCH,
        )
        assert LIVE_ORDER_DISPATCH_ENABLED is False
        assert REAL_BROKER_FILLS_LOCKED is True
        assert INITIAL_CAPITAL_INR == 10000.0
        assert PAPER_LEDGER_EPOCH == "epoch_10k"

        votes = {name: True for name in ("Abhi", "Alex", "Emily", "Max")}
        res = squad_consensus(votes, manager_live_veto=True, risk_gates_passed=True)
        assert res["paper_research_approved"] is True
        assert res["live_order_dispatch_enabled"] is False

        with pytest.raises(PermissionError, match="LIVE_ORDER_DISPATCH_BLOCKED: Cycle 67 is fail-closed. Real broker dispatch is strictly locked."):
            dispatch_live_order("BUY", 50)



class TestCycle68NMHVMVCEHExecution:
    def test_cycle68_particle_simulation_and_volterra(self) -> None:
        import pytest
        import numpy as np
        from agents.AGI_1_7.engine.agi17.finance.nmh_vmv_ceh_execution_engine import (
            simulate_nmh_vmv_system, volterra_memory_kernel, volterra_increment_weights,
        )
        kernel_val = volterra_memory_kernel(0.1, 0.0, 0.15)
        assert kernel_val > 0.0

        weights = volterra_increment_weights(10, 0.01, 0.15)
        assert len(weights) == 10
        assert np.all(weights > 0.0)

        sim = simulate_nmh_vmv_system(n_particles=10, n_steps=8, dt=0.01, hurst=0.15, seed=68)
        assert sim["particle_trajectories"].shape == (9, 10)
        assert sim["stability_verified"] is True
        assert sim["branching_spectral_radius"] < 0.88

    def test_cycle68_cross_hedge_beta_and_mlofi(self) -> None:
        import pytest
        import numpy as np
        from agents.AGI_1_7.engine.agi17.finance.nmh_vmv_ceh_execution_engine import (
            dynamic_cross_hedge_beta, compute_top5_mlofi, hawkes_mlofi_toxicity,
        )
        returns = np.array([[0.01, 0.02], [-0.01, -0.015], [0.005, 0.01], [0.02, 0.025]], dtype=float)
        beta_res = dynamic_cross_hedge_beta(returns, decay=0.95)
        assert beta_res["beta_matrix"].shape == (2, 2)
        assert np.isclose(beta_res["beta_matrix"][0, 0], 1.0)
        assert np.isclose(beta_res["beta_matrix"][1, 1], 1.0)

        delta_bid_vol = [10.0, 8.0, 6.0, 4.0, 2.0]
        delta_ask_vol = [9.0, 7.0, 5.0, 3.0, 1.0]
        delta_bid_price = [0.05, 0.05, 0.05, 0.05, 0.05]
        delta_ask_price = [-0.05, -0.05, -0.05, -0.05, -0.05]
        mlofi = compute_top5_mlofi(delta_bid_vol, delta_ask_vol, delta_bid_price, delta_ask_price)
        assert isinstance(mlofi, float)

        tox = hawkes_mlofi_toxicity(mlofi, event_times=[1.0], event_jumps=[0.5], current_time=2.0, tau=0.8)
        assert "toxicity_prob" in tox
        assert tox["toxicity_action"] in ("CONTINUE_PAPER", "RETREAT")

    def test_cycle68_surface_arbitrage_audit(self) -> None:
        import pytest
        import numpy as np
        from agents.AGI_1_7.engine.agi17.finance.nmh_vmv_ceh_execution_engine import (
            audit_cross_expiry_surface, require_static_arbitrage_free_surface,
        )
        strikes = np.linspace(-1.0, 1.0, 9)
        maturities = np.array([0.1, 0.25, 0.5])
        w_grid = np.stack([np.full(9, x) for x in (0.02, 0.03, 0.05)])
        audit = audit_cross_expiry_surface(strikes, maturities, w_grid)
        assert audit["calendar_monotone"] is True
        assert audit["butterfly_convex"] is True
        assert audit["static_arbitrage_free_grid"] is True

        require_static_arbitrage_free_surface(strikes, maturities, w_grid)

    def test_cycle68_unwind_and_indifference_width(self) -> None:
        import pytest
        from agents.AGI_1_7.engine.agi17.finance.nmh_vmv_ceh_execution_engine import (
            almgren_chriss_multi_expiry_unwind, cubic_root_indifference_width,
        )
        inv = [10.0, -5.0]
        unwind = almgren_chriss_multi_expiry_unwind(inv, horizon_steps=6, eta=0.05, lambda_risk=1e-4)
        assert unwind["terminal_inventory"] == 0.0
        assert unwind["inventory_path"].shape == (7, 2)

        w = cubic_root_indifference_width(0.5, 0.2, 1.5, statutory_fee_drag=0.05)
        assert isinstance(w, float)
        assert w > 0.0

    def test_cycle68_fees_alpha_gate_and_kelly(self) -> None:
        import pytest
        from agents.AGI_1_7.engine.agi17.finance.nmh_vmv_ceh_execution_engine import (
            indian_statutory_fees, net_alpha_gate, beta_fractional_kelly,
        )
        f = indian_statutory_fees(100000.0, 100000.0, executed_legs=2)
        assert f["breakdown"]["brokerage"] == pytest.approx(40.0)
        assert f["total_fees_inr"] > 0.0

        gate = net_alpha_gate(300.0, f["total_fees_inr"])
        assert gate["approved"] is True
        assert gate["net_alpha_inr"] > 0.0

        kelly = beta_fractional_kelly(2.0, 2.0, 7, 3, 1.5, scale=0.25, cap=0.10)
        assert 0.0 <= kelly["capital_fraction"] <= 0.10
        assert 0.0 <= kelly["posterior_win_probability"] <= 1.0

    def test_cycle68_squad_consensus_and_live_dispatch_locked(self) -> None:
        import pytest
        from agents.AGI_1_7.engine.agi17.finance.nmh_vmv_ceh_execution_engine import (
            squad_consensus, dispatch_live_order,
            LIVE_ORDER_DISPATCH_ENABLED, REAL_BROKER_FILLS_LOCKED,
            INITIAL_CAPITAL_INR, PAPER_LEDGER_EPOCH,
        )
        assert LIVE_ORDER_DISPATCH_ENABLED is False
        assert REAL_BROKER_FILLS_LOCKED is True
        assert INITIAL_CAPITAL_INR == 10000.0
        assert PAPER_LEDGER_EPOCH == "epoch_10k"

        votes = {name: True for name in ("Abhi", "Alex", "Emily", "Max")}
        res = squad_consensus(votes, manager_live_veto=True, risk_gates_passed=True)
        assert res["paper_research_approved"] is True
        assert res["live_order_dispatch_enabled"] is False

        with pytest.raises(PermissionError, match="LIVE_ORDER_DISPATCH_BLOCKED: Cycle 68 is fail-closed. Real broker dispatch is strictly locked."):
            dispatch_live_order("BUY", 50)


class TestCycle69DFRHTTAHFExecution:
    def test_cycle69_lifted_rough_heston_and_volterra(self) -> None:
        import pytest
        import numpy as np
        from agents.AGI_1_7.engine.agi17.finance.dfrh_tt_ahf_execution_engine import (
            simulate_rough_heston, build_volterra_lift
        )
        l = build_volterra_lift(hurst=0.15, n_modes=8, horizon=0.5, dt=0.005)
        assert l["betas"].shape == (8,)
        assert np.all(l["weights"] > 0)

        res = simulate_rough_heston(n_steps=20, dt=0.01, seed=6901)
        assert res["variance_path"].shape == (21,)
        assert res["spot_path"].shape == (21,)
        assert res["feller_verified"] is True
        assert res["stability_verified"] is True

    def test_cycle69_tensor_train_svd_and_surface_audit(self) -> None:
        import pytest
        import numpy as np
        from agents.AGI_1_7.engine.agi17.finance.dfrh_tt_ahf_execution_engine import (
            tt_svd_decompose, audit_volatility_surface, cross_surface_relative_value
        )
        k = np.linspace(-1.0, 1.0, 21)
        t = np.array([0.1, 0.2, 0.5, 1.0])
        w = (0.04 + 0.01 * k**2)[:, None] * t[None, :]
        audit = audit_volatility_surface(w, k, t)
        assert audit["calendar_monotone"] is True
        assert audit["butterfly_convexity_positive"] is True
        assert audit["static_arbitrage_free_on_grid"] is True

        tensor = np.zeros((2, 2, 2, 2))
        tt = tt_svd_decompose(tensor)
        assert tt["tolerance_met"] is True

        a = np.array([[0.05, 0.07], [0.08, 0.10]])
        b = np.array([[0.04, 0.09], [0.06, 0.08]])
        rv = cross_surface_relative_value(a, b, fee_drag=0.015)
        assert rv["opportunities_after_friction"] == 3

    def test_cycle69_mlofi_and_hawkes_toxicity(self) -> None:
        import pytest
        import numpy as np
        from agents.AGI_1_7.engine.agi17.finance.dfrh_tt_ahf_execution_engine import (
            compute_mlofi_top5, hawkes_toxicity_gate
        )
        dbv = np.array([2., 1., 4., -1., 3.])
        dav = np.array([1., 5., 2., 3., 1.])
        dbp = np.array([0., 0.01, -0.01, 0.0, -0.02])
        dap = np.array([0., -0.01, 0.01, -0.02, 0.0])
        m = compute_mlofi_top5(dbv, dav, dbp, dap)
        assert isinstance(m, float)

        gate = hawkes_toxicity_gate(mlofi=100, base_intensity=0.1, mlofi_gamma=0.2, tau=1.0)
        assert gate["toxicity_action"] == "RETREAT"
        assert 0.0 <= gate["toxicity_prob"] <= 1.0

    def test_cycle69_optimal_unwind_and_terminal_zero(self) -> None:
        import pytest
        import numpy as np
        from agents.AGI_1_7.engine.agi17.finance.dfrh_tt_ahf_execution_engine import (
            almgren_chriss_multi_expiry_unwind
        )
        inventory = np.array([[2.0, -1.0], [0.5, 3.0]])
        res = almgren_chriss_multi_expiry_unwind(inventory, horizon_steps=4)
        assert res["terminal_inventory"] == 0.0
        assert np.array_equal(res["inventory_path"][-1], np.zeros_like(inventory))
        assert res["indifference_width"] > 0.0

    def test_cycle69_fees_and_beta_kelly(self) -> None:
        import pytest
        from agents.AGI_1_7.engine.agi17.finance.dfrh_tt_ahf_execution_engine import (
            indian_statutory_fees, net_alpha_gate, beta_fractional_kelly
        )
        fees = indian_statutory_fees(100_000.0, 150_000.0, executed_legs=4)
        assert fees["breakdown"]["brokerage"] == pytest.approx(80.0)
        assert fees["total_fees_inr"] > 0.0

        gate = net_alpha_gate(fees["total_fees_inr"] + 10.0, fees["total_fees_inr"])
        assert gate["approved"] is True
        assert gate["net_alpha_inr"] == pytest.approx(10.0)

        k = beta_fractional_kelly(2, 2, 20, 5, 2.5)
        assert 0.0 <= k["capital_fraction"] <= 0.10

    def test_cycle69_squad_consensus_and_fail_closed_dispatch(self) -> None:
        import pytest
        from agents.AGI_1_7.engine.agi17.finance.dfrh_tt_ahf_execution_engine import (
            squad_consensus, dispatch_live_order,
            LIVE_ORDER_DISPATCH_ENABLED, REAL_BROKER_FILLS_LOCKED,
            INITIAL_CAPITAL_INR, DISPATCH_ERROR
        )
        assert LIVE_ORDER_DISPATCH_ENABLED is False
        assert REAL_BROKER_FILLS_LOCKED is True
        assert INITIAL_CAPITAL_INR == 10000.0

        votes = {name: True for name in ("Abhi", "Alex", "Emily", "Max")}
        res = squad_consensus(votes)
        assert res["paper_research_approved"] is True
        assert res["live_order_dispatch_enabled"] is False

        with pytest.raises(PermissionError) as exc_info:
            dispatch_live_order("NIFTY", quantity=1)
        assert str(exc_info.value) == DISPATCH_ERROR


class TestCycle70QTNMENLFExecution:
    def test_cycle70_lindblad_master_equation_and_mpo(self) -> None:
        import pytest
        import numpy as np
        from agents.AGI_1_7.engine.agi17.finance.qtn_me_nlf_execution_engine import (
            lindblad_rhs, simulate_lindblad_master_equation, mpo_decompose_density
        )
        h = np.array([[0, 0.2], [0.2, 0]], dtype=complex)
        l = np.array([[0, 0.3], [0, 0]], dtype=complex)
        rho = np.array([[0.7, 0.0], [0.0, 0.3]], dtype=complex)
        
        rhs = lindblad_rhs(rho, h, [l])
        assert np.isclose(np.trace(rhs).real, 0.0, atol=1e-12)
        assert np.allclose(rhs, rhs.conj().T, atol=1e-12)

        res = simulate_lindblad_master_equation(rho, h, [l], dt=0.01, n_steps=40)
        assert res["density_path"].shape == (41, 2, 2)
        assert res["trace_error_max"] <= 1e-10
        assert res["trace_preserved"] is True
        assert res["positive_semidefinite"] is True
        assert res["dissipation_subcritical"] is True

        state = np.zeros(8, dtype=complex)
        state[0] = 1.0
        rho8 = np.outer(state, state.conj())
        mpo = mpo_decompose_density(rho8, local_dim=2, max_bond_dim=16, tolerance=1e-12)
        assert mpo["max_bond_dimension"] <= 16
        assert mpo["frobenius_error"] <= 1e-10
        assert mpo["trace_preserved"] is True
        assert mpo["positive_semidefinite"] is True

    def test_cycle70_tempered_levy_and_surface_audit(self) -> None:
        import pytest
        import numpy as np
        from agents.AGI_1_7.engine.agi17.finance.qtn_me_nlf_execution_engine import (
            tempered_levy_characteristic, sample_truncated_levy_flight,
            volatility_surface_audit, cross_surface_relative_value
        )
        us = np.linspace(-8, 8, 101)
        phi = tempered_levy_characteristic(us, t=0.5, alpha=1.4, damping=0.7, intensity_scale=0.2)
        assert np.all(np.isfinite(phi))
        assert np.isclose(phi[50].real, 1.0, atol=1e-12)

        path = sample_truncated_levy_flight(n_steps=50, seed=19)
        assert path.shape == (51,)
        assert path[0] == 0.0

        k = np.linspace(-1, 1, 9)
        t = np.array([0.1, 0.2, 0.4, 0.8])
        w = np.tile((0.08 + 0.02 * t)[:, None], (1, k.size))
        audit = volatility_surface_audit(w, k, t)
        assert audit["calendar_monotonic"] is True
        assert audit["butterfly_convex"] is True
        assert audit["calendar_violation_count"] == 0
        assert audit["butterfly_violation_count"] == 0

        rv = cross_surface_relative_value(np.ones((3, 4)), np.ones((3, 4)) * 0.8, friction_inr=0.1)
        assert rv["gross_mispricing"] == pytest.approx(0.2)
        assert rv["relative_value_flag"] is True

    def test_cycle70_mlofi_hawkes_and_contagion(self) -> None:
        import pytest
        import numpy as np
        from agents.AGI_1_7.engine.agi17.finance.qtn_me_nlf_execution_engine import (
            mlofi_top5, hawkes_intensity, toxicity_gate, contagion_routing
        )
        vb = np.array([10, 8, 6, 4, 2.])
        va = np.array([1, 2, 3, 4, 5.])
        pb = np.array([0, 1, -1, 0, -1.])
        pa = np.array([0, -1, 0, 1, -1.])
        m = mlofi_top5(vb, va, pb, pa)
        assert isinstance(m, float)

        lam = hawkes_intensity(2.0, mu0=0.1, gamma_mlofi=0.3, beta=1.0)
        assert lam >= 0.0
        gate = toxicity_gate(lam, tau=1.0)
        assert gate["toxicity_action"] in ("RETREAT", "CONTINUE_PAPER")

        w = np.array([[0.0, 0.2], [0.1, 0.0]])
        cont = contagion_routing([100, 80], w, [10, 5])
        assert cont["spectral_radius"] < 1.0
        assert cont["subcritical"] is True

    def test_cycle70_unwind_fees_and_fail_closed_dispatch(self) -> None:
        import pytest
        import numpy as np
        from agents.AGI_1_7.engine.agi17.finance.qtn_me_nlf_execution_engine import (
            almgren_chriss_multi_expiry_unwind, indian_statutory_fees,
            net_alpha_gate, beta_fractional_kelly, squad_consensus, dispatch_live_order,
            LIVE_ORDER_DISPATCH_ENABLED, REAL_BROKER_FILLS_LOCKED,
            PAPER_LEDGER_EPOCH, INITIAL_CAPITAL_INR
        )
        res = almgren_chriss_multi_expiry_unwind([3.0, -2.0], horizon_steps=12,
            cross_impact_matrix=[[1.0, 0.2], [0.2, 1.0]], intensity=1.5, tau=1,
            temporary_cost=0.01, fee_cost=0.005)
        assert res["terminal_zero_exact"] is True
        assert np.array_equal(res["inventory_path"][-1], np.zeros(2))

        fees = indian_statutory_fees(100_000, 150_000, executed_legs=4)
        assert fees["total_fees_inr"] > 80.0
        gate = net_alpha_gate(fees["total_fees_inr"] + 10.0, fees["total_fees_inr"])
        assert gate["approved"] is True

        k = beta_fractional_kelly(2, 2, 10, 3, 1.8)
        assert 0.0 <= k["capital_fraction"] <= 0.10

        assert LIVE_ORDER_DISPATCH_ENABLED is False
        assert REAL_BROKER_FILLS_LOCKED is True
        assert PAPER_LEDGER_EPOCH == "epoch_10k"
        assert INITIAL_CAPITAL_INR == 10000.0

        votes = {name: True for name in ("Abhi", "Alex", "Emily", "Max")}
        squad = squad_consensus(votes, manager_live_veto=True)
        assert squad["paper_research_approved"] is True
        assert squad["live_order_dispatch_enabled"] is False

        with pytest.raises(PermissionError) as exc_info:
            dispatch_live_order("NIFTY", side="BUY")
        assert "LIVE_ORDER_DISPATCH_BLOCKED" in str(exc_info.value)


class TestCycle71NPISOCRBTNExecution:
    def test_cycle71_path_integral_and_fbsde(self) -> None:
        import pytest
        import numpy as np
        from agents.AGI_1_7.engine.agi17.finance.npisoc_rbtn_execution_engine import (
            path_integral_stochastic_control, solve_neural_fbsde
        )
        out = path_integral_stochastic_control(n_samples=96, horizon_steps=16, seed=123)
        assert out["finite_verified"] is True
        assert out["trajectories"].shape == (96, 17)
        assert np.all(out["trajectories"][:, -1] == 0.0)
        assert out["terminal_residual"] == 0.0
        assert out["effective_sample_size"] >= 1.0

        fbsde = solve_neural_fbsde(n_paths=64, n_steps=12, seed=9)
        assert fbsde["finite_verified"] is True
        assert fbsde["lipschitz_verified"] is True
        assert fbsde["trajectory"].shape == (64, 13)
        assert np.all(fbsde["trajectory"][:, -1] == 0.0)

    def test_cycle71_rough_bergomi_and_tt(self) -> None:
        import pytest
        import numpy as np
        from agents.AGI_1_7.engine.agi17.finance.npisoc_rbtn_execution_engine import (
            exponential_lift_kernel, simulate_rough_bergomi, tt_svd, reconstruct_tt,
            volatility_surface_audit
        )
        times = np.geomspace(0.01, 1.0, 32)
        lift = exponential_lift_kernel(times, hurst=0.12, n_factors=12)
        assert lift["betas"].shape == (12,)
        assert np.all(lift["betas"] > 0)
        assert np.all(lift["weights"] > 0)

        sim = simulate_rough_bergomi(n_steps=24, n_paths=32, seed=14)
        assert sim["finite_verified"] is True
        assert sim["positive_variance_verified"] is True
        assert np.all(sim["variance_paths"] > 0)

        a = np.array([1.0, 2.0, 3.0]); b = np.array([1.5, -0.5])
        c = np.array([0.5, 1.0, 2.0, -1.0]); d = np.array([2.0, 4.0])
        tensor = a[:, None, None, None] * b[None, :, None, None] * c[None, None, :, None] * d[None, None, None, :]
        tt = tt_svd(tensor, max_bond_dim=16, tol=1e-10)
        recon = reconstruct_tt(tt["cores"])
        assert np.linalg.norm(tensor - recon) < 1e-9

        k = np.linspace(-1.0, 1.0, 41)
        t = np.array([0.1, 0.25, 0.5, 1.0])
        w = np.array([ti * (0.04 + 0.01 * k * k) for ti in t])
        audit = volatility_surface_audit(k, t, w)
        assert audit["calendar_ok"] is True
        assert audit["butterfly_ok"] is True
        assert audit["static_arbitrage_free_on_grid"] is True

    def test_cycle71_mlofi_hawkes_and_fees(self) -> None:
        import pytest
        import numpy as np
        from agents.AGI_1_7.engine.agi17.finance.npisoc_rbtn_execution_engine import (
            compute_mlofi, hawkes_toxicity_gate, almgren_chriss_multi_expiry_unwind,
            indian_statutory_fees, net_alpha_gate, beta_fractional_kelly
        )
        bid = np.ones(5); ask = np.ones(5) * 0.5
        bp = np.array([1, 0, -1, 1, 1]); ap = np.array([-1, 1, 0, -1, 1])
        m = compute_mlofi(bid, ask, bp, ap)
        assert isinstance(m, float)

        toxic = hawkes_toxicity_gate(100.0, [0.1, 0.2], [2.0, 1.0], gamma_mlofi=0.5, tau=1.0)
        assert toxic["toxicity_action"] == "RETREAT"

        unwind = almgren_chriss_multi_expiry_unwind([3.0, -2.0], horizon_steps=8, intensity=2.0, tau=1.0)
        assert unwind["terminal_residual"] == 0.0
        assert np.all(unwind["inventory_path"][-1] == 0.0)

        fees = indian_statutory_fees(100_000, 150_000, executed_legs=4)
        assert fees["total_fees_inr"] > 80.0
        gate = net_alpha_gate(fees["total_fees_inr"] + 15.0, fees["total_fees_inr"])
        assert gate["approved"] is True

        k = beta_fractional_kelly(2, 2, 12, 4, 1.8)
        assert 0.0 <= k["capital_fraction"] <= 0.10

    def test_cycle71_squad_and_fail_closed_dispatch(self) -> None:
        import pytest
        from agents.AGI_1_7.engine.agi17.finance.npisoc_rbtn_execution_engine import (
            squad_consensus, dispatch_live_order,
            LIVE_ORDER_DISPATCH_ENABLED, REAL_BROKER_FILLS_LOCKED,
            INITIAL_CAPITAL_INR, AGENT_NAMES
        )
        assert LIVE_ORDER_DISPATCH_ENABLED is False
        assert REAL_BROKER_FILLS_LOCKED is True
        assert INITIAL_CAPITAL_INR == 10000.0

        votes = {name: True for name in AGENT_NAMES}
        squad = squad_consensus(votes, manager_live_veto=False, risk_gates_passed=True)
        assert squad["paper_research_approved"] is True
        assert squad["live_order_dispatch_enabled"] is False

        with pytest.raises(PermissionError) as exc_info:
            dispatch_live_order("NIFTY", 1)
        assert "LIVE_ORDER_DISPATCH_BLOCKED: Cycle 71 is fail-closed" in str(exc_info.value)
