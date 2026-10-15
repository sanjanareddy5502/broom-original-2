"""Local, explainable business-context analysis. No LLM or external connection needed."""
from __future__ import annotations
import pandas as pd
from date_intelligence import inspect_dates


def understand_dataset(df: pd.DataFrame, profile: dict | None = None) -> dict:
    """Summarize likely purpose, time span, and actionable quality questions.

    Never invent causal explanations, forecasts, or financial conclusions.
    """
    profile = profile or {}
    report = profile.get("report_profile", {}) or {}
    names = {str(c).lower(): str(c) for c in df.columns}
    if report.get("detected") or {"vendor", "net_amount"}.issubset(names):
        kind = "Vendor and accounting transactions"
    elif any("invoice" in c or "order" in c for c in names):
        kind = "Orders or invoices"
    elif any("member" in c or "customer" in c for c in names):
        kind = "Customer or membership records"
    else:
        kind = "Business spreadsheet (type not confirmed)"

    questions = []
    notes = []
    datetime_cols = []
    for col in df.columns:
        name = str(col)
        if pd.api.types.is_datetime64_any_dtype(df[col]):
            datetime_cols.append((name, df[col]))
        elif any(k in name.lower() for k in ("date", "time", "created", "updated")):
            evidence = inspect_dates(df[col])
            if evidence["status"] == "ready":
                datetime_cols.append((name, evidence["parsed"]))
            elif evidence.get("nonmissing", 0):
                questions.append(f"{name}: confirm date formats ({evidence.get('ambiguous_count',0)} ambiguous; {evidence.get('invalid_count',0)} invalid).")

    if profile.get("duplicate_rows", 0):
        questions.append(f"Are {profile['duplicate_rows']} repeated rows valid separate business events?")
    if profile.get("actionable_missing_values", 0) and not report.get("detected"):
        questions.append("Which missing fields are required, and which are legitimately optional?")

    time_info = None
    if datetime_cols:
        col, dates = datetime_cols[0]
        valid = pd.to_datetime(dates, errors="coerce").dropna()
        if len(valid) > 0:
            time_info = {"column": col, "first": valid.min().strftime("%Y-%m-%d"), "last": valid.max().strftime("%Y-%m-%d"), "records_with_dates": len(valid)}
            notes.append(f"Time coverage: {time_info['first']} to {time_info['last']} (based on {col}).")
            months = valid.dt.to_period("M").value_counts().sort_index()
            if len(months) >= 2:
                notes.append(f"Records by month: {months.index[-2]} = {int(months.iloc[-2])}, {months.index[-1]} = {int(months.iloc[-1])}. Counts are not revenue or performance measures.")
            # Only summarize an explicitly named numeric business metric, not arbitrary numeric IDs.
            for candidate in ("net_amount", "revenue", "sales", "amount", "spend", "total"):
                target = next((c for c in df.columns if candidate in str(c).lower() and pd.api.types.is_numeric_dtype(df[c])), None)
                if target is not None:
                    frame = pd.DataFrame({"month": valid.dt.to_period("M"), "value": df.loc[valid.index, target]})
                    monthly = frame.groupby("month")["value"].agg(["sum", "count"]).dropna()
                    if len(monthly) >= 2:
                        p, q = monthly.iloc[-2], monthly.iloc[-1]
                        notes.append(f"Observed {target} totals: {monthly.index[-2]} = {p['sum']:,.2f} across {int(p['count'])} records; {monthly.index[-1]} = {q['sum']:,.2f} across {int(q['count'])} records. This is descriptive only; incomplete months or missing records can distort comparisons.")
                    break
    if not time_info:
        notes.append("No trustworthy timeline yet. Confirm a date column before doing time-based analysis.")

    numeric_cols = [str(c) for c in df.select_dtypes(include="number").columns if not any(k in str(c).lower() for k in ("id", "code", "number", "zip"))]
    if numeric_cols:
        notes.append("Numeric measures available: " + ", ".join(numeric_cols[:5]) + ". Verify their business meaning before aggregating.")
    else:
        notes.append("No reliable numeric business measures detected yet.")
    return {"dataset_type": kind, "timeline": time_info, "observations": notes, "questions": questions[:8], "numeric_columns": numeric_cols[:10]}


def summarize_for_ai(intelligence: dict, profile: dict) -> dict:
    """Aggregates and type labels only; no row values. Column names may be sensitive."""
    return {
        "dataset_type": intelligence.get("dataset_type"),
        "rows": profile.get("rows"), "columns": profile.get("columns"),
        "problem_count": profile.get("problem_count"),
        "duplicate_row_count": profile.get("duplicate_rows"),
        "time_coverage": intelligence.get("timeline"),
        "observations": intelligence.get("observations", []),
        "review_questions": intelligence.get("questions", []),
    }
