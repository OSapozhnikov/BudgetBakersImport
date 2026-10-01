"""In-memory conversion jobs (preview → CSV / API import).

Jobs are process-local. WEB_CONCURRENCY must stay 1.
"""

from __future__ import annotations

import secrets
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

from app.services.csv_export import ConversionResult, build_export_filename

_TWO_PLACES = Decimal("0.01")
JOB_CAP = 20


@dataclass
class Job:
    job_id: str
    created_at: str
    account_name: str
    account_id: str | None
    filename: str
    export_filename: str
    result: ConversionResult
    imported_indices: set[int] = field(default_factory=set)
    in_flight: set[int] = field(default_factory=set)
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)

    @property
    def imported(self) -> bool:
        """True when every non-zero, non-FX-blocked row has been imported at least once."""
        importable = _importable_indices(self.result)
        if not importable:
            return False
        return all(i in self.imported_indices for i in importable)

    def claim_indices(self, indices: list[int]) -> list[int]:
        """Reserve row indexes for import. Returns newly claimed original indexes."""
        with self.lock:
            claimed: list[int] = []
            for idx in indices:
                if idx in self.imported_indices or idx in self.in_flight:
                    continue
                row = self.result.rows[idx]
                if row.fx_blocked:
                    continue
                self.in_flight.add(idx)
                claimed.append(idx)
            return claimed

    def release_in_flight(self, indices: list[int]) -> None:
        """Drop reserved indexes (after abort or when they were not successfully posted)."""
        with self.lock:
            for idx in indices:
                self.in_flight.discard(idx)

    def mark_imported(self, indices: list[int]) -> None:
        """Move indexes from in_flight to imported_indices."""
        with self.lock:
            for idx in indices:
                self.in_flight.discard(idx)
                self.imported_indices.add(idx)


def _importable_indices(result: ConversionResult) -> list[int]:
    return [
        i
        for i, row in enumerate(result.rows)
        if not row.fx_blocked and row.amount.quantize(_TWO_PLACES) != 0
    ]


@dataclass
class JobStore:
    jobs: dict[str, Job] = field(default_factory=dict)

    def put(
        self,
        result: ConversionResult,
        account_name: str,
        filename: str,
        account_id: str | None = None,
    ) -> str:
        job_id = secrets.token_urlsafe(16)
        export_filename = build_export_filename(account_name, result.rows)
        self.jobs[job_id] = Job(
            job_id=job_id,
            created_at=datetime.now(UTC).isoformat(),
            account_name=account_name,
            account_id=(account_id or "").strip() or None,
            filename=filename,
            export_filename=export_filename,
            result=result,
        )
        if len(self.jobs) > JOB_CAP:
            oldest = sorted(self.jobs.items(), key=lambda kv: kv[1].created_at)[:-JOB_CAP]
            for key, _ in oldest:
                self.jobs.pop(key, None)
        return job_id

    def get(self, job_id: str) -> Job | None:
        return self.jobs.get(job_id)
