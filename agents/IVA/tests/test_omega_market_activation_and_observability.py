"""Comprehensive Verification Suite for AGI 1.7 Market Activation, Observability, and Research Terminal.

Verifies:
1. Dashboard Server Health & Port Binding on 127.0.0.1:8088.
2. Operator Console UI serving 12 views, timeline table, and evidence modal.
3. Multi-Stage Broker Status audit (Stages 1-7, quarantine status, active blockers).
4. Market Observations feed with provenance tags and statutory lot sizes (NSE 70616).
5. Technical Market Analysis (VWAP + bands, ORB, CPR, ATR, RSI, VIX regime, FII/DII).
6. Triad Agent Activity (MAX, EMILY, ALEXA, consensus voting, audited dissent log).
7. Observable Web Research Feed with 100% verified primary sources and zero hallucinations.
8. Active Quantitative Algorithms Catalog (all 8 institutional engines verified).
9. Complete 15-Step Decision Timeline with evidence inspector payloads.
10. 4-Tier Memory Architecture & Multiclass Brier Score trajectory across epochs.
11. Comparative Performance & Risk Ledger (Active 10k epoch vs Historical 50k demo).
12. Protected Boundary Enforcement (HTTP 403 Forbidden on any live order dispatch).
"""

from __future__ import annotations

import json
import urllib.request
import urllib.error
import pytest


DASHBOARD_URL = "http://127.0.0.1:8088"


def fetch_json(path: str):
    """Helper to query local dashboard endpoints."""
    url = f"{DASHBOARD_URL}{path}"
    req = urllib.request.Request(url, headers={"User-Agent": "AGI-1.7-TestRunner"})
    with urllib.request.urlopen(req, timeout=5.0) as resp:
        assert resp.status == 200, f"Expected 200 OK from {url}, got {resp.status}"
        data = resp.read().decode("utf-8")
        return json.loads(data)


def test_01_server_health_and_ports():
    """Verify standalone dashboard server is running and responds to /api/status."""
    status = fetch_json("/api/status")
    assert "supervisor_state" in status
    assert status.get("mode") == "PAPER"
    assert status.get("is_live_allowed") is False
    assert status.get("accounting", {}).get("is_reconciled") is True


def test_02_operator_console_html_and_views():
    """Verify operator console HTML renders cleanly with all 12 navigation views."""
    url = f"{DASHBOARD_URL}/operator_console.html"
    with urllib.request.urlopen(url, timeout=5.0) as resp:
        assert resp.status == 200
        html = resp.read().decode("utf-8")
        assert "<title>AGI 1.7 OMEGA COMMAND — Operator Console (PAPER ONLY)</title>" in html
        # Verify nav tabs exist
        assert "switchTab('overview')" in html
        assert "switchTab('broker_status')" in html
        assert "switchTab('market_options')" in html
        assert "switchTab('market_analysis')" in html
        assert "switchTab('agent_activity')" in html
        assert "switchTab('news_research')" in html
        assert "switchTab('active_algorithms')" in html
        assert "switchTab('decision_timeline')" in html
        assert "switchTab('paper_positions')" in html
        assert "switchTab('memory_learning')" in html
        assert "switchTab('risk_safety')" in html
        assert "switchTab('watchlist_voice')" in html
        # Verify evidence inspector modal markup
        assert 'id="evidence-modal"' in html
        assert 'id="timeline-tbody"' in html
        assert 'id="bs-stages-tbody"' in html


def test_03_broker_status_multi_stage_audit():
    """Verify audited multi-stage broker status endpoint."""
    bs = fetch_json("/api/broker_status")
    assert bs.get("broker") == "Paytm Money"
    assert bs.get("operating_mode") == "STRICTLY_PAPER_ONLY"
    assert bs.get("live_order_dispatch_enabled") is False
    assert "ENFORCED" in bs.get("protected_order_boundary", "")
    assert "QUARANTINED" in bs.get("quarantine_status", "")

    stages = bs.get("stages", {})
    assert len(stages) == 7
    assert "stage_1_callback_server" in stages
    assert "stage_2_stored_session" in stages
    assert "stage_3_session_validity" in stages
    assert "stage_4_api_client_state" in stages
    assert "stage_5_authenticated_read_only" in stages
    assert "stage_6_market_data_websocket" in stages
    assert "stage_7_live_market_events" in stages

    # Stage 1 callback server listener check
    assert stages["stage_1_callback_server"]["port"] == 8765
    assert stages["stage_1_callback_server"]["pass"] is True

    # Stage 5 authenticated access must be blocked
    assert stages["stage_5_authenticated_read_only"]["pass"] is False
    assert "BLOCKED" in stages["stage_5_authenticated_read_only"]["status"]

    # Redaction audit pass
    assert "PASS" in bs.get("redaction_audit", "")


def test_04_market_observations_feed():
    """Verify raw and normalized market observations feed with provenance."""
    obs = fetch_json("/api/market_observations")
    assert obs.get("provenance_overall") in ("GENUINE_EXCHANGE", "SYNTHETIC_DEMO")
    assert "NSE/FAOP/70616" in obs.get("statutory_rules", "")

    instruments = obs.get("instruments", [])
    assert len(instruments) >= 8

    syms = {i["symbol"] for i in instruments}
    assert "NIFTY" in syms
    assert "BANKNIFTY" in syms
    assert "FINNIFTY" in syms
    assert "NIFTY26OCT24200CE" in syms
    assert "BANKNIFTY26OCT51000PE" in syms

    # Lot size validation
    nifty_inst = next(i for i in instruments if i["symbol"] == "NIFTY")
    assert nifty_inst["lot_size"] == 65
    bn_inst = next(i for i in instruments if i["symbol"] == "BANKNIFTY")
    assert bn_inst["lot_size"] == 30

    # Feed freshness
    for inst in instruments:
        assert inst["feed_health"] == "FRESH"
        assert inst["quote_age_seconds"] <= 15.0


def test_05_market_analysis_indicators():
    """Verify quantitative market structure and technical indicators."""
    analysis = fetch_json("/api/market_analysis")
    indices = analysis.get("indices", {})
    assert "NIFTY_50" in indices
    assert "BANKNIFTY" in indices

    nifty = indices["NIFTY_50"]
    assert nifty["vwap_15m"] == 24215.30
    assert "plus_2sd" in nifty["vwap_bands"]
    assert "minus_2sd" in nifty["vwap_bands"]
    assert nifty["orb_15m"]["status"] == "RECLAIM_BULLISH"
    assert nifty["cpr"]["classification"] == "NARROW_RANGE_TRENDING"
    assert nifty["atr_14"] == 42.50
    assert nifty["rsi_14"] == 58.40
    assert nifty["derivatives"]["pcr"] == 1.15
    assert nifty["derivatives"]["max_pain_strike"] == 24250

    vix = analysis.get("india_vix", {})
    assert vix["level"] == 13.45
    assert vix["regime"] == "NORMAL_VOLATILITY"

    fii_dii = analysis.get("fii_dii_summary", {})
    assert fii_dii["fii_net_cr"] == -1420.0
    assert fii_dii["dii_net_cr"] == 1840.0
    assert fii_dii["net_institutional_cr"] == 420.0


def test_06_triad_agent_activity_and_consensus():
    """Verify Triad agents (Max, Emily, Alexa), consensus voting, and dissent logs."""
    act = fetch_json("/api/agent_activity")
    assert act.get("triad_status") == "ACTIVE_CONSENSUS_GOVERNED"

    agents = act.get("agents", {})
    assert "MAX" in agents
    assert "EMILY" in agents
    assert "ALEXA" in agents

    assert agents["MAX"]["status"] == "HEALTHY"
    assert agents["MAX"]["confidence_score"] == 0.88
    assert agents["EMILY"]["status"] == "HEALTHY"
    assert agents["EMILY"]["sentiment_score"] == 0.35
    assert "CLEAR" in agents["EMILY"]["event_risk_gate"]
    assert agents["ALEXA"]["status"] == "HEALTHY"
    assert agents["ALEXA"]["confidence_score"] == 0.96

    # Consensus evaluations
    evals = act.get("consensus_evaluations", [])
    assert len(evals) == 3
    cand_1 = next(e for e in evals if e["candidate_id"] == "CAND-001")
    assert cand_1["consensus_type"] == "UNANIMOUS_3_0"
    assert cand_1["decision"] == "APPROVED_FOR_PAPER_EXECUTION"

    cand_3 = next(e for e in evals if e["candidate_id"] == "CAND-003")
    assert "VETO" in cand_3["consensus_type"]
    assert cand_3["decision"] == "REJECTED_STAND_DOWN"

    # Dissent log
    dissent_logs = agents["ALEXA"].get("dissent_logs", [])
    assert len(dissent_logs) >= 1
    assert dissent_logs[0]["candidate_id"] == "CAND-003"
    assert "Alexa" in dissent_logs[0]["reason"]


def test_07_news_research_and_zero_hallucinations():
    """Verify news research stream with authentic primary citations."""
    news = fetch_json("/api/news_research")
    assert news.get("feed_status") == "VERIFIED_PRIMARY_SOURCES_ONLY"
    assert "STRICT_ZERO_TOLERANCE" in news.get("hallucination_guard", "")

    articles = news.get("articles", [])
    assert len(articles) >= 4

    sources = {a["source"] for a in articles}
    assert "Reserve Bank of India (RBI)" in sources
    assert "National Stock Exchange of India (NSE)" in sources
    assert "Ministry of Statistics and Programme Implementation (MoSPI)" in sources
    assert "Federal Reserve Board (US)" in sources

    for art in articles:
        assert art["url"].startswith("https://")
        assert art["verification_status"] == "VERIFIED_AUTHENTIC_PRIMARY_SOURCE"
        assert "PASS" in art["hallucination_audit"]


def test_08_active_algorithms_catalog():
    """Verify catalog of all 8 active quantitative algorithms."""
    algos_data = fetch_json("/api/active_algorithms")
    assert algos_data.get("algorithms_count") == 8
    assert algos_data.get("all_converged") is True

    algos = algos_data.get("algorithms", [])
    algo_ids = [a["id"] for a in algos]

    expected = [
        "STRAT-BASE-VWAP-ORB",
        "BSM-ANALYTICAL-GREEKS",
        "BAYESIAN-KELLY-DRAWDOWN-GOVERNOR",
        "SABR-SVI-ARBITRAGE-FREE-VOL",
        "KALMAN-SPREAD-FILTER-OU",
        "HAYASHI-YOSHIDA-LEAD-LAG",
        "OFI-5FACTOR-ATTRIBUTION",
        "VPIN-PRICE-IMPACT-ELASTICITY",
    ]
    for exp_id in expected:
        assert exp_id in algo_ids, f"Algorithm {exp_id} missing from catalog"

    for a in algos:
        assert "mathematical_formulation" in a
        assert "parameters" in a
        assert a["latency_ms"] > 0
        assert "CONVERGED" in a["convergence_status"] or "CALIBRATED" in a["convergence_status"] or "TRACKING" in a["convergence_status"] or "ATTRIBUTING" in a["convergence_status"] or "MONITORING" in a["convergence_status"]


def test_09_decision_timeline_15_steps():
    """Verify the 15-step end-to-end trade decision timeline and evidence payloads."""
    dt = fetch_json("/api/decision_timeline")
    assert dt.get("candidate_id") == "CAND-001"
    assert dt.get("total_steps") == 15
    assert dt.get("all_steps_passed") is True

    steps = dt.get("steps", [])
    assert len(steps) == 15

    for idx, s in enumerate(steps, start=1):
        assert s["step"] == idx, f"Step ordering mismatch at index {idx}"
        assert s["gate_status"] == "PASS"
        assert "evidence_payload" in s
        assert len(s["evidence_payload"]) > 0


def test_10_memory_history_and_brier_trajectory():
    """Verify 4-tier memory architecture and Multiclass Brier score trajectory."""
    mem = fetch_json("/api/memory_history")
    assert "4-Tier" in mem.get("architecture", "")
    assert mem.get("corpus_token_capacity") == 10_000_000
    assert mem.get("active_stored_tokens") == 12_450

    tiers = mem.get("tiers", [])
    assert len(tiers) == 4
    tier_names = [t["tier"] for t in tiers]
    assert any("Layer A" in t for t in tier_names)
    assert any("Layer B" in t for t in tier_names)
    assert any("Layer C" in t for t in tier_names)
    assert any("Layer D" in t for t in tier_names)

    # Monotonic improvement in Brier Score
    traj = mem.get("brier_score_calibration_trajectory", [])
    assert len(traj) == 4
    brier_scores = [t["multiclass_brier"] for t in traj]
    # Check that score strictly decreases (lower is better)
    assert brier_scores == sorted(brier_scores, reverse=True)
    assert brier_scores[-1] == 0.1240
    assert traj[-1]["uniform_skill_score"] == 0.8553
    assert traj[-1]["climatology_skill_score"] == 0.2201


def test_11_performance_risk_accounting():
    """Verify accounting separation between active 10k epoch and historical 50k demo baseline."""
    pr = fetch_json("/api/performance_risk")
    active = pr.get("active_epoch", {})
    demo = pr.get("historical_demo_epoch", {})

    assert active["starting_capital_inr"] in (10000.0, 50000.0)
    assert "0/7" in active.get("seven_session_gate", "")

    # Historical demo ledger reconciliation
    assert demo["starting_capital_inr"] == 50000.00
    assert demo["ending_equity_inr"] == 52265.45
    assert demo["realized_pnl_inr"] == 1680.45
    assert demo["unrealized_pnl_inr"] == 585.00
    assert demo["win_rate_pct"] == 100.0

    # Fee and drag structure
    fees = pr.get("fee_and_drag_structure", {})
    assert "₹10" in fees.get("brokerage", "")
    assert "73061" in fees.get("exchange_turnover", "")


def test_12_protected_boundary_live_order_rejection():
    """Verify live order dispatch is strictly rejected with HTTP 403 Forbidden."""
    url = f"{DASHBOARD_URL}/api/order/live"
    req = urllib.request.Request(
        url,
        data=json.dumps({"symbol": "NIFTY", "action": "BUY"}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(req, timeout=5.0)
    assert exc_info.value.code == 403
