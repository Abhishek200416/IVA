"""AGI 1.7 Verification Suite for Recency-Weighted Exponential Decay in Memory Retrieval.

Verifies:
1. Mathematical precision of score = confidence * exp(-lambda * (now - created_at) / 86400).
2. Categorical differentiation:
   - VERIFIED_FACT (lambda = 0.0): Zero decay over arbitrary elapsed time.
   - LESSON_LEARNED (lambda = 0.1): Half-life ~6.93 days.
   - TEMPORARY_OBSERVATION (lambda = 0.5): Half-life ~1.39 days, prunes stale noise.
3. Custom category decay rate overrides and min_score pruning.
4. Seamless integration with CentralizedLLMGateway context budgeting.
5. Absolute enforcement of fail-closed safety invariant: LIVE_ORDER_DISPATCH_ENABLED = False.
"""

from __future__ import annotations

import math
import time
from pathlib import Path
import pytest

from agents.AGI_1_7.engine.agi17.adapters.centralized_llm_gateway import (
    CentralizedLLMGateway,
)
from agents.AGI_1_7.engine.agi17.memory.omega_command_memory import OmegaCommandMemory
from agents.AGI_1_7.engine.agi17.memory.persistent_memory_subsystem import (
    DEFAULT_CATEGORY_DECAY_LAMBDA,
    MemoryCategory,
    PersistentMemorySubsystem,
    StructuredMemoryRecord,
    VerificationStatus,
)
from agents.AGI_1_7.engine.agi17.runtime.authoritative_brain_config import (
    AuthoritativeBrainConfig,
)


class TestMemoryRetrievalRecencyDecay:
    """Automated test suite verifying recency-weighted exponential decay."""

    @pytest.fixture(autouse=True)
    def setup_test_environment(self, tmp_path: Path):
        self.tmp_dir = tmp_path
        self.mem_core = OmegaCommandMemory(primary_dir=tmp_path / "memory")
        self.memory = PersistentMemorySubsystem(memory_core=self.mem_core)
        self.gateway = CentralizedLLMGateway(workspace_root=tmp_path, memory=self.mem_core)
        self.brain_config = AuthoritativeBrainConfig.get_instance()
        self.brain_config.load()

    def test_01_mathematical_precision_of_exponential_decay(self):
        """Validates exact numerical output of confidence * exp(-lambda * dt_days)."""
        now = time.time()
        record_fact = StructuredMemoryRecord(
            record_id="MEM-FACT-001",
            category=MemoryCategory.VERIFIED_FACT,
            layer=5,
            subject_key="router_invariant",
            content="Router latency must stay under 50ms.",
            confidence=1.0,
            verification_status=VerificationStatus.VERIFIED,
            created_at=now - 30 * 86400,  # 30 days ago
        )
        # lambda = 0.0 -> no decay
        score_fact = record_fact.compute_decayed_confidence(now=now)
        assert score_fact == 1.0

        # lambda = 0.1 -> half life is ln(2)/0.1 ~= 6.93147 days
        half_life_days = math.log(2.0) / 0.1
        record_lesson = StructuredMemoryRecord(
            record_id="MEM-LESS-001",
            category=MemoryCategory.LESSON_LEARNED,
            layer=6,
            subject_key="backtest_isolation",
            content="Always mock network sockets during unit tests.",
            confidence=1.0,
            verification_status=VerificationStatus.VERIFIED,
            created_at=now - half_life_days * 86400,
        )
        score_lesson = record_lesson.compute_decayed_confidence(now=now)
        assert pytest.approx(score_lesson, abs=1e-4) == 0.5000

        # lambda = 0.5 -> after 7 days: exp(-0.5 * 7) = exp(-3.5) ~= 0.030197
        record_obs = StructuredMemoryRecord(
            record_id="MEM-OBS-001",
            category=MemoryCategory.TEMPORARY_OBSERVATION,
            layer=1,
            subject_key="cpu_spike",
            content="CPU utilization temporarily hit 88%.",
            confidence=0.8,
            verification_status=VerificationStatus.VERIFIED,
            created_at=now - 7 * 86400,
        )
        score_obs = record_obs.compute_decayed_confidence(now=now)
        expected_obs = 0.8 * math.exp(-0.5 * 7.0)
        assert pytest.approx(score_obs, abs=1e-4) == round(expected_obs, 6)
        assert score_obs < 0.03

    def test_02_retrieve_records_categorical_re_ranking(self):
        """Verifies that an older verified fact cleanly outranks a stale temporary observation."""
        now = time.time()

        # 1. 30-day-old verified fact
        fact = self.memory.store_record(
            category=MemoryCategory.VERIFIED_FACT,
            subject_key="execution_safety_policy",
            content="Fail-closed order dispatch invariant must be maintained.",
            confidence=1.0,
        )
        # Manually backdate created_at in core SQLite DB for simulation
        with self.mem_core._lock:
            conn = self.mem_core._connect()
            try:
                conn.execute(
                    "UPDATE memory_entries SET created_at = ?, updated_at = ? WHERE entry_id = ?",
                    (now - 30 * 86400, now - 30 * 86400, fact.record_id),
                )
                conn.commit()
            finally:
                conn.close()

        # 2. 7-day-old temporary observation (conf = 0.9)
        obs_old = self.memory.store_record(
            category=MemoryCategory.TEMPORARY_OBSERVATION,
            subject_key="stale_telemetry",
            content="Temporary buffer warning on worker 3.",
            confidence=0.9,
        )
        with self.mem_core._lock:
            conn = self.mem_core._connect()
            try:
                conn.execute(
                    "UPDATE memory_entries SET created_at = ?, updated_at = ? WHERE entry_id = ?",
                    (now - 7 * 86400, now - 7 * 86400, obs_old.record_id),
                )
                conn.commit()
            finally:
                conn.close()

        # 3. 2-day-old lesson learned (conf = 0.95)
        lesson = self.memory.store_record(
            category=MemoryCategory.LESSON_LEARNED,
            subject_key="connection_timeout_pattern",
            content="Set connect timeout to 3000ms for resilient socket reconnection.",
            confidence=0.95,
        )
        with self.mem_core._lock:
            conn = self.mem_core._connect()
            try:
                conn.execute(
                    "UPDATE memory_entries SET created_at = ?, updated_at = ? WHERE entry_id = ?",
                    (now - 2 * 86400, now - 2 * 86400, lesson.record_id),
                )
                conn.commit()
            finally:
                conn.close()

        # Retrieve across all active records
        retrieved = self.memory.retrieve_records(apply_decay=True, limit=10)
        assert len(retrieved) >= 3

        # Rank 1 must be VERIFIED_FACT (score = 1.0)
        assert retrieved[0].category == MemoryCategory.VERIFIED_FACT
        assert retrieved[0].subject_key == "execution_safety_policy"
        assert retrieved[0].decayed_confidence == 1.0

        # Rank 2 must be LESSON_LEARNED (score = 0.95 * exp(-0.1 * 2) ~= 0.7779)
        assert retrieved[1].category == MemoryCategory.LESSON_LEARNED
        assert retrieved[1].subject_key == "connection_timeout_pattern"
        assert 0.70 < retrieved[1].decayed_confidence < 0.85

        # Rank 3 must be the decayed TEMPORARY_OBSERVATION (score = 0.9 * exp(-0.5 * 7) ~= 0.027)
        assert retrieved[2].category == MemoryCategory.TEMPORARY_OBSERVATION
        assert retrieved[2].decayed_confidence < 0.05

    def test_03_min_score_pruning_and_custom_decay_rates(self):
        """Verifies custom category decay rate dictionary and min_score threshold pruning."""
        now = time.time()
        obs = self.memory.store_record(
            category=MemoryCategory.TEMPORARY_OBSERVATION,
            subject_key="noise_metric",
            content="Minor packet jitter 3ms.",
            confidence=0.8,
        )
        with self.mem_core._lock:
            conn = self.mem_core._connect()
            try:
                conn.execute(
                    "UPDATE memory_entries SET created_at = ?, updated_at = ? WHERE entry_id = ?",
                    (now - 5 * 86400, now - 5 * 86400, obs.record_id),
                )
                conn.commit()
            finally:
                conn.close()

        # At 5 days with lambda=0.5, score ~= 0.8 * exp(-2.5) ~= 0.065
        # With min_score=0.1, it must be excluded
        pruned = self.memory.retrieve_records(
            category=MemoryCategory.TEMPORARY_OBSERVATION,
            min_score=0.1,
        )
        assert len(pruned) == 0

        # With min_score=0.01, it must be included
        included = self.memory.retrieve_records(
            category=MemoryCategory.TEMPORARY_OBSERVATION,
            min_score=0.01,
        )
        assert len(included) == 1
        assert included[0].subject_key == "noise_metric"

        # Custom lambda override: set TEMPORARY_OBSERVATION lambda to 0.0
        custom_rates = {MemoryCategory.TEMPORARY_OBSERVATION: 0.0}
        custom_retrieved = self.memory.retrieve_records(
            category=MemoryCategory.TEMPORARY_OBSERVATION,
            category_decay_rates=custom_rates,
            min_score=0.5,
        )
        assert len(custom_retrieved) == 1
        assert custom_retrieved[0].decayed_confidence == 0.8

    def test_04_apply_decay_false_preserves_raw_confidence(self):
        """Verifies that apply_decay=False bypasses time decay."""
        now = time.time()
        obs = self.memory.store_record(
            category=MemoryCategory.TEMPORARY_OBSERVATION,
            subject_key="raw_test_metric",
            content="Telemetry test value.",
            confidence=0.75,
        )
        with self.mem_core._lock:
            conn = self.mem_core._connect()
            try:
                conn.execute(
                    "UPDATE memory_entries SET created_at = ?, updated_at = ? WHERE entry_id = ?",
                    (now - 14 * 86400, now - 14 * 86400, obs.record_id),
                )
                conn.commit()
            finally:
                conn.close()

        records = self.memory.retrieve_records(
            category=MemoryCategory.TEMPORARY_OBSERVATION,
            apply_decay=False,
        )
        assert len(records) == 1
        assert records[0].decayed_confidence == 0.75

    def test_05_centralized_llm_gateway_budgeted_memory_integration(self):
        """Verifies CentralizedLLMGateway.get_budgeted_memory_context with recency decay."""
        now = time.time()
        # High value fact
        self.memory.store_record(
            category=MemoryCategory.VERIFIED_FACT,
            subject_key="rms_capital_limit",
            content="Max single order margin allocation is capped at 10% of portfolio net liquidating value.",
            confidence=1.0,
        )
        # Stale noise
        noise = self.memory.store_record(
            category=MemoryCategory.TEMPORARY_OBSERVATION,
            subject_key="old_ping",
            content="Ping to gateway server took 14ms.",
            confidence=0.5,
        )
        with self.mem_core._lock:
            conn = self.mem_core._connect()
            try:
                conn.execute(
                    "UPDATE memory_entries SET created_at = ?, updated_at = ? WHERE entry_id = ?",
                    (now - 10 * 86400, now - 10 * 86400, noise.record_id),
                )
                conn.commit()
            finally:
                conn.close()

        context_block = self.gateway.get_budgeted_memory_context(
            task_id="TASK-GATEWAY-DECAY-TEST",
            memory_subsystem=self.memory,
            max_tokens=250,
        )
        assert "LIVE_ORDER_DISPATCH_ENABLED=False" in context_block
        assert "rms_capital_limit" in context_block
        assert "10% of portfolio net liquidating value" in context_block

    def test_06_safety_invariant_live_order_dispatch_locked(self):
        """Verifies safety invariant LIVE_ORDER_DISPATCH_ENABLED = False fail-closed."""
        assert self.brain_config.operating_policy.live_order_dispatch_enabled is False
        assert self.brain_config.operating_policy.financial_execution_locked is True
        assert self.brain_config.core_identity.fail_closed_invariant is True
