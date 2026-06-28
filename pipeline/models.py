"""Pydantic models mirroring the PCC API responses.

Lightweight stubs for Phase 1 -- the ``pcc_client`` returns raw parsed JSON
(list[dict]) for verification, so these are not yet wired in. They define the
expected shapes and will be used for validation in a later phase.

Note the two distinct patient identifiers (CLAUDE.md hard rule 1):
- ``patient_id`` (string, e.g. "FA-001") -> diagnoses + coverage
- ``id`` / ``patient_internal_id`` (int, e.g. 1) -> notes + assessments
"""

from __future__ import annotations

from pydantic import BaseModel


class Patient(BaseModel):
    id: int
    facility_id: int
    patient_id: str
    first_name: str | None = None
    last_name: str | None = None
    birth_date: str | None = None
    gender: str | None = None
    primary_payer_code: str | None = None
    last_modified_at: str | None = None
    is_new_admission: bool | None = None


class Diagnosis(BaseModel):
    id: int
    patient_id: str
    icd10_code: str | None = None
    icd10_description: str | None = None
    clinical_status: str | None = None
    onset_date: str | None = None
    last_modified_at: str | None = None


class Coverage(BaseModel):
    id: int
    patient_id: str
    payer_name: str | None = None
    payer_code: str | None = None
    payer_type: str | None = None
    effective_from: str | None = None
    effective_to: str | None = None
    last_modified_at: str | None = None


class Note(BaseModel):
    id: int
    patient_id: int
    org_id: str | None = None
    pcc_note_id: int | None = None
    note_type: str | None = None
    effective_date: str | None = None
    note_text: str | None = None
    created_by: str | None = None
    note_label: str | None = None


class Assessment(BaseModel):
    id: int
    patient_id: int
    org_id: str | None = None
    pcc_assessment_id: int | None = None
    assessment_type: str | None = None
    status: str | None = None
    assessment_date: str | None = None
    completion_date: str | None = None
    template_id: int | None = None
    assessment_type_description: str | None = None
    raw_json: str | None = None
