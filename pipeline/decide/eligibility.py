"""Eligibility engine: auto_accept / flag_for_review / reject.

Stub for a later phase. Pure function over the assembled patient record.
Golden rule: a failed API call routes to flag_for_review, never reject.
"""

from __future__ import annotations


def decide_eligibility(record: dict) -> dict:
    raise NotImplementedError("Eligibility engine is implemented in a later phase.")
