"""Convert / download / import HTTP routes."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from starlette.concurrency import run_in_threadpool

from app.errors import AppError
from app.i18n import (
    get_lang,
    normalize_lang,
    render_job_not_found,
    safe_redirect_url,
    set_lang_cookie,
    t_for,
    translate,
)
from app.selection import rows_by_indices
from app.services.csv_export import ConversionResult, build_export_filename, exportable_rows
from app.settings import Settings
from app.use_cases.convert import convert_upload
from app.use_cases.import_records import import_selected_rows
from app.views import (
    csv_download_response,
    index_page,
    preview_page,
)

_READ_CHUNK = 64 * 1024


def _settings(request: Request) -> Settings:
    return request.app.state.settings


async def _read_upload_capped(file: UploadFile, max_bytes: int) -> bytes:
    """Read upload body with a hard byte cap (ignores missing Content-Length)."""
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(_READ_CHUNK)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise AppError(
                "err.file_too_large",
                max_mb=max(1, max_bytes // (1024 * 1024)),
            )
        chunks.append(chunk)
    return b"".join(chunks)


def convert_router() -> APIRouter:
    router = APIRouter()

    @router.get("/healthz")
    def healthz(request: Request) -> dict[str, str]:
        data_ok = _data_dir_writable(_settings(request).data_dir)
        return {
            "status": "ok" if data_ok else "degraded",
            "data_dir": "ok" if data_ok else "error",
        }

    @router.get("/lang/{code}")
    def set_language(code: str, request: Request) -> RedirectResponse:
        lang = normalize_lang(code)
        response = RedirectResponse(
            url=safe_redirect_url(request, "/"),
            status_code=303,
        )
        set_lang_cookie(response, lang)
        return response

    @router.get("/", response_class=HTMLResponse)
    def index(request: Request) -> HTMLResponse:
        return index_page(
            request,
            request.app.state.templates,
            _settings(request),
            request.app.state.accounts_store,
            request.app.state.prefs_store,
        )

    @router.post("/convert", response_class=HTMLResponse)
    async def convert(
        request: Request,
        file: UploadFile = File(...),
        account_name: str = Form(""),
    ) -> HTMLResponse:
        t = t_for(request)
        settings = _settings(request)
        account = (account_name or "").strip()
        templates = request.app.state.templates

        def refuse(message: str, status_code: int = 400) -> HTMLResponse:
            return index_page(
                request,
                templates,
                settings,
                request.app.state.accounts_store,
                request.app.state.prefs_store,
                error=message,
                status_code=status_code,
                selected_account=account,
            )

        filename = file.filename or "upload.xlsx"
        try:
            content = await _read_upload_capped(file, settings.max_upload_bytes)
            outcome = await run_in_threadpool(
                convert_upload,
                content=content,
                filename=filename,
                account_name=account,
                settings=settings,
                accounts_store=request.app.state.accounts_store,
                mapping_store=request.app.state.mapping_store,
                fingerprint_store=request.app.state.fingerprint_store,
                prefs_store=request.app.state.prefs_store,
                jobs=request.app.state.jobs,
                lang=get_lang(request),
            )
        except AppError as exc:
            return refuse(t(exc.code, **exc.params), status_code=400)

        job = request.app.state.jobs.get(outcome.job_id)
        assert job is not None
        return preview_page(
            request,
            templates,
            settings,
            outcome.job_id,
            job,
            request.app.state.category_cache,
        )

    @router.get("/download/{job_id}")
    def download(request: Request, job_id: str) -> Response:
        job = request.app.state.jobs.get(job_id)
        if not job:
            return HTMLResponse(render_job_not_found(request), status_code=404)
        return csv_download_response(job, exportable_rows(job.result.rows))

    @router.post("/download/{job_id}")
    def download_selected(
        request: Request,
        job_id: str,
        row: Annotated[list[int], Form()] = [],
    ) -> Response:
        t = t_for(request)
        job = request.app.state.jobs.get(job_id)
        if not job:
            return HTMLResponse(render_job_not_found(request), status_code=404)
        selected = exportable_rows(rows_by_indices(job.result.rows, row))
        if not selected:
            return preview_page(
                request,
                request.app.state.templates,
                _settings(request),
                job_id,
                job,
                request.app.state.category_cache,
                error=t("err.pick_rows_csv"),
                status_code=400,
            )
        return csv_download_response(job, selected)

    @router.post("/import/{job_id}", response_class=HTMLResponse)
    def import_records(
        request: Request,
        job_id: str,
        row: Annotated[list[int], Form()] = [],
    ) -> HTMLResponse:
        t = t_for(request)
        job = request.app.state.jobs.get(job_id)
        if not job:
            return HTMLResponse(render_job_not_found(request), status_code=404)

        def refuse(message: str, status_code: int = 400) -> HTMLResponse:
            return preview_page(
                request,
                request.app.state.templates,
                _settings(request),
                job_id,
                job,
                request.app.state.category_cache,
                error=message,
                status_code=status_code,
            )

        try:
            import_result = import_selected_rows(
                job=job,
                job_id=job_id,
                indices=row,
                settings=_settings(request),
                fingerprint_store=request.app.state.fingerprint_store,
                history_store=request.app.state.history_store,
                category_cache=request.app.state.category_cache,
            )
        except AppError as exc:
            return refuse(t(exc.code, **exc.params))

        total = import_result.posted + import_result.not_sent
        success = t("ok.imported", succeeded=import_result.succeeded, total=total)
        error = None
        if import_result.fatal_error:
            error = translate(get_lang(request), import_result.fatal_error)
        if import_result.aborted and not error:
            error = t("err.import_aborted")

        return preview_page(
            request,
            request.app.state.templates,
            _settings(request),
            job_id,
            job,
            request.app.state.category_cache,
            error=error,
            success=success,
            import_result=import_result,
        )

    @router.post("/jobs/{job_id}/rows/{index}/category")
    def patch_row_category(
        request: Request,
        job_id: str,
        index: int,
        category: str = Form(""),
    ) -> Response:
        t = t_for(request)
        job = request.app.state.jobs.get(job_id)
        if not job:
            return HTMLResponse(render_job_not_found(request), status_code=404)
        result: ConversionResult = job.result
        if index < 0 or index >= len(result.rows):
            return Response(content=t("err.row_not_found"), status_code=404)
        row = result.rows[index]
        new_category = (category or "").strip()
        row.category = new_category
        bb_names = {
            str(item.get("name") or "").strip().casefold()
            for item in request.app.state.category_cache.load()
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
        job.export_filename = build_export_filename(job.account_name, result.rows)
        return Response(status_code=204)

    return router


def _data_dir_writable(data_dir: str) -> bool:
    try:
        path = Path(data_dir)
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".healthz"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True
    except OSError:
        return False
