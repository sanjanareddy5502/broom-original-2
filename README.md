# Broom / DataTrust — Safer five-stage data-cleaning prototype

**Broom = DataTrust = DataTrust Broom.** Inlet is a separate AI-solutions project and is **not** this repository.

This version strengthens reliability, predictable transformations, privacy controls, local business analysis, and automated tests. It is **not** a production-hardened multi-tenant SaaS or a fully autonomous, trained AI analyst. It does not learn from clients without their involvement.

## Start Broom (beginner instructions)

1. Unzip the project. Open the **Broom-DataTrust-main** folder in VS Code.
2. Select **Terminal → New Terminal**.
3. Create an environment: `python -m venv .venv`.
4. Activate it:
   - Windows PowerShell: `.venv\Scripts\Activate.ps1`
   - Windows Command Prompt: `.venv\Scripts\activate.bat`
   - macOS/Linux: `source .venv/bin/activate`
5. Install packages: `python -m pip install -r requirements.txt`
6. Launch: `python -m streamlit run app.py`
7. Open the URL shown in the terminal (usually http://localhost:8501).
8. Upload **demo_data/sample_orders.csv** and follow the five stages.

If PowerShell activation is restricted, run `.venv\Scripts\python -m pip install -r requirements.txt` and `.venv\Scripts\python -m streamlit run app.py` without activating.

## The five stages (kept exactly as requested)

1. **Upload Dataset** — CSV or first worksheet of Excel; review preview.
2. **Diagnose Problems** — likely meaning, missing data, duplicates, dates, amounts.
3. **Cleaning Plan & Risk Review** — riskier changes need individual approval.
4. **Clean Data** — run reviewed operations and compare before/after.
5. **Validate & Export** — see changes, exception items, business observations and downloads.

Complex engineering views are inside optional expandable sections.

## What this version actually does

- Input validation: 15 MB upload limit, row/column/cell quotas, Excel archive expansion checks, macros/external links/formulas rejected (values-only workbook required).
- Conservative dates: checks multiple date formats, asks before ambiguous day/month choices, never invents missing years, and won't overwrite partially invalid columns.
- Conservative numbers: parses known currencies and thousands formats; preserves leading-zero IDs, `%`, malformed numbers, and nonfinite values for review.
- Category handling: merges case-only variants using **observed**, most common label after explicit approval; doesn't indiscriminately title-case acronyms.
- Business safeguards: protected financial/identifier missing fields; confirmation for duplicate deletion, date changes, category merges, imputation, QuickBooks transformation; no auto-deletion of accounting transactions.
- Contextual descriptive analysis: date coverage, monthly record counts, named numeric metric sums, optional line-total vs `quantity × unit_price` reconciliation.
- Customer-controlled preferences: save and re-import a **JSON recipe** with confirmed date orientation. Broom does **not** silently learn from private customer files or auto-approve risky actions.
- Audit: cleaning log, validation alerts, Excel / CSV / JSON exports, and spreadsheet formula-injection escaping.
- Long-file scan limits: duplicate-column similarities use sampled data when necessary; sampling is clearly disclosed.
- Optional AI text explanation: uses an external API **only with explicit consent**, and only aggregate metadata; does not execute cleaning decisions. The app works without an API key.

## How to run tests

Install: `python -m pip install -r requirements-dev.txt`

Run: `python -m pytest -q`

Tests cover dates, identifiers, numbers, upload security, approvals, recipe behavior, reconciliation, QuickBooks, spreadsheet-export safety, a five-stage UI **facade** and 120 generated end-to-end business-file scenarios. UI facade tests exercise Python page paths; a real Streamlit browser test is still required.

## Repository map

| File | Responsibility |
|---|---|
| `app.py` | Five-stage customer UI |
| `broom_core/security.py` | File intake policy and limits |
| `broom_core/pipeline.py` | Stateless diagnostic/clean/validate/export orchestration; approval gate |
| `broom_core/recipes.py` | Opt-in, portable date-cleaning preferences |
| `broom_core/relationships.py` | Non-destructive order-total reconciliation |
| `numeric_intelligence.py` | Strict number parsing |
| `date_intelligence.py` | Conservative date inference |
| `business_brief.py` | Aggregate business observations and time breakdown |
| `profiler.py`, `decision_engine.py`, `cleaner.py` | Profiling, rule plans and transformations |
| `report_intelligence.py` | QuickBooks report extraction |
| `validator.py`, `builder.py` | Checks and audited exports |
| `ai_advisor.py` | Optional aggregate-only AI explanation |
| `tests/` | Regression and generated integration tests |

## Security warning

**Run locally with synthetic or de-identified files only. Do NOT put this Streamlit app on the public internet or upload confidential customer data yet.** It lacks account authentication, per-tenant authorization, durable encrypted storage, key-management controls, retention and deletion guarantees, rate limits, infrastructure monitoring, and independent security review. Client-facing deployment requires these additional layers. See `SECURITY_NOTES.md`.
