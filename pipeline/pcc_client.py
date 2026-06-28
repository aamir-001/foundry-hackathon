"""HTTP client for the mock PointClickCare (PCC) API.

This is the ONLY module that talks to the API (CLAUDE.md hard rule 2). Every GET
is wrapped with tenacity retry/backoff that honors the ``Retry-After`` header on
HTTP 429 responses (~30% of requests fail this way by design).

Two patient identifiers are kept deliberately distinct (CLAUDE.md hard rule 1):
- string ``patient_id`` (e.g. "FA-001") -> ``/pcc/diagnoses`` + ``/pcc/coverage``
- integer ``patient_internal_id`` (e.g. 1) -> ``/pcc/notes`` + ``/pcc/assessments``

For Phase 1, methods return raw parsed JSON (``list[dict]``) so the verification
script can inspect true response shapes. Pydantic parsing is wired in later.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_random_exponential,
)

from . import config

logger = logging.getLogger(__name__)

# Total attempts per request before giving up. With Retry-After of 1-5s this
# keeps worst-case latency bounded while surviving several consecutive 429s.
MAX_ATTEMPTS = 6
DEFAULT_TIMEOUT = 30.0


class RateLimited(Exception):
    """Raised on HTTP 429 so tenacity can retry honoring ``Retry-After``."""

    def __init__(self, retry_after: float):
        self.retry_after = retry_after
        super().__init__(f"Rate limited; retry after {retry_after}s")


def _parse_retry_after(response: httpx.Response) -> float | None:
    """Parse the ``Retry-After`` header (seconds). Returns None if absent/invalid."""
    raw = response.headers.get("Retry-After")
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        # Some servers send an HTTP-date; we don't expect that here, so fall back.
        return None


def _wait_honoring_retry_after(retry_state) -> float:
    """tenacity wait strategy: use ``Retry-After`` when present, else backoff."""
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    if isinstance(exc, RateLimited) and exc.retry_after is not None:
        return exc.retry_after
    # Fallback for transient transport errors with no header.
    return wait_random_exponential(multiplier=1, max=10)(retry_state)


class PCCClient:
    """Thin wrapper around ``httpx.Client`` with 429-aware retry on every GET."""

    def __init__(
        self,
        base_url: str | None = None,
        timeout: float = DEFAULT_TIMEOUT,
    ):
        self.base_url = (base_url or config.PCC_BASE_URL).rstrip("/")
        # follow_redirects: the API 307-redirects some paths (e.g. /health -> /health/).
        self._client = httpx.Client(
            base_url=self.base_url, timeout=timeout, follow_redirects=True
        )

    # -- lifecycle ---------------------------------------------------------
    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "PCCClient":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # -- core fetch --------------------------------------------------------
    @retry(
        retry=retry_if_exception_type((RateLimited, httpx.TransportError)),
        wait=_wait_honoring_retry_after,
        stop=stop_after_attempt(MAX_ATTEMPTS),
        reraise=True,
    )
    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """GET ``path`` with retry. Raises ``RateLimited`` on 429, ``HTTPStatusError``
        on other 4xx/5xx, and re-raises after attempts are exhausted."""
        response = self._client.get(path, params=params)

        if response.status_code == 429:
            retry_after = _parse_retry_after(response)
            logger.warning("429 on %s params=%s; retry_after=%s", path, params, retry_after)
            raise RateLimited(retry_after if retry_after is not None else 2.0)

        response.raise_for_status()
        return response.json()

    # -- endpoints ---------------------------------------------------------
    def health(self) -> Any:
        return self._get("/health")

    def get_patients(self, facility_id: int, since: str | None = None) -> list[dict]:
        """All patients for a facility. Both identifiers live in this response."""
        params: dict[str, Any] = {"facility_id": facility_id}
        if since:
            params["since"] = since
        return self._get("/pcc/patients", params=params)

    def get_diagnoses(self, patient_id: str) -> list[dict]:
        """ICD-10 diagnoses. Keyed by the STRING patient_id (e.g. "FA-001")."""
        return self._get("/pcc/diagnoses", params={"patient_id": patient_id})

    def get_coverage(self, patient_id: str) -> list[dict]:
        """Insurance coverage. Keyed by the STRING patient_id (e.g. "FA-001")."""
        return self._get("/pcc/coverage", params={"patient_id": patient_id})

    def get_notes(self, patient_internal_id: int, since: str | None = None) -> list[dict]:
        """Free-text progress notes. Keyed by the INTEGER internal id (e.g. 1)."""
        params: dict[str, Any] = {"patient_id": patient_internal_id}
        if since:
            params["since"] = since
        return self._get("/pcc/notes", params=params)

    def get_assessments(self, patient_internal_id: int, since: str | None = None) -> list[dict]:
        """Structured wound assessments. Keyed by the INTEGER internal id (e.g. 1)."""
        params: dict[str, Any] = {"patient_id": patient_internal_id}
        if since:
            params["since"] = since
        return self._get("/pcc/assessments", params=params)
