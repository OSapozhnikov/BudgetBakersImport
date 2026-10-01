from __future__ import annotations

import logging

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse

from app.errors import AppError
from app.i18n import t_for
from app.services.accounts import BudgetBakersAccountsClient
from app.services.categories import (
    BudgetBakersCategoriesClient,
    category_to_cache_dict,
)
from app.settings import Settings
from app.views import accounts_page, categories_page, history_page


def _settings(request: Request) -> Settings:
    return request.app.state.settings


def settings_router() -> APIRouter:
    router = APIRouter()

    @router.get("/settings/history", response_class=HTMLResponse)
    def import_history(request: Request) -> HTMLResponse:
        return history_page(request, request.app.state.templates, request.app.state.history_store)

    @router.get("/settings/categories", response_class=HTMLResponse)
    def categories_settings(request: Request) -> HTMLResponse:
        return categories_page(
            request,
            request.app.state.templates,
            _settings(request),
            request.app.state.mapping_store,
            request.app.state.category_cache,
        )

    @router.post("/settings/categories/refresh", response_class=HTMLResponse)
    def categories_refresh(request: Request) -> HTMLResponse:
        t = t_for(request)
        error = None
        bb_categories: list = []
        settings = _settings(request)
        try:
            with BudgetBakersCategoriesClient(
                base_url=settings.budgetbakers_api_base,
                token=settings.budgetbakers_api_token,
                max_pages=settings.max_wallet_pages,
                max_items=settings.max_wallet_items,
            ) as client:
                bb_categories = client.list_categories()
            request.app.state.category_cache.save(
                [category_to_cache_dict(c) for c in bb_categories]
            )
        except AppError as exc:
            logging.exception("Failed to refresh BB categories")
            error = t(exc.code, **exc.params)
        except Exception:  # noqa: BLE001
            logging.exception("Failed to refresh BB categories")
            error = t("err.refresh_failed")

        return categories_page(
            request,
            request.app.state.templates,
            settings,
            request.app.state.mapping_store,
            request.app.state.category_cache,
            error=error,
            success=None if error else t("ok.categories_loaded", n=len(bb_categories)),
        )

    @router.post("/settings/categories/save", response_class=HTMLResponse)
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
        request.app.state.mapping_store.update(updates)
        return categories_page(
            request,
            request.app.state.templates,
            _settings(request),
            request.app.state.mapping_store,
            request.app.state.category_cache,
            success=t("ok.mapping_saved"),
        )

    @router.get("/settings/accounts", response_class=HTMLResponse)
    def accounts_settings(request: Request) -> HTMLResponse:
        return accounts_page(
            request,
            request.app.state.templates,
            _settings(request),
            request.app.state.accounts_store,
        )

    @router.post("/settings/accounts/refresh", response_class=HTMLResponse)
    def accounts_refresh(request: Request) -> HTMLResponse:
        t = t_for(request)
        error = None
        count = 0
        settings = _settings(request)
        try:
            with BudgetBakersAccountsClient(
                base_url=settings.budgetbakers_api_base,
                token=settings.budgetbakers_api_token,
                max_pages=settings.max_wallet_pages,
                max_items=settings.max_wallet_items,
            ) as client:
                api_accounts = client.list_accounts()
            request.app.state.accounts_store.merge_from_api(
                [(a.name, a.id) for a in api_accounts]
            )
            count = len(api_accounts)
        except AppError as exc:
            logging.exception("Failed to refresh BB accounts")
            error = t(exc.code, **exc.params)
        except Exception:  # noqa: BLE001
            logging.exception("Failed to refresh BB accounts")
            error = t("err.refresh_failed")

        return accounts_page(
            request,
            request.app.state.templates,
            settings,
            request.app.state.accounts_store,
            error=error,
            success=None if error else t("ok.accounts_refreshed", n=count),
        )

    @router.post("/settings/accounts/add", response_class=HTMLResponse)
    def accounts_add(request: Request, name: str = Form("")) -> HTMLResponse:
        t = t_for(request)
        error = None
        success = None
        try:
            request.app.state.accounts_store.add_manual(name)
            success = t("ok.account_added", name=name.strip())
        except ValueError:
            error = t("err.account_empty_name")
        return accounts_page(
            request,
            request.app.state.templates,
            _settings(request),
            request.app.state.accounts_store,
            error=error,
            success=success,
        )

    @router.post("/settings/accounts/delete", response_class=HTMLResponse)
    def accounts_delete(request: Request, name: str = Form("")) -> HTMLResponse:
        t = t_for(request)
        request.app.state.accounts_store.remove(name)
        return accounts_page(
            request,
            request.app.state.templates,
            _settings(request),
            request.app.state.accounts_store,
            success=t("ok.account_deleted", name=name),
        )

    @router.post("/settings/accounts/primary", response_class=HTMLResponse)
    def accounts_primary(request: Request, name: str = Form("")) -> HTMLResponse:
        request.app.state.accounts_store.set_primary(name)
        return accounts_page(
            request,
            request.app.state.templates,
            _settings(request),
            request.app.state.accounts_store,
        )

    return router
