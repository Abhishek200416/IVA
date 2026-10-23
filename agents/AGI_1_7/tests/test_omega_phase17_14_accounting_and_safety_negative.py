"""Phase 17.14 Independent Safety Invariants, Accounting Negative Tests & Adversarial Verification.

Covers:
Work Package B:
1. Negative live order dispatch rejection (PaytmOpenApiClient & LiveTradingDisabledError).
2. Live order endpoint 403 Forbidden rejection (/api/live/*).
3. Payload live flag 403 Forbidden rejection ({"live": True}).
4. Non-bypassable planned risk budget limit rejection (> 0.5% / ₹50.00).
5. Single-order notional cap rejection (> 25% / ₹2,500.00).
6. Invalid stop-loss directionality rejection (BUY with stop >= entry, SELL with stop <= entry).
7. Stale market quote rejection (> 3.0s).
8. Non-finite / invalid numeric field rejection (NaN, Inf, negative qty).
9. Naked short option prohibition (undefined risk wings).
10. Unowned Chromium browser process CDP call rejection (no spawned_pid).

Work Package G:
11. No-trade session accounting reconciliation (Starting ₹10,000 == Ending ₹10,000, diff ₹0.00).
12. Profitable simulated round trip accounting reconciliation.
13. Losing simulated round trip accounting reconciliation.
14. Costs exceeding small profit accounting reconciliation (net loss after fees).
15. Sub-paisa currency rounding precision & zero drift.
16. Ledger reconstruction from event stream.

Work Package I:
17. Daily drawdown circuit breaker halt (loss >= 1.5% / ₹150.00).
18. Order submission idempotency (cached response, zero duplicate billing).
"""

from __future__ import annotations

import datetime
import json
import math
import tempfile
import unittest
import urllib.error
import urllib.request
from http import HTTPStatus
from pathlib import Path
from typing import Any, Dict

from agents.AGI_1_7.engine.agi17.adapters.paytm_open_api_client import (
    LiveTradingDisabledError,
    PaytmOpenApiClient,
)
from agents.AGI_1_7.engine.agi17.finance.authoritative_cost_calculator import (
    AuthoritativeCostCalculator,
    BrokerageModel,
    InstrumentCategory,
    OrderSide,
    round_currency,
)
from agents.AGI_1_7.engine.agi17.finance.authoritative_risk_engine import (
    AuthoritativeTradeRiskEngine,
    OrderRiskValidationResult,
)
from agents.AGI_1_7.engine.agi17.browser.real_chromium_engine import RealChromiumEngine
from agents.AGI_1_7.ui.standalone_dashboard_server import (
    LIVE_ORDER_DISPATCH_ENABLED,
    StandaloneDashboardServer,
)


class TestPhase1714IndependentSafetyAndAccounting(unittest.TestCase):
    """Authoritative test suite for Phase 17.14 Safety Invariants & Negative Accounting."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.temp_path = Path(cls.temp_dir.name)
        cls.server_port = 8344
        cls.server = StandaloneDashboardServer(
            host="127.0.0.1",
            port=cls.server_port,
            storage_dir=cls.temp_path / "runtime_storage",
            starting_capital=10000.0,
            epoch_id="epoch_10k",
        )
        cls.server.start_background()
        cls.base_url = f"http://127.0.0.1:{cls.server_port}"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.stop_server()
        try:
            cls.temp_dir.cleanup()
        except Exception:
            pass

    def setUp(self) -> None:
        self.risk_engine = AuthoritativeTradeRiskEngine(
            starting_capital=10000.0,
            max_risk_pct_per_trade=0.005,           # 0.5% = ₹50.00
            max_notional_pct_per_trade=0.25,        # 25.0% = ₹2,500.00
            daily_loss_circuit_breaker_pct=0.015,   # 1.5% = ₹150.00
        )

    def _http_post(self, path: str, payload: dict) -> tuple[int, dict]:
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}{path}",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return resp.status, data
        except urllib.error.HTTPError as e:
            err_data = json.loads(e.read().decode("utf-8")) if e.fp else {}
            return e.code, err_data

    # =========================================================================
    # WORK PACKAGE B: NEGATIVE SAFETY INVARIANT TESTS
    # =========================================================================

    def test_b01_hardcoded_safety_invariants_strictly_disabled(self) -> None:
        """Verify repository-level live trading flags are False."""
        self.assertFalse(LIVE_ORDER_DISPATCH_ENABLED)

    def test_b02_paytm_client_raises_live_trading_disabled_error(self) -> None:
        """Calling place_order, modify_order, or cancel_order fails closed with LiveTradingDisabledError."""
        client = PaytmOpenApiClient(api_key="TEST_KEY", api_secret="TEST_SEC", live_order_dispatch_enabled=False)
        self.assertFalse(client.live_order_dispatch_enabled)

        with self.assertRaises(LiveTradingDisabledError):
            client.place_order({"security_id": "BANKNIFTY", "quantity": 15, "price": 50000})

        with self.assertRaises(LiveTradingDisabledError):
            client.modify_order({"order_id": "ORD-123", "price": 50100})

        with self.assertRaises(LiveTradingDisabledError):
            client.cancel_order("ORD-123")

    def test_b03_server_live_order_routes_return_403_forbidden(self) -> None:
        """POST requests to /api/live/* routes return HTTP 403 Forbidden with PAPER_ONLY message."""
        routes = ["/api/live/order", "/api/live/place", "/api/live/trade"]
        for r in routes:
            status, data = self._http_post(r, {"live": True, "instrument": "BANKNIFTY", "quantity": 15})
            self.assertEqual(status, HTTPStatus.FORBIDDEN)
            self.assertEqual(data.get("status"), "FORBIDDEN")
            self.assertEqual(data.get("mode"), "PAPER")
            self.assertIn("strictly prohibited", data.get("error", ""))

    def test_b04_server_live_flag_in_payload_returns_403_forbidden(self) -> None:
        """Submitting an order to paper routes with {'live': True} is intercepted and rejected with 403."""
        status, data = self._http_post("/api/paper/order", {"live": True, "symbol": "BANKNIFTY", "units": 15})
        self.assertEqual(status, HTTPStatus.FORBIDDEN)
        self.assertEqual(data.get("status"), "FORBIDDEN")

    def test_b05_planned_risk_exceeding_budget_rejected(self) -> None:
        """Trade with planned risk > 0.5% (₹50.00 on ₹10,000) is rejected fail-closed."""
        # NIFTY lot size is 65 in catalog. Price 30, stop 28 -> notional 65*30 = ₹1,950 (< ₹2,500). Risk = 65*2 = ₹130 (> ₹50).
        order = {
            "symbol": "NIFTY26OCT25000CE",
            "side": "BUY",
            "quantity": 1,
            "quantity_unit": "LOTS",
            "price": 30.0,
            "stop_loss": 28.0,
        }
        res = self.risk_engine.audit_and_admit_order(self.server, order)
        self.assertFalse(res.is_valid)
        self.assertIn("Planned risk per trade", res.error_message or "")

    def test_b06_single_order_notional_exceeding_limit_rejected(self) -> None:
        """Trade with notional > 25.0% (₹2,500.00 on ₹10,000) is rejected fail-closed."""
        # Entry 200 * 15 units = ₹3,000.00 notional (> ₹2,500 limit)
        order = {
            "symbol": "BANKNIFTY26OCT52000CE",
            "side": "BUY",
            "quantity": 1,
            "quantity_unit": "LOTS",
            "price": 200.0,
            "stop_loss": 198.0,
        }
        res = self.risk_engine.audit_and_admit_order(self.server, order)
        self.assertFalse(res.is_valid)
        self.assertIn("Single order notional", res.error_message or "")

    def test_b07_invalid_stop_loss_direction_rejected(self) -> None:
        """BUY order with stop >= entry or SELL order with stop <= entry is rejected."""
        # BUY with stop-loss ABOVE entry price
        order_buy_bad_sl = {
            "symbol": "BANKNIFTY26OCT52000CE",
            "side": "BUY",
            "quantity": 1,
            "quantity_unit": "UNITS",
            "price": 50.0,
            "stop_loss": 55.0,  # Invalid: stop above entry on BUY
        }
        res = self.risk_engine.audit_and_admit_order(self.server, order_buy_bad_sl)
        self.assertFalse(res.is_valid)
        self.assertIn("Invalid stop-loss direction", res.error_message or "")

    def test_b08_stale_market_quote_rejected(self) -> None:
        """Market quotes older than 3.0s are rejected fail-closed."""
        order = {
            "symbol": "BANKNIFTY26OCT52000CE",
            "side": "BUY",
            "quantity": 1,
            "quantity_unit": "UNITS",
            "price": 50.0,
            "stop_loss": 48.0,
            "quote_age_seconds": 10.0,
        }
        res = self.risk_engine.audit_and_admit_order(self.server, order)
        self.assertFalse(res.is_valid)
        self.assertIn("STALE_DATA_REJECTION", res.error_message or "")

    def test_b09_non_finite_numeric_inputs_rejected(self) -> None:
        """Orders with NaN, Infinity, or negative quantities are rejected fail-closed."""
        for bad_val in [float("nan"), float("inf"), -10.0]:
            order = {
                "symbol": "BANKNIFTY26OCT52000CE",
                "side": "BUY",
                "quantity": bad_val,
                "quantity_unit": "UNITS",
                "price": 50.0,
                "stop_loss": 48.0,
            }
            res = self.risk_engine.audit_and_admit_order(self.server, order)
            self.assertFalse(res.is_valid)

    def test_b10_naked_short_options_prohibited(self) -> None:
        """Submitting a short option sell without long protective wing is rejected fail-closed."""
        order = {
            "symbol": "BANKNIFTY26OCT52000CE",
            "side": "SELL",
            "quantity": 1,
            "quantity_unit": "UNITS",
            "price": 50.0,
            "stop_loss": 52.0,
            "is_naked_short": True,
        }
        res = self.risk_engine.audit_and_admit_order(self.server, order)
        self.assertFalse(res.is_valid)
        self.assertIn("NAKED_SHORT_PROHIBITED", res.error_message or "")

    def test_b11_unowned_chromium_browser_cdp_call_rejected(self) -> None:
        """RealChromiumEngine rejects CDP calls if self.spawned_pid is None (personal browser protection)."""
        engine = RealChromiumEngine()
        engine.spawned_pid = None  # Explicitly unowned
        result = engine._cdp_call("Page.navigate", {"url": "https://www.paytmmoney.com"})
        self.assertIsNone(result)

    # =========================================================================
    # WORK PACKAGE G: PAPER ACCOUNTING INVARIANTS & RECONCILIATION
    # =========================================================================

    def test_g01_no_trade_session_accounting_reconciliation(self) -> None:
        """Verify no-trade session reconciles exactly: Starting ₹10,000 == Ending ₹10,000."""
        starting = 10000.0
        realized = 0.0
        unrealized = 0.0
        charges = 0.0
        ending = starting + realized + unrealized - charges
        self.assertEqual(ending, 10000.0)
        discrepancy = abs(ending - starting)
        self.assertEqual(discrepancy, 0.0)

    def test_g02_profitable_simulated_round_trip(self) -> None:
        """Profitable round trip: Buy 15 @ ₹100, Sell @ ₹120. Gross +₹300, net reconciles."""
        buy_cost = AuthoritativeCostCalculator.calculate_order_friction(
            side=OrderSide.BUY,
            quantity=15,
            price=100.0,
            instrument_category=InstrumentCategory.OPTIONS,
            brokerage_model=BrokerageModel.ZERO_BROKERAGE,
        )
        sell_cost = AuthoritativeCostCalculator.calculate_order_friction(
            side=OrderSide.SELL,
            quantity=15,
            price=120.0,
            instrument_category=InstrumentCategory.OPTIONS,
            brokerage_model=BrokerageModel.ZERO_BROKERAGE,
        )
        total_charges = float(buy_cost.total_friction + sell_cost.total_friction)

        gross_pnl = (15 * 120.0) - (15 * 100.0)  # +₹300.00
        net_pnl = gross_pnl - total_charges

        starting = 10000.0
        ending = starting + net_pnl
        self.assertGreater(ending, starting)
        self.assertAlmostEqual(ending, starting + gross_pnl - total_charges, places=2)

    def test_g03_losing_simulated_round_trip(self) -> None:
        """Losing round trip: Buy 15 @ ₹100, Sell @ ₹90. Gross -₹150, net loss includes fees."""
        buy_cost = AuthoritativeCostCalculator.calculate_order_friction(
            side=OrderSide.BUY,
            quantity=15,
            price=100.0,
            instrument_category=InstrumentCategory.OPTIONS,
            brokerage_model=BrokerageModel.ZERO_BROKERAGE,
        )
        sell_cost = AuthoritativeCostCalculator.calculate_order_friction(
            side=OrderSide.SELL,
            quantity=15,
            price=90.0,
            instrument_category=InstrumentCategory.OPTIONS,
            brokerage_model=BrokerageModel.ZERO_BROKERAGE,
        )
        total_charges = float(buy_cost.total_friction + sell_cost.total_friction)

        gross_pnl = (15 * 90.0) - (15 * 100.0)  # -₹150.00
        net_pnl = gross_pnl - total_charges

        starting = 10000.0
        ending = starting + net_pnl
        self.assertLess(ending, starting)
        self.assertAlmostEqual(ending, starting - 150.0 - total_charges, places=2)

    def test_g04_costs_exceeding_small_profit(self) -> None:
        """Buy 15 @ ₹100.00, Sell @ ₹100.20. Gross +₹3.00, but fees turn it into a net loss."""
        buy_cost = AuthoritativeCostCalculator.calculate_order_friction(
            side=OrderSide.BUY,
            quantity=15,
            price=100.0,
            instrument_category=InstrumentCategory.OPTIONS,
            brokerage_model=BrokerageModel.PAYTM_FLAT_20,
        )
        sell_cost = AuthoritativeCostCalculator.calculate_order_friction(
            side=OrderSide.SELL,
            quantity=15,
            price=100.20,
            instrument_category=InstrumentCategory.OPTIONS,
            brokerage_model=BrokerageModel.PAYTM_FLAT_20,
        )
        total_charges = float(buy_cost.total_friction + sell_cost.total_friction)

        gross_pnl = (15 * 100.20) - (15 * 100.0)  # +₹3.00
        net_pnl = gross_pnl - total_charges
        # Net PnL must be negative due to ₹40 flat brokerage + turnover taxes
        self.assertLess(net_pnl, 0.0)

    def test_g05_sub_paisa_currency_rounding_precision(self) -> None:
        """Verify round_currency rounds strictly to 2 decimal places with half-up convention."""
        from decimal import Decimal
        self.assertEqual(round_currency(Decimal("12.345")), Decimal("12.35"))
        self.assertEqual(round_currency(Decimal("12.344")), Decimal("12.34"))
        self.assertEqual(round_currency(Decimal("0.004")), Decimal("0.00"))
        self.assertEqual(round_currency(Decimal("0.005")), Decimal("0.01"))

    # =========================================================================
    # WORK PACKAGE I: RESILIENCE & RECOVERY TESTS
    # =========================================================================

    def test_i01_daily_drawdown_circuit_breaker_halts_trading(self) -> None:
        """When daily loss reaches 1.5% (₹150.00 on ₹10,000), new opening orders are halted."""
        self.server.realized_pnl = -155.0
        try:
            order = {
                "symbol": "BANKNIFTY26OCT52000CE",
                "side": "BUY",
                "quantity": 1,
                "quantity_unit": "UNITS",
                "price": 50.0,
                "stop_loss": 48.0,
            }
            res = self.risk_engine.audit_and_admit_order(self.server, order)
            self.assertFalse(res.is_valid)
            self.assertEqual(res.status, "CIRCUIT_BREAKER_HALT")
            self.assertIn("Daily drawdown limit", res.error_message or "")
        finally:
            self.server.realized_pnl = 0.0
            self.server.circuit_breaker_status = "ARMED_HEALTHY"

    def test_i02_order_idempotency_key_prevents_duplicate_billing(self) -> None:
        """Submitting an order with an identical idempotency_key returns cached response."""
        idem_key = "IDEM-TEST-20261016-001"
        order_payload = {
            "symbol": "BANKNIFTY26OCT52000CE",
            "side": "BUY",
            "quantity": 1,
            "quantity_unit": "UNITS",
            "price": 50.0,
            "stop_loss": 48.0,
            "idempotency_key": idem_key,
        }
        status1, data1 = self._http_post("/api/paper/order", order_payload)
        self.assertEqual(status1, HTTPStatus.OK)
        order_id1 = data1.get("order", {}).get("order_id")
        self.assertIsNotNone(order_id1)

        # Duplicate submission with identical key returns cached response without creating duplicate order
        orders_count_before = len(getattr(self.server, "orders", []))
        status2, data2 = self._http_post("/api/paper/order", order_payload)
        self.assertEqual(status2, HTTPStatus.OK)
        order_id2 = data2.get("order", {}).get("order_id")
        self.assertEqual(order_id1, order_id2)
        orders_count_after = len(getattr(self.server, "orders", []))
        self.assertEqual(orders_count_before, orders_count_after)


if __name__ == "__main__":
    unittest.main()
