"""Audit-risk engine: independent risk level + flags.

Stub for a later phase. Multi-visit flags (STALLED_WOUND, HIGH_VISIT_FREQUENCY,
AREA_INCREASE) require multiple dated records -- guard against single-record
patients so they never throw on absent/short series.
"""

from __future__ import annotations


def assess_audit_risk(record: dict) -> dict:
    raise NotImplementedError("Audit-risk engine is implemented in a later phase.")
