import re
import warnings
import pandas as pd
from report_intelligence import detect_report_structure
from date_intelligence import inspect_dates
from numeric_intelligence import parse_series

NULL_LIKE_VALUES = ["", " ", "nan", "NaN", "None", "NULL", "null", "N/A", "n/a", "NA", "na", "-", "--", "none"]
ORDINAL_PATTERN = re.compile(r"\b(\d{1,2})(st|nd|rd|th)\b", flags=re.IGNORECASE)
ID_VALUE_PATTERNS = [
    re.compile(r"^[A-Za-z]{1,10}[-_ ]?\d{1,12}$"),      # T1, EMP001, INV-1001
    re.compile(r"^[A-Za-z]{1,10}[-_ ]?\d{1,6}[-_ ]?\d{1,6}$"),
    re.compile(r"^\d{3,}$"),                              # 1001, 1002 as IDs when unique
]
DATE_SIGNAL_PATTERN = re.compile(
    r"(\d{1,4}[-/]\d{1,2}[-/]\d{1,4})|"
    r"(\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\b)|"
    r"(\b\d{1,2}(st|nd|rd|th)?\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\b)|"
    r"(\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\s+\d{1,2}(st|nd|rd|th)?\b)",
    flags=re.IGNORECASE,
)

SYSTEM_PREFIXES = ("datatrust_",)
SYSTEM_SUFFIXES = ("_flag", "_review", "_outlier_flag")


def is_system_column(col) -> bool:
    name = str(col).lower()
    return name.startswith(SYSTEM_PREFIXES) or name.endswith(SYSTEM_SUFFIXES)


def classify_missing_severity(missing_percent):
    if missing_percent == 0:
        return "none"
    if missing_percent < 5:
        return "low"
    if missing_percent < 25:
        return "medium"
    if missing_percent < 60:
        return "high"
    return "critical"


def _as_clean_text(series):
    return series.astype("string").str.strip().replace(NULL_LIKE_VALUES, pd.NA)


def _numeric_conversion(series):
    return parse_series(series)


def _date_conversion(series):
    if pd.api.types.is_bool_dtype(series) or pd.api.types.is_numeric_dtype(series):
        return pd.Series([pd.NaT] * len(series), index=series.index)
    cleaned = _as_clean_text(series)
    cleaned = cleaned.str.replace(ORDINAL_PATTERN, r"\1", regex=True)
    has_month_text = cleaned.str.contains(
        r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)",
        case=False,
        na=False,
        regex=True,
    )
    has_year = cleaned.str.contains(r"\b\d{4}\b", na=False, regex=True)
    cleaned = cleaned.where(~(has_month_text & ~has_year), pd.NA)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        return pd.to_datetime(cleaned, errors="coerce")


def _looks_like_identifier_column(series, column_name=""):
    """Detect ID-like columns before attempting date/numeric conversion.

    This prevents values like T1, T2, T3 from being misread as dates.
    """
    clean = _as_clean_text(series).dropna()
    if clean.empty:
        return False

    name = str(column_name).lower()
    unique_ratio = clean.nunique(dropna=True) / max(len(clean), 1)
    sample = clean.astype(str).head(200)
    pattern_ratio = sample.apply(lambda v: any(p.match(v.strip()) for p in ID_VALUE_PATTERNS)).mean()

    name_says_id = any(token in name for token in ["id", "_id", "task", "job", "project", "invoice", "ticket", "record", "key", "code", "zip", "postal", "phone", "sku", "account", "tracking", "reference"])

    if unique_ratio >= 0.90 and (pattern_ratio >= 0.70 or name_says_id):
        return True
    if name_says_id and pattern_ratio >= 0.50:
        return True
    return False


def _real_date_signal_ratio(series):
    clean = _as_clean_text(series).dropna().astype(str)
    if clean.empty:
        return 0.0
    sample = clean.head(200)
    return float(sample.apply(lambda x: bool(DATE_SIGNAL_PATTERN.search(x))).mean())


def _needs_column_standardization(columns):
    """Return columns that are genuinely messy, not merely Title_Case snake-style names.

    Task_ID is acceptable. Unnamed: 4, age.1, spaces, hyphens, and special chars are not.
    """
    messy = []
    for col in columns:
        text = str(col)
        stripped = text.strip()
        if stripped != text or stripped == "" or "unnamed" in stripped.lower():
            messy.append(str(col))
            continue
        if not re.match(r"^[A-Za-z][A-Za-z0-9_]*$", stripped):
            messy.append(str(col))
            continue
        if "__" in stripped:
            messy.append(str(col))
    return messy


def _outlier_count(series):
    """IQR outlier count that is safe for bool, text, dates, and mixed columns."""
    if pd.api.types.is_bool_dtype(series) or pd.api.types.is_datetime64_any_dtype(series):
        return 0

    numeric = pd.to_numeric(series, errors="coerce").dropna()

    if len(numeric) < 5:
        return 0

    q1 = numeric.quantile(0.25)
    q3 = numeric.quantile(0.75)
    iqr = q3 - q1

    if pd.isna(iqr) or iqr == 0:
        return 0

    lower = q1 - 1.5 * iqr
    upper = q3 + 1.5 * iqr

    return int(((numeric < lower) | (numeric > upper)).sum())


def _trailing_space_count(series):
    if not (pd.api.types.is_object_dtype(series) or pd.api.types.is_string_dtype(series)):
        return 0
    non_null = series.dropna().astype(str)
    return int((non_null != non_null.str.strip()).sum())


def _category_inconsistency_count(series):
    if not (pd.api.types.is_object_dtype(series) or pd.api.types.is_string_dtype(series)):
        return 0
    non_null = _as_clean_text(series).dropna()
    if non_null.empty:
        return 0
    raw_unique = non_null.nunique(dropna=True)
    normalized_unique = non_null.str.lower().nunique(dropna=True)
    return int(max(raw_unique - normalized_unique, 0))


def _normalized_for_compare(series):
    return _as_clean_text(series).astype("string").str.lower()


def _duplicate_value_columns(df, threshold=0.95):
    """Bounded duplicate-column *screen*, not a guarantee of no duplicate columns.

    Comparing every column pair on every row is quadratic and can freeze a demo.
    We sample at most 1,500 rows and 70 non-system columns. The scan limit is
    disclosed to users in the profile when the dataset is larger.
    """
    pairs = []
    sample = df.iloc[:1500]
    cols = [c for c in df.columns if not is_system_column(c)][:70]
    normalized = {col: _normalized_for_compare(sample[col]) for col in cols}
    for i, col_a in enumerate(cols):
        a = normalized[col_a]
        for col_b in cols[i + 1:]:
            b = normalized[col_b]
            valid = a.notna() | b.notna()
            if not bool(valid.any()):
                continue
            similarity = float((a[valid].fillna('<MISSING>') == b[valid].fillna('<MISSING>')).mean())
            if similarity >= threshold:
                pairs.append({
                    'column_a': str(col_a),
                    'column_b': str(col_b),
                    'similarity': round(similarity, 3),
                })
    return pairs


def _add_problem(rows, problem, column, severity, impact, recommended_fix, evidence=""):
    rows.append({
        "problem": problem,
        "column": str(column),
        "severity": severity,
        "impact": impact,
        "recommended_fix": recommended_fix,
        "evidence": evidence,
    })


def build_missing_value_intelligence(df):
    rows = []
    for col in df.columns:
        if is_system_column(col):
            continue
        missing_mask = df[col].isna()
        missing_count = int(missing_mask.sum())
        if missing_count == 0:
            continue
        missing_percent = round(float(missing_mask.mean() * 100), 2)
        rows.append({
            "column": str(col),
            "missing_count": missing_count,
            "missing_percent": missing_percent,
            "severity": classify_missing_severity(missing_percent),
            "recommended_action": "remove if fully empty" if missing_percent == 100 else "fill or review based on business meaning",
            "sample_missing_rows": missing_mask[missing_mask].index.tolist()[:20],
        })
    return pd.DataFrame(rows)


def _is_accounting_transaction_table(df: pd.DataFrame) -> bool:
    cols = {str(c) for c in df.columns}
    required = {"Vendor", "Transaction_Date", "Debit", "Credit", "Net_Amount"}
    return required.issubset(cols)


def _expected_accounting_blank_columns(df: pd.DataFrame) -> set[str]:
    if not _is_accounting_transaction_table(df):
        return set()
    optional = {"Debit", "Credit", "Memo", "Transaction_Number", "Cleared_Status", "Account_Code", "Split_Code"}
    return {c for c in optional if c in set(map(str, df.columns))}


def profile_dataset(df: pd.DataFrame):
    problem_rows = []
    issues = []

    user_cols = [c for c in df.columns if not is_system_column(c)]
    user_df = df[user_cols].copy()
    report_profile = detect_report_structure(user_df)
    is_report_layout = bool(report_profile.get("detected"))
    is_accounting_table = _is_accounting_transaction_table(user_df)
    expected_blank_columns = _expected_accounting_blank_columns(user_df)

    rows, cols = user_df.shape
    total_missing = int(user_df.isna().sum().sum())
    actionable_missing_values = int(user_df[[c for c in user_df.columns if str(c) not in expected_blank_columns]].isna().sum().sum()) if len(user_df.columns) else 0
    duplicate_rows = int(user_df.duplicated().sum())
    fully_empty_rows = int(user_df.isna().all(axis=1).sum())
    fully_empty_columns = [str(c) for c in user_df.columns if user_df[c].isna().all()]
    unnamed_columns = [str(c) for c in user_df.columns if str(c).strip() == "" or "unnamed" in str(c).lower()]
    duplicate_name_columns = [str(c) for c in user_df.columns[user_df.columns.duplicated()]]
    duplicate_value_columns = _duplicate_value_columns(user_df)
    duplicate_scan_limited = rows > 1500 or len(user_cols) > 70
    if is_accounting_table:
        # Credit and Net_Amount can naturally be almost identical in credit-heavy reports.
        # That is not a duplicate-column problem; it is a derived accounting field.
        derived_pairs = [{"Credit", "Net_Amount"}, {"Debit", "Net_Amount"}]
        duplicate_value_columns = [
            p for p in duplicate_value_columns
            if {p.get("column_a"), p.get("column_b")} not in derived_pairs
        ]

    high_missing_columns = []
    possible_numeric_columns = []
    possible_date_columns = []
    mixed_type_columns = []
    outlier_columns = []
    category_inconsistent_columns = []
    constant_columns = []
    trailing_space_columns = []
    identifier_columns = []
    columns_needing_standardization = [] if is_report_layout else _needs_column_standardization(user_df.columns)

    if is_report_layout:
        _add_problem(
            problem_rows,
            "Report-style export detected",
            report_profile.get("display_name", "report layout"),
            "high",
            "This file is a formatted report, not a clean table. Vendor names and transaction rows are mixed together.",
            report_profile.get("recommended_action", "Convert the report to a flat analysis-ready table."),
            f"{report_profile.get('vendor_header_rows', 0)} vendor header rows; {report_profile.get('unnamed_column_ratio', 0) * 100:.0f}% unnamed/spacer columns",
        )
        if fully_empty_columns:
            _add_problem(
                problem_rows,
                "Report spacer columns",
                f"{len(fully_empty_columns)} columns",
                "medium",
                "Report exports often contain blank spacer columns that are not useful for analysis.",
                "Remove spacer columns during report-to-table conversion.",
                ", ".join(fully_empty_columns[:8]) + ("..." if len(fully_empty_columns) > 8 else ""),
            )

    # Report-style exports should not be diagnosed like normal flat tables.
    # For QuickBooks reports, blank cells in vendor header rows, spacer columns,
    # and debit/credit pairs are expected layout artifacts. The right first action
    # is report-to-table conversion, then re-profile the transformed table.
    if is_report_layout:
        problems_df = pd.DataFrame(problem_rows).drop_duplicates() if problem_rows else pd.DataFrame()
        missing_intelligence = pd.DataFrame([
            {
                "column": "Report layout",
                "missing_count": total_missing,
                "missing_percent": round(float(total_missing / max(rows * cols, 1) * 100), 2),
                "severity": "expected_layout",
                "recommended_action": "Convert the report to a transaction table before evaluating missing values.",
                "sample_missing_rows": [],
            }
        ])
        column_report = pd.DataFrame({
            "column": [str(col) for col in user_df.columns],
            "dtype": [str(user_df[col].dtype) for col in user_df.columns],
            "missing_count": [int(user_df[col].isna().sum()) for col in user_df.columns],
            "missing_percent": [round(float(user_df[col].isna().mean() * 100), 2) for col in user_df.columns],
            "unique_values": [int(user_df[col].nunique(dropna=True)) for col in user_df.columns],
            "detected_role": ["report_spacer" if str(col) in fully_empty_columns or "unnamed" in str(col).lower() else "report_field" for col in user_df.columns],
            "sample_values": [", ".join(user_df[col].dropna().astype(str).head(3).tolist()) for col in user_df.columns],
        })
        profile = {
            "rows": int(rows),
            "columns": int(cols),
            "total_missing_values": total_missing,
            "duplicate_rows": duplicate_rows,
            "fully_empty_rows": fully_empty_rows,
            "fully_empty_columns": fully_empty_columns,
            "unnamed_columns": unnamed_columns,
            "duplicate_columns": duplicate_name_columns,
            "duplicate_value_columns": [],
            "high_missing_columns": [],
            "possible_numeric_columns": [],
            "possible_date_columns": [],
            "mixed_type_columns": [],
            "outlier_columns": [],
            "category_inconsistent_columns": [],
            "constant_columns": [],
            "trailing_space_columns": [],
            "identifier_columns": [],
            "columns_needing_standardization": [],
            "report_profile": report_profile,
            "report_type": report_profile.get("report_type", "flat_table"),
            "system_columns_ignored": [str(c) for c in df.columns if is_system_column(c)],
            "issues_found": [
                f"Report-style export detected: {report_profile.get('display_name')}",
                f"{report_profile.get('vendor_header_rows', 0)} vendor section/header rows detected.",
                f"{len(fully_empty_columns)} spacer/empty columns detected.",
            ],
            "problem_count": int(len(problems_df)) if not problems_df.empty else 0,
        }
        return profile, column_report, missing_intelligence, problems_df

    if duplicate_rows > 0:
        if is_accounting_table:
            _add_problem(problem_rows, "Potential duplicate transactions", "row-level", "medium", "Repeated accounting transactions can be valid, but exact duplicate rows should be reviewed before reporting.", "Flag duplicate transactions for review; do not remove automatically.", f"{duplicate_rows} exact repeated rows")
        else:
            _add_problem(problem_rows, "Exact duplicate rows", "row-level", "medium", "Duplicate rows can inflate totals and distort reports.", "Review and remove exact duplicate rows if they are accidental.", f"{duplicate_rows} duplicate rows")
    if fully_empty_rows > 0:
        _add_problem(problem_rows, "Fully empty rows", "row-level", "low", "Rows with no values add no analytical value.", "Remove fully empty rows.", f"{fully_empty_rows} rows")
    if duplicate_name_columns:
        _add_problem(problem_rows, "Duplicate column names", ", ".join(duplicate_name_columns), "high", "Duplicate column names can break transformations and exports.", "Rename or merge duplicate columns after review.")
    for pair in duplicate_value_columns:
        _add_problem(problem_rows, "Possible duplicate columns", f"{pair['column_a']} / {pair['column_b']}", "high", "The same data appears in multiple columns, which can confuse analysis and modeling.", "Review and remove or merge one duplicate column.", f"{pair['similarity']*100:.1f}% value similarity")

    for col in user_df.columns:
        series = user_df[col]
        name = str(col)
        non_null_count = int(series.notna().sum())
        unique_count = int(series.nunique(dropna=True))
        missing_percent = round(float(series.isna().mean() * 100), 2)
        expected_blank_column = name in expected_blank_columns
        is_identifier = _looks_like_identifier_column(series, name)
        if is_identifier:
            identifier_columns.append(name)

        if name in unnamed_columns and not is_report_layout:
            _add_problem(problem_rows, "Unnamed column", name, "medium", "The column has no meaningful name, so downstream users will not know what it represents.", "Preserve the data but rename the column for review.")

        if name in fully_empty_columns:
            if not is_report_layout:
                _add_problem(problem_rows, "Fully empty column", name, "critical", "This column contains no usable values.", "Remove the column unless it is required as a placeholder.", "100% missing")
            continue

        if missing_percent > 50 and not expected_blank_column:
            high_missing_columns.append(name)

        if non_null_count > 0 and unique_count <= 1:
            constant_columns.append(name)
            _add_problem(problem_rows, "Constant column", name, "low", "This column has only one unique value and adds little analytical value.", "Remove if it is not needed for context or audit.", f"{unique_count} unique value")

        trailing_spaces = _trailing_space_count(series)
        if trailing_spaces > 0:
            trailing_space_columns.append(name)
            _add_problem(problem_rows, "Trailing or leading spaces", name, "low", "Extra spaces create duplicate-looking categories and messy exports.", "Trim spaces from text values.", f"{trailing_spaces} values")

        converted_numeric = _numeric_conversion(series)
        numeric_ratio = float(converted_numeric.notna().mean())
        date_result = inspect_dates(series)
        date_ratio = float(1 - (date_result.get("invalid_count", 0) / max(date_result.get("nonmissing", 0), 1))) if date_result.get("nonmissing", 0) else 0
        real_date_signal = _real_date_signal_ratio(series)

        if (not is_identifier) and numeric_ratio >= 0.85 and not pd.api.types.is_numeric_dtype(series) and not pd.api.types.is_bool_dtype(series):
            possible_numeric_columns.append(name)
            _add_problem(problem_rows, "Numeric values stored as text", name, "medium", "Calculations, charts, and forecasts may fail or be incorrect.", "Convert this column to numeric.", f"{numeric_ratio:.0%} parseable as numbers")

        if (not is_identifier) and date_ratio >= 0.70 and real_date_signal >= 0.70 and not pd.api.types.is_datetime64_any_dtype(series):
            possible_date_columns.append(name)
            _add_problem(problem_rows, "Date values need standardization", name, "medium", "Inconsistent or ambiguous dates can distort time-series analysis.", "Confirm ambiguous day/month formats before conversion.", f"{date_result.get('ambiguous_count', 0)} ambiguous; {date_result.get('invalid_count', 0)} invalid values")

        if (not is_identifier) and 0.30 < numeric_ratio < 0.85 and not pd.api.types.is_numeric_dtype(series) and not pd.api.types.is_bool_dtype(series):
            mixed_type_columns.append(name)
            _add_problem(problem_rows, "Mixed numeric/text values", name, "high", "Mixed types can break calculations and model features.", "Review and standardize values manually or with rules.", f"{numeric_ratio:.0%} numeric-like")

        if (not is_identifier) and (not (is_accounting_table and name in {"Debit", "Credit", "Net_Amount"})) and (numeric_ratio >= 0.85 or pd.api.types.is_numeric_dtype(series)) and not pd.api.types.is_bool_dtype(series):
            safe_numeric = converted_numeric if numeric_ratio >= 0.85 else pd.to_numeric(series, errors="coerce")
            outliers = _outlier_count(safe_numeric)
            if outliers > 0:
                outlier_columns.append(name)
                _add_problem(problem_rows, "Numeric outliers detected", name, "medium", "Extreme values may distort averages, charts, and forecasts.", "Flag outliers for review; do not delete automatically.", f"{outliers} outliers")

        inconsistencies = _category_inconsistency_count(series)
        if is_accounting_table and name in {"Memo", "Transaction_Number"}:
            inconsistencies = 0
        if inconsistencies > 0:
            category_inconsistent_columns.append(name)
            _add_problem(problem_rows, "Category casing/spacing inconsistency", name, "low", "The same category may be counted as multiple categories.", "Trim spaces and standardize category casing.", f"{inconsistencies} duplicate-looking categories")

        if missing_percent > 0 and not expected_blank_column:
            _add_problem(problem_rows, "Missing values", name, classify_missing_severity(missing_percent), "Missing values can reduce reliability of analysis and models.", "Fill low/medium missing values; review high missing values.", f"{missing_percent}% missing")

    if total_missing > 0:
        issues.append(f"{total_missing} missing values found.")
    if duplicate_rows > 0:
        issues.append(f"{duplicate_rows} duplicate rows found.")
    if fully_empty_columns:
        issues.append(f"{len(fully_empty_columns)} fully empty columns found: {fully_empty_columns}")
    if unnamed_columns:
        issues.append(f"{len(unnamed_columns)} unnamed columns found: {unnamed_columns}")
    if duplicate_value_columns:
        issues.append(f"{len(duplicate_value_columns)} possible duplicate column pairs found.")
    if possible_date_columns:
        issues.append(f"{len(possible_date_columns)} date-like text columns found: {possible_date_columns}")
    if trailing_space_columns:
        issues.append(f"{len(trailing_space_columns)} columns contain leading/trailing spaces.")

    problems_df = pd.DataFrame(problem_rows).drop_duplicates() if problem_rows else pd.DataFrame()
    missing_intelligence = build_missing_value_intelligence(user_df)
    column_report = pd.DataFrame({
        "column": [str(col) for col in user_df.columns],
        "dtype": [str(user_df[col].dtype) for col in user_df.columns],
        "missing_count": [int(user_df[col].isna().sum()) for col in user_df.columns],
        "missing_percent": [round(float(user_df[col].isna().mean() * 100), 2) for col in user_df.columns],
        "unique_values": [int(user_df[col].nunique(dropna=True)) for col in user_df.columns],
        "trailing_space_count": [_trailing_space_count(user_df[col]) for col in user_df.columns],
        "detected_role": ["identifier" if str(col) in set(identifier_columns) else "data" for col in user_df.columns],
        "sample_values": [", ".join(user_df[col].dropna().astype(str).head(3).tolist()) for col in user_df.columns],
    })

    profile = {
        "rows": int(rows),
        "columns": int(cols),
        "total_missing_values": total_missing,
        "actionable_missing_values": actionable_missing_values,
        "expected_blank_columns": sorted(expected_blank_columns),
        "accounting_transaction_table": bool(is_accounting_table),
        "duplicate_rows": duplicate_rows,
        "fully_empty_rows": fully_empty_rows,
        "fully_empty_columns": fully_empty_columns,
        "unnamed_columns": unnamed_columns,
        "duplicate_columns": duplicate_name_columns,
        "duplicate_value_columns": duplicate_value_columns,
        "duplicate_comparison_sampled": duplicate_scan_limited,
        "high_missing_columns": high_missing_columns,
        "possible_numeric_columns": possible_numeric_columns,
        "possible_date_columns": possible_date_columns,
        "mixed_type_columns": mixed_type_columns,
        "outlier_columns": outlier_columns,
        "category_inconsistent_columns": category_inconsistent_columns,
        "constant_columns": constant_columns,
        "trailing_space_columns": trailing_space_columns,
        "identifier_columns": sorted(set(identifier_columns)),
        "columns_needing_standardization": columns_needing_standardization,
        "report_profile": report_profile,
        "report_type": report_profile.get("report_type", "flat_table"),
        "system_columns_ignored": [str(c) for c in df.columns if is_system_column(c)],
        "issues_found": issues,
        "problem_count": int(len(problems_df)) if not problems_df.empty else 0,
    }
    return profile, column_report, missing_intelligence, problems_df
