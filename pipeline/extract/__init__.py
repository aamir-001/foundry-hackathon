"""Wound extraction layer.

Shared text core (text_fields) + body-based format detection (format_detect),
with thin per-source adapters (notes, assessments) and an Anthropic LLM fallback
(llm) used only for Envive bodies or incomplete regex results.
"""
