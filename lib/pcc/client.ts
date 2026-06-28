import Bottleneck from "bottleneck";
import type {
  RawAssessment,
  RawCoverage,
  RawDiagnosis,
  RawNote,
  RawPatient,
} from "@/lib/pcc/types";

const DEFAULT_BASE = "https://hackathon.prod.pulsefoundry.ai";
const MAX_ATTEMPTS = 8; // BUILD_PLAN §6: retry 429/500 up to 8 attempts

export interface PccStats {
  retries: number; // every re-attempt (429 + 500 + network)
  rateLimited: number; // 429s
  serverErrors: number; // 500s
  networkErrors: number;
  calls: number; // successful 200s
}

/** Surfaced (not retried) — e.g. 422 invalid params. */
export class PccError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
    this.name = "PccError";
  }
}

const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));
const sinceParam = (since?: string): string =>
  since ? `&since=${encodeURIComponent(since)}` : "";

/**
 * Rate-limit-aware PCC API client.
 * - Bottleneck maxConcurrent (default 8).
 * - 429 → sleep `Retry-After` seconds, retry (≤8 attempts total).
 * - 500 / network error → backoff + retry (≤8 attempts).
 * - 422 → surfaced immediately (never retried).
 * Tracks retry counts for `pipeline_run.retries`.
 */
export class PccClient {
  private limiter: Bottleneck;
  private base: string;
  readonly stats: PccStats = {
    retries: 0,
    rateLimited: 0,
    serverErrors: 0,
    networkErrors: 0,
    calls: 0,
  };

  constructor(maxConcurrent = 8, base = process.env.PCC_BASE_URL || DEFAULT_BASE) {
    this.limiter = new Bottleneck({ maxConcurrent });
    this.base = base;
  }

  private fetchJson<T>(path: string): Promise<T> {
    return this.limiter.schedule(() => this.attempt<T>(path));
  }

  private async attempt<T>(path: string): Promise<T> {
    const url = `${this.base}${path}`;
    let lastErr: unknown;

    for (let attempt = 1; attempt <= MAX_ATTEMPTS; attempt++) {
      let res: Response;
      try {
        res = await fetch(url);
      } catch (e) {
        this.stats.networkErrors++;
        this.stats.retries++;
        lastErr = e;
        await sleep(Math.min(1000 * attempt, 5000));
        continue;
      }

      if (res.status === 200) {
        this.stats.calls++;
        return (await res.json()) as T;
      }

      if (res.status === 429) {
        this.stats.rateLimited++;
        this.stats.retries++;
        const ra = Number.parseInt(res.headers.get("retry-after") ?? "1", 10);
        await sleep((Number.isFinite(ra) && ra > 0 ? ra : 1) * 1000);
        continue;
      }

      if (res.status === 500) {
        this.stats.serverErrors++;
        this.stats.retries++;
        lastErr = new PccError(500, `500 for ${path}`);
        await sleep(Math.min(1000 * attempt, 5000));
        continue;
      }

      if (res.status === 422) {
        const body = await res.text().catch(() => "");
        throw new PccError(422, `422 Unprocessable Entity for ${path}: ${body}`);
      }

      // Any other status: surface (don't spin).
      const body = await res.text().catch(() => "");
      throw new PccError(res.status, `${res.status} for ${path}: ${body}`);
    }

    throw new PccError(
      0,
      `Exhausted ${MAX_ATTEMPTS} attempts for ${path}${lastErr ? `: ${String(lastErr)}` : ""}`,
    );
  }

  // ── Typed endpoints (dual-key: string patient_id vs integer id) ──
  // `since` (ISO 8601) enables incremental fetch where the API supports it
  // (patients=last_modified_at, notes=effective_date, assessments=assessment_date).
  getPatients(facilityId: number, since?: string): Promise<RawPatient[]> {
    return this.fetchJson<RawPatient[]>(`/pcc/patients?facility_id=${facilityId}${sinceParam(since)}`);
  }
  getDiagnoses(patientId: string): Promise<RawDiagnosis[]> {
    return this.fetchJson<RawDiagnosis[]>(
      `/pcc/diagnoses?patient_id=${encodeURIComponent(patientId)}`,
    );
  }
  getCoverage(patientId: string): Promise<RawCoverage[]> {
    return this.fetchJson<RawCoverage[]>(
      `/pcc/coverage?patient_id=${encodeURIComponent(patientId)}`,
    );
  }
  getNotes(id: number, since?: string): Promise<RawNote[]> {
    return this.fetchJson<RawNote[]>(`/pcc/notes?patient_id=${id}${sinceParam(since)}`);
  }
  getAssessments(id: number, since?: string): Promise<RawAssessment[]> {
    return this.fetchJson<RawAssessment[]>(`/pcc/assessments?patient_id=${id}${sinceParam(since)}`);
  }
}
