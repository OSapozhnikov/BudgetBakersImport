"""Jinja page helpers."""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Any
from urllib.parse import quote

from fastapi import Request
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates

from app.i18n import get_lang, render_message, translate
from app.jobs import Job
from app.persistence.accounts_store import AccountsStore
from app.persistence.category_cache import CategoryCacheStore
from app.persistence.import_history import ImportHistoryStore
from app.persistence.mapping_store import CategoryMappingStore
from app.persistence.prefs_store import PrefsStore
from app.services.categories import grouped_bb_categories
from app.services.csv_export import ConversionResult, ExportRow, build_csv, build_export_filename
from app.services.records import RecordImportResult, RecordItemError
from app.settings import Settings
from app.use_cases.convert import select_account
from app.version import __version__

IMPORT_ERROR_CAP = 20


def i18n_context(request: Request) -> dict[str, Any]:
    lang = get_lang(request)

    def t(key: str, **kwargs: Any) -> str:
        return translate(lang, key, **kwargs)

    return {"lang": lang, "t": t, "app_version": __version__}


def format_int_display(value: int) -> str:
    return f"{value:,}".replace(",", " ")


def format_uah_display(amount: Decimal) -> str:
    quantized = amount.quantize(Decimal("0.01"))
    sign = "-" if quantized < 0 else ""
    absolute = abs(quantized)
    whole, _, fraction = f"{absolute:.2f}".partition(".")
    grouped = f"{int(whole):,}".replace(",", " ")
    return f"{sign}{grouped}.{fraction} ₴"


def translate_maybe(lang: str, text: str | None) -> str | None:
    if not text:
        return text
    rendered = translate(lang, text)
    return rendered


def csv_download_response(
    job: Job,
    rows: list[ExportRow],
    *,
    content: bytes | None = None,
) -> Response:
    result: ConversionResult = job.result
    out_name = job.export_filename or build_export_filename(job.account_name, result.rows)
    ascii_name = re.sub(r"[^A-Za-z0-9._-]+", "_", out_name).strip("._") or "bbi-export.csv"
    if not ascii_name.lower().endswith(".csv"):
        ascii_name += ".csv"
    disposition = (
        f'attachment; filename="{ascii_name}"; '
        f"filename*=UTF-8''{quote(out_name)}"
    )
    return Response(
        content=content if content is not None else build_csv(rows),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": disposition},
    )


def import_ui_state(job: Job, settings: Settings, lang: str) -> dict[str, Any]:
    result: ConversionResult = job.result
    token_configured = bool(settings.budgetbakers_api_token.strip())
    account_id = str(job.account_id or "").strip()
    already_imported = job.imported
    reason: str | None = None
    if already_imported:
        reason = translate(lang, "err.already_imported")
    elif not result.rows:
        reason = translate(lang, "err.no_rows_import")
    elif not token_configured:
        reason = translate(lang, "err.need_token")
    elif not account_id:
        reason = translate(lang, "err.need_account_id")
    return {
        "token_configured": token_configured,
        "can_import": reason is None,
        "import_disabled_reason": reason,
        "already_imported": already_imported,
    }


def preview_page(
    request: Request,
    templates: Jinja2Templates,
    settings: Settings,
    job_id: str,
    job: Job,
    category_cache: CategoryCacheStore,
    *,
    error: str | None = None,
    success: str | None = None,
    status_code: int = 200,
    import_result: RecordImportResult | None = None,
) -> HTMLResponse:
    result: ConversionResult = job.result
    lang = get_lang(request)
    total_rows = len(result.rows)
    total_amount_uah = sum((r.amount for r in result.rows), Decimal("0"))
    duplicate_count = sum(1 for r in result.rows if r.is_duplicate)
    import_errors = []
    import_error_total = 0
    if import_result is not None:
        import_error_total = len(import_result.errors)
        import_errors = [
            RecordItemError(
                row_index=e.row_index,
                date=e.date,
                note=e.note,
                error=translate_maybe(lang, e.error) or e.error,
                error_type=e.error_type,
            )
            for e in import_result.errors[:IMPORT_ERROR_CAP]
        ]

    bb_cats = category_cache.load()
    bb_groups = grouped_bb_categories(bb_cats)
    bb_names = [item["name"] for group in bb_groups for item in group["items"]]
    warning_messages = [render_message(lang, w) for w in result.warnings]

    fatal = None
    if import_result is not None and import_result.fatal_error:
        fatal = translate_maybe(lang, import_result.fatal_error)

    context: dict[str, Any] = {
        **i18n_context(request),
        "active_nav": "convert",
        "job_id": job_id,
        "filename": job.filename,
        "export_filename": job.export_filename or build_export_filename(job.account_name, result.rows),
        "account_name": job.account_name,
        "rows": result.rows,
        "total_rows": total_rows,
        "total_rows_display": format_int_display(total_rows),
        "total_amount_uah": total_amount_uah,
        "total_amount_uah_display": format_uah_display(total_amount_uah),
        "duplicate_count": duplicate_count,
        "preview_limit": settings.preview_row_limit,
        "skipped": result.skipped,
        "converted_fx_count": result.converted_fx_count,
        "fx_failures": result.fx_failures,
        "unmapped_categories": result.unmapped_categories,
        "warnings": warning_messages[:30],
        "warning_total": len(warning_messages),
        "bb_groups": bb_groups,
        "bb_names": bb_names,
        "error": error,
        "success": success,
        "import_result": import_result,
        "import_errors": import_errors,
        "import_error_total": import_error_total,
        "import_succeeded": import_result.succeeded if import_result else None,
        "import_failed": import_result.failed if import_result else None,
        "import_skipped_zero": import_result.skipped_zero if import_result else None,
        "import_not_sent": import_result.not_sent if import_result else None,
        "import_fatal_error": fatal,
        "import_aborted": import_result.aborted if import_result else False,
        "import_posted": import_result.posted if import_result else None,
    }
    context.update(import_ui_state(job, settings, lang))
    return templates.TemplateResponse(
        request,
        "preview.html",
        context,
        status_code=status_code,
    )


def index_page(
    request: Request,
    templates: Jinja2Templates,
    settings: Settings,
    accounts_store: AccountsStore,
    prefs_store: PrefsStore,
    *,
    error: str | None = None,
    status_code: int = 200,
    selected_account: str | None = None,
) -> HTMLResponse:
    accounts = accounts_store.list()
    selected = select_account(
        accounts,
        settings,
        preferred=selected_account,
        last_account_name=prefs_store.get_last_account_name(),
    )
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            **i18n_context(request),
            "active_nav": "convert",
            "accounts": accounts,
            "selected_account": selected,
            "default_account": settings.default_account_name,
            "error": error,
        },
        status_code=status_code,
    )


def categories_page(
    request: Request,
    templates: Jinja2Templates,
    settings: Settings,
    store: CategoryMappingStore,
    category_cache: CategoryCacheStore,
    *,
    error: str | None = None,
    success: str | None = None,
) -> HTMLResponse:
    mappings = store.load()
    bank_cats = store.load_discovered()
    for key in mappings:
        if key not in bank_cats:
            bank_cats.append(key)
    bank_cats = sorted(set(bank_cats))
    bb_cats = category_cache.load()
    bb_groups = grouped_bb_categories(bb_cats)
    bb_names = [item["name"] for group in bb_groups for item in group["items"]]

    return templates.TemplateResponse(
        request,
        "categories.html",
        {
            **i18n_context(request),
            "active_nav": "categories",
            "bank_categories": bank_cats,
            "mappings": mappings,
            "bb_groups": bb_groups,
            "bb_names": bb_names,
            "token_configured": bool(settings.budgetbakers_api_token.strip()),
            "error": error,
            "success": success,
        },
    )


def accounts_page(
    request: Request,
    templates: Jinja2Templates,
    settings: Settings,
    accounts_store: AccountsStore,
    *,
    error: str | None = None,
    success: str | None = None,
) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "accounts.html",
        {
            **i18n_context(request),
            "active_nav": "accounts",
            "accounts": accounts_store.list(),
            "token_configured": bool(settings.budgetbakers_api_token.strip()),
            "default_account": settings.default_account_name,
            "error": error,
            "success": success,
        },
    )


def history_page(
    request: Request,
    templates: Jinja2Templates,
    history_store: ImportHistoryStore,
) -> HTMLResponse:
    entries = history_store.list()
    return templates.TemplateResponse(
        request,
        "history.html",
        {
            **i18n_context(request),
            "active_nav": "history",
            "entries": entries,
        },
    )
