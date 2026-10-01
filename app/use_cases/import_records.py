"""Import selected preview rows into BudgetBakers."""

from __future__ import annotations

import logging

from app.errors import AppError
from app.jobs import Job
from app.persistence.category_cache import CategoryCacheStore
from app.persistence.fingerprints import FingerprintStore
from app.persistence.import_history import ImportHistoryStore
from app.selection import unique_indices
from app.services.csv_export import ExportRow
from app.services.fingerprints import fingerprint_row
from app.services.records import BudgetBakersRecordsClient, RecordImportResult
from app.settings import Settings


def import_selected_rows(
    *,
    job: Job,
    job_id: str,
    indices: list[int],
    settings: Settings,
    fingerprint_store: FingerprintStore,
    history_store: ImportHistoryStore,
    category_cache: CategoryCacheStore,
) -> RecordImportResult:
    result = job.result
    token = settings.budgetbakers_api_token.strip()
    account_id = str(job.account_id or "").strip()

    if not result.rows:
        raise AppError("err.no_rows_import")
    selected_idx = unique_indices(len(result.rows), indices)
    if not selected_idx:
        raise AppError("err.pick_rows_import")
    if not token:
        raise AppError("err.need_token")
    if not account_id:
        raise AppError("err.need_account_id")

    if selected_idx and all(result.rows[i].fx_blocked for i in selected_idx):
        raise AppError("err.fx_blocked_only")

    claimed_idx = job.claim_indices(selected_idx)
    if not claimed_idx:
        raise AppError("err.already_imported")

    selected = [result.rows[i] for i in claimed_idx]
    try:
        with BudgetBakersRecordsClient(
            base_url=settings.budgetbakers_api_base,
            token=settings.budgetbakers_api_token,
        ) as client:
            import_result = client.import_rows(
                selected,
                account_id=account_id,
                category_cache=category_cache.load(),
            )
    except AppError:
        job.release_in_flight(claimed_idx)
        raise
    except (RuntimeError, ValueError) as exc:
        job.release_in_flight(claimed_idx)
        raise AppError("err.import_failed", exc=exc) from exc
    except Exception as exc:  # noqa: BLE001
        job.release_in_flight(claimed_idx)
        logging.exception("BudgetBakers import failed")
        raise AppError("err.import_failed", exc=exc) from exc

    try:
        if import_result.succeeded_indices:
            persist_successful_import(
                fingerprint_store=fingerprint_store,
                history_store=history_store,
                job=job,
                job_id=job_id,
                selected=selected,
                selected_original_indices=claimed_idx,
                import_result=import_result,
                account_id=account_id,
            )
        else:
            job.release_in_flight(claimed_idx)
    except Exception:
        # Succeeded rows already marked when possible; release leftover in_flight.
        job.release_in_flight(claimed_idx)
        raise

    # Rows that failed or were never sent stay selectable.
    unfinished = [
        claimed_idx[i]
        for i in range(len(claimed_idx))
        if i not in set(import_result.succeeded_indices)
    ]
    if unfinished:
        job.release_in_flight(unfinished)

    logging.info(
        "Import job %s: succeeded=%s failed=%s skipped_zero=%s not_sent=%s aborted=%s",
        job_id,
        import_result.succeeded,
        import_result.failed,
        import_result.skipped_zero,
        import_result.not_sent,
        import_result.aborted,
    )
    return import_result


def persist_successful_import(
    *,
    fingerprint_store: FingerprintStore,
    history_store: ImportHistoryStore,
    job: Job,
    job_id: str,
    selected: list[ExportRow],
    selected_original_indices: list[int],
    import_result: RecordImportResult,
    account_id: str,
) -> None:
    """Save fingerprints for succeeded rows and append history. No all-rows fallback."""
    succeeded_rows: list[ExportRow] = []
    succeeded_original: list[int] = []
    seen: set[int] = set()
    for idx in import_result.succeeded_indices:
        if idx < 0 or idx >= len(selected) or idx in seen:
            continue
        seen.add(idx)
        succeeded_rows.append(selected[idx])
        original = selected_original_indices[idx]
        succeeded_original.append(original)
        selected[idx].is_duplicate = True

    if succeeded_original:
        job.mark_imported(succeeded_original)

    if succeeded_rows and account_id:
        fps = [fingerprint_row(row, account_id) for row in succeeded_rows]
        fingerprint_store.add_many(fps)

    history_store.append(
        filename=job.filename,
        account_name=job.account_name,
        account_id=account_id,
        requested=len(selected),
        succeeded=import_result.succeeded,
        failed=import_result.failed,
        skipped_zero=import_result.skipped_zero,
        job_id=job_id,
    )
