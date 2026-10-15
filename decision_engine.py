def _decision(issue, action, risk, confidence, reason, columns=None, requires_approval=False, metadata=None):
    return {
        "issue": issue,
        "action": action,
        "risk": risk,
        "confidence": confidence,
        "reason": reason,
        "columns": columns or [],
        "requires_approval": bool(requires_approval),
        "approved": not bool(requires_approval),
        "metadata": metadata or {},
    }


def decide_cleaning_actions(profile):
    """Create a practical cleaning plan from profiler output."""
    decisions = []

    report_profile = profile.get("report_profile", {}) or {}
    if report_profile.get("detected") and report_profile.get("report_type") == "quickbooks_vendor_transaction_report":
        report_decision = _decision(
            "QuickBooks report layout",
            "transform_quickbooks_vendor_report",
            "high",
            report_profile.get("confidence", 0.90),
            "Convert the QuickBooks report export into a clean transaction table with vendor names filled down, spacer columns removed, and net amount calculated.",
            columns=["Vendor", "Type", "Date", "Account", "Split", "Debit", "Credit"],
            requires_approval=True,
            metadata=report_profile,
        )
        # Report conversion changes the shape of data. The user must explicitly approve it.
        report_decision["approved"] = False
        decisions.append(report_decision)
        # For report-style exports, do not stack generic cleaning actions on raw report layout.
        # First convert to a canonical transaction table. Generic diagnosis/cleaning can run
        # on the transformed table afterward if needed.
        return decisions

    if profile.get("fully_empty_rows", 0) > 0:
        decisions.append(_decision(
            "Fully empty rows", "remove_fully_empty_rows", "low", 0.99,
            "Rows with no values contain no useful information."
        ))

    if profile.get("fully_empty_columns"):
        decisions.append(_decision(
            "Fully empty columns", "remove_fully_empty_columns", "low", 0.99,
            "Columns with no values contain no useful information.",
            columns=profile.get("fully_empty_columns", [])
        ))

    if profile.get("unnamed_columns"):
        decisions.append(_decision(
            "Unnamed columns", "preserve_and_rename", "medium", 0.90,
            "Unnamed columns may contain useful exported data, so preserve them and rename for review.",
            columns=profile.get("unnamed_columns", [])
        ))

    if profile.get("duplicate_value_columns"):
        pairs = profile.get("duplicate_value_columns", [])
        decisions.append(_decision(
            "Possible duplicate columns", "flag_duplicate_columns", "high", 0.92,
            "Columns with almost identical values should be reviewed before dropping. DataTrust will flag them, not delete them automatically.",
            columns=[f"{p['column_a']} / {p['column_b']}" for p in pairs],
            requires_approval=False,
            metadata={"pairs": pairs}
        ))

    if profile.get("columns_needing_standardization"):
        decisions.append(_decision(
            "Column name standardization", "standardize_column_names", "low", 0.99,
            "Clean column names make data easier to use in charts, transformations, and models.",
            columns=profile.get("columns_needing_standardization", [])
        ))

    if profile.get("trailing_space_columns") or profile.get("category_inconsistent_columns") or profile.get("total_missing_values", 0) > 0:
        decisions.append(_decision(
            "Messy text and null-like values", "trim_text_and_standardize_nulls", "low", 0.99,
            "Trim spaces and convert blank/null-like strings into real missing values."
        ))

    if profile.get("possible_numeric_columns"):
        decisions.append(_decision(
            "Numbers stored as text", "convert_text_to_numeric", "low", 0.90,
            "Convert only when all nonblank values are safely parseable; otherwise preserve the original.",
            columns=profile.get("possible_numeric_columns", [])
        ))

    if profile.get("possible_date_columns"):
        decisions.append(_decision(
            "Dates need review", "convert_text_to_datetime", "medium", 0.88,
            "Convert only when every nonblank date can be interpreted safely. Ambiguous values will be preserved.",
            columns=profile.get("possible_date_columns", []), requires_approval=True
        ))

    if profile.get("category_inconsistent_columns"):
        decisions.append(_decision(
            "Inconsistent category labels", "standardize_categories", "low", 0.86,
            "Merge only case/whitespace variants using an observed label. This may change business naming and requires approval.",
            columns=profile.get("category_inconsistent_columns", []), requires_approval=True
        ))

    if profile.get("duplicate_rows", 0) > 0:
        if profile.get("accounting_transaction_table"):
            decisions.append(_decision(
                "Potential duplicate transactions", "flag_duplicate_transactions", "medium", 0.85,
                "Repeated accounting transactions can be valid. DataTrust will flag them for review instead of deleting them.",
                requires_approval=False
            ))
        else:
            decisions.append(_decision(
                "Exact duplicate rows", "remove_exact_duplicate_rows", "medium", 0.85,
                "Exact duplicates may inflate totals. Reviewable because repeated business events can be valid.",
                requires_approval=True
            ))

    fillable_missing = profile.get("actionable_missing_values", profile.get("total_missing_values", 0)) > 0 and len(profile.get("fully_empty_columns", [])) < profile.get("columns", 0)
    if fillable_missing:
        decisions.append(_decision(
            "Missing values", "fill_missing_values", "medium", 0.82,
            "Optional: estimate missing values with median/mode; can change business meaning. Never use on critical accounting/identifier fields.",
            requires_approval=True
        ))

    if profile.get("outlier_columns"):
        decisions.append(_decision(
            "Outliers", "flag_outliers", "medium", 0.80,
            "Flag outliers for review. Do not delete automatically.",
            columns=profile.get("outlier_columns", [])
        ))

    if profile.get("constant_columns"):
        decisions.append(_decision(
            "Constant columns", "remove_constant_columns", "low", 0.80,
            "Constant columns add little analytical value.",
            columns=profile.get("constant_columns", []),
            requires_approval=True
        ))

    return decisions
