# Broom engineering iteration / quality assessment

## Changes in this code pass

- Introduced `broom_core` orchestration, upload policy, relationship checks and portable recipes.
- Strengthened mixed-format date parsing and rejected conflicting date conventions.
- Shared a conservative number parser between profiler and cleaner; added stricter QuickBooks amount conversion.
- Removed ambiguous `NA` and `-` from automatic null markers, protecting legitimate business values.
- Prevented category title-casing corrupting `USA`/brand spellings; changed category merges to **approval required**.
- Guarded existing system flag columns from being silently overwritten.
- Added detection of Excel formulas on upload, plus XLSX archive checks and source size limits.
- Fixed UI stale export problem with decision-plan fingerprints and added a safe approval gate in the shared workflow.
- Simplified review display by collapsing automatically selected steps.
- Added descriptive business overview with monthly counts, named measures, and line-total discrepancies, without pretending these are forecasts or causal findings.
- Added optional export/import of confirmed date-order preferences without storing customer data on a remote server.
- Limited resource-intensive duplicate-column matching to samples and disclosed the limitation.

## Test evidence

The project passes `python -m pytest -q` in the provided environment with pandas 2.2.3 and openpyxl 3.1.5. This includes 120 deterministic generated workflow cases, dozens of targeted regressions, and a five-stage Python UI-path smoke test using a facade.

**Not tested:** Live browser clicking and visual appearance in Streamlit; Streamlit could not be installed in this sandbox because the package index was unreachable. Also not established: cleaning accuracy against annotated real customer datasets, large-input throughput, user/tenant authorization, and operational production security.

## Honest product readiness

- **Ready for:** continued development, local demos with synthetic data, technical review, qualitative feedback.
- **Not ready for:** public SaaS deployment, confidential accounting/legal/health client datasets, autonomous unattended edits or selling as a mature intelligent business-analyst platform.
- The product is still a deterministic cleaning engine plus structured business heuristics, with an optional external AI explanation. It is **not** a trained self-improving AI.

## Priority next steps

1. Run real Streamlit UI click-through and repair anything broken on the user's computer.
2. Create a reference corpus of 25–50 labeled synthetic or de-identified datasets and measure cell-level cleaning precision, recall, untouched-value preservation, and transformations that required human approval.
3. Add per-cell exceptions resolution for mixed or invalid dates, not just all-or-nothing column conversion.
4. Add customer-confirmed column meaning dictionaries, relationships, units and business-specific rules, with explicit storage consent.
5. Add granular reconciliation invariants for invoice/order/accounting data; avoid optimistic quality-score claims.
6. Build authenticated backend, tenant isolation, encrypted storage, deletion/recovery policy, operational alerting and external security review before customer production use.

**Rating:** No numeric "9/10" claim is made. Code quality has been strengthened and regression-tested, but production readiness cannot be scored as 9/10 without the missing external and real-world verification.
