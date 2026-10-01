"""Convert an uploaded statement into an in-memory preview job."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from app.errors import AppError, ErrorMessage, merge_messages
from app.jobs import JobStore
from app.persistence.accounts_store import AccountsStore, StoredAccount
from app.persistence.fingerprints import FingerprintStore
from app.persistence.mapping_store import CategoryMappingStore
from app.persistence.prefs_store import PrefsStore
from app.services.csv_export import ExportRow, convert_rows
from app.services.excel_parser import parse_excel
from app.services.fingerprints import fingerprint_from_api_item, fingerprint_row
from app.services.fx_nbu import NbuFxConverter
from app.services.records import BudgetBakersRecordsClient
from app.settings import Settings


@dataclass
class ConvertOutcome:
    job_id: str
    error: AppError | None = None


def select_account(
    accounts: list[StoredAccount],
    settings: Settings,
    preferred: str | None = None,
    last_account_name: str | None = None,
) -> str | None:
    """preferred → last_account_name → primary → DEFAULT_ACCOUNT_NAME → first."""
    if not accounts:
        return None
    names = [a.name for a in accounts]
    if preferred and preferred in names:
        return preferred
    if last_account_name and last_account_name in names:
        return last_account_name
    for acc in accounts:
        if acc.primary:
            return acc.name
    if settings.default_account_name in names:
        return settings.default_account_name
    return names[0]


def mark_duplicates(
    rows: list[ExportRow],
    *,
    account_id: str | None,
    fingerprint_store: FingerprintStore,
    settings: Settings,
    lang: str,
) -> list[ErrorMessage]:
    """Set ``is_duplicate`` / ``fp_collision`` from local store, Wallet, and in-file collisions."""
    warnings: list[ErrorMessage] = []
    if not rows:
        return warnings

    local = fingerprint_store.load()
    if len(local) >= settings.fingerprint_warn_count:
        logging.warning(
            "Fingerprint store has %s entries (warn threshold %s)",
            len(local),
            settings.fingerprint_warn_count,
        )
        warnings.append(
            ErrorMessage(
                "preview.fingerprints_large",
                {"count": len(local), "threshold": settings.fingerprint_warn_count},
            )
        )

    api_fps: set[str] = set()
    token = settings.budgetbakers_api_token.strip()
    acc_id = (account_id or "").strip()

    if token and acc_id:
        try:
            dates = [r.date for r in rows]
            with BudgetBakersRecordsClient(
                base_url=settings.budgetbakers_api_base,
                token=settings.budgetbakers_api_token,
                max_pages=settings.max_wallet_pages,
                max_items=settings.max_wallet_items,
            ) as client:
                api_items = client.list_records(
                    account_id=acc_id,
                    date_from=min(dates),
                    date_to=max(dates),
                )
            for item in api_items:
                fp = fingerprint_from_api_item(item, acc_id)
                if fp:
                    api_fps.add(fp)
        except Exception as exc:  # noqa: BLE001
            logging.warning("Optional GET /records dedup failed: %s", exc)
            warnings.append(ErrorMessage("preview.dedup_api_warn"))

    # Within-file collisions (same account/date/amount/note/counterparty).
    seen_fp: dict[str, int] = {}
    collision_fps: set[str] = set()
    if acc_id:
        for row in rows:
            if row.fx_blocked:
                continue
            fp = fingerprint_row(row, acc_id)
            if fp in seen_fp:
                collision_fps.add(fp)
            else:
                seen_fp[fp] = 1

    for row in rows:
        if not acc_id:
            row.is_duplicate = False
            row.fp_collision = False
            continue
        fp = fingerprint_row(row, acc_id)
        row.fp_collision = fp in collision_fps and not row.fx_blocked
        row.is_duplicate = (fp in local or fp in api_fps) and not row.fx_blocked

    if collision_fps:
        warnings.append(
            ErrorMessage("preview.fp_collision_warn", {"n": len(collision_fps)})
        )

    return warnings


def convert_upload(
    *,
    content: bytes,
    filename: str,
    account_name: str,
    settings: Settings,
    accounts_store: AccountsStore,
    mapping_store: CategoryMappingStore,
    fingerprint_store: FingerprintStore,
    prefs_store: PrefsStore,
    jobs: JobStore,
    lang: str,
) -> ConvertOutcome:
    accounts = accounts_store.list()
    if not accounts:
        raise AppError("err.add_account_first")
    allowed = {a.name for a in accounts}
    if account_name not in allowed:
        raise AppError("err.pick_account")
    if not filename.lower().endswith((".xlsx", ".xlsm")):
        raise AppError("err.need_xlsx")
    if not content:
        raise AppError("err.empty_file")
    if len(content) > settings.max_upload_bytes:
        max_mb = max(1, settings.max_upload_bytes // (1024 * 1024))
        raise AppError("err.file_too_large", max_mb=max_mb)

    try:
        parsed = parse_excel(
            content,
            max_rows=settings.max_excel_rows,
            max_uncompressed_bytes=settings.max_excel_uncompressed_bytes,
        )
    except AppError:
        raise
    except Exception as exc:  # noqa: BLE001
        logging.exception("Excel parse failed")
        raise AppError("err.excel_read", exc=exc) from exc

    mapping_store.remember_bank_categories(parsed.bank_categories)

    with NbuFxConverter(
        lookback_days=settings.nbu_fx_lookback_days,
        data_dir=settings.data_dir,
    ) as fx:
        result = convert_rows(
            parsed.rows,
            account_name=account_name,
            mapping_store=mapping_store,
            fx=fx,
        )

    result.skipped = parsed.skipped
    result.bank_categories = parsed.bank_categories
    result.warnings = merge_messages(parsed.warnings, result.warnings)

    stored = next((a for a in accounts if a.name == account_name), None)
    account_id = stored.id if stored else None
    dedup_warnings = mark_duplicates(
        result.rows,
        account_id=account_id,
        fingerprint_store=fingerprint_store,
        settings=settings,
        lang=lang,
    )
    if dedup_warnings:
        result.warnings = merge_messages(result.warnings, dedup_warnings)

    prefs_store.set_last_account_name(account_name)
    job_id = jobs.put(result, account_name, filename, account_id=account_id)
    return ConvertOutcome(job_id=job_id)
