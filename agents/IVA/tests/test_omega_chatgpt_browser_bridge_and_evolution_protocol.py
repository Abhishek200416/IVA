"""AGI 1.7 Phase 28 Verification Suite: Autonomous Self-Evolution, 4-Question Questionnaire & ChatGPT Browser Bridge.

Verifies:
1. Deterministic intent classification across all evolution phrasing variants (including voice speech transcription typos like '24 paise').
2. Complete 4-question configuration questionnaire generation and parameter validation.
3. ChatGPT browser bridge state transitions: UNINITIALIZED -> AWAITING_OPERATOR_LOGIN -> LOGGED_IN -> READY_FOR_INQUIRY -> RESPONSE_CAPTURED.
4. Intelligent login status verification (detecting login walls vs authenticated prompt textareas).
5. Closed-loop cycle execution and dual-section reporting ('What Was Improved' and 'What Can Still Be Improved Next').
6. Fail-closed safety invariant verification: LIVE_ORDER_DISPATCH_ENABLED = False.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
import pytest

from agents.AGI_1_7.engine.agi17.browser.chatgpt_browser_bridge import (
    ChatGPTBrowserBridge,
    ChatGPTBridgeState,
    ChatGPTInquiryRecord,
)
from agents.AGI_1_7.engine.agi17.orchestration.autonomous_evolution_protocol import (
    AutonomousEvolutionProtocol,
    EvolutionConfiguration,
    CycleReport,
)
from agents.AGI_1_7.engine.agi17.runtime.command_router import (
    CommandRouter,
    CommandIntent,
)
from agents.AGI_1_7.engine.agi17.runtime.authoritative_brain_config import (
    AuthoritativeBrainConfig,
)


class TestAutonomousEvolutionAndChatGPTBridge:
    """Automated test suite verifying Phase 28 self-evolution and browser bridge protocol."""

    @pytest.fixture(autouse=True)
    def setup_test_environment(self, tmp_path: Path):
        self.tmp_dir = tmp_path
        self.router = CommandRouter(storage_dir=tmp_path / "runtime_storage")
        self.protocol = AutonomousEvolutionProtocol(workspace_root=tmp_path)
        self.bridge = ChatGPTBrowserBridge(
            chatgpt_url="https://chatgpt.com",
            storage_dir=tmp_path / "scratch",
        )
        self.brain_config = AuthoritativeBrainConfig.get_instance()
        self.brain_config.load()

    def test_01_command_router_evolution_intent_classification(self):
        """Verifies fast deterministic routing for all evolution phrases and voice transcription typos."""
        evolution_prompts = [
            "start evolving 24/7",
            "start evolving 20% 24 by 7",
            "start evolving my 24 paise",  # voice transcription typo test
            "continue to start evolving",
            "start evolving",
            "evolve yourself",
            "start improving yourself 24/7 in chat",
            "start improving yourself 20% 24 by 7",
        ]
        for prompt in evolution_prompts:
            intent = self.router.classify_intent(prompt)
            assert intent == CommandIntent.START_EVOLUTION_INTERVIEW, f"Failed on prompt: {prompt}"

        # Ensure handle_command returns EVOLUTION_QUESTIONNAIRE action
        res = self.router.handle_command("start evolving 24/7")
        assert res["intent"] == CommandIntent.START_EVOLUTION_INTERVIEW.value
        assert res["action"] == "EVOLUTION_QUESTIONNAIRE"
        assert "Autonomous Self-Evolution Setup" in res["dialog"]
        assert res["stage"] == "QUESTIONNAIRE"

    def test_02_evolution_protocol_startup_questionnaire_structure(self):
        """Validates that the questionnaire rigorously addresses all 4 operator dimensions."""
        quest = self.protocol.generate_startup_questionnaire()
        dialog = quest["dialog"]
        config = quest["config"]

        # Dimension 1: Work Cadence & Limitations
        assert "1. Work Cadence & Limitations Acknowledgement" in dialog
        assert "Software & API Limitations:" in dialog
        assert "Hosted LLM API:" in dialog
        assert "Local-First Execution:" in dialog
        assert "LIVE_ORDER_DISPATCH_ENABLED = False" in dialog

        # Dimension 2: Web Research & Literature
        assert "2. Web Research & Literature Scope" in dialog
        assert "arXiv" in dialog

        # Dimension 3: ChatGPT Browser Bridge
        assert "3. ChatGPT Desktop Browser Bridge" in dialog
        assert "AWAITING_OPERATOR_LOGIN" in dialog
        assert "chatgpt.com" in dialog

        # Dimension 4: Continuous Closed-Loop Cadence & Reporting
        assert "4. Continuous Closed-Loop Cadence" in dialog
        assert "What Was Improved" in dialog
        assert "What Can Still Be Improved Next" in dialog

        assert config["work_24_7"] is True
        assert config["chatgpt_browser_bridge_enabled"] is True

    def test_03_chatgpt_browser_bridge_state_machine_and_login_detection(self):
        """Tests the browser bridge handshake, login wall detection, and login verification."""
        # 1. Initial State
        assert self.bridge.state == ChatGPTBridgeState.UNINITIALIZED

        # 2. Handshake Initiation -> AWAITING_OPERATOR_LOGIN
        handshake = self.bridge.initiate_browser_handshake()
        assert handshake["status"] == "AWAITING_OPERATOR_LOGIN"
        assert self.bridge.state == ChatGPTBridgeState.AWAITING_OPERATOR_LOGIN
        assert handshake["can_query"] is False

        # 3. Simulate page with login wall (Not yet logged in)
        login_wall_html = """
        <html>
            <button>Log in</button>
            <button>Sign up</button>
            <h1>Welcome back to ChatGPT</h1>
        </html>
        """
        is_logged_in, msg = self.bridge.verify_login_status(dom_html=login_wall_html)
        assert is_logged_in is False
        assert self.bridge.state == ChatGPTBridgeState.AWAITING_OPERATOR_LOGIN
        assert "Operator authentication in progress" in msg

        # 4. Simulate page after user logs in (Active prompt textarea appears)
        authenticated_html = """
        <html>
            <div class="user-menu">My Account</div>
            <textarea id="prompt-textarea" placeholder="Message ChatGPT..."></textarea>
        </html>
        """
        is_logged_in, msg = self.bridge.verify_login_status(dom_html=authenticated_html)
        assert is_logged_in is True
        assert self.bridge.state == ChatGPTBridgeState.LOGGED_IN
        assert "Operator login confirmed" in msg

        # 5. Transition to Ready
        ready = self.bridge.transition_to_ready()
        assert ready["status"] == "READY_FOR_INQUIRY"
        assert ready["can_query"] is True

    def test_04_chatgpt_inquiry_generation_and_response_parsing(self):
        """Tests automated research inquiry formatting and response extraction."""
        # Formulate inquiry
        inquiry = self.bridge.prepare_research_inquiry(
            topic="SABR Volatility Smile Calibration",
            context="Current error is 0.0018 MSE on NIFTY 50 options.",
        )
        assert "SABR Volatility Smile Calibration" in inquiry.prompt
        assert "Theoretical formulation & mathematical grounding" in inquiry.prompt
        assert "Production-grade Python code implementation" in inquiry.prompt
        assert inquiry.status == "PREPARED"

        # Record mock ChatGPT response
        mock_response = """
        Here is the state-of-the-art Hagan SABR formula calibration:
        
        ```python
        import numpy as np
        def sabr_volatility(f, k, t, alpha, beta, rho, nu):
            return alpha * (1.0 + 0.25 * rho * nu)
        ```
        
        Key Architectural Guidelines:
        - Use Levenberg-Marquardt with bounds: alpha > 0, nu >= 0, -1 <= rho <= 1.
        - Enforce Feller condition on volatility variance: 2*kappa*theta > sigma^2.
        - Verify no-arbitrage butterfly spread density condition d2C/dK2 >= 0.
        """
        res = self.bridge.record_chatgpt_response(
            inquiry_id=inquiry.inquiry_id,
            response_text=mock_response,
            duration_sec=3.4,
        )
        assert res["status"] == "COMPLETED"
        assert res["code_blocks_count"] == 1
        assert res["insights_count"] >= 3
        assert self.bridge.state == ChatGPTBridgeState.RESPONSE_CAPTURED

    def test_05_operator_custom_url_and_evolution_cycle_execution(self):
        """Tests operator customization and single evolution cycle execution with dual reporting."""
        # Test custom URL input
        custom_chat_url = "https://chatgpt.com/c/6789abcd-1234-5678-9abc-def012345678"
        update_res = self.protocol.process_operator_response(custom_chat_url)
        assert self.protocol.config.chatgpt_chat_url == custom_chat_url
        assert self.protocol.chatgpt_bridge.chatgpt_url == custom_chat_url

        # Test starting workflow
        start_res = self.protocol.process_operator_response("1")
        assert start_res["status"] == "STARTED"
        assert self.protocol._stage == "RUNNING"
        assert start_res["current_cycle"] == 1

        # Execute a complete cycle
        what_improved = [
            "Implemented SABR volatility calibration with Levenberg-Marquardt bounds.",
            "Added Feller condition check to stochastic volatility engine.",
        ]
        what_next = [
            "Integrate Hawkes process order flow clustering into intraday decision engine.",
            "Run 100-sample Monte Carlo stress test against sudden liquidity drops.",
        ]
        test_stats = {"passed": 34, "total": 34, "pass_rate": 1.0}

        report = self.protocol.execute_single_evolution_cycle(
            what_improved=what_improved,
            what_next=what_next,
            test_results=test_stats,
        )

        assert report.cycle_number == 2
        assert len(report.what_was_improved) == 2
        assert len(report.what_can_be_improved_next) == 2
        assert report.safety_invariant_verified is True

        chat_msg = report.format_chat_message()
        assert "Evolution Cycle #2 Completed" in chat_msg
        assert "What Has Been Improved:" in chat_msg
        assert "What Can Still Be Improved Next:" in chat_msg
        assert "LIVE_ORDER_DISPATCH_ENABLED = False" in chat_msg

    def test_06_safety_invariant_strict_enforcement(self):
        """Verifies fail-closed execution invariant across authoritative config and router."""
        assert self.brain_config.operating_policy.live_order_dispatch_enabled is False
        assert self.brain_config.operating_policy.financial_execution_locked is True

        # Router must strictly block any attempt to dispatch live trades
        gate_res = self.router.handle_command("dispatch live trade to broker")
        assert gate_res["permissible"] is False
        assert gate_res["action"] == "SAFETY_GATE_LOCKED"
        assert "LIVE_ORDER_DISPATCH_ENABLED = False" in gate_res["safety_invariant"]
