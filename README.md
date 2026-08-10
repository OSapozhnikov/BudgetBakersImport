# BudgetBakers Excel → CSV

Stage 1 web app: convert bank Excel statement exports to BudgetBakers-compatible CSV (UTF-8 with BOM), convert foreign amounts to UAH via NBU rates, and map bank categories to BudgetBakers category names.

## Features

- Upload `.xlsx` → preview → download CSV
- Skip non-`Виконано` rows
- Accounts directory (API refresh and/or manual) → select account on the home page
- Currency: `₴` / `грн` → `UAH`; `USD` / `EUR` via NBU on operation date (with lookback if rate missing)
- Category mapping UI backed by `GET /categories`
- Unmapped / empty category directory → keep bank category name from the import file
- Download name: `bbi-<account>-<dateStart>-<dateEnd>.csv` (spaces stripped from account; dates `DD.MM.YYYY`)
- Health check: `GET /healthz`

**Not in stage 1:** `POST /records` API import, per-card account mapping, web UI auth.

## Quick start (Docker)

```bash
cp .env.example .env
# edit .env — optionally DEFAULT_ACCOUNT_NAME and BUDGETBAKERS_API_TOKEN

docker compose up --build
```

Open http://localhost:8000

Durable data (mappings, accounts) lives in `./data` (mounted to `/data`).

Before converting, open **Рахунки** and either refresh from BudgetBakers API or add an account name manually.

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
| `DEFAULT_ACCOUNT_NAME` | `Account` | Preselected account when present in the directory |
| `DATA_DIR` | `./data` | Durable data directory |
| `BUDGETBAKERS_API_BASE` | `https://api.budgetbakers.com/api/v1` | API base URL |
| `BUDGETBAKERS_API_TOKEN` | _(empty)_ | Bearer token for categories/accounts |
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
3. On the home page, pick the target account from the dropdown.

Stored at `$DATA_DIR/accounts.json`. API refresh merges by name and keeps manual-only entries.

## Category mapping

1. Upload an Excel file once (discovers bank categories).
2. Open **Категорії** → refresh from BudgetBakers API (needs token).
3. Map and save. Stored at `$DATA_DIR/category_mappings.json`.

If the BudgetBakers category list is empty, or a bank category has no mapping, the CSV keeps the category name from the import file.

Without a token you can still type BudgetBakers category names manually in the mapping fields.

## Stage 2 (not implemented)

Extension point for later: call BudgetBakers `POST /records` to import converted rows directly instead of (or after) CSV download. Account `id` values from the API are already stored for that. Stage 1 deliberately stops at CSV export.

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
    mapping_store.py
    csv_export.py
  templates/
  static/
Dockerfile
docker-compose.yml
.env.example
```
