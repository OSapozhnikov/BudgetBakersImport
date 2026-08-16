# BudgetBakers Excel → CSV / API import

Stage 2 web app: convert bank Excel statement exports to BudgetBakers-compatible CSV (UTF-8 with BOM), convert foreign amounts to UAH via NBU rates, map bank categories to BudgetBakers category names, and import reviewed rows via `POST /records`.

## Features

- Upload `.xlsx` → preview → import to BudgetBakers and/or download CSV
- Skip non-`Виконано` rows
- Accounts directory (API refresh and/or manual) → select account on the home page
- **Primary account** checkbox on **Рахунки** — used as the default selection on upload
- Currency: `₴` / `грн` → `UAH`; `USD` / `EUR` via NBU on operation date (with lookback if rate missing)
- Category mapping UI backed by `GET /categories`
- Unmapped / empty category directory → keep bank category name from the import file
- Download name: `bbi-<account>-<dateStart>-<dateEnd>.csv` (spaces stripped from account; dates `DD.MM.YYYY`)
- Health check: `GET /healthz`

**Out of scope:** per-card account mapping, web UI auth, dedup against existing Wallet records (review the preview, then one import per job).

## Quick start (Docker)

```bash
cp .env.example .env
# edit .env — optionally DEFAULT_ACCOUNT_NAME and BUDGETBAKERS_API_TOKEN

docker compose up --build
```

Open http://localhost:8000

Durable data (mappings, accounts) lives in `./data` (mounted to `/data`).

Before converting, open **Рахунки** and either refresh from BudgetBakers API or add an account name manually. Import to Wallet needs a token **and** an account with a BudgetBakers `id` (refresh from API).

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
| `DEFAULT_ACCOUNT_NAME` | `Account` | Preselected account when present in the directory (after primary) |
| `DATA_DIR` | `./data` | Durable data directory |
| `BUDGETBAKERS_API_BASE` | `https://rest.budgetbakers.com/wallet/v1/api` | Wallet API base URL ([docs](https://rest.budgetbakers.com/wallet/reference)) |
| `BUDGETBAKERS_API_TOKEN` | _(empty)_ | Bearer token for `GET /categories`, `GET /accounts`, and `POST /records` |
| `NBU_FX_LOOKBACK_DAYS` | `7` | Days to walk back if NBU rate missing |

Put secrets only in `.env` (gitignored), never in the image.

## CSV format

BudgetBakers-compatible import layout:

Delimiter: `,` · Encoding: `utf-8-sig` (BOM) · Line endings: CRLF

| Column | Content |
|---|---|
| `Cтатус` | Always `Виконано` (Latin `C` + Cyrillic — required by the format BudgetBakers accepts) |
| `Дата операції` | `DD.MM.YYYY` |
| `Опис операції` | Operation description |
| `Рахунок/картка` | Selected account from the directory |
| `Категорія` | Mapped BudgetBakers name, or original import category if unmapped |
| `Сума` | Amount in UAH (sign preserved; trailing zeros stripped) |
| `Валюта` | Always `₴` |

## Accounts directory

1. Open **Рахунки**.
2. Refresh from BudgetBakers `GET /accounts` (needs token), and/or add names manually.
3. Optionally check **Основний** on one account — it is preselected on the home page.
4. On the home page, pick the target account from the dropdown.

Selection priority: form retry → primary account → `DEFAULT_ACCOUNT_NAME` → first account.

Stored at `$DATA_DIR/accounts.json`. API refresh merges by name and keeps manual-only entries (and the `primary` flag).

Manual-only names have no BudgetBakers `id` and cannot be imported via API until you refresh from the API.

## Import to BudgetBakers (Stage 2)

On the preview page, **Імпортувати** posts converted rows to BudgetBakers `POST /records` (batches of 20). **Завантажити CSV** stays available as a secondary action.

Requirements (the button is disabled with a short reason otherwise):

- `BUDGETBAKERS_API_TOKEN` in `.env`
- Selected account has a BudgetBakers `id` (refresh **Рахунки** from the API)
- Job has at least one row
- This job has not already been imported (prevents duplicate posts)

Result banner: `Імпортовано X з Y`, plus capped per-item errors if any. Zero-amount rows are skipped (the API rejects them). Unmapped / unknown category names omit `categoryId` so Wallet assigns Unknown Income/Expense. Amounts stay in UAH — the target account should be a UAH account.

Each in-memory job can be imported at most once (marked after any successful row).

## Category mapping

1. Upload an Excel file once (discovers bank categories).
2. Open **Категорії** → refresh from BudgetBakers API (needs token).
3. Map and save. Stored at `$DATA_DIR/category_mappings.json`.

If the BudgetBakers category list is empty, or a bank category has no mapping, the CSV (and import) keep the category name from the import file.

Without a token you can still type BudgetBakers category names manually in the mapping fields.

## Project layout

```
app/
  main.py
  settings.py
  services/
    excel_parser.py
    fx_nbu.py
    categories.py
    accounts.py
    accounts_store.py
    records.py
    mapping_store.py
    csv_export.py
  templates/
  static/
Dockerfile
docker-compose.yml
.env.example
```
