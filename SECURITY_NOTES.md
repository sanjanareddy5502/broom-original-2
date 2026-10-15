# Broom security posture (prototype, not production approved)

## Implemented safeguards

1. CSV or XLSX only. 15 MB max and bounded row/column/cell counts.
2. XLSX archive expansion/part limits; macros, external workbook references and formulas rejected before import. A user should export a **values-only** copy first.
3. No arbitrary code generation/execution by the AI advisor. Cleaning actions are whitelisted in `broom_core/pipeline.py`.
4. Require explicit approval for high-risk transformations (date conversion, category merging, report reshaping, missing-value filling, duplicate deletion, constant-column removal).
5. Invalidate stale results whenever review selections change.
6. Use formula-safe CSV/Excel export copies; never modify uploaded source in place.
7. Optional external-model request requires explicit checkbox; only minimal aggregates shared. AI output cannot authorize data edits.
8. Streamlit XSRF/CORS settings and upload limit configured. These settings do not substitute for server security.
9. User-controlled JSON preferences are imported only for matching operations and do not authorize changes.

## High-priority work before using private client files

- Authenticate users and enforce authorization on **every** file, dataset and export.
- Isolate organizations and customers; test for cross-session and cross-tenant data leakage.
- Use a secured backend worker with CPU, memory, file and execution time budgets. The Streamlit demonstration is not an isolation boundary.
- Terminate TLS at a trusted proxy; add rate limits, allowlists, request limits, security headers, safe error handling and observability.
- Implement explicit retention/deletion policy; encrypt managed files at rest, control secrets, audit access, and confirm data processing agreements.
- Threat-model prompt injection, untrusted CSV/Excel contents, dependency vulnerabilities, malicious archives, and exported spreadsheets.
- Perform browser end-to-end tests with the pinned Streamlit release, load/large-file benchmarks, third-party dependency audit and external security review.
- Decide if and when external AI may receive **any** business metadata. Obtain customer consent and a contractual data-handling policy.
- Add CI plus automated regression gates, tested backup recovery and incident response.

**Never claim this prototype is secure enough for financial, legal, medical or other sensitive client records without those controls.**
