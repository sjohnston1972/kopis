"""Shared state schema for the LangGraph pipeline."""

from typing import Annotated, Literal, TypedDict

from langgraph.graph import add_messages


class FindingDict(TypedDict, total=False):
    id: str
    category: str  # interface, routing, security, performance
    severity: str  # critical, high, medium, low, info
    confidence: float  # 0.0 - 1.0
    title: str
    description: str
    affected_entity: str  # e.g. "GigabitEthernet0/1"
    evidence: dict
    requires_remediation: bool


class RecommendationDict(TypedDict, total=False):
    id: str
    finding_id: str
    action: str  # human-readable description
    commands: list[str]  # CLI commands to execute
    risk_level: str  # low, medium, high
    reasoning: str
    rollback_commands: list[str]
    model_used: str


class KopisState(TypedDict, total=False):
    # ── Input ────────────────────────────────────────────────
    snapshot_id: str
    device_id: str
    device_hostname: str
    device_platform: str  # e.g. "iosxe", "nxos", "iosv"
    raw_snapshot: dict  # Full pyATS learned data for this device

    # ── Normaliser output ────────────────────────────────────
    normalised_data: dict
    interface_summary: list[dict]
    routing_summary: list[dict]
    anomalies_detected: list[dict]

    # ── Topology agent output ────────────────────────────────
    findings: list[FindingDict]

    # ── Remediation agent output ─────────────────────────────
    recommendations: list[RecommendationDict]

    # ── Control flow ─────────────────────────────────────────
    escalate_to_opus: bool
    force_escalation: bool  # Set by manual escalation — always routes to Opus
    processing_stage: Literal[
        "normalise", "topology", "remediation", "escalation", "complete"
    ]
    errors: list[str]

    # ── Tracking ─────────────────────────────────────────────
    tokens_used: dict  # {model_name: token_count}
