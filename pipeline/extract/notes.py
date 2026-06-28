"""Adapter: a progress note's ``note_text`` -> ExtractionResult.

note_text is already plain text, so this is thin: detect the body format, run the
shared regex core, and fall back to the LLM for Envive bodies or any
incomplete/low-confidence regex result.
"""

from __future__ import annotations

from . import llm
from .format_detect import detect_format
from .text_fields import (
    FMT_ENVIVE,
    ExtractionResult,
    extract_fields,
)


def extract_from_note(note_text: str | None, use_llm: bool = True) -> ExtractionResult:
    text = note_text or ""
    fmt = detect_format(text)

    if fmt == FMT_ENVIVE:
        # Envive always routes to the LLM (the messy-paragraph demo case).
        return llm.extract_with_llm(text, source_format=FMT_ENVIVE) if use_llm \
            else _envive_shell(text)

    res = extract_fields(text, fmt)

    # LLM fallback when regex came back incomplete / low-confidence.
    if use_llm and (not res.is_complete()):
        llm_res = llm.extract_with_llm(text, source_format=fmt, regex_result=res)
        if llm_res is not None:
            return llm_res
    return res


def _envive_shell(text: str) -> ExtractionResult:
    res = ExtractionResult(source_format=FMT_ENVIVE)
    res.ambiguous = True
    return res
