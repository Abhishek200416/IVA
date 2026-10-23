"""Unit and regression tests for Phase 8.5 Contract-Expiry Transition Correction.

Verifies NSE Circular NSE/FAOP/70616 and annexure transition schedules:
- Previous market lots: NIFTY 75, BANKNIFTY 35
- Revised market lots: NIFTY 65, BANKNIFTY 30
- Unexpired weekly/monthly transition concluding by Dec 30, 2025
- Quarterly & Half-Yearly existing contract transition at EOD Dec 30, 2025
- Historical epochs (25/15, 50/15, 50/25, 75/25)
- Fail-closed handling for contradictory/missing metadata and invalid tick/lot sizes.
"""

from __future__ import annotations

import datetime
import unittest

from agents.AGI_1_7.engine.agi17.finance.live_contract_validator import (
    LiveContract,
    LiveContractValidator,
    OptionType,
    get_standard_lot_size,
)


class TestPhase85ContractTransitionCorrection(unittest.TestCase):
    """Rigorous test battery verifying NSE Circular NSE/FAOP/70616 transition logic."""

    def setUp(self):
        self.validator = LiveContractValidator()

    # -------------------------------------------------------------------------
    # 1. NEW-LOT VS OLD-LOT TRANSITION BOUNDARIES (NSE/FAOP/70616)
    # -------------------------------------------------------------------------

    def test_01_post_transition_2026_contracts(self):
        """All standard 2026 contracts resolve to revised statutory lot sizes (NIFTY 65, BANKNIFTY 30)."""
        # Modern 2026 contracts
        self.assertEqual(get_standard_lot_size("NIFTY", as_of_date="2026-10-13"), 65)
        self.assertEqual(get_standard_lot_size("NIFTY", expiry_date="2026-10-29"), 65)
        self.assertEqual(get_standard_lot_size("NIFTY", as_of_date="2026-03-15", expiry_date="2026-03-26"), 65)

        self.assertEqual(get_standard_lot_size("BANKNIFTY", as_of_date="2026-10-13"), 30)
        self.assertEqual(get_standard_lot_size("BANKNIFTY", expiry_date="2026-10-29"), 30)
        self.assertEqual(get_standard_lot_size("BANKNIFTY", as_of_date="2026-03-15", expiry_date="2026-03-26"), 30)

    def test_02_transition_window_weekly_and_monthly_contracts(self):
        """Under circular 70616, existing weekly/monthly contracts expiring <= Dec 30, 2025 maintain old lots (75 / 35)."""
        # Weekly contract in November 2025
        self.assertEqual(
            get_standard_lot_size("NIFTY", as_of_date="2025-11-01", expiry_date="2025-11-06"),
            75,
        )
        self.assertEqual(
            get_standard_lot_size("BANKNIFTY", as_of_date="2025-11-01", expiry_date="2025-11-06"),
            35,
        )

        # Monthly contract in November 2025
        self.assertEqual(
            get_standard_lot_size("NIFTY", as_of_date="2025-11-15", expiry_date="2025-11-27"),
            75,
        )
        self.assertEqual(
            get_standard_lot_size("BANKNIFTY", as_of_date="2025-11-15", expiry_date="2025-11-27"),
            35,
        )

        # Monthly contract in December 2025 (concluding transition window on Dec 30, 2025)
        self.assertEqual(
            get_standard_lot_size("NIFTY", as_of_date="2025-12-10", expiry_date="2025-12-25"),
            75,
        )
        self.assertEqual(
            get_standard_lot_size("BANKNIFTY", as_of_date="2025-12-10", expiry_date="2025-12-25"),
            35,
        )

    def test_03_quarterly_and_half_yearly_contracts_transition(self):
        """Quarterly/Half-Yearly contracts traded on/before Dec 30, 2025 have lot 75/35; after Dec 30, 2025 have lot 65/30."""
        # March 2026 quarterly contract observed in November 2025 before the Dec 30 EOD automatic revision
        self.assertEqual(
            get_standard_lot_size(
                "NIFTY",
                as_of_date="2025-11-15",
                expiry_date="2026-03-26",
                cycle_type="QUARTERLY",
            ),
            75,
        )
        self.assertEqual(
            get_standard_lot_size(
                "BANKNIFTY",
                as_of_date="2025-11-15",
                expiry_date="2026-03-26",
                cycle_type="QUARTERLY",
            ),
            35,
        )

        # That same March 2026 quarterly contract observed in January 2026 (post Dec 30 EOD revision)
        self.assertEqual(
            get_standard_lot_size(
                "NIFTY",
                as_of_date="2026-01-05",
                expiry_date="2026-03-26",
                cycle_type="QUARTERLY",
            ),
            65,
        )
        self.assertEqual(
            get_standard_lot_size(
                "BANKNIFTY",
                as_of_date="2026-01-05",
                expiry_date="2026-03-26",
                cycle_type="QUARTERLY",
            ),
            30,
        )

    # -------------------------------------------------------------------------
    # 2. HISTORICAL REGULATORY REGIMES & CONTRACT SCHEDULES
    # -------------------------------------------------------------------------

    def test_04_historical_epochs_nifty(self):
        """NIFTY lot sizes accurately match historical regulatory circulars."""
        # SEBI Nov 20, 2024 to Oct 28, 2025 regime: Lot 75
        self.assertEqual(get_standard_lot_size("NIFTY", as_of_date="2025-05-15"), 75)

        # NSE/FAOP/61320 (April 26, 2024 to Nov 19, 2024): Lot 25
        self.assertEqual(get_standard_lot_size("NIFTY", as_of_date="2024-06-15"), 25)

        # NSE/FAOP/47786 (July 1, 2021 to April 25, 2024): Lot 50
        self.assertEqual(get_standard_lot_size("NIFTY", as_of_date="2023-06-15"), 50)
        self.assertEqual(get_standard_lot_size("NIFTY", as_of_date="2022-01-15"), 50)

        # Pre-July 2021 historical epoch: Lot 75
        self.assertEqual(get_standard_lot_size("NIFTY", as_of_date="2020-05-15"), 75)

    def test_05_historical_epochs_banknifty(self):
        """BANKNIFTY lot sizes accurately match historical regulatory circulars."""
        # SEBI Nov 20, 2024 to Oct 28, 2025 regime: Lot 35
        self.assertEqual(get_standard_lot_size("BANKNIFTY", as_of_date="2025-05-15"), 35)

        # NSE/FAOP/57014 (July 1, 2023 to Nov 19, 2024): Lot 15
        self.assertEqual(get_standard_lot_size("BANKNIFTY", as_of_date="2024-06-15"), 15)
        self.assertEqual(get_standard_lot_size("BANKNIFTY", as_of_date="2023-08-15"), 15)

        # Pre-July 2023 historical epoch: Lot 25
        self.assertEqual(get_standard_lot_size("BANKNIFTY", as_of_date="2022-06-15"), 25)
        self.assertEqual(get_standard_lot_size("BANKNIFTY", as_of_date="2020-05-15"), 25)

    # -------------------------------------------------------------------------
    # 3. FAIL-CLOSED DEFENSIVE GATES & CONTRADICTORY METADATA
    # -------------------------------------------------------------------------

    def test_06_unauthorized_and_unknown_underlyings_fail_closed(self):
        """Unsupported or unrecognized underlyings raise ValueError."""
        with self.assertRaises(ValueError) as ctx:
            get_standard_lot_size("UNKNOWN_INDEX", as_of_date="2026-10-13")
        self.assertIn("UNKNOWN_UNDERLYING", str(ctx.exception))

        with self.assertRaises(ValueError) as ctx:
            get_standard_lot_size("", as_of_date="2026-10-13")
        self.assertIn("UNKNOWN_UNDERLYING", str(ctx.exception))

        with self.assertRaises(ValueError) as ctx:
            get_standard_lot_size("SENSEX", as_of_date="2026-10-13")
        self.assertIn("UNKNOWN_UNDERLYING", str(ctx.exception))

    def test_07_invalid_and_contradictory_date_metadata(self):
        """Invalid date strings or contradictory dates (expiry < as_of) fail closed."""
        # Malformed date strings
        with self.assertRaises(ValueError) as ctx:
            get_standard_lot_size("NIFTY", as_of_date="invalid-date")
        self.assertIn("INVALID_DATE_METADATA", str(ctx.exception))

        with self.assertRaises(ValueError) as ctx:
            get_standard_lot_size("NIFTY", expiry_date="2026-99-99")
        self.assertIn("INVALID_DATE_METADATA", str(ctx.exception))

        # Contradictory: expiry date is in the past relative to as_of observation date
        with self.assertRaises(ValueError) as ctx:
            get_standard_lot_size("NIFTY", as_of_date="2026-10-15", expiry_date="2026-10-01")
        self.assertIn("CONTRADICTORY_METADATA", str(ctx.exception))

    # -------------------------------------------------------------------------
    # 4. CONTRACT VALIDATOR END-TO-END REJECTION TESTS
    # -------------------------------------------------------------------------

    def test_08_validator_rejects_wrong_lot_size(self):
        """Validator rejects contract if lot size does not match statutory expectation."""
        # 2026 NIFTY contract with wrong lot size 50 instead of 65
        invalid_contract = {
            "underlying": "NIFTY",
            "symbol": "NIFTY2026102922500CE",
            "expiry_date": "2026-10-29",
            "strike": 22500.0,
            "option_type": "CE",
            "lot_size": 50,  # Invalid for 2026 (must be 65)
            "ltp": 50.0,
            "bid": 49.95,
            "ask": 50.05,
        }
        res = self.validator.validate_contract(invalid_contract, action="BUY")
        self.assertFalse(res.is_valid)
        self.assertTrue(any("does not match statutory standard lot size 65" in r for r in res.reasons))

    def test_09_validator_rejects_invalid_tick_size(self):
        """Validator rejects contract if LTP is not an exact multiple of 0.05."""
        invalid_tick_contract = {
            "underlying": "NIFTY",
            "symbol": "NIFTY2026102922500CE",
            "expiry_date": "2026-10-29",
            "strike": 22500.0,
            "option_type": "CE",
            "lot_size": 65,
            "ltp": 50.03,  # Invalid tick (not multiple of 0.05)
            "bid": 49.95,
            "ask": 50.05,
        }
        res = self.validator.validate_contract(invalid_tick_contract, action="BUY")
        self.assertFalse(res.is_valid)
        self.assertTrue(any("not a valid multiple of NSE tick size" in r for r in res.reasons))

    def test_10_is_valid_lot_size_multiples(self):
        """is_valid_lot_size checks integer multiples of statutory lot size."""
        # 2026 NIFTY lot is 65
        self.assertTrue(LiveContractValidator.is_valid_lot_size("NIFTY", 65, as_of_date="2026-10-13"))
        self.assertTrue(LiveContractValidator.is_valid_lot_size("NIFTY", 130, as_of_date="2026-10-13"))
        self.assertFalse(LiveContractValidator.is_valid_lot_size("NIFTY", 50, as_of_date="2026-10-13"))
        self.assertFalse(LiveContractValidator.is_valid_lot_size("NIFTY", -65, as_of_date="2026-10-13"))
        self.assertFalse(LiveContractValidator.is_valid_lot_size("NIFTY", 0, as_of_date="2026-10-13"))

        # 2026 BANKNIFTY lot is 30
        self.assertTrue(LiveContractValidator.is_valid_lot_size("BANKNIFTY", 30, as_of_date="2026-10-13"))
        self.assertTrue(LiveContractValidator.is_valid_lot_size("BANKNIFTY", 90, as_of_date="2026-10-13"))
        self.assertFalse(LiveContractValidator.is_valid_lot_size("BANKNIFTY", 15, as_of_date="2026-10-13"))


if __name__ == "__main__":
    unittest.main()
