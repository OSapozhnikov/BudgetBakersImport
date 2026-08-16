"""Lightweight Ukrainian / English UI translations."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from starlette.requests import Request
from starlette.responses import Response

COOKIE_NAME = "bbi_lang"
DEFAULT_LANG = "uk"
SUPPORTED_LANGS = ("uk", "en")
COOKIE_MAX_AGE = 365 * 24 * 60 * 60

# Message id → {lang: text}. Use ``{name}`` placeholders for .format().
TRANSLATIONS: dict[str, dict[str, str]] = {
    # Base / nav
    "nav.convert": {"uk": "Конвертація", "en": "Convert"},
    "nav.accounts": {"uk": "Рахунки", "en": "Accounts"},
    "nav.categories": {"uk": "Категорії", "en": "Categories"},
    "footer.stage": {
        "uk": "Етап 2: Excel → CSV або імпорт у BudgetBakers через API.",
        "en": "Stage 2: Excel → CSV or import into BudgetBakers via API.",
    },
    "lang.switcher": {"uk": "Мова", "en": "Language"},
    # Index
    "index.title": {"uk": "Конвертація — BudgetBakers Import", "en": "Convert — BudgetBakers Import"},
    "index.eyebrow": {"uk": "Конвертація", "en": "Convert"},
    "index.h1": {"uk": "Excel → CSV", "en": "Excel → CSV"},
    "index.lead": {
        "uk": (
            "Завантажте банківську Excel-виписку (.xlsx). Суми в USD/EUR конвертуються в UAH "
            "за курсом НБУ на дату операції. Усі рядки потрапляють на один рахунок з довідника."
        ),
        "en": (
            "Upload a bank Excel statement (.xlsx). USD/EUR amounts are converted to UAH "
            "using the NBU rate on the transaction date. All rows go to one account from the directory."
        ),
    },
    "index.empty_accounts": {
        "uk": "Довідник рахунків порожній. Спочатку {link}додайте або завантажте рахунки{/link}.",
        "en": "The accounts directory is empty. First {link}add or load accounts{/link}.",
    },
    "index.file_label": {"uk": "Файл Excel", "en": "Excel file"},
    "index.account_label": {"uk": "Рахунок BudgetBakers", "en": "BudgetBakers account"},
    "index.account_hint": {
        "uk": "Список з {link}довідника рахунків{/link}. Однакова назва для всіх рядків.",
        "en": "List from the {link}accounts directory{/link}. The same name for every row.",
    },
    "index.no_accounts_option": {"uk": "— немає рахунків —", "en": "— no accounts —"},
    "index.submit": {"uk": "Конвертувати та переглянути", "en": "Convert and preview"},
    "index.hints_title": {"uk": "Що робить додаток", "en": "What the app does"},
    "index.hint_status": {
        "uk": "Бере лише рядки зі статусом «Виконано»",
        "en": "Keeps only rows with status “Completed”",
    },
    "index.hint_fx": {
        "uk": "Мапить ₴ / грн → UAH; інші валюти — через НБУ",
        "en": "Maps ₴ / грн → UAH; other currencies via NBU",
    },
    "index.hint_mapping": {
        "uk": (
            "Підставляє категорії з {link}мапінгу{/link}; якщо мапінгу немає — "
            "залишає категорію з файлу імпорту"
        ),
        "en": (
            "Applies categories from the {link}mapping{/link}; if unmapped — "
            "keeps the category from the import file"
        ),
    },
    "index.hint_csv": {
        "uk": "Віддає CSV з BOM, роздільник {code}",
        "en": "Exports CSV with BOM, delimiter {code}",
    },
    # Preview
    "preview.title": {
        "uk": "Перегляд — BudgetBakers Import",
        "en": "Preview — BudgetBakers Import",
    },
    "preview.eyebrow": {"uk": "Конвертація", "en": "Convert"},
    "preview.h1": {
        "uk": "Попередній перегляд конвертації",
        "en": "Conversion preview",
    },
    "preview.lead": {
        "uk": "Зніміть позначку з рядків, які не потрібно включати в CSV або імпорт у BudgetBakers.",
        "en": "Uncheck rows you do not want in the CSV or BudgetBakers import.",
    },
    "preview.stat_rows": {"uk": "Рядків після фільтрації", "en": "Rows after filtering"},
    "preview.stat_sum": {"uk": "Сума UAH", "en": "Total UAH"},
    "preview.stat_account": {"uk": "Рахунок", "en": "Account"},
    "preview.stat_file": {"uk": "Файл", "en": "File"},
    "preview.import": {"uk": "Імпортувати", "en": "Import"},
    "preview.download_csv": {"uk": "Завантажити CSV", "en": "Download CSV"},
    "preview.back": {"uk": "← Назад до завантаження", "en": "← Back to upload"},
    "preview.export_file": {"uk": "Файл експорту:", "en": "Export file:"},
    "preview.import_stats": {
        "uk": (
            "Успішно: {succeeded} · помилок: {failed} · пропущено (сума 0): {skipped_zero} "
            "· не надіслано: {not_sent}"
        ),
        "en": (
            "Succeeded: {succeeded} · failed: {failed} · skipped (amount 0): {skipped_zero} "
            "· not sent: {not_sent}"
        ),
    },
    "preview.import_aborted_suffix": {"uk": " · імпорт перервано", "en": " · import aborted"},
    "preview.record_errors": {"uk": "Помилки записів:", "en": "Record errors:"},
    "preview.row_n": {"uk": "Рядок {n}", "en": "Row {n}"},
    "preview.and_more": {"uk": "…і ще {n}", "en": "…and {n} more"},
    "preview.unmapped": {
        "uk": "Категорії без мапінгу (залишено оригінальні назви):",
        "en": "Unmapped categories (original names kept):",
    },
    "preview.warnings": {"uk": "Попередження ({n})", "en": "Warnings ({n})"},
    "preview.meta_line": {
        "uk": "Пропущено: {skipped} · FX-конверсій: {fx} · помилок курсу: {fx_failures}",
        "en": "Skipped: {skipped} · FX conversions: {fx} · rate errors: {fx_failures}",
    },
    "preview.total_rows": {"uk": "Усього рядків: {n}.", "en": "Total rows: {n}."},
    "preview.col_date": {"uk": "Дата", "en": "Date"},
    "preview.col_counterparty": {"uk": "Контрагент", "en": "Counterparty"},
    "preview.col_note": {"uk": "Опис", "en": "Description"},
    "preview.col_category": {"uk": "Категорія", "en": "Category"},
    "preview.col_amount_uah": {"uk": "Сума (UAH)", "en": "Amount (UAH)"},
    "preview.col_currency": {"uk": "Валюта", "en": "Currency"},
    "preview.col_amount_orig": {"uk": "Сума (ориг.)", "en": "Amount (orig.)"},
    "preview.col_account": {"uk": "Рахунок", "en": "Account"},
    "preview.select_all_title": {
        "uk": "Вибрати всі / зняти всі",
        "en": "Select all / clear all",
    },
    "preview.select_all_aria": {
        "uk": "Вибрати всі або зняти всі",
        "en": "Select all or clear all",
    },
    "preview.include_row_aria": {
        "uk": "Включити рядок {n}",
        "en": "Include row {n}",
    },
    "preview.tag_unmapped": {"uk": "без мапінгу", "en": "unmapped"},
    "preview.js_pick_one": {
        "uk": "Оберіть хоча б одну операцію.",
        "en": "Select at least one transaction.",
    },
    "preview.js_confirm_import": {
        "uk": "Імпортувати {count} операцій у BudgetBakers?",
        "en": "Import {count} transactions into BudgetBakers?",
    },
    # Accounts
    "accounts.title": {"uk": "Рахунки — BudgetBakers Import", "en": "Accounts — BudgetBakers Import"},
    "accounts.eyebrow": {"uk": "Налаштування", "en": "Settings"},
    "accounts.h1": {"uk": "Довідник рахунків", "en": "Accounts directory"},
    "accounts.lead": {
        "uk": (
            "Рахунки BudgetBakers для колонки {code} у CSV. "
            "Можна підтягнути через API або додати назву вручну. Зберігається в {file}."
        ),
        "en": (
            "BudgetBakers accounts for the {code} CSV column. "
            "Load via API or add a name manually. Stored in {file}."
        ),
    },
    "accounts.refresh": {
        "uk": "Оновити з BudgetBakers API",
        "en": "Refresh from BudgetBakers API",
    },
    "accounts.token_hint": {
        "uk": "Спочатку задайте BUDGETBAKERS_API_TOKEN",
        "en": "Set BUDGETBAKERS_API_TOKEN first",
    },
    "accounts.back": {"uk": "← До конвертації", "en": "← Back to convert"},
    "accounts.no_token": {
        "uk": (
            "Токен API не задано ({code}). Можна додати назви рахунків вручну нижче."
        ),
        "en": (
            "API token is not set ({code}). You can still add account names manually below."
        ),
    },
    "accounts.add_label": {"uk": "Додати рахунок вручну", "en": "Add account manually"},
    "accounts.add": {"uk": "Додати", "en": "Add"},
    "accounts.empty": {
        "uk": (
            "Довідник порожній. Оновіть з API або додайте рахунок вручну — "
            "інакше конвертація недоступна."
        ),
        "en": (
            "Directory is empty. Refresh from API or add an account manually — "
            "otherwise conversion is unavailable."
        ),
    },
    "accounts.col_name": {"uk": "Назва", "en": "Name"},
    "accounts.col_source": {"uk": "Джерело", "en": "Source"},
    "accounts.col_id": {"uk": "ID", "en": "ID"},
    "accounts.col_primary": {"uk": "Основний", "en": "Primary"},
    "accounts.source_api": {"uk": "API", "en": "API"},
    "accounts.source_manual": {"uk": "вручну", "en": "manual"},
    "accounts.primary_title": {"uk": "Основний", "en": "Primary"},
    "accounts.primary_aria": {
        "uk": "Основний рахунок {name}",
        "en": "Primary account {name}",
    },
    "accounts.delete": {"uk": "Видалити", "en": "Delete"},
    # Categories
    "categories.title": {
        "uk": "Категорії — BudgetBakers Import",
        "en": "Categories — BudgetBakers Import",
    },
    "categories.eyebrow": {"uk": "Налаштування", "en": "Settings"},
    "categories.h1": {"uk": "Мапінг категорій", "en": "Category mapping"},
    "categories.lead": {
        "uk": (
            "Банківські категорії з останніх завантажень зіставляються з назвами категорій BudgetBakers. "
            "У списку групи = батьківські категорії у Wallet (наприклад Food & Drinks → Groceries). "
            "Мапінг зберігає лише назву категорії (лист) у {file} — так очікує CSV BudgetBakers. "
            "Якщо довідник порожній або для категорії немає відповідника — "
            "у CSV потрапляє назва з файлу імпорту як є."
        ),
        "en": (
            "Bank categories from recent uploads are matched to BudgetBakers category names. "
            "Groups in the list are parent categories in Wallet (e.g. Food & Drinks → Groceries). "
            "The mapping stores only the leaf category name in {file} — as BudgetBakers CSV expects. "
            "If the directory is empty or a category has no match — "
            "the import file name is written to CSV as-is."
        ),
    },
    "categories.refresh": {
        "uk": "Оновити з BudgetBakers API",
        "en": "Refresh from BudgetBakers API",
    },
    "categories.back": {"uk": "← До конвертації", "en": "← Back to convert"},
    "categories.no_token": {
        "uk": (
            "Токен API не задано ({code}). Можна вводити назви категорій вручну в полі нижче."
        ),
        "en": (
            "API token is not set ({code}). You can type category names manually in the field below."
        ),
    },
    "categories.empty": {
        "uk": "Ще немає банківських категорій. Спочатку {link}завантажте Excel{/link} — список з’явиться тут.",
        "en": "No bank categories yet. First {link}upload an Excel file{/link} — the list will appear here.",
    },
    "categories.col_bank": {"uk": "Категорія з виписки", "en": "Statement category"},
    "categories.col_bb": {"uk": "Категорія BudgetBakers", "en": "BudgetBakers category"},
    "categories.keep_file": {
        "uk": "— залишити як у файлі імпорту —",
        "en": "— keep as in import file —",
    },
    "categories.current": {"uk": "Поточне: {name}", "en": "Current: {name}"},
    "categories.placeholder": {
        "uk": "Порожньо = як у файлі імпорту",
        "en": "Empty = as in import file",
    },
    "categories.save": {"uk": "Зберегти мапінг", "en": "Save mapping"},
    # Route / flash messages
    "err.add_account_first": {
        "uk": "Спочатку додайте рахунок у довідник (Рахунки).",
        "en": "Add an account to the directory first (Accounts).",
    },
    "err.pick_account": {
        "uk": "Оберіть рахунок зі списку довідника.",
        "en": "Choose an account from the directory list.",
    },
    "err.need_xlsx": {
        "uk": "Потрібен файл Excel (.xlsx).",
        "en": "An Excel file (.xlsx) is required.",
    },
    "err.empty_file": {"uk": "Файл порожній.", "en": "The file is empty."},
    "err.excel_read": {
        "uk": "Помилка читання Excel: {exc}",
        "en": "Excel read error: {exc}",
    },
    "err.job_not_found": {
        "uk": (
            "Завдання не знайдено або вже протерміноване. "
            "{link}Завантажте файл знову{/link}."
        ),
        "en": (
            "Job not found or expired. "
            "{link}Upload the file again{/link}."
        ),
    },
    "err.pick_rows_csv": {
        "uk": "Оберіть хоча б одну операцію для завантаження CSV.",
        "en": "Select at least one transaction to download CSV.",
    },
    "err.already_imported": {
        "uk": "Це завдання вже імпортовано.",
        "en": "This job has already been imported.",
    },
    "err.no_rows_import": {
        "uk": "Немає рядків для імпорту.",
        "en": "No rows to import.",
    },
    "err.pick_rows_import": {
        "uk": "Оберіть хоча б одну операцію для імпорту.",
        "en": "Select at least one transaction to import.",
    },
    "err.need_token": {
        "uk": "Спочатку задайте BUDGETBAKERS_API_TOKEN.",
        "en": "Set BUDGETBAKERS_API_TOKEN first.",
    },
    "err.need_account_id": {
        "uk": "У рахунку немає ID BudgetBakers. Оновіть довідник з API.",
        "en": "Account has no BudgetBakers ID. Refresh the directory from the API.",
    },
    "err.import_failed": {
        "uk": "Помилка імпорту: {exc}",
        "en": "Import error: {exc}",
    },
    "ok.imported": {
        "uk": "Імпортовано {succeeded} з {total}",
        "en": "Imported {succeeded} of {total}",
    },
    "err.import_aborted": {"uk": "Імпорт перервано.", "en": "Import aborted."},
    "ok.categories_loaded": {
        "uk": "Завантажено {n} категорій BudgetBakers.",
        "en": "Loaded {n} BudgetBakers categories.",
    },
    "ok.mapping_saved": {"uk": "Мапінг збережено.", "en": "Mapping saved."},
    "ok.accounts_refreshed": {
        "uk": "Оновлено з API: {n} рахунків (ручні записи збережено).",
        "en": "Updated from API: {n} accounts (manual entries kept).",
    },
    "ok.account_added": {
        "uk": "Додано рахунок «{name}».",
        "en": "Added account “{name}”.",
    },
    "ok.account_deleted": {
        "uk": "Видалено «{name}».",
        "en": "Deleted “{name}”.",
    },
    "err.account_empty_name": {
        "uk": "Назва рахунку порожня.",
        "en": "Account name is empty.",
    },
}


def normalize_lang(code: str | None) -> str:
    if not code:
        return DEFAULT_LANG
    cleaned = str(code).strip().lower().replace("_", "-")
    if cleaned.startswith("uk"):
        return "uk"
    if cleaned.startswith("en"):
        return "en"
    return DEFAULT_LANG


def get_lang(request: Request) -> str:
    cookie = request.cookies.get(COOKIE_NAME)
    if cookie:
        return normalize_lang(cookie)
    return DEFAULT_LANG


def translate(lang: str, key: str, **kwargs: Any) -> str:
    entry = TRANSLATIONS.get(key)
    if not entry:
        return key
    text = entry.get(lang) or entry.get(DEFAULT_LANG) or key
    if not kwargs:
        return text

    class _FormatMap(dict):
        def __missing__(self, name: str) -> str:
            return "{" + name + "}"

    mapping = _FormatMap((k, str(v)) for k, v in kwargs.items())
    try:
        return text.format_map(mapping)
    except ValueError:
        # Malformed braces in the template (or rare edge cases): substitute
        # known placeholders literally so alerts never show raw "{name}".
        result = text
        for k, v in kwargs.items():
            result = result.replace("{" + k + "}", str(v))
        return result


def t_for(request: Request):
    lang = get_lang(request)

    def t(key: str, **kwargs: Any) -> str:
        return translate(lang, key, **kwargs)

    return t


def set_lang_cookie(response: Response, lang: str) -> None:
    response.set_cookie(
        key=COOKIE_NAME,
        value=normalize_lang(lang),
        max_age=COOKIE_MAX_AGE,
        httponly=False,
        samesite="lax",
        path="/",
    )


def _get_safe_redirect_path(path: str, query: str = "") -> str:
    """Rewrite POST-only paths to a page that accepts GET (avoids 405 on lang switch)."""
    bare = path or "/"
    if bare == "/convert" or bare.startswith("/import/"):
        return "/"
    if bare.startswith("/settings/categories/"):
        return "/settings/categories"
    if bare.startswith("/settings/accounts/"):
        return "/settings/accounts"
    if query:
        return f"{bare}?{query}"
    return bare


def safe_redirect_url(request: Request, fallback: str = "/") -> str:
    """Prefer Referer if it points at this app; otherwise fallback.

    After form POSTs the browser address bar may still show a POST-only path
    (``/convert``, ``/import/...``). Those are rewritten to a GET-safe page.
    """
    referer = (request.headers.get("referer") or "").strip()
    if not referer:
        return fallback
    parsed = urlparse(referer)
    # Relative path only
    if not parsed.scheme and not parsed.netloc and parsed.path.startswith("/"):
        return _get_safe_redirect_path(parsed.path, parsed.query)
    # Same host as current request
    host = request.headers.get("host", "")
    if parsed.netloc and host and parsed.netloc.lower() == host.lower():
        return _get_safe_redirect_path(parsed.path or "/", parsed.query)
    return fallback


def render_job_not_found(request: Request) -> str:
    t = t_for(request)
    body = t("err.job_not_found")
    body = body.replace("{link}", "<a href='/'>").replace("{/link}", "</a>")
    return f"<p>{body}</p>"
