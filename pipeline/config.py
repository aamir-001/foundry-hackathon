"""Environment + configuration for the pipeline.

Loads variables from a ``.env`` file (via python-dotenv) with sane fallbacks.
The PCC base URL requires no auth.
"""

from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()

DEFAULT_PCC_BASE_URL = "https://hackathon.prod.pulsefoundry.ai"

PCC_BASE_URL: str = os.getenv("PCC_BASE_URL", DEFAULT_PCC_BASE_URL).rstrip("/")

ANTHROPIC_API_KEY: str | None = os.getenv("ANTHROPIC_API_KEY")
SUPABASE_URL: str | None = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY: str | None = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

# The three mock facilities (see API.md / README.md).
FACILITY_IDS: tuple[int, ...] = (101, 102, 103)
