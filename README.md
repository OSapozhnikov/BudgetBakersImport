# BudgetBakers Excel → CSV / API import

Stage 2+ web app: convert bank Excel statement exports to BudgetBakers-compatible CSV (UTF-8 with BOM), convert foreign amounts to UAH via NBU rates, map bank categories to BudgetBakers category names, and import selected rows via `POST /records`.

UI is bilingual (Ukrainian default, English via the header switcher).

## Features

- Upload `.xlsx` / `.xlsm` (browse or drag-and-drop) → preview → import to BudgetBakers and/or download CSV
- Skip non-`Виконано` rows
- Accounts directory (API refresh and/or manual) → select account on the home page
- **Primary account** on **Accounts** — default when nothing else applies
- **Last used account** remembered after a successful convert (`prefs.json`)
- Counterparty extracted from the operation note (shown in preview; sent as `counterParty` on API import; CSV keeps the note in `Опис операції`)
- Preview: row checkboxes, select-all, filters (All / Unmapped / FX), sticky actions + selected counter
- Hybrid dedup: local fingerprints + optional `GET /records` for the account/date range — duplicates get a badge and are unchecked by default
- Inline category edit on preview (job only; does not update the mapping store)
- Import confirmation modal (selected count, expense/income, unmapped, duplicates, account)
- Import history page (last successful API imports)
- Category mapping UI backed by `GET /categories`
- Unmapped / empty category → keep bank category name from the import file
- Download name: `bbi-<account>-<dateStart>-<dateEnd>.csv` (spaces stripped from account; dates `DD.MM.YYYY`)
- Health check: `GET /healthz`

**Out of scope:** per-card account mapping, web UI auth.

## Quick start (Docker)

```bash
cp .env.example .env
# edit .env — optionally DEFAULT_ACCOUNT_NAME and BUDGETBAKERS_API_TOKEN

docker compose up --build
```

Open http://localhost:8000

Durable data lives in `./data` (mounted to `/data`).

Before converting, open **Accounts** and either refresh from BudgetBakers API or add an account name manually. Import to Wallet needs a token **and** an account with a BudgetBakers `id` (refresh from API).

## Local run (without Docker)

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
mkdir data
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `PORT` | `8000` | Listen port |
| `LOG_LEVEL` | `INFO` | Logging level |
| `WEB_CONCURRENCY` | `1` | Uvicorn workers |
| `DEFAULT_ACCOUNT_NAME` | `Account` | Fallback preselected account when present in the directory |
| `DATA_DIR` | `./data` | Durable data directory |
| `BUDGETBAKERS_API_BASE` | `https://rest.budgetbakers.com/wallet/v1/api` | Wallet API base URL ([docs](https://rest.budgetbakers.com/wallet/reference)) |
| `BUDGETBAKERS_API_TOKEN` | _(empty)_ | Bearer token for `GET /categories`, `GET /accounts`, `GET /records`, and `POST /records` |
| `NBU_FX_LOOKBACK_DAYS` | `7` | Days to walk back if NBU rate missing |

Put secrets only in `.env` (gitignored), never in the image.

## Data files (`$DATA_DIR`)

| File | Purpose |
|---|---|
| `accounts.json` | Accounts directory (names, API ids, primary flag) |
| `category_mappings.json` | Bank → BudgetBakers category mappings |
| `bb_categories_cache.json` | Cached `GET /categories` list (for mapping + inline edit) |
| `prefs.json` | UI prefs (last used account name) |
| `import_fingerprints.json` | Fingerprints of successfully imported rows (local dedup) |
| `import_history.json` | Append-only API import history (capped) |

## CSV format

BudgetBakers-compatible import layout:

Delimiter: `,` · Encoding: `utf-8-sig` (BOM) · Line endings: CRLF

| Column | Content |
|---|---|
| `Cтатус` | Always `Виконано` (Latin `C` + Cyrillic — required by the format BudgetBakers accepts) |
| `Дата операції` | `DD.MM.YYYY` |
| `Опис операції` | Operation description (note) |
| `Рахунок/картка` | Selected account from the directory |
| `Категорія` | Mapped BudgetBakers name, or original import category if unmapped |
| `Сума` | Amount in UAH (sign preserved; trailing zeros stripped) |
| `Валюта` | Always `₴` |

Currency on convert: `₴` / `грн` → `UAH`; `USD` / `EUR` via NBU on the operation date (with lookback if rate missing).

## Accounts directory

1. Open **Accounts**.
2. Refresh from BudgetBakers `GET /accounts` (needs token), and/or add names manually.
3. Optionally mark one account as **Primary** — used when there is no last-used account.
4. On the home page, pick the target account from the dropdown (or rely on last used / primary).

Selection priority: form retry → last used account → primary → `DEFAULT_ACCOUNT_NAME` → first account.

API refresh merges by name and keeps manual-only entries (and the `primary` flag). Manual-only names have no BudgetBakers `id` and cannot be imported via API until you refresh from the API.

## Preview & import

On the preview page:

- Checkboxes control which rows go to **Import** or **Download CSV** (duplicates unchecked by default).
- Filters: All / Unmapped / FX (client-side; does not change selection).
- Sticky action bar shows how many rows are selected.
- Inline category dropdown updates that job row only (not `category_mappings.json`).
- **Import** opens a summary modal, then posts selected rows to `POST /records` (batches of 20).

### Dedup

When the account has a BudgetBakers `id`, rows are fingerprinted (account + date + amount + note + counterparty):

1. Match against `$DATA_DIR/import_fingerprints.json` (rows successfully imported before).
2. Optionally match against Wallet `GET /records` for the job’s date range (needs token). If that call fails, convert still works and a muted warning is shown.

Duplicates show a badge and stay unchecked unless you select them.

### Import requirements

The Import button is disabled with a short reason otherwise:

- `BUDGETBAKERS_API_TOKEN` in `.env`
- Selected account has a BudgetBakers `id`
- Job has at least one row
- At least one row is checked
- This job has not already been imported (prevents duplicate posts for the same in-memory job)

Result: success banner plus capped per-item errors if any. Zero-amount rows are skipped (the API rejects them). Unmapped / unknown category names omit `categoryId` so Wallet assigns Unknown Income/Expense. Amounts stay in UAH — the target account should be a UAH account.

Successful imports append history and store fingerprints for the succeeded rows. Each in-memory job can be imported at most once (marked after any successful row).

## Category mapping

1. Upload an Excel file once (discovers bank categories).
2. Open **Categories** → refresh from BudgetBakers API (needs token).
3. Map and save. Stored at `$DATA_DIR/category_mappings.json`.

If the BudgetBakers category list is empty, or a bank category has no mapping, the CSV (and import) keep the category name from the import file.

Without a token you can still type BudgetBakers category names manually in the mapping fields.

## Language

Header **UK | EN** sets a cookie (`bbi_lang`). Default language is Ukrainian.

## Tests

```bash
python -m unittest discover -s tests -v
```

## Project layout

```
app/
  main.py
  settings.py
  i18n.py
  services/
    excel_parser.py
    counterparty.py
    fx_nbu.py
    categories.py
    accounts.py
    accounts_store.py
    mapping_store.py
    prefs_store.py
    fingerprints.py
    import_history.py
    records.py
    csv_export.py
  templates/
  static/
tests/
Dockerfile
docker-compose.yml
.env.example
```
