from __future__ import annotations

import json
import logging
import re
import secrets
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import quote

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.i18n import (
    get_lang,
    normalize_lang,
    render_job_not_found,
    safe_redirect_url,
    set_lang_cookie,
    t_for,
    translate,
)
from app.services.accounts import BudgetBakersAccountsClient
from app.services.accounts_store import AccountsStore, StoredAccount
from app.services.categories import (
    BudgetBakersCategoriesClient,
    category_to_cache_dict,
    grouped_bb_categories,
)
from app.services.csv_export import (
    ConversionResult,
    ExportRow,
    build_csv,
    build_export_filename,
    convert_rows,
)
from app.services.excel_parser import parse_excel
from app.services.fingerprints import (
    FingerprintStore,
    fingerprint_from_api_item,
    fingerprint_row,
)
from app.services.fx_nbu import NbuFxConverter
from app.services.import_history import ImportHistoryStore
from app.services.mapping_store import CategoryMappingStore
from app.services.prefs_store import PrefsStore
from app.services.records import BudgetBakersRecordsClient, RecordImportResult
from app.settings import Settings, get_settings

APP_DIR = Path(__file__).resolve().parent
IMPORT_ERROR_CAP = 20


def _configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        stream=sys.stdout,
    )


@dataclass
class JobStore:
    """In-memory conversion jobs for preview → CSV download / API import."""

    jobs: dict[str, dict[str, Any]] = field(default_factory=dict)

    def put(
        self,
        result: ConversionResult,
        account_name: str,
        filename: str,
        account_id: str | None = None,
    ) -> str:
        job_id = secrets.token_urlsafe(16)
        export_filename = build_export_filename(account_name, result.rows)
        self.jobs[job_id] = {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "account_name": account_name,
            "account_id": (account_id or "").strip() or None,
            "filename": filename,
            "export_filename": export_filename,
            "result": result,
            "csv": build_csv(result.rows),
            "imported": False,
        }
        # Keep last 20 jobs
        if len(self.jobs) > 20:
            oldest = sorted(self.jobs.items(), key=lambda kv: kv[1]["created_at"])[:-20]
            for key, _ in oldest:
                self.jobs.pop(key, None)
        return job_id

    def get(self, job_id: str) -> dict[str, Any] | None:
        return self.jobs.get(job_id)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    _configure_logging(settings.log_level)

    app = FastAPI(title="BudgetBakers Excel → CSV", version="1.0.0")
    templates = Jinja2Templates(directory=str(APP_DIR / "templates"))
    app.mount("/static", StaticFiles(directory=str(APP_DIR / "static")), name="static")

    store = CategoryMappingStore(settings.data_dir)
    accounts_store = AccountsStore(settings.data_dir)
    fingerprint_store = FingerprintStore(settings.data_dir)
    history_store = ImportHistoryStore(settings.data_dir)
    prefs_store = PrefsStore(settings.data_dir)
    jobs = JobStore()

    app.state.settings = settings
    app.state.mapping_store = store
    app.state.accounts_store = accounts_store
    app.state.fingerprint_store = fingerprint_store
    app.state.history_store = history_store
    app.state.prefs_store = prefs_store
    app.state.jobs = jobs

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/lang/{code}")
    def set_language(code: str, request: Request) -> RedirectResponse:
        lang = normalize_lang(code)
        response = RedirectResponse(
            url=safe_redirect_url(request, "/"),
            status_code=303,
        )
        set_lang_cookie(response, lang)
        return response

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request) -> HTMLResponse:
        return _index_page(request, templates, settings, accounts_store, prefs_store)

    @app.post("/convert", response_class=HTMLResponse)
    async def convert(
        request: Request,
        file: UploadFile = File(...),
        account_name: str = Form(""),
    ) -> HTMLResponse:
        t = t_for(request)
        accounts = accounts_store.list()
        account = (account_name or "").strip()
        if not accounts:
            return _index_page(
                request,
                templates,
                settings,
                accounts_store,
                prefs_store,
                error=t("err.add_account_first"),
                status_code=400,
            )
        allowed = {a.name for a in accounts}
        if account not in allowed:
            return _index_page(
                request,
                templates,
                settings,
                accounts_store,
                prefs_store,
                error=t("err.pick_account"),
                status_code=400,
                selected_account=account,
            )

        filename = file.filename or "upload.xlsx"
        if not filename.lower().endswith((".xlsx", ".xlsm")):
            return _index_page(
                request,
                templates,
                settings,
                accounts_store,
                prefs_store,
                error=t("err.need_xlsx"),
                status_code=400,
                selected_account=account,
            )

        content = await file.read()
        if not content:
            return _index_page(
                request,
                templates,
                settings,
                accounts_store,
                prefs_store,
                error=t("err.empty_file"),
                status_code=400,
                selected_account=account,
            )

        try:
            parsed = parse_excel(content)
        except Exception as exc:  # noqa: BLE001
            logging.exception("Excel parse failed")
            return _index_page(
                request,
                templates,
                settings,
                accounts_store,
                prefs_store,
                error=t("err.excel_read", exc=exc),
                status_code=400,
                selected_account=account,
            )

        store.remember_bank_categories(parsed.bank_categories)

        with NbuFxConverter(lookback_days=settings.nbu_fx_lookback_days) as fx:
            result = convert_rows(
                parsed.rows,
                account_name=account,
                mapping_store=store,
                fx=fx,
            )

        result.skipped = parsed.skipped
        result.bank_categories = parsed.bank_categories
        result.warnings = list(dict.fromkeys([*parsed.warnings, *result.warnings]))

        stored = next((a for a in accounts if a.name == account), None)
        account_id = stored.id if stored else None
        dedup_warning = _mark_duplicates(
            result.rows,
            account_id=account_id,
            fingerprint_store=fingerprint_store,
            settings=settings,
            lang=get_lang(request),
        )
        if dedup_warning:
            result.warnings = list(dict.fromkeys([*result.warnings, dedup_warning]))

        prefs_store.set_last_account_name(account)

        job_id = jobs.put(
            result,
            account,
            filename,
            account_id=account_id,
        )
        job = jobs.get(job_id)
        assert job is not None
        return _preview_page(request, templates, settings, job_id, job)

    @app.get("/download/{job_id}")
    def download(request: Request, job_id: str) -> Response:
        """Download all converted rows (backward-compatible; selection uses POST)."""
        job = jobs.get(job_id)
        if not job:
            return HTMLResponse(
                render_job_not_found(request),
                status_code=404,
            )
        result: ConversionResult = job["result"]
        return _csv_download_response(
            job,
            result.rows,
            content=job["csv"],
        )

    @app.post("/download/{job_id}")
    def download_selected(
        request: Request,
        job_id: str,
        row: Annotated[list[int], Form()] = [],
    ) -> Response:
        t = t_for(request)
        job = jobs.get(job_id)
        if not job:
            return HTMLResponse(
                render_job_not_found(request),
                status_code=404,
            )
        result: ConversionResult = job["result"]
        selected = _rows_by_indices(result.rows, row)
        if not selected:
            return _preview_page(
                request,
                templates,
                settings,
                job_id,
                job,
                error=t("err.pick_rows_csv"),
                status_code=400,
            )
        return _csv_download_response(job, selected)

    @app.post("/import/{job_id}", response_class=HTMLResponse)
    def import_records(
        request: Request,
        job_id: str,
        row: Annotated[list[int], Form()] = [],
    ) -> HTMLResponse:
        t = t_for(request)
        job = jobs.get(job_id)
        if not job:
            return HTMLResponse(
                render_job_not_found(request),
                status_code=404,
            )

        result: ConversionResult = job["result"]
        token = settings.budgetbakers_api_token.strip()
        account_id = str(job.get("account_id") or "").strip()

        def refuse(message: str, status_code: int = 400) -> HTMLResponse:
            return _preview_page(
                request,
                templates,
                settings,
                job_id,
                job,
                error=message,
                status_code=status_code,
            )

        if job.get("imported"):
            return refuse(t("err.already_imported"))
        if not result.rows:
            return refuse(t("err.no_rows_import"))
        selected = _rows_by_indices(result.rows, row)
        if not selected:
            return refuse(t("err.pick_rows_import"))
        if not token:
            return refuse(t("err.need_token"))
        if not account_id:
            return refuse(t("err.need_account_id"))

        try:
            with BudgetBakersRecordsClient(
                base_url=settings.budgetbakers_api_base,
                token=settings.budgetbakers_api_token,
            ) as client:
                import_result = client.import_rows(
                    selected,
                    account_id=account_id,
                    category_cache=_load_bb_cache(settings),
                )
        except (RuntimeError, ValueError) as exc:
            return refuse(str(exc))
        except Exception as exc:  # noqa: BLE001
            logging.exception("BudgetBakers import failed")
            return refuse(t("err.import_failed", exc=exc), status_code=500)

        if import_result.succeeded:
            job["imported"] = True
            _persist_successful_import(
                fingerprint_store=fingerprint_store,
                history_store=history_store,
                job=job,
                job_id=job_id,
                selected=selected,
                import_result=import_result,
                account_id=account_id,
            )

        total = import_result.posted + import_result.not_sent
        success = t("ok.imported", succeeded=import_result.succeeded, total=total)
        error = import_result.fatal_error
        if import_result.aborted and not error:
            error = t("err.import_aborted")

        logging.info(
            "Import job %s: succeeded=%s failed=%s skipped_zero=%s not_sent=%s aborted=%s",
            job_id,
            import_result.succeeded,
            import_result.failed,
            import_result.skipped_zero,
            import_result.not_sent,
            import_result.aborted,
        )

        return _preview_page(
            request,
            templates,
            settings,
            job_id,
            job,
            error=error,
            success=success,
            import_result=import_result,
        )

    @app.post("/jobs/{job_id}/rows/{index}/category")
    def patch_row_category(
        request: Request,
        job_id: str,
        index: int,
        category: str = Form(""),
    ) -> Response:
        """Update category on one job row only (does not write mapping_store)."""
        t = t_for(request)
        job = jobs.get(job_id)
        if not job:
            return HTMLResponse(render_job_not_found(request), status_code=404)
        result: ConversionResult = job["result"]
        if index < 0 or index >= len(result.rows):
            return Response(content=t("err.row_not_found"), status_code=404)
        row = result.rows[index]
        new_category = (category or "").strip()
        row.category = new_category
        # Job-only: keep bank_category; mapped/unmapped reflect BB cache presence.
        bb_names = {
            str(item.get("name") or "").strip().casefold()
            for item in _load_bb_cache(settings)
            if str(item.get("name") or "").strip()
        }
        if new_category and new_category.casefold() in bb_names:
            row.mapped = True
            row.unmapped = False
        elif new_category:
            row.mapped = False
            row.unmapped = True
        else:
            row.mapped = False
            row.unmapped = bool(row.bank_category)
        # Refresh CSV cache for full-job download path
        job["csv"] = build_csv(result.rows)
        job["export_filename"] = build_export_filename(
            str(job.get("account_name") or ""),
            result.rows,
        )
        return Response(status_code=204)

    @app.get("/settings/history", response_class=HTMLResponse)
    def import_history(request: Request) -> HTMLResponse:
        return _history_page(request, templates, history_store)

    @app.get("/settings/categories", response_class=HTMLResponse)
    def categories_settings(request: Request) -> HTMLResponse:
        return _categories_page(request, templates, settings, store)

    @app.post("/settings/categories/refresh", response_class=HTMLResponse)
    def categories_refresh(request: Request) -> HTMLResponse:
        t = t_for(request)
        error = None
        bb_categories: list[Any] = []
        try:
            with BudgetBakersCategoriesClient(
                base_url=settings.budgetbakers_api_base,
                token=settings.budgetbakers_api_token,
            ) as client:
                bb_categories = client.list_categories()
            cache_path = Path(settings.data_dir) / "bb_categories_cache.json"
            cache_path.write_text(
                json.dumps(
                    [category_to_cache_dict(c) for c in bb_categories],
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
        except Exception as exc:  # noqa: BLE001
            logging.exception("Failed to refresh BB categories")
            error = str(exc)

        return _categories_page(
            request,
            templates,
            settings,
            store,
            error=error,
            success=None if error else t("ok.categories_loaded", n=len(bb_categories)),
        )

    @app.post("/settings/categories/save", response_class=HTMLResponse)
    async def categories_save(request: Request) -> HTMLResponse:
        t = t_for(request)
        form = await request.form()
        updates: dict[str, str] = {}
        for key, value in form.multi_items():
            if not key.startswith("bank_"):
                continue
            idx = key[len("bank_") :]
            bank_cat = str(value)
            mapped = form.get(f"map_{idx}", "")
            updates[bank_cat] = str(mapped) if mapped is not None else ""
        store.update(updates)
        return _categories_page(
            request,
            templates,
            settings,
            store,
            success=t("ok.mapping_saved"),
        )

    @app.get("/settings/accounts", response_class=HTMLResponse)
    def accounts_settings(request: Request) -> HTMLResponse:
        return _accounts_page(request, templates, settings, accounts_store)

    @app.post("/settings/accounts/refresh", response_class=HTMLResponse)
    def accounts_refresh(request: Request) -> HTMLResponse:
        t = t_for(request)
        error = None
        count = 0
        try:
            with BudgetBakersAccountsClient(
                base_url=settings.budgetbakers_api_base,
                token=settings.budgetbakers_api_token,
            ) as client:
                api_accounts = client.list_accounts()
            accounts_store.merge_from_api([(a.name, a.id) for a in api_accounts])
            count = len(api_accounts)
        except Exception as exc:  # noqa: BLE001
            logging.exception("Failed to refresh BB accounts")
            error = str(exc)

        return _accounts_page(
            request,
            templates,
            settings,
            accounts_store,
            error=error,
            success=None if error else t("ok.accounts_refreshed", n=count),
        )

    @app.post("/settings/accounts/add", response_class=HTMLResponse)
    def accounts_add(request: Request, name: str = Form("")) -> HTMLResponse:
        t = t_for(request)
        error = None
        success = None
        try:
            accounts_store.add_manual(name)
            success = t("ok.account_added", name=name.strip())
        except ValueError:
            error = t("err.account_empty_name")
        return _accounts_page(
            request,
            templates,
            settings,
            accounts_store,
            error=error,
            success=success,
        )

    @app.post("/settings/accounts/delete", response_class=HTMLResponse)
    def accounts_delete(request: Request, name: str = Form("")) -> HTMLResponse:
        t = t_for(request)
        accounts_store.remove(name)
        return _accounts_page(
            request,
            templates,
            settings,
            accounts_store,
            success=t("ok.account_deleted", name=name),
        )

    @app.post("/settings/accounts/primary", response_class=HTMLResponse)
    def accounts_primary(request: Request, name: str = Form("")) -> HTMLResponse:
        accounts_store.set_primary(name)
        return _accounts_page(request, templates, settings, accounts_store)

    return app


def _i18n_context(request: Request) -> dict[str, Any]:
    lang = get_lang(request)

    def t(key: str, **kwargs: Any) -> str:
        return translate(lang, key, **kwargs)

    return {"lang": lang, "t": t}


def _select_account(
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


def _mark_duplicates(
    rows: list[ExportRow],
    *,
    account_id: str | None,
    fingerprint_store: FingerprintStore,
    settings: Settings,
    lang: str,
) -> str | None:
    """Set ``is_duplicate`` from local store and optional Wallet GET /records.

    Returns a muted warning string if the API check failed (non-fatal).
    """
    if not rows:
        return None

    local = fingerprint_store.load()
    api_fps: set[str] = set()
    api_warning: str | None = None
    token = settings.budgetbakers_api_token.strip()
    acc_id = (account_id or "").strip()

    if token and acc_id:
        try:
            dates = [r.date for r in rows]
            with BudgetBakersRecordsClient(
                base_url=settings.budgetbakers_api_base,
                token=settings.budgetbakers_api_token,
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
            api_warning = translate(lang, "preview.dedup_api_warn")

    for row in rows:
        if not acc_id:
            row.is_duplicate = False
            continue
        fp = fingerprint_row(row, acc_id)
        row.is_duplicate = fp in local or fp in api_fps

    return api_warning


def _persist_successful_import(
    *,
    fingerprint_store: FingerprintStore,
    history_store: ImportHistoryStore,
    job: dict[str, Any],
    job_id: str,
    selected: list[ExportRow],
    import_result: RecordImportResult,
    account_id: str,
) -> None:
    """Save fingerprints for succeeded rows and append history entry."""
    succeeded_rows: list[ExportRow] = []
    if import_result.succeeded_indices:
        seen: set[int] = set()
        for idx in import_result.succeeded_indices:
            if idx < 0 or idx >= len(selected) or idx in seen:
                continue
            seen.add(idx)
            succeeded_rows.append(selected[idx])
    elif import_result.succeeded > 0 and not import_result.failed:
        # Best-effort: all non-zero selected rows that were posted succeeded.
        succeeded_rows = [
            row
            for row in selected
            if row.amount.quantize(Decimal("0.01")) != 0
        ][: import_result.succeeded]

    if succeeded_rows and account_id:
        fps = [fingerprint_row(row, account_id) for row in succeeded_rows]
        fingerprint_store.add_many(fps)

    history_store.append(
        filename=str(job.get("filename") or ""),
        account_name=str(job.get("account_name") or ""),
        account_id=account_id,
        requested=len(selected),
        succeeded=import_result.succeeded,
        failed=import_result.failed,
        skipped_zero=import_result.skipped_zero,
        job_id=job_id,
    )


def _format_int_display(value: int) -> str:
    return f"{value:,}".replace(",", " ")


def _format_uah_display(amount: Decimal) -> str:
    quantized = amount.quantize(Decimal("0.01"))
    sign = "-" if quantized < 0 else ""
    absolute = abs(quantized)
    whole, _, fraction = f"{absolute:.2f}".partition(".")
    grouped = f"{int(whole):,}".replace(",", " ")
    return f"{sign}{grouped}.{fraction} ₴"


def _rows_by_indices(rows: list[ExportRow], indices: list[int]) -> list[ExportRow]:
    """Return rows for valid, unique indices in the order they appear in the form."""
    selected: list[ExportRow] = []
    seen: set[int] = set()
    n = len(rows)
    for idx in indices:
        if idx < 0 or idx >= n or idx in seen:
            continue
        seen.add(idx)
        selected.append(rows[idx])
    return selected


def _csv_download_response(
    job: dict[str, Any],
    rows: list[ExportRow],
    *,
    content: bytes | None = None,
) -> Response:
    result: ConversionResult = job["result"]
    out_name = str(
        job.get("export_filename")
        or build_export_filename(str(job.get("account_name") or ""), result.rows)
    )
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


def _import_ui_state(job: dict[str, Any], settings: Settings, lang: str) -> dict[str, Any]:
    result: ConversionResult = job["result"]
    token_configured = bool(settings.budgetbakers_api_token.strip())
    account_id = str(job.get("account_id") or "").strip()
    already_imported = bool(job.get("imported"))
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


def _preview_page(
    request: Request,
    templates: Jinja2Templates,
    settings: Settings,
    job_id: str,
    job: dict[str, Any],
    *,
    error: str | None = None,
    success: str | None = None,
    status_code: int = 200,
    import_result: RecordImportResult | None = None,
) -> HTMLResponse:
    result: ConversionResult = job["result"]
    account_name = str(job.get("account_name") or "")
    filename = str(job.get("filename") or "")
    export_filename = str(
        job.get("export_filename") or build_export_filename(account_name, result.rows)
    )
    total_rows = len(result.rows)
    total_amount_uah = sum((r.amount for r in result.rows), Decimal("0"))
    duplicate_count = sum(1 for r in result.rows if r.is_duplicate)
    import_errors = []
    import_error_total = 0
    if import_result is not None:
        import_error_total = len(import_result.errors)
        import_errors = import_result.errors[:IMPORT_ERROR_CAP]

    lang = get_lang(request)
    bb_cats = _load_bb_cache(settings)
    bb_groups = grouped_bb_categories(bb_cats)
    bb_names = [item["name"] for group in bb_groups for item in group["items"]]

    context: dict[str, Any] = {
        **_i18n_context(request),
        "active_nav": "convert",
        "job_id": job_id,
        "filename": filename,
        "export_filename": export_filename,
        "account_name": account_name,
        "rows": result.rows,
        "total_rows": total_rows,
        "total_rows_display": _format_int_display(total_rows),
        "total_amount_uah": total_amount_uah,
        "total_amount_uah_display": _format_uah_display(total_amount_uah),
        "duplicate_count": duplicate_count,
        "preview_limit": settings.preview_row_limit,
        "skipped": result.skipped,
        "converted_fx_count": result.converted_fx_count,
        "fx_failures": result.fx_failures,
        "unmapped_categories": result.unmapped_categories,
        "warnings": result.warnings[:30],
        "warning_total": len(result.warnings),
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
        "import_fatal_error": import_result.fatal_error if import_result else None,
        "import_aborted": import_result.aborted if import_result else False,
        "import_posted": import_result.posted if import_result else None,
    }
    context.update(_import_ui_state(job, settings, lang))
    return templates.TemplateResponse(
        request,
        "preview.html",
        context,
        status_code=status_code,
    )


def _index_page(
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
    selected = _select_account(
        accounts,
        settings,
        preferred=selected_account,
        last_account_name=prefs_store.get_last_account_name(),
    )
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            **_i18n_context(request),
            "active_nav": "convert",
            "accounts": accounts,
            "selected_account": selected,
            "default_account": settings.default_account_name,
            "error": error,
        },
        status_code=status_code,
    )


def _load_bb_cache(settings: Settings) -> list[dict[str, Any]]:
    path = Path(settings.data_dir) / "bb_categories_cache.json"
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(raw, list):
        return []
    return [x for x in raw if isinstance(x, dict) and x.get("name")]


def _categories_page(
    request: Request,
    templates: Jinja2Templates,
    settings: Settings,
    store: CategoryMappingStore,
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
    bb_cats = _load_bb_cache(settings)
    bb_groups = grouped_bb_categories(bb_cats)
    bb_names = [item["name"] for group in bb_groups for item in group["items"]]

    return templates.TemplateResponse(
        request,
        "categories.html",
        {
            **_i18n_context(request),
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


def _accounts_page(
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
            **_i18n_context(request),
            "active_nav": "accounts",
            "accounts": accounts_store.list(),
            "token_configured": bool(settings.budgetbakers_api_token.strip()),
            "default_account": settings.default_account_name,
            "error": error,
            "success": success,
        },
    )


def _history_page(
    request: Request,
    templates: Jinja2Templates,
    history_store: ImportHistoryStore,
) -> HTMLResponse:
    entries = history_store.list()
    return templates.TemplateResponse(
        request,
        "history.html",
        {
            **_i18n_context(request),
            "active_nav": "history",
            "entries": entries,
        },
    )


app = create_app()
