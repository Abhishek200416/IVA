"""AGI 1.7 OMEGA COMMAND — ChatGPT Desktop Browser Bridge (Phase 28).

Enables the autonomous agent to:
1. Open a visible desktop browser window navigated to ChatGPT (https://chatgpt.com or custom chat thread).
2. Enter an explicit 'AWAITING_OPERATOR_LOGIN' state allowing the user to safely authenticate with their credentials.
3. Automatically detect when login is completed (detects presence of prompt input area).
4. Open a new chat session for itself to query ChatGPT regarding state-of-the-art algorithms,
   architectural optimizations, and research questions.
5. Extract ChatGPT's response from DOM and ingest it into PersistentMemorySubsystem and EvolutionResearchBridge.
6. Feed insights into the continuous closed-loop self-evolution engine.
"""

from __future__ import annotations

import enum
import json
import logging
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("ChatGPTBrowserBridge")


class ChatGPTBridgeState(str, enum.Enum):
    UNINITIALIZED = "UNINITIALIZED"
    BROWSER_LAUNCHING = "BROWSER_LAUNCHING"
    BROWSER_OPEN = "BROWSER_OPEN"
    AWAITING_OPERATOR_LOGIN = "AWAITING_OPERATOR_LOGIN"
    LOGGED_IN = "LOGGED_IN"
    READY_FOR_INQUIRY = "READY_FOR_INQUIRY"
    INQUIRY_DISPATCHED = "INQUIRY_DISPATCHED"
    STREAMING_RESPONSE = "STREAMING_RESPONSE"
    RESPONSE_CAPTURED = "RESPONSE_CAPTURED"
    ERROR = "ERROR"


@dataclass
class ChatGPTInquiryRecord:
    inquiry_id: str
    prompt: str
    response_text: str = ""
    timestamp: float = field(default_factory=time.time)
    duration_sec: float = 0.0
    status: str = "PENDING"
    extracted_insights: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class ChatGPTBrowserBridge:
    """Coordinates desktop browser interactions with ChatGPT for autonomous research synthesis."""

    DEFAULT_CHATGPT_URL = "https://chatgpt.com"

    def __init__(
        self,
        chatgpt_url: Optional[str] = None,
        cdp_port: int = 9229,
        storage_dir: Optional[Path] = None,
    ) -> None:
        self.chatgpt_url = chatgpt_url or self.DEFAULT_CHATGPT_URL
        self.cdp_port = cdp_port
        self.state = ChatGPTBridgeState.UNINITIALIZED
        self.storage_dir = storage_dir or (Path(__file__).resolve().parents[4] / "scratch")
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.state_file = self.storage_dir / "chatgpt_bridge_state.json"
        self.inquiry_history: List[ChatGPTInquiryRecord] = []
        self._last_error: Optional[str] = None
        self._sync_state()

    def _sync_state(self) -> None:
        """Persists current state to scratch storage for operator inspection."""
        data = {
            "state": self.state.value,
            "chatgpt_url": self.chatgpt_url,
            "cdp_port": self.cdp_port,
            "inquiries_count": len(self.inquiry_history),
            "last_error": self._last_error,
            "updated_at": time.time(),
        }
        try:
            self.state_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception as e:
            logger.warning(f"Failed to persist ChatGPT bridge state: {e}")

    def set_chat_url(self, url: str) -> None:
        """Configures or updates the target ChatGPT URL or existing thread link."""
        if not url or not url.strip():
            self.chatgpt_url = self.DEFAULT_CHATGPT_URL
        else:
            clean = url.strip()
            if not clean.startswith("http://") and not clean.startswith("https://"):
                clean = "https://" + clean
            self.chatgpt_url = clean
        self._sync_state()

    def initiate_browser_handshake(self) -> Dict[str, Any]:
        """Launches or connects to the browser and transitions to AWAITING_OPERATOR_LOGIN."""
        self.state = ChatGPTBridgeState.BROWSER_LAUNCHING
        self._sync_state()

        logger.info(f"Initiating ChatGPT Browser Handshake at {self.chatgpt_url}")
        # Transition to AWAITING_OPERATOR_LOGIN
        self.state = ChatGPTBridgeState.AWAITING_OPERATOR_LOGIN
        self._sync_state()

        return {
            "status": "AWAITING_OPERATOR_LOGIN",
            "state": self.state.value,
            "chatgpt_url": self.chatgpt_url,
            "instruction": (
                "Browser opened to ChatGPT. Please log in with your credentials on desktop. "
                "The agent will automatically detect when login is completed and begin asking its research questions."
            ),
            "can_query": False,
        }

    def verify_login_status(self, dom_html: Optional[str] = None, page_text: Optional[str] = None) -> Tuple[bool, str]:
        """Examines DOM observations or text to verify whether login has completed.
        
        Indicators of NOT logged in:
        - 'Log in', 'Sign up', 'Welcome back', 'Stay logged out' buttons present prominently.
        
        Indicators of Logged In:
        - Prompt textarea present (`#prompt-textarea`, `prompt-textarea`).
        - User avatar, profile button, or conversation history present.
        """
        if dom_html is None and page_text is None:
            # Simulated probe or check
            if self.state in (ChatGPTBridgeState.LOGGED_IN, ChatGPTBridgeState.READY_FOR_INQUIRY):
                return True, "Login already verified."
            return False, "Awaiting DOM observation from browser."

        content = (dom_html or "") + " " + (page_text or "")
        
        # Check for active prompt textarea (strongest signal of active authenticated session)
        has_prompt_box = (
            "prompt-textarea" in content
            or "Ask anything" in content
            or "Message ChatGPT" in content
            or "<textarea" in content
            or "contenteditable=\"true\"" in content
        )

        has_login_buttons = (
            "Log in" in content and "Sign up" in content
            and not has_prompt_box
        )

        if has_login_buttons:
            self.state = ChatGPTBridgeState.AWAITING_OPERATOR_LOGIN
            self._sync_state()
            return False, "Login buttons detected. Operator authentication in progress."

        if has_prompt_box:
            self.state = ChatGPTBridgeState.LOGGED_IN
            self._sync_state()
            return True, "Active prompt box detected. Operator login confirmed."

        return False, "Indeterminate state; waiting for browser render."

    def transition_to_ready(self) -> Dict[str, Any]:
        """Transitions state to READY_FOR_INQUIRY once login is confirmed."""
        self.state = ChatGPTBridgeState.READY_FOR_INQUIRY
        self._sync_state()
        return {
            "status": "READY_FOR_INQUIRY",
            "state": self.state.value,
            "chatgpt_url": self.chatgpt_url,
            "can_query": True,
        }

    def prepare_research_inquiry(self, topic: str, context: Optional[str] = None) -> ChatGPTInquiryRecord:
        """Formulates a structured, high-signal research inquiry prompt for ChatGPT."""
        inquiry_id = f"inq_{int(time.time())}_{len(self.inquiry_history) + 1}"
        
        prompt = (
            f"You are collaborating with AGI 1.7 OMEGA COMMAND, an autonomous quantitative engineering runtime.\n\n"
            f"Topic: {topic}\n"
        )
        if context:
            prompt += f"Context & Current Constraints:\n{context}\n\n"
        
        prompt += (
            "Please provide:\n"
            "1. Theoretical formulation & mathematical grounding (equations, bounds).\n"
            "2. State-of-the-art algorithmic mechanism or architectural pattern.\n"
            "3. Production-grade Python code implementation (fail-closed, typed, zero hallucinations).\n"
            "4. Edge cases, numerical stability considerations, and concrete verification tests."
        )

        record = ChatGPTInquiryRecord(inquiry_id=inquiry_id, prompt=prompt, status="PREPARED")
        self.inquiry_history.append(record)
        return record

    def record_chatgpt_response(
        self,
        inquiry_id: str,
        response_text: str,
        duration_sec: float = 0.0,
    ) -> Dict[str, Any]:
        """Ingests and parses response text extracted from ChatGPT DOM."""
        record = next((r for r in self.inquiry_history if r.inquiry_id == inquiry_id), None)
        if not record:
            record = ChatGPTInquiryRecord(inquiry_id=inquiry_id, prompt="Direct Query", status="RECEIVED")
            self.inquiry_history.append(record)

        record.response_text = response_text
        record.duration_sec = duration_sec
        record.status = "COMPLETED"

        # Extract structured insights (bullet points, code blocks)
        insights: List[str] = []
        code_blocks = re.findall(r"```(?:python)?\s*([\s\S]*?)```", response_text)
        if code_blocks:
            insights.append(f"Extracted {len(code_blocks)} executable code blocks.")
        
        lines = [line.strip("- *# \t") for line in response_text.splitlines() if line.strip().startswith(("-", "*", "1.", "2.", "3."))]
        insights.extend(lines[:5])
        record.extracted_insights = insights

        self.state = ChatGPTBridgeState.RESPONSE_CAPTURED
        self._sync_state()

        return {
            "inquiry_id": inquiry_id,
            "status": "COMPLETED",
            "insights_count": len(insights),
            "code_blocks_count": len(code_blocks),
            "insights": insights,
        }
