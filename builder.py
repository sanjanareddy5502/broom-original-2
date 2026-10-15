import json
from io import BytesIO
import re
import pandas as pd


def _safe_df(records):
    if records is None:
        return pd.DataFrame()
    if isinstance(records, pd.DataFrame):
        return records
    if isinstance(records, list):
        return pd.DataFrame(records)
    if isinstance(records, dict):
        return pd.DataFrame([records])
    return pd.DataFrame([{"value": str(records)}])





def _spreadsheet_safe(df):
    """Prevent formula-like user strings from executing when opened in spreadsheets.

    This applies to export copies only and does not mutate the user's original data.
    """
    safe = df.copy()
    for col in safe.columns:
        if pd.api.types.is_object_dtype(safe[col]) or pd.api.types.is_string_dtype(safe[col]):
            safe[col] = safe[col].map(lambda v: ("'" + v) if isinstance(v, str) and re.match(r"^\s*[=+@-]", v) else v)
    return safe

def _build_executive_summary(before_profile, cleaning_summary, validation_report):
    report_summary = cleaning_summary.get("report_summary") or {}
    score = validation_report.get("datatrust_score", {}) or {}
    lines = []
    lines.append("DataTrust Executive Summary")
    lines.append("=" * 32)
    lines.append("")
    if report_summary:
        lines.append("Dataset Type: QuickBooks Vendor Transaction Report")
        lines.append("Transformation: Report-to-table conversion")
        lines.append("")
        lines.append(f"Rows Processed: {cleaning_summary.get('original_rows', 0):,}")
        lines.append(f"Transactions Extracted: {report_summary.get('transactions_extracted', report_summary.get('final_rows', 0)):,}")
        lines.append(f"Vendors Identified: {report_summary.get('vendors_detected', 0):,}")
        lines.append(f"Spacer Columns Removed: {report_summary.get('columns_removed_as_report_spacers', 0):,}")
        lines.append(f"Net Amount Total: {report_summary.get('net_amount_total', 0):,.2f}")
        lines.append("")
    else:
        lines.append("Dataset Type: Generic tabular dataset")
        lines.append(f"Rows Processed: {cleaning_summary.get('original_rows', 0):,}")
        lines.append(f"Final Rows: {cleaning_summary.get('final_rows', 0):,}")
        lines.append(f"Columns Removed: {cleaning_summary.get('columns_removed', 0):,}")
        lines.append("")

    if score:
        lines.append("DataTrust Score")
        lines.append(f"Before: {score.get('before')}/100")
        lines.append(f"After: {score.get('after')}/100")
        lines.append(f"Improvement: +{score.get('improvement')}")
        lines.append("")

    lines.append("Business Impact")
    if report_summary:
        impact = [
            "Converted a formatted QuickBooks report into an analytics-ready transaction table",
            f"Extracted {report_summary.get('transactions_extracted', report_summary.get('final_rows', 0)):,} transaction rows",
            f"Identified {report_summary.get('vendors_detected', 0):,} vendor sections",
            f"Removed {report_summary.get('columns_removed_as_report_spacers', 0):,} report spacer columns",
            "Created Net_Amount for spend and vendor analysis",
            "Preserved the original file and logged the transformation for audit review",
        ]
    else:
        impact = [
            "Diagnosed dataset quality issues",
            "Applied approved cleaning actions",
            "Generated cleaned dataset and audit report",
            "Preserved the original file for traceability",
        ]
    for item in impact:
        lines.append(f"- {item}")
    lines.append("")

    lines.append("Export Status")
    lines.append(str(validation_report.get("export_status", "Unknown")))
    lines.append("")

    pending = validation_report.get("pending_review", []) or []
    if pending:
        lines.append("Review Items")
        for item in pending:
            lines.append(f"- {item.get('item')}: {item.get('details')}")
    else:
        lines.append("Review Items: None")

    return "\n".join(lines)


def build_outputs(clean_df, before_profile, after_profile, decisions, cleaning_summary, validation_report, problems_df=None):
    report = {
        "product": "DataTrust Core Cleaning MVP",
        "before_profile": before_profile,
        "problems_found": _safe_df(problems_df).to_dict(orient="records"),
        "cleaning_plan": decisions,
        "cleaning_summary": cleaning_summary,
        "after_profile": after_profile,
        "validation_report": validation_report,
    }

    export_df = _spreadsheet_safe(clean_df)
    csv_output = export_df.to_csv(index=False)
    json_output = json.dumps(report, indent=4, default=str)
    executive_summary = _build_executive_summary(before_profile, cleaning_summary, validation_report)

    excel_buffer = BytesIO()
    with pd.ExcelWriter(excel_buffer, engine="openpyxl") as writer:
        export_df.to_excel(writer, sheet_name="cleaned_data", index=False)
        _spreadsheet_safe(_safe_df(problems_df)).to_excel(writer, sheet_name="problems_found", index=False)
        _spreadsheet_safe(_safe_df(decisions)).to_excel(writer, sheet_name="cleaning_plan", index=False)
        _spreadsheet_safe(_safe_df(cleaning_summary.get("cleaning_log", []))).to_excel(writer, sheet_name="cleaning_log", index=False)
        report_summary = cleaning_summary.get("report_summary") or {}
        if report_summary:
            _spreadsheet_safe(_safe_df(report_summary)).to_excel(writer, sheet_name="report_summary", index=False)
            _spreadsheet_safe(_safe_df(report_summary.get("top_vendors", []))).to_excel(writer, sheet_name="top_vendors", index=False)
        _spreadsheet_safe(_safe_df(validation_report.get("resolved_actions", []))).to_excel(writer, sheet_name="resolved_actions", index=False)
        _spreadsheet_safe(_safe_df(validation_report.get("pending_review", []))).to_excel(writer, sheet_name="pending_review", index=False)
        _spreadsheet_safe(_safe_df(validation_report)).to_excel(writer, sheet_name="validation_summary", index=False)
    excel_buffer.seek(0)

    return {"csv": csv_output, "json_report": json_output, "excel": excel_buffer, "executive_summary": executive_summary}
