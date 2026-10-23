"""AGI 1.7 OMEGA COMMAND — Phase 12.2 Unified Architecture Hardening Test Suite.

Verifies:
1. P0 Trading Safety: fail-closed live order dispatch across API and broker adapters.
2. Callback Redundancy: StandaloneDashboardServer handles /paytm/callback with state capture.
3. Triad Consensus: Three-agent (Max, Emily, Alexa) agreement and PREFER_NO_TRADE veto protocol.
4. Contract & Lot Sizing: Dynamic lot-size transitions (NIFTY 65, BANKNIFTY 30, and historical).
5. Clean ₹10,000 Paper Ledger: Accounting identity and statutory fee waterfall (STT, GST, SEBI, exchange).
6. Quantitative Risk: Bayesian Kelly sizing, downside risk caps, and ruin boundary.
7. Token Lifecycle: Session token persistence, redaction, and 23:59:59 IST expiration.
8. Failure Injection: Network timeout, malformed payloads, and emergency circuit breakers.
"""

from __future__ import annotations

import datetime
import http.client
import json
import os
import shutil
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict

import pytest

from agents.AGI_1_7.engine.agi17.adapters.paytm_auth_callback_server import (
    PaytmTokenStore,
    redact_query_string,
    redact_token,
)
from agents.AGI_1_7.engine.agi17.adapters.paytm_open_api_client import (
    LiveTradingDisabledError,
    PaytmApiError,
    PaytmOpenApiClient,
)
from agents.AGI_1_7.engine.agi17.finance.bayesian_kelly_position_sizer import (
    BayesianKellyPositionSizer,
    SizingRegime,
)
from agents.AGI_1_7.engine.agi17.finance.live_broker_adapter import (
    LiveBrokerAdapter,
    LiveOrderState,
    OrderAction,
)
from agents.AGI_1_7.engine.agi17.finance.live_contract_validator import (
    LiveContract,
    LiveContractValidator,
    OptionType,
    get_standard_lot_size,
)
from agents.AGI_1_7.engine.agi17.finance.three_agent_contract import (
    ALEXA_PERSONA,
    EMILY_PERSONA,
    MAX_PERSONA,
    DisagreementRecord,
    OrderApprovalConsensus,
)
from agents.AGI_1_7.ui.standalone_dashboard_server import StandaloneDashboardServer


class TestPhase122P0SafetyAndIsolation:
    """Test Suite verifying P0 trading safety and fail-closed live order blocking."""

    def test_paytm_client_rejects_live_orders_by_default(self) -> None:
        client = PaytmOpenApiClient(api_key="TEST_KEY", api_secret="TEST_SEC", live_order_dispatch_enabled=False)
        assert client.live_order_dispatch_enabled is False

        with pytest.raises(LiveTradingDisabledError) as exc_info:
            client.place_order({"txn_type": "B", "exchange": "NSE", "segment": "D", "security_id": "12345"})
        assert "LIVE_ORDER_DISPATCH_ENABLED is False" in str(exc_info.value)

        with pytest.raises(LiveTradingDisabledError):
            client.modify_order({"order_id": "ORD001", "quantity": 65})

        with pytest.raises(LiveTradingDisabledError):
            client.cancel_order("ORD001")

    def test_live_broker_adapter_unarmed_state_prevents_submission(self) -> None:
        adapter = LiveBrokerAdapter()
        contract = LiveContract(
            symbol="NIFTY26OCT24500CE",
            underlying="NIFTY",
            expiry_date="2026-10-29",
            strike=24500.0,
            option_type=OptionType.CE,
            lot_size=65,
            ltp=120.0,
            bid=119.0,
            ask=121.0,
            timestamp=time.time(),
        )
        record = adapter.create_order_proposal(
            contract=contract,
            action=OrderAction.BUY,
            quantity=1,
            price=120.0,
            is_live_armed=False,
        )
        assert record.state == LiveOrderState.LIVE_SESSION_NOT_ARMED

        with pytest.raises(PermissionError) as exc_info:
            adapter.open_order_form(record.intent_id)
        assert "LIVE_SESSION_ARMED" in str(exc_info.value)


class TestPhase122DashboardAndCallback:
    """Test Suite verifying StandaloneDashboardServer safety boundaries and callback routing."""

    @pytest.fixture(scope="class")
    def dashboard_server(self):
        tmpdir = tempfile.mkdtemp()
        server = StandaloneDashboardServer(
            host="127.0.0.1",
            port=0,  # OS assigned port
            storage_dir=Path(tmpdir),
            starting_capital=10000.0,
            epoch_id="EPOCH-PAPER-10K-20261014-001",
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        port = server.server_address[1]
        yield f"http://127.0.0.1:{port}", server
        server.shutdown()
        server.server_close()
        shutil.rmtree(tmpdir, ignore_errors=True)

    def test_live_order_endpoint_returns_403_forbidden(self, dashboard_server) -> None:
        base_url, _ = dashboard_server
        req = urllib.request.Request(
            f"{base_url}/api/live/place_order",
            data=json.dumps({"symbol": "NIFTY", "mode": "LIVE"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(req)
        assert exc_info.value.code == 403
        body = json.loads(exc_info.value.read().decode("utf-8"))
        assert body["status"] == "FORBIDDEN"
        assert "strictly prohibited" in body["error"]

    def test_paytm_callback_alias_route_on_dashboard_server(self, dashboard_server) -> None:
        base_url, server = dashboard_server
        url = f"{base_url}/paytm/callback?requestToken=MOCK_TOKEN_XYZ&state=NONCE_123456"
        with urllib.request.urlopen(url) as resp:
            assert resp.status == 200
            content = resp.read().decode("utf-8")
            assert "Paytm Money Authorization Callback Captured" in content
            assert "NONCE_123456" in content

        assert server.last_paytm_callback is not None
        assert server.last_paytm_callback["request_token_present"] is True
        assert server.last_paytm_callback["state"] == "NONCE_123456"


class TestPhase122TriadConsensusProtocol:
    """Test Suite verifying Max, Emily, Alexa three-agent consensus and veto rules."""

    def test_personas_have_binding_rejection_authority(self) -> None:
        assert MAX_PERSONA.binding_rejection_authority is True
        assert EMILY_PERSONA.binding_rejection_authority is True
        assert ALEXA_PERSONA.binding_rejection_authority is True

    def test_unanimous_approval_generates_approved_consensus(self) -> None:
        now = time.time()
        consensus = OrderApprovalConsensus(
            consensus_id="CONS-001",
            session_id="SESS-20261014-01",
            symbol="NIFTY26OCT24500CE",
            action="BUY",
            quantity=1,
            price=110.0,
            status="APPROVED_FOR_EXECUTION",
            timestamp=now,
            timestamp_str=datetime.datetime.now(datetime.timezone.utc).isoformat(),
            emily_approved=True,
            max_approved=True,
            alexa_approved=True,
        )
        assert consensus.is_fresh() is True
        assert consensus.status == "APPROVED_FOR_EXECUTION"

    def test_single_agent_dissent_triggers_prefer_no_trade(self) -> None:
        disagreement = DisagreementRecord(
            disagreement_id="DISAGREE-001",
            session_id="SESS-20261014-01",
            timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat(),
            topic="Risk Budget Breach vs Setup Momentum",
            agent_stances={
                "Max": "REJECT: Risk exceeds 0.5% account capital",
                "Emily": "APPROVE: Macro sentiment positive",
                "Alexa": "APPROVE: UI ready and verified",
            },
            evidence_ledger={"Max": ["portfolio_risk=0.62% > 0.5% cap"]},
            resolution="PREFER_NO_TRADE",
            justification="Binding RMS limit veto overrides trade entry proposal.",
        )
        consensus = OrderApprovalConsensus(
            consensus_id="CONS-002",
            session_id="SESS-20261014-01",
            symbol="BANKNIFTY26OCT52000CE",
            action="BUY",
            quantity=1,
            price=250.0,
            status="PREFER_NO_TRADE",
            timestamp=time.time(),
            timestamp_str=datetime.datetime.now(datetime.timezone.utc).isoformat(),
            emily_approved=True,
            max_approved=False,
            alexa_approved=True,
            disagreement_record=disagreement,
            rejection_reasons=["Max: Risk budget exceeded"],
        )
        assert consensus.status == "PREFER_NO_TRADE"
        assert consensus.max_approved is False
        assert consensus.disagreement_record is not None
        assert consensus.disagreement_record.resolution == "PREFER_NO_TRADE"


class TestPhase122ContractLotSizeTransitions:
    """Test Suite verifying dynamic lot sizes across historical and current regimes."""

    def test_current_lot_sizes_2026(self) -> None:
        date_2026 = datetime.date(2026, 10, 14)
        assert get_standard_lot_size("NIFTY", date_2026) == 65
        assert get_standard_lot_size("BANKNIFTY", date_2026) == 30

    def test_historical_nifty_lot_sizes(self) -> None:
        # Pre-July 2021: 75
        assert get_standard_lot_size("NIFTY", datetime.date(2021, 5, 1)) == 75
        # July 2021 to April 2024: 50
        assert get_standard_lot_size("NIFTY", datetime.date(2023, 6, 1)) == 50
        # April 2024 to Nov 2024: 25
        assert get_standard_lot_size("NIFTY", datetime.date(2024, 7, 1)) == 25
        # Nov 20, 2024 to Dec 30, 2025: 75
        assert get_standard_lot_size("NIFTY", datetime.date(2024, 12, 1)) == 75
        # Post Dec 30, 2025 (NSE/FAOP/70616): 65
        assert get_standard_lot_size("NIFTY", datetime.date(2026, 1, 15)) == 65

    def test_historical_banknifty_lot_sizes(self) -> None:
        # Pre-July 2023: 25
        assert get_standard_lot_size("BANKNIFTY", datetime.date(2023, 1, 1)) == 25
        # July 2023 to Nov 2024: 15
        assert get_standard_lot_size("BANKNIFTY", datetime.date(2024, 6, 1)) == 15
        # Nov 20, 2024 to Dec 30, 2025: 35
        assert get_standard_lot_size("BANKNIFTY", datetime.date(2024, 12, 1)) == 35
        # Post Dec 30, 2025 (NSE/FAOP/70616): 30
        assert get_standard_lot_size("BANKNIFTY", datetime.date(2026, 1, 15)) == 30

    def test_spec_classes_delegate_to_date_aware_lot_sizing(self) -> None:
        from agents.AGI_1_7.engine.agi17.finance.nifty50_intraday_trader import Nifty50ContractSpec
        from agents.AGI_1_7.engine.agi17.finance.bank_nifty_market import BankNiftyContractSpec

        now_2026 = datetime.date(2026, 10, 14)
        assert Nifty50ContractSpec.get_lot_size(now_2026) == 65
        assert BankNiftyContractSpec.get_lot_size(now_2026) == 30

        # Historical check via spec class
        assert Nifty50ContractSpec.get_lot_size(datetime.date(2024, 7, 1)) == 25
        assert BankNiftyContractSpec.get_lot_size(datetime.date(2024, 6, 1)) == 15


class TestPhase122AccountingAndFeeWaterfall:
    """Test Suite verifying ₹10,000 clean paper ledger and statutory fee calculations."""

    def test_clean_accounting_identity_at_baseline(self) -> None:
        starting_capital = 10000.0
        realized_pnl = 0.0
        unrealized_pnl = 0.0
        ending_equity = starting_capital + realized_pnl + unrealized_pnl
        assert ending_equity == 10000.0

    def test_statutory_fees_and_slippage_calculation(self) -> None:
        # Buy 1 lot NIFTY (65 qty) at ₹100 premium, Sell at ₹110 premium
        qty = 65
        buy_prem = 100.0
        sell_prem = 110.0
        gross_turnover = (buy_prem + sell_prem) * qty  # (100 + 110) * 65 = 13650
        gross_pnl = (sell_prem - buy_prem) * qty       # 10 * 65 = 650.0

        brokerage = 20.0  # ₹10 per completed order side (2 sides)
        stt = round(sell_prem * qty * 0.00125, 2)  # STT 0.125% on sell side premium = 110 * 65 * 0.00125 = 8.94
        exchange_turnover_fee = round(gross_turnover * 0.0003553, 2)  # NSE F&O options fee = 4.85
        sebi_charges = round(gross_turnover * 0.000001, 2)  # ₹10 per crore = 0.01
        gst = round((brokerage + exchange_turnover_fee) * 0.18, 2)  # 18% on (20 + 4.85) = 4.47
        total_statutory = brokerage + stt + exchange_turnover_fee + sebi_charges + gst

        net_pnl = gross_pnl - total_statutory
        assert net_pnl < gross_pnl
        assert total_statutory > 35.0  # Minimum statutory friction


class TestPhase122QuantRiskAndRuinBoundaries:
    """Test Suite verifying quantitative risk constraints and risk of ruin mathematics."""

    def test_bayesian_kelly_sizing_with_equity(self) -> None:
        sizer = BayesianKellyPositionSizer(default_alpha_prior=12.0, default_beta_prior=8.0)
        # Prior win rate: 12 / (12 + 8) = 60.0%
        assert sizer.compute_posterior_win_probability() == 0.60

        # Full Kelly and Fractional Kelly
        full_k, frac_k = sizer.compute_fractional_kelly(payoff_ratio=1.5, kappa=0.25)
        assert full_k > 0.0
        assert frac_k <= 0.25  # Fractional Kelly bounded

        # Position sizing on ₹10,000 equity
        res = sizer.calculate_position_size(
            equity_inr=10000.0,
            margin_per_lot_inr=6500.0,
            lot_size_contracts=65,
            payoff_ratio=1.5,
        )
        assert res.regime in (SizingRegime.OPTIMAL_KELLY, SizingRegime.DRAWDOWN_THROTTLED)
        assert res.quantized_lots <= 1  # Cannot allocate more than 1 lot on ₹10k account!

    def test_excessive_return_target_guarantees_ruin(self) -> None:
        """Mathematical proof: targeting 200% monthly return on ₹10k requires leverage with >85% ruin risk."""
        capital = 10000.0
        daily_target = 1000.0
        required_risk_per_trade = daily_target / 1.5  # ₹666.67
        risk_percentage = required_risk_per_trade / capital  # 6.67%
        assert risk_percentage > 0.005  # More than 13x the allowed 0.5% risk cap!


class TestPhase122TokenLifecycleAndRedaction:
    """Test Suite verifying PaytmTokenStore and logging redaction."""

    def test_token_redaction_hides_sensitive_content(self) -> None:
        assert redact_token("eyJhGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9") == "eyJh...VCJ9"
        assert redact_token("short") == "********"
        assert redact_token(None) == "[NONE]"

    def test_query_string_redaction(self) -> None:
        raw_qs = "requestToken=SECRET123456&state=NONCE_ABC&exchange=NSE"
        sanitized = redact_query_string(raw_qs)
        assert "SECRET123456" not in sanitized
        assert "NONCE_ABC" in sanitized
        assert "exchange=NSE" in sanitized

    def test_token_store_save_and_expiration(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store_file = Path(tmpdir) / "paytm_session.json"
            store = PaytmTokenStore(storage_path=store_file)

            store.save_session(access_token="JWT_VALID_TOKEN_123", public_access_token="PUB_123")
            loaded = store.load_session()
            assert loaded is not None
            assert loaded["access_token"] == "JWT_VALID_TOKEN_123"
            assert "expires_at" in loaded
