"""AGI 1.7 Task-REV-01 Mathematical & Federated Model Verification Suite.

Validates:
1. Analytical Black-Scholes Greeks derivations vs finite-difference approximations.
2. Put-Call parity invariance across moneyness regimes.
3. IV bisection solver precision and round-trip consistency.
4. Asymptotic boundary conditions (T->0, deep ITM, deep OTM, sigma floor).
5. Federated model authorization and quota failover contracts.
"""

from __future__ import annotations

import math
import unittest

from agents.AGI_1_7.engine.agi17.finance.bank_nifty_paper_trader import (
    BlackScholesCalculator,
    OptionGreeks,
    OptionType,
    BankNiftyContractSpec,
)
from agents.AGI_1_7.engine.agi17.adapters.model_adapter import (
    ModelAdapter,
    ModelProviderConfig,
    DirectiveZeroViolationError,
)


class TestOmegaGreeksAndFederated(unittest.TestCase):
    """Rigorous mathematical cross-validation of Greeks and federated models."""

    def test_01_put_call_parity_exact(self) -> None:
        """Verifies Put-Call Parity: C - P = S - K * exp(-r * T)."""
        spot = 51200.0
        strikes = [49000.0, 50000.0, 51200.0, 52000.0, 53500.0]
        rate = 0.065
        vol = 0.175
        time_to_expiry = 14.0 / 365.0  # 14 days

        discount = math.exp(-rate * time_to_expiry)

        for k in strikes:
            ce = BlackScholesCalculator.calculate_greeks(spot, k, time_to_expiry, rate, vol, OptionType.CE)
            pe = BlackScholesCalculator.calculate_greeks(spot, k, time_to_expiry, rate, vol, OptionType.PE)

            theoretical_diff = spot - k * discount
            actual_diff = ce.price - pe.price

            # Due to tick rounding to 2 decimals, parity holds within 0.10 INR
            self.assertLess(
                abs(actual_diff - theoretical_diff),
                0.10,
                f"Parity violated for K={k}: actual {actual_diff:.2f} vs theoretical {theoretical_diff:.2f}",
            )

    def test_02_finite_difference_greeks_cross_validation(self) -> None:
        """Numerically verifies Delta, Gamma, and Vega using centered finite differences."""
        spot = 50000.0
        strike = 50000.0
        t = 7.0 / 365.0
        rate = 0.065
        vol = 0.16

        greeks_ce = BlackScholesCalculator.calculate_greeks(spot, strike, t, rate, vol, OptionType.CE)
        greeks_pe = BlackScholesCalculator.calculate_greeks(spot, strike, t, rate, vol, OptionType.PE)

        # 1. Delta check via centered difference: dC/dS ~= (C(S+h) - C(S-h)) / (2h)
        h_s = 0.50
        c_up = BlackScholesCalculator.calculate_greeks(spot + h_s, strike, t, rate, vol, OptionType.CE).price
        c_dn = BlackScholesCalculator.calculate_greeks(spot - h_s, strike, t, rate, vol, OptionType.CE).price
        num_delta_ce = (c_up - c_dn) / (2.0 * h_s)
        self.assertLess(abs(greeks_ce.delta - num_delta_ce), 0.02)

        p_up = BlackScholesCalculator.calculate_greeks(spot + h_s, strike, t, rate, vol, OptionType.PE).price
        p_dn = BlackScholesCalculator.calculate_greeks(spot - h_s, strike, t, rate, vol, OptionType.PE).price
        num_delta_pe = (p_up - p_dn) / (2.0 * h_s)
        self.assertLess(abs(greeks_pe.delta - num_delta_pe), 0.02)

        # 2. Gamma check: d2C/dS2 ~= (C(S+h) - 2C(S) + C(S-h)) / h^2
        num_gamma = (c_up - 2.0 * greeks_ce.price + c_dn) / (h_s ** 2)
        self.assertLess(abs(greeks_ce.gamma - num_gamma), 0.001)

        # 3. Vega symmetry: Call Vega == Put Vega
        self.assertLess(abs(greeks_ce.vega - greeks_pe.vega), 0.0001)
        self.assertEqual(greeks_ce.gamma, greeks_pe.gamma)

    def test_03_iv_bisection_inversion(self) -> None:
        """Verifies that calculate_implied_volatility precisely inverts Black-Scholes price."""
        spot = 51500.0
        strike = 51500.0
        t = 10.0 / 365.0
        rate = 0.065
        true_vols = [0.11, 0.155, 0.22, 0.35]

        for v in true_vols:
            ce = BlackScholesCalculator.calculate_greeks(spot, strike, t, rate, v, OptionType.CE)
            recovered_iv = BlackScholesCalculator.calculate_implied_volatility(
                market_price=ce.price,
                spot=spot,
                strike=strike,
                time_to_expiry_years=t,
                rate=rate,
                option_type=OptionType.CE,
            )
            self.assertLessEqual(abs(recovered_iv - v), 0.005, f"Expected IV {v}, recovered {recovered_iv}")

    def test_04_asymptotic_boundary_conditions(self) -> None:
        """Verifies behavior at boundary extremes (T->0, deep ITM, deep OTM, volatility floor)."""
        rate = 0.065
        vol = 0.18

        # 1. Near-instant expiry (T ~ 0)
        t_zero = 0.00001
        itm_ce = BlackScholesCalculator.calculate_greeks(52000.0, 50000.0, t_zero, rate, vol, OptionType.CE)
        self.assertGreaterEqual(itm_ce.price, 1999.0)
        self.assertGreaterEqual(itm_ce.delta, 0.99)

        otm_ce = BlackScholesCalculator.calculate_greeks(48000.0, 50000.0, t_zero, rate, vol, OptionType.CE)
        self.assertEqual(otm_ce.price, 0.05)  # minimum price floor
        self.assertLessEqual(otm_ce.delta, 0.01)

        # 2. Zero / negative volatility safety floor
        zero_vol_res = BlackScholesCalculator.calculate_greeks(50000.0, 50000.0, 0.1, rate, 0.0, OptionType.CE)
        self.assertGreaterEqual(zero_vol_res.price, 0.05)
        self.assertEqual(zero_vol_res.implied_volatility, 0.0001)

    def test_05_federated_models_contract_governance(self) -> None:
        """Verifies external federated models are recognized, authorized, and failover-ordered."""
        self.assertTrue(ModelAdapter.is_authorized_model("gemini-3.8-flash-high"))
        self.assertTrue(ModelAdapter.is_authorized_model("deepseek-ai/DeepSeek-V4-Flash-0731"))
        self.assertTrue(ModelAdapter.is_authorized_model("zai-org/GLM-5.3-Flash"))
        self.assertTrue(ModelAdapter.is_authorized_model("MiniMaxAI/MiniMax-M2.7"))
        self.assertFalse(ModelAdapter.is_authorized_model("unauthorized-rogue-llm"))

        # Failover chain determinism
        failover_1 = ModelAdapter.get_quota_failover_model("gemini-3.8-flash-high")
        self.assertEqual(failover_1, "deepseek-ai/DeepSeek-V4-Flash-0731")

        failover_2 = ModelAdapter.get_quota_failover_model("deepseek-ai/DeepSeek-V4-Flash-0731")
        self.assertEqual(failover_2, "MiniMaxAI/MiniMax-M2.7")

        # Enforcement when allow_federated is False
        cfg = ModelProviderConfig(model_name="deepseek-ai/DeepSeek-V4-Flash-0731", allow_federated_models=False)
        with self.assertRaises(DirectiveZeroViolationError):
            ModelAdapter(config=cfg)


if __name__ == "__main__":
    unittest.main()
