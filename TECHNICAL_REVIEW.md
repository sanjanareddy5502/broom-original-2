# Broom code review and iteration log

## What was wrong / why the UI felt complicated

The original `app.py` was ~500 lines and surfaced hero banners, repeated scorecards, problem cards, plan tables, four simultaneous export buttons, schema reports, audit logs and internal approval states. This overwhelmed a first-time user. It also displayed a prototype DataTrust score as if it were a confidence guarantee. The new `app.py` exposes **one main purpose per stage** and hides technical material behind expanders.

| Problem in uploaded version | What changed | How checked |
| --- | --- | --- |
| `cleaner._date_candidate` and `profiler._date_conversion` appended `2026` to missing-year date strings | No fabricated years; `date_intelligence.inspect_dates` examines entire column | test_dates_without_year... |
| Ambiguous `03/04/2026` parsed with implicit locale | Reviewer selects day-first / month-first; without evidence it remains unchanged | test_ambiguous_dates... |
| numeric conversion used `errors='coerce'` and threshold 85% (can silently destroy 15% of source values) | Entire numeric field is converted only if all nonblank values parse | test_numeric_conversion... |
| IDs or postal codes risk leading-zero loss | Identifier-like names never automatically undergo numeric conversion | test_inference_preserves... |
| the generic mode/median fill could overwrite missing financial values or dates | Protected critical fields, risk remains opt-in for noncritical fields | test_business_critical... |
| QuickBooks report conversion checked by default despite high risk | Conversion must be approved before advancing | test_quickbooks... |
| QuickBooks money parser lost commas, dollar signs, accounting negative numbers and invalid text | Parser supports currency string and refuses to silently discard invalid values | 2 QuickBooks tests |
| QuickBooks "spacer columns removed" was calculated as original columns minus derived schema width and could become negative | Count actual fully empty unnamed columns | test_quickbooks... |
| uploading the same file on Streamlit reruns destroyed downstream state | SHA256 file fingerprint resets only if bytes change | review in app.py; visual QA outstanding |
| validation could label output blocked but export buttons were still offered | Disable downloads on serious validation failures | review in app.py; visual QA outstanding |
| export of strings beginning `=` could be treated as spreadsheet formulas | Escape potentially executable formula-like text during exports | test_export_escapes... |
| no business context or temporal observations | Added local contextual analysis, year/month coverage, monthly counts and safely identified metric totals | engine tests + demo |

## Current product boundaries

- **Reliable engine**: inspect -> plan -> review -> transform -> validate.
- **Contextual business analyst**: heuristics for report type, basic schema role and historical monthly summaries, plus optional external model explanation of aggregates.
- **Not yet**: a trained model, accumulated learning from previous customers, adaptive knowledge base, end-to-end AI generated cleaning plans, production security or general-purpose natural-language querying.

## Recommended next build order

1. **Review 10 real but de-identified files** with expected outputs for different industries and record exact accuracy metrics. Do not assume "60%" has a measurable definition until a labeled test set exists.
2. Add **row-level exceptions table** in Step 3 so users can resolve individual ambiguous and invalid values instead of skipping an entire column.
3. Separate column role inference into date, identifier, currency, percentage, categorical, measured quantity, optional accounting field.
4. Add a **customer-confirmed data dictionary**, retained only with permission, to teach Broom how a recurring business's files should be interpreted over time.
5. Introduce structured AI cleaning plan suggestions that can use only a safe list of deterministic transformations; require human approval and validator invariants before applying.
6. Add an isolated, protected backend (authentication, tenant isolation, encrypted storage, deletion policy, event logging) before real client use.

## Verification performed

- Python syntax compilation for each source file.
- 13 targeted `pytest` unit/regression tests.
- 150 generated adversarial synthetic data examples through diagnose → decision → clean → validation → export with no runtime failures.
- **UI screenshot/interactive test not performed here**: Streamlit is unavailable in this execution environment and outbound package installation is blocked. The user should execute a quick five-step click test after local installation.
