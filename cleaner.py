import re
import warnings
import pandas as pd
from report_intelligence import transform_report_if_applicable
from date_intelligence import inspect_dates
from numeric_intelligence import parse_series

NULL_LIKE_VALUES = ["", " "]  # Do not mistake NA (a region code), dash or literal text for missing data.
ORDINAL_PATTERN = re.compile(r"\b(\d{1,2})(st|nd|rd|th)\b", flags=re.IGNORECASE)
DATE_SIGNAL_PATTERN = re.compile(
    r"(\d{1,4}[-/]\d{1,2}[-/]\d{1,4})|"
    r"(\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\b)|"
    r"(\b\d{1,2}(st|nd|rd|th)?\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\b)|"
    r"(\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\s+\d{1,2}(st|nd|rd|th)?\b)",
    flags=re.IGNORECASE,
)


def clean_column_name(col, fallback_name):
    col = str(col).strip()
    if col == "" or "unnamed" in col.lower():
        col = fallback_name
    col = col.lower().replace(" ", "_").replace("-", "_")
    cleaned = "".join(ch for ch in col if ch.isalnum() or ch == "_")
    while "__" in cleaned:
        cleaned = cleaned.replace("__", "_")
    cleaned = cleaned.strip("_")
    return cleaned or fallback_name


def make_unique_columns(columns):
    seen = {}
    out = []
    for col in columns:
        if col not in seen:
            seen[col] = 0
            out.append(col)
        else:
            seen[col] += 1
            out.append(f"{col}_{seen[col]}")
    return out


def _is_approved(decisions, action):
    return any(d.get("action") == action and bool(d.get("approved", False)) for d in decisions or [])


def _decision_columns(decisions, action):
    cols = []
    for d in decisions or []:
        if d.get("action") == action and d.get("approved", False):
            cols.extend(d.get("columns", []))
    return [str(c) for c in cols]


def _clean_text_series(series):
    return series.astype("string").str.strip().replace(NULL_LIKE_VALUES, pd.NA)


def _numeric_candidate(series):
    cleaned = (
        _clean_text_series(series)
        .str.replace(",", "", regex=False)
        .str.replace("$", "", regex=False)
        .str.replace("%", "", regex=False)
        .str.replace("(", "-", regex=False)
        .str.replace(")", "", regex=False)
    )
    return parse_series(series)


def _real_date_signal_ratio(series):
    clean = _clean_text_series(series).dropna().astype(str)
    if clean.empty:
        return 0.0
    sample = clean.head(200)
    return float(sample.apply(lambda x: bool(DATE_SIGNAL_PATTERN.search(x))).mean())


def _date_candidate(series):
    cleaned = _clean_text_series(series)
    cleaned = cleaned.str.replace(ORDINAL_PATTERN, r"\1", regex=True)
    has_month_text = cleaned.str.contains(r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)", case=False, na=False, regex=True)
    has_year = cleaned.str.contains(r"\b\d{4}\b", na=False, regex=True)
    # Missing years are not inferred; converting them could silently corrupt records.
    cleaned = cleaned.where(~(has_month_text & ~has_year), pd.NA)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        return pd.to_datetime(cleaned, errors="coerce")


def _safe_col_name(name):
    safe = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in str(name).lower())
    while "__" in safe:
        safe = safe.replace("__", "_")
    return safe.strip("_") or "column"


def _flag_outliers(df, col, cleaning_log):
    if pd.api.types.is_bool_dtype(df[col]):
        return df
    numeric = pd.to_numeric(df[col], errors="coerce")
    values = numeric.dropna()
    if len(values) < 5:
        return df
    q1 = values.quantile(0.25)
    q3 = values.quantile(0.75)
    iqr = q3 - q1
    if pd.isna(iqr) or iqr == 0:
        return df
    lower = q1 - 1.5 * iqr
    upper = q3 + 1.5 * iqr
    flag_col = f"datatrust_{_safe_col_name(col)}_outlier_flag"
    if flag_col in df.columns:
        cleaning_log.append({"action": "skipped_flag_name_collision", "column": str(col), "risk": "high", "reason": "A pre-existing flag column would be overwritten."})
        return df
    flags = ((numeric < lower) | (numeric > upper)).fillna(False)
    count = int(flags.sum())
    if count > 0:
        df[flag_col] = flags.astype(bool)
        cleaning_log.append({
            "action": "flagged_outliers",
            "column": str(col),
            "flag_column": flag_col,
            "count": count,
            "lower_bound": round(float(lower), 4),
            "upper_bound": round(float(upper), 4),
            "risk": "medium",
            "before_example": str(df.loc[flags, col].head(1).iloc[0]) if count else "",
            "after_example": "flagged for review",
        })
    return df


def _lookup_columns(df_clean):
    return {str(c).lower().replace("_", " "): c for c in df_clean.columns}


def _find_current_column(df_clean, raw_col, lookup):
    if raw_col in df_clean.columns:
        return raw_col
    key = str(raw_col).lower().replace("_", " ")
    return lookup.get(key)


def clean_dataset(df, decisions):
    df_clean = df.copy()
    cleaning_log = []
    report_summary = None
    original_rows, original_columns = df_clean.shape

    if _is_approved(decisions, "transform_quickbooks_vendor_report"):
        report_meta = None
        for d in decisions or []:
            if d.get("action") == "transform_quickbooks_vendor_report":
                report_meta = d.get("metadata", {})
                break
        df_clean, report_summary = transform_report_if_applicable(df_clean, report_meta)
        if report_summary:
            cleaning_log.append({
                "action": "transformed_quickbooks_vendor_report",
                "risk": "high",
                "before_example": "Vendor header rows mixed with transaction rows",
                "after_example": "Clean transaction table with Vendor and Net_Amount",
                "summary": report_summary,
                "rows_before": report_summary.get("original_rows"),
                "rows_after": report_summary.get("final_rows"),
                "columns_before": report_summary.get("original_columns"),
                "columns_after": report_summary.get("final_columns"),
            })

    for d in decisions or []:
        if not d.get("approved", False):
            cleaning_log.append({
                "action": "skipped_unapproved_decision",
                "planned_action": d.get("action"),
                "risk": d.get("risk"),
                "reason": d.get("reason"),
            })

    if _is_approved(decisions, "flag_duplicate_columns"):
        for d in decisions or []:
            if d.get("action") == "flag_duplicate_columns":
                cleaning_log.append({
                    "action": "flagged_possible_duplicate_columns",
                    "pairs": d.get("metadata", {}).get("pairs", []),
                    "risk": "high",
                    "reason": "Possible duplicate columns were flagged, not removed automatically.",
                })


    if _is_approved(decisions, "flag_duplicate_transactions"):
        count = int(df_clean.duplicated().sum())
        if count > 0 and "datatrust_potential_duplicate_transaction" in df_clean.columns:
            raise ValueError("Existing duplicate flag column must not be overwritten.")
        if count > 0:
            df_clean["datatrust_potential_duplicate_transaction"] = df_clean.duplicated(keep=False)
            cleaning_log.append({
                "action": "flagged_potential_duplicate_transactions",
                "count": count,
                "risk": "medium",
                "before_example": f"{count} exact repeated transaction rows",
                "after_example": "flagged for review, not removed",
            })

    if _is_approved(decisions, "remove_fully_empty_rows"):
        count = int(df_clean.isna().all(axis=1).sum())
        if count > 0:
            df_clean = df_clean.dropna(how="all")
            cleaning_log.append({"action": "removed_fully_empty_rows", "count": count, "risk": "low"})

    if _is_approved(decisions, "remove_fully_empty_columns"):
        cols = [c for c in df_clean.columns if df_clean[c].isna().all()]
        if cols:
            df_clean = df_clean.drop(columns=cols)
            cleaning_log.append({
                "action": "removed_fully_empty_columns",
                "columns": [str(c) for c in cols],
                "risk": "low",
                "before_example": ", ".join(map(str, cols)),
                "after_example": "removed",
            })

    if _is_approved(decisions, "preserve_and_rename"):
        renamed = []
        unknown_counter = 1
        for col in df_clean.columns:
            col_text = str(col).strip()
            if col_text == "" or "unnamed" in col_text.lower():
                new_name = f"unknown_column_{unknown_counter}"
                unknown_counter += 1
                renamed.append(new_name)
                cleaning_log.append({
                    "action": "renamed_unnamed_column",
                    "old_column": str(col),
                    "new_column": new_name,
                    "risk": "medium",
                    "before_example": str(col),
                    "after_example": new_name,
                })
            else:
                renamed.append(col_text)
        df_clean.columns = renamed

    if _is_approved(decisions, "standardize_column_names"):
        old_cols = list(df_clean.columns)
        new_cols = [clean_column_name(c, f"column_{i + 1}") for i, c in enumerate(df_clean.columns)]
        new_cols = make_unique_columns(new_cols)
        df_clean.columns = new_cols
        if old_cols != new_cols:
            cleaning_log.append({
                "action": "standardized_column_names",
                "old_columns": [str(c) for c in old_cols],
                "new_columns": new_cols,
                "risk": "low",
                "before_example": ", ".join(map(str, old_cols[:3])),
                "after_example": ", ".join(map(str, new_cols[:3])),
            })

    if _is_approved(decisions, "trim_text_and_standardize_nulls"):
        for col in df_clean.select_dtypes(include=["object", "string"]).columns:
            before_missing = int(df_clean[col].isna().sum())
            before_unique = int(df_clean[col].nunique(dropna=True))
            non_null_before = df_clean[col].dropna().astype(str)
            trailing_spaces = int((non_null_before != non_null_before.str.strip()).sum())
            before_example = ""
            if trailing_spaces:
                before_example = non_null_before[non_null_before != non_null_before.str.strip()].head(1).iloc[0]
            df_clean[col] = _clean_text_series(df_clean[col])
            after_missing = int(df_clean[col].isna().sum())
            after_unique = int(df_clean[col].nunique(dropna=True))
            cleaning_log.append({
                "action": "trimmed_text_and_standardized_nulls",
                "column": str(col),
                "trimmed_values": trailing_spaces,
                "missing_before": before_missing,
                "missing_after": after_missing,
                "unique_before": before_unique,
                "unique_after": after_unique,
                "risk": "low",
                "before_example": before_example,
                "after_example": str(before_example).strip() if before_example else "",
            })

    lookup = _lookup_columns(df_clean)

    numeric_targets = _decision_columns(decisions, "convert_text_to_numeric")
    for raw_col in numeric_targets:
        col = _find_current_column(df_clean, raw_col, lookup)
        if col in df_clean.columns and not pd.api.types.is_numeric_dtype(df_clean[col]):
            name = str(col).lower()
            if any(word in name for word in ("id", "zip", "postal", "phone", "sku", "code", "account", "tracking", "reference", "invoice", "number")):
                cleaning_log.append({"action": "needs_numeric_review", "column": str(col), "risk": "medium", "reason": "Identifier-like column; preserving text to avoid losing leading zeros."})
                continue
            if df_clean[col].astype("string").str.contains("%", regex=False, na=False).any():
                cleaning_log.append({"action": "needs_numeric_review", "column": str(col), "risk": "medium", "reason": "Percent values require clarification (12% could represent 0.12 or 12)."})
                continue
            nonempty = _clean_text_series(df_clean[col]).notna()
            converted = parse_series(df_clean[col])
            invalid_count = int((nonempty & converted.isna()).sum())
            if invalid_count:
                cleaning_log.append({"action": "needs_numeric_review", "column": str(col), "count": invalid_count, "risk": "medium", "reason": "Unparseable entries preserved; no values overwritten."})
            elif int(nonempty.sum()) > 0:
                before_example = str(df_clean.loc[nonempty, col].iloc[0])
                df_clean[col] = converted
                cleaning_log.append({"action": "converted_text_to_numeric", "column": str(col), "risk": "low", "before_example": before_example, "after_example": str(converted.dropna().iloc[0])})

    lookup = _lookup_columns(df_clean)
    date_targets = _decision_columns(decisions, "convert_text_to_datetime")
    for raw_col in date_targets:
        col = _find_current_column(df_clean, raw_col, lookup)
        if col in df_clean.columns and not pd.api.types.is_datetime64_any_dtype(df_clean[col]):
            prefs = [d.get("metadata", {}).get("date_preference", "infer") for d in decisions or []
                     if d.get("action") == "convert_text_to_datetime" and raw_col in d.get("columns", [])]
            result = inspect_dates(df_clean[col], preference=prefs[0] if prefs else "infer")
            if result["status"] == "ready":
                before_example = str(df_clean[col].dropna().iloc[0])
                df_clean[col] = result["parsed"]
                cleaning_log.append({"action": "converted_text_to_datetime", "column": str(col), "risk": "low", "before_example": before_example, "after_example": str(df_clean[col].dropna().iloc[0]), "format": result["format"]})
            else:
                cleaning_log.append({"action": "needs_date_review", "column": str(col), "risk": "medium", "count": result.get("ambiguous_count", 0) + result.get("invalid_count", 0), "reason": "Dates preserved: ambiguous or invalid values require review."})

    lookup = _lookup_columns(df_clean)
    category_targets = _decision_columns(decisions, "standardize_categories")
    for raw_col in category_targets:
        col = _find_current_column(df_clean, raw_col, lookup)
        if col in df_clean.columns and (pd.api.types.is_object_dtype(df_clean[col]) or pd.api.types.is_string_dtype(df_clean[col])):
            before = df_clean[col].dropna().astype(str)
            if before.empty:
                continue
            # Use an observed representative instead of .title() (which corrupts "USA" / "iPhone").
            # Only unify variants that differ by case or surrounding spaces.
            frequencies = before.value_counts()
            representatives = {}
            for label, count in frequencies.items():
                key = label.strip().casefold()
                if key not in representatives or count > representatives[key][1]:
                    representatives[key] = (label.strip(), int(count))
            replacement = {label: representatives[label.strip().casefold()][0] for label in frequencies.index}
            modifications = sum(int(frequencies[label]) for label, mapped in replacement.items() if label != mapped)
            if modifications:
                df_clean[col] = df_clean[col].map(lambda value: replacement.get(str(value), value) if pd.notna(value) else value)
                cleaning_log.append({
                    "action": "standardized_categories", "column": str(col),
                    "count": modifications, "risk": "medium",
                    "reason": "Case/whitespace-only variants merged using the most common observed spelling.",
                })

    if _is_approved(decisions, "remove_exact_duplicate_rows"):
        count = int(df_clean.duplicated().sum())
        if count > 0:
            df_clean = df_clean.drop_duplicates()
            cleaning_log.append({"action": "removed_exact_duplicate_rows", "count": count, "risk": "medium"})

    if _is_approved(decisions, "fill_missing_values"):
        for col in df_clean.columns:
            # Missing identifiers, dates, accounting figures, and business keys MUST
            # never be invented by a generic median/mode fill.
            critical_words = ("id", "key", "code", "date", "time", "invoice", "transaction", "amount",
                              "price", "cost", "debit", "credit", "balance", "account", "revenue", "sales")
            if any(w in str(col).lower() for w in critical_words) or pd.api.types.is_datetime64_any_dtype(df_clean[col]):
                if df_clean[col].isna().any():
                    cleaning_log.append({"action": "skipped_business_critical_missing", "column": str(col), "risk": "high", "reason": "Critical business fields are not imputed without a domain-specific policy."})
                continue
            missing_before = int(df_clean[col].isna().sum())
            if missing_before == 0:
                continue
            missing_pct = df_clean[col].isna().mean()
            if missing_pct > 0.60:
                cleaning_log.append({"action": "skipped_high_missing_column", "column": str(col), "missing_percent": round(float(missing_pct * 100), 2), "risk": "medium", "reason": "High-missing columns should not be blindly filled."})
                continue
            if pd.api.types.is_numeric_dtype(df_clean[col]):
                value = df_clean[col].median()
                if pd.notna(value):
                    df_clean[col] = df_clean[col].fillna(value)
                    cleaning_log.append({"action": "filled_numeric_missing_with_median", "column": str(col), "count": missing_before, "value": float(value), "risk": "medium", "before_example": "missing", "after_example": str(value)})
            else:
                mode = df_clean[col].mode(dropna=True)
                if not mode.empty:
                    value = mode.iloc[0]
                    df_clean[col] = df_clean[col].fillna(value)
                    cleaning_log.append({"action": "filled_categorical_missing_with_mode", "column": str(col), "count": missing_before, "value": str(value), "risk": "medium", "before_example": "missing", "after_example": str(value)})

    lookup = _lookup_columns(df_clean)
    outlier_targets = _decision_columns(decisions, "flag_outliers")
    for raw_col in outlier_targets:
        col = _find_current_column(df_clean, raw_col, lookup)
        if col in df_clean.columns:
            df_clean = _flag_outliers(df_clean, col, cleaning_log)

    if _is_approved(decisions, "remove_constant_columns"):
        targets = []
        lookup = _lookup_columns(df_clean)
        for raw_col in _decision_columns(decisions, "remove_constant_columns"):
            col = _find_current_column(df_clean, raw_col, lookup)
            if col in df_clean.columns:
                targets.append(col)
        if targets:
            df_clean = df_clean.drop(columns=targets)
            cleaning_log.append({"action": "removed_constant_columns", "columns": [str(c) for c in targets], "risk": "low", "before_example": ", ".join(map(str, targets)), "after_example": "removed"})

    cleaning_summary = {
        "original_rows": int(original_rows),
        "original_columns": int(original_columns),
        "final_rows": int(df_clean.shape[0]),
        "final_columns": int(df_clean.shape[1]),
        "rows_removed": int(original_rows - df_clean.shape[0]),
        "columns_removed": int(original_columns - df_clean.shape[1]),
        "missing_before": int(df.isna().sum().sum()),
        "missing_after": int(df_clean.isna().sum().sum()),
        "duplicates_before": int(df.duplicated().sum()),
        "duplicates_after": int(df_clean.duplicated().sum()),
        "total_actions": len(cleaning_log),
        "cleaning_log": cleaning_log,
        "report_summary": report_summary,
    }
    return df_clean, cleaning_summary
