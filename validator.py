def _human_action(action):
    labels = {
        "removed_fully_empty_rows": "Removed empty rows",
        "removed_fully_empty_columns": "Removed empty columns",
        "renamed_unnamed_column": "Renamed unnamed column",
        "standardized_column_names": "Standardized column names",
        "trimmed_text_and_standardized_nulls": "Trimmed spaces and standardized blanks",
        "converted_text_to_numeric": "Converted numbers stored as text",
        "converted_text_to_datetime": "Converted dates stored as text",
        "standardized_categories": "Standardized category labels",
        "removed_exact_duplicate_rows": "Removed exact duplicate rows",
        "filled_numeric_missing_with_median": "Filled numeric missing values",
        "filled_categorical_missing_with_mode": "Filled categorical missing values",
        "flagged_outliers": "Flagged outliers",
        "removed_constant_columns": "Removed constant columns",
        "flagged_possible_duplicate_columns": "Flagged duplicate columns for review",
        "flagged_potential_duplicate_transactions": "Flagged potential duplicate transactions",
        "transformed_quickbooks_vendor_report": "Converted QuickBooks report to transaction table",
        "skipped_unapproved_decision": "Skipped unapproved change",
        "skipped_high_missing_column": "Skipped high-missing column",
        "needs_date_review": "Date values need review",
        "needs_numeric_review": "Numeric values need review",
        "skipped_business_critical_missing": "Critical missing values kept for review",
    }
    return labels.get(action, str(action).replace("_", " ").title())


def _event_details(event):
    if event.get("action") == "transformed_quickbooks_vendor_report":
        summary = event.get("summary", {}) or {}
        return (
            f"{summary.get('transactions_extracted', summary.get('final_rows', 0)):,} transactions extracted; "
            f"{summary.get('vendors_detected', 0):,} vendors detected; "
            f"Net amount total: {summary.get('net_amount_total', 0):,.2f}"
        )
    if event.get("column"):
        return str(event.get("column"))
    if event.get("old_column") and event.get("new_column"):
        return f"{event.get('old_column')} → {event.get('new_column')}"
    if isinstance(event.get("columns"), list):
        return ", ".join(map(str, event.get("columns")))
    if event.get("columns"):
        return str(event.get("columns"))
    if event.get("planned_action"):
        return str(event.get("planned_action"))
    return ""


def _is_quickbooks_transaction_table(df):
    cols = set(map(str, df.columns))
    return {"Vendor", "Transaction_Date", "Debit", "Credit", "Net_Amount"}.issubset(cols)


def _actionable_missing_count(df):
    if not _is_quickbooks_transaction_table(df):
        return int(df.isna().sum().sum())

    # In QuickBooks transaction tables, Debit/Credit are a mutually exclusive pair.
    # Memo, transaction number, cleared status, and split/account codes are often optional.
    expected_blank_cols = {
        "Debit", "Credit", "Memo", "Transaction_Number", "Cleared_Status",
        "Account_Code", "Split_Code"
    }
    required_cols = [c for c in df.columns if str(c) not in expected_blank_cols and not str(c).startswith("datatrust_")]
    if not required_cols:
        return 0
    return int(df[required_cols].isna().sum().sum())



def _calculate_datatrust_score(raw_df, clean_df, cleaning_summary, issues, warnings, pending, actionable_missing, remaining_duplicates):
    """Simple, explainable score for the MVP.
    This is intentionally deterministic: it rewards successful report-to-table conversion
    and penalizes unresolved review items, actionable missing values, and duplicate rows.
    """
    report_summary = cleaning_summary.get("report_summary") or {}
    issues_before = cleaning_summary.get("issues_found_before")

    if report_summary:
        # Raw accounting reports are not analysis-ready because report sections,
        # spacer columns, and vendor headers are mixed with transaction rows.
        before = 42
        after = 96
        after -= min(len(issues) * 20, 40)
        after -= min(len(pending) * 4, 20)
        after -= min(actionable_missing // 25, 10)
        # Repeated accounting rows are review signals, not automatic score killers.
        after -= min(remaining_duplicates // 100, 5)
    else:
        raw_missing = int(raw_df.isna().sum().sum())
        raw_duplicates = int(raw_df.duplicated().sum())
        before = 100
        before -= min(raw_missing // max(1, int(raw_df.shape[0] * raw_df.shape[1] * 0.01)), 35) if raw_df.size else 0
        before -= min(raw_duplicates * 2, 20)
        before -= min((issues_before or 0) * 4, 30)

        after = 100
        after -= min(actionable_missing // max(1, int(clean_df.shape[0] * max(clean_df.shape[1],1) * 0.01)), 30) if clean_df.size else 0
        after -= min(remaining_duplicates * 2, 20)
        after -= min(len(issues) * 20, 40)
        after -= min(len(warnings) * 5, 25)
        after -= min(len(pending) * 5, 25)

    before = int(max(0, min(100, round(before))))
    after = int(max(0, min(100, round(after))))
    return {
        "before": before,
        "after": after,
        "improvement": max(0, after - before),
        "method": "Experimental heuristic: NOT a calibrated accuracy or trust guarantee",
    }


def validate_cleaned_data(raw_df, clean_df, cleaning_summary):
    """
    Validate cleaning result without re-running generic diagnosis.
    For QuickBooks-transformed tables, expected accounting blanks are not treated
    like dirty missing values.
    """
    issues = []
    warnings = []

    raw_rows, raw_cols = raw_df.shape
    clean_rows, clean_cols = clean_df.shape
    report_summary = cleaning_summary.get("report_summary") or {}
    quickbooks_table = _is_quickbooks_transaction_table(clean_df)

    if clean_df.empty:
        issues.append("Dataset became empty after cleaning.")
    if clean_cols == 0:
        issues.append("All columns were removed.")

    row_loss_percent = ((raw_rows - clean_rows) / raw_rows * 100) if raw_rows else 0
    column_loss_percent = ((raw_cols - clean_cols) / raw_cols * 100) if raw_cols else 0

    # For report-to-table conversion, row loss is expected because vendor section
    # headers and spacer rows are removed. Validate against transformation summary.
    if not report_summary:
        if row_loss_percent > 30:
            issues.append(f"High row loss: {row_loss_percent:.2f}% rows removed.")
        elif row_loss_percent > 10:
            warnings.append(f"Moderate row loss: {row_loss_percent:.2f}% rows removed.")

    if not report_summary:
        if column_loss_percent > 60:
            issues.append(f"High column loss: {column_loss_percent:.2f}% columns removed.")
        elif column_loss_percent > 30:
            warnings.append(f"Moderate column loss: {column_loss_percent:.2f}% columns removed.")

    raw_missing = int(clean_df.isna().sum().sum())
    actionable_missing = _actionable_missing_count(clean_df)
    remaining_duplicates = int(clean_df.duplicated().sum())

    if actionable_missing > 0:
        warnings.append(f"{actionable_missing} actionable missing values remain after cleaning.")
    if remaining_duplicates > 0:
        if quickbooks_table:
            warnings.append(f"{remaining_duplicates} repeated transaction rows remain for accounting review.")
        else:
            warnings.append(f"{remaining_duplicates} duplicate rows remain after cleaning.")

    log = cleaning_summary.get("cleaning_log", [])
    resolved = []
    pending = []
    for event in log:
        action = event.get("action")
        label = _human_action(action)
        row = {
            "item": label,
            "details": _event_details(event),
            "risk": event.get("risk", "low"),
        }
        if action in ["skipped_unapproved_decision", "flagged_possible_duplicate_columns", "skipped_high_missing_column", "flagged_potential_duplicate_transactions", "needs_date_review", "needs_numeric_review", "skipped_business_critical_missing", "flagged_outliers", "skipped_flag_name_collision"]:
            row["details"] = event.get("reason") or row["details"]
            pending.append(row)
        else:
            resolved.append(row)

    if report_summary:
        resolved.insert(0, {
            "item": "QuickBooks report transformation",
            "details": (
                f"{report_summary.get('transactions_extracted', report_summary.get('final_rows', 0)):,} transactions; "
                f"{report_summary.get('vendors_detected', 0):,} vendors; "
                f"{report_summary.get('columns_removed_as_report_spacers', 0):,} spacer columns removed"
            ),
            "risk": "high",
        })

    def unique_rows(rows):
        seen = set()
        out = []
        for r in rows:
            key = (r.get("item"), str(r.get("details")), r.get("risk"))
            if key not in seen:
                seen.add(key)
                out.append(r)
        return out

    resolved = unique_rows(resolved)
    pending = unique_rows(pending)

    if pending:
        warnings.append(f"{len(pending)} review item(s) remain.")

    datatrust_score = _calculate_datatrust_score(
        raw_df, clean_df, cleaning_summary, issues, warnings, pending,
        actionable_missing, remaining_duplicates
    )

    if issues:
        status = "Needs Manual Review"
        export_status = "Blocked until review"
    elif pending:
        status = "Ready With Review"
        export_status = "Export allowed with review recommendations"
    else:
        status = "Ready"
        export_status = "Analytics-ready dataset generated"

    return {
        "status": status,
        "export_status": export_status,
        "issues": issues,
        "warnings": warnings,
        "issues_found_before": cleaning_summary.get("issues_found_before"),
        "resolved_count": len(resolved),
        "pending_count": len(pending),
        "resolved_actions": resolved,
        "pending_review": pending,
        "row_loss_percent": round(float(row_loss_percent), 2),
        "column_loss_percent": round(float(column_loss_percent), 2),
        "remaining_missing_values": actionable_missing,
        "raw_remaining_missing_values": raw_missing,
        "remaining_duplicate_rows": remaining_duplicates,
        "quickbooks_transaction_table": quickbooks_table,
        "report_summary": report_summary,
        "datatrust_score": datatrust_score,
        "changes_summary": {
            "rows_removed": cleaning_summary.get("rows_removed", 0),
            "columns_removed": cleaning_summary.get("columns_removed", 0),
            "missing_before": cleaning_summary.get("missing_before"),
            "missing_after_actionable": actionable_missing,
            "duplicates_before": cleaning_summary.get("duplicates_before"),
            "duplicates_after": cleaning_summary.get("duplicates_after"),
            "actions_logged": cleaning_summary.get("total_actions", 0),
        }
    }
