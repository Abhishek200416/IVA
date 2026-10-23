"""AGI 1.7 Structured Research Record & News Provenance Engine (Phase 12.4).

Provides:
1. StructuredResearchRecord: Separates factual source evidence from agent interpretations.
2. Official Source Hierarchy: Prioritizes regulatory (SEBI, RBI) and exchange (NSE, BSE) sources.
3. Content-Addressed Deduplication: Identifies identical documents via SHA-256 hash.
4. Unverified News Gating: Prevents sensational headlines from directly authorizing trading entries.
5. Inaccessible / Outdated Source Disclosures.
"""

from __future__ import annotations

import datetime
from enum import Enum
import hashlib
import json
import logging
from pathlib import Path
import time
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger("ResearchProvenance")

IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30), name="IST")


class VerificationState(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    VERIFIED_OFFICIAL_EXCHANGE = "VERIFIED_OFFICIAL_EXCHANGE"  # NSE / BSE circulars
    VERIFIED_REGULATORY = "VERIFIED_REGULATORY"                # SEBI / RBI
    VERIFIED_FINANCIAL_PRESS = "VERIFIED_FINANCIAL_PRESS"      # Reuters / Bloomberg / ET
    INACCESSIBLE = "INACCESSIBLE"                              # 404 / 403 / paywall
    OUTDATED = "OUTDATED"                                      # Beyond staleness TTL


class SourceAuthorityLevel(int, Enum):
    STATUTORY_REGULATOR = 1   # SEBI, RBI, Ministry of Finance
    EXCHANGE_OFFICIAL = 2     # NSE, BSE, MCX
    PRIMARY_CORPORATE = 3     # Direct company filings, earnings calls
    FINANCIAL_MAINSTREAM = 4  # PTI, Bloomberg, Reuters, ET Markets
    AGGREGATOR_SOCIAL = 5     # Blog posts, Twitter/X, unverified chat


class StructuredResearchRecord:
    """Rigorous research intelligence unit strictly distinguishing facts from agent bias."""

    def __init__(
        self,
        *,
        headline: str,
        publisher: str,
        source_url: str,
        factual_summary: str,
        extracted_facts: List[str],
        supporting_passages: List[str],
        agent_interpretation: str,
        author_agent: str,
        published_at: Optional[datetime.datetime] = None,
        retrieved_at: Optional[datetime.datetime] = None,
        relevant_instruments: Optional[List[str]] = None,
        relevant_themes: Optional[List[str]] = None,
        confidence: float = 0.85,
        verification_state: VerificationState = VerificationState.UNVERIFIED,
        authority_level: SourceAuthorityLevel = SourceAuthorityLevel.FINANCIAL_MAINSTREAM,
        staleness_ttl_hours: float = 24.0,
    ):
        now_ist = datetime.datetime.now(IST)
        self.headline = headline.strip()
        self.publisher = publisher.strip()
        self.source_url = source_url.strip()
        self.factual_summary = factual_summary.strip()
        self.extracted_facts = list(extracted_facts)
        self.supporting_passages = list(supporting_passages)
        self.agent_interpretation = agent_interpretation.strip()
        self.author_agent = author_agent.strip()
        self.published_at = published_at or now_ist
        self.retrieved_at = retrieved_at or now_ist
        self.relevant_instruments = list(relevant_instruments or [])
        self.relevant_themes = list(relevant_themes or [])
        self.confidence = float(min(1.0, max(0.0, confidence)))
        self.verification_state = verification_state
        self.authority_level = authority_level
        self.staleness_ttl_hours = staleness_ttl_hours

        # Compute deterministic content hash
        hash_payload = f"{self.headline}:{self.publisher}:{self.source_url}:{self.factual_summary}"
        self.document_hash = hashlib.sha256(hash_payload.encode("utf-8")).hexdigest()
        self.record_id = f"RES-{self.document_hash[:16]}"

    @property
    def is_stale(self) -> bool:
        """Evaluates whether the research record exceeds its TTL."""
        now_ist = datetime.datetime.now(IST)
        age_hours = (now_ist - self.retrieved_at).total_seconds() / 3600.0
        return age_hours > self.staleness_ttl_hours

    def evaluate_evidence_eligibility(self) -> Tuple[bool, Optional[str]]:
        """Evidence credibility gate:
        Determines whether research evidence is verified and eligible for strategy analysis.
        INVARIANT: Evidence alone NEVER authorizes trade execution. It serves strictly as contextual input.
        """
        if self.verification_state == VerificationState.UNVERIFIED:
            return False, "Unverified research source is ineligible for strategy consideration"
        if self.verification_state in (VerificationState.INACCESSIBLE, VerificationState.OUTDATED):
            return False, f"Research source is {self.verification_state.value}"
        if self.is_stale:
            return False, f"Research record is stale (age exceeds {self.staleness_ttl_hours}h TTL)"
        if self.authority_level.value > SourceAuthorityLevel.PRIMARY_CORPORATE.value:
            return False, "Secondary news press requires corroborating primary exchange/regulatory evidence"
        return True, None

    def can_authorize_trade(self) -> Tuple[bool, Optional[str]]:
        """Trading safety gate (Phase 12.4.1):
        Research credibility NEVER translates directly into trade authorization.
        Strict separation:
        Verified source -> validated factual record -> strategy-specific analysis -> candidate signal -> independent risk validation -> paper approval or NO_TRADE.
        """
        if self.verification_state == VerificationState.UNVERIFIED:
            return False, "Unverified research source cannot authorize trade entry"
        if self.verification_state in (VerificationState.INACCESSIBLE, VerificationState.OUTDATED):
            return False, f"Research source is {self.verification_state.value}"
        return (
            False,
            "SAFETY INVARIANT (Phase 12.4.1): Research evidence alone cannot directly authorize trade execution; "
            "requires strategy quantitative signal and independent pre-trade RMS approval",
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "record_id": self.record_id,
            "document_hash": self.document_hash,
            "headline": self.headline,
            "publisher": self.publisher,
            "source_url": self.source_url,
            "published_at_iso": self.published_at.isoformat(),
            "retrieved_at_iso": self.retrieved_at.isoformat(),
            "is_stale": self.is_stale,
            "relevant_instruments": self.relevant_instruments,
            "relevant_themes": self.relevant_themes,
            "factual_summary": self.factual_summary,
            "extracted_facts": self.extracted_facts,
            "supporting_passages": self.supporting_passages,
            "agent_interpretation": self.agent_interpretation,
            "author_agent": self.author_agent,
            "confidence": round(self.confidence, 3),
            "verification_state": self.verification_state.value,
            "authority_level": self.authority_level.name,
            "staleness_ttl_hours": self.staleness_ttl_hours,
        }


class ResearchProvenanceRepository:
    """Manages deduplication, authority validation, and persistence of market intelligence."""

    def __init__(self, storage_dir: Optional[Path] = None):
        self.storage_dir = storage_dir or Path(__file__).resolve().parent.parent / "runtime_storage" / "research"
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.records_file = self.storage_dir / "research_records.jsonl"
        self._records_by_hash: Dict[str, StructuredResearchRecord] = {}
        self._records_by_id: Dict[str, StructuredResearchRecord] = {}
        self._load_records()

    def _load_records(self) -> None:
        if self.records_file.exists():
            try:
                for line in self.records_file.read_text(encoding="utf-8").splitlines():
                    if not line.strip():
                        continue
                    data = json.loads(line)
                    # Reconstruct record
                    rec = StructuredResearchRecord(
                        headline=data["headline"],
                        publisher=data["publisher"],
                        source_url=data["source_url"],
                        factual_summary=data["factual_summary"],
                        extracted_facts=data.get("extracted_facts", []),
                        supporting_passages=data.get("supporting_passages", []),
                        agent_interpretation=data.get("agent_interpretation", ""),
                        author_agent=data.get("author_agent", "Emily"),
                        confidence=data.get("confidence", 0.85),
                        verification_state=VerificationState(data.get("verification_state", "UNVERIFIED")),
                        authority_level=SourceAuthorityLevel[data.get("authority_level", "FINANCIAL_MAINSTREAM")],
                    )
                    self._records_by_hash[rec.document_hash] = rec
                    self._records_by_id[rec.record_id] = rec
            except Exception as exc:
                logger.warning(f"Error loading research records: {exc}")

    def add_record(self, record: StructuredResearchRecord) -> Tuple[StructuredResearchRecord, bool]:
        """Adds a research record with deduplication. Returns (record, is_new)."""
        if record.document_hash in self._records_by_hash:
            return self._records_by_hash[record.document_hash], False

        self._records_by_hash[record.document_hash] = record
        self._records_by_id[record.record_id] = record

        # Append to persistent JSONL
        try:
            with open(self.records_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(record.to_dict()) + "\n")
        except Exception as exc:
            logger.warning(f"Failed to persist research record: {exc}")

        return record, True

    def get_by_id(self, record_id: str) -> Optional[StructuredResearchRecord]:
        return self._records_by_id.get(record_id)

    def query_by_instrument(self, instrument: str) -> List[StructuredResearchRecord]:
        return [
            r for r in self._records_by_id.values()
            if instrument in r.relevant_instruments
        ]
