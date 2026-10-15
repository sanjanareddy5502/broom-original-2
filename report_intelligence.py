"""Report Intelligence for DataTrust.

This module detects report-style exports (especially QuickBooks vendor transaction
reports) and converts them into clean, analysis-ready tables before generic
cleaning rules run.
"""
from __future__ import annotations

from typing import Dict, Any, Tuple
import pandas as pd
from date_intelligence import inspect_dates
from numeric_intelligence import parse_series


QB_REQUIRED_COLUMNS = {"Type", "Date", "Account", "Split"}
QB_MONEY_COLUMNS = {"Debit", "Credit"}


def _unnamed_ratio(df: pd.DataFrame) -> float:
    if df.shape[1] == 0:
        return 0.0
    return sum(1 for c in df.columns if "unnamed" in str(c).lower()) / df.shape[1]


def _vendor_header_candidates(df: pd.DataFrame) -> int:
    """Rows where the vendor/section name is present but transaction fields are blank."""
    if "Unnamed: 1" not in df.columns:
        return 0
    tx_cols = [c for c in ["Type", "Date", "Account", "Split", "Debit", "Credit"] if c in df.columns]
    if not tx_cols:
        return 0
    mask = df["Unnamed: 1"].notna() & df[tx_cols].isna().all(axis=1)
    return int(mask.sum())


def detect_report_structure(df: pd.DataFrame) -> Dict[str, Any]:
    """Detect whether the uploaded file is a report export rather than a flat table."""
    cols = set(map(str, df.columns))
    has_qb_core = QB_REQUIRED_COLUMNS.issubset(cols) and bool(QB_MONEY_COLUMNS & cols)
    unnamed = _unnamed_ratio(df)
    vendor_headers = _vendor_header_candidates(df)

    if has_qb_core and unnamed >= 0.25 and vendor_headers >= 3:
        confidence = min(0.99, 0.70 + min(vendor_headers / 200, 0.20) + min(unnamed, 0.09))
        return {
            "detected": True,
            "report_type": "quickbooks_vendor_transaction_report",
            "display_name": "QuickBooks Vendor Transaction Report",
            "confidence": round(float(confidence), 2),
            "vendor_header_rows": vendor_headers,
            "unnamed_column_ratio": round(float(unnamed), 2),
            "recommended_action": "Convert report-style vendor sections into a clean transaction table with Vendor, Date, Account, Split, Debit, Credit, and Net Amount.",
        }

    return {
        "detected": False,
        "report_type": "flat_table",
        "display_name": "Flat Table",
        "confidence": 0.0,
        "vendor_header_rows": vendor_headers,
        "unnamed_column_ratio": round(float(unnamed), 2),
        "recommended_action": "Use generic data diagnosis and cleaning.",
    }


def _split_code_and_name(value: Any) -> Tuple[Any, Any]:
    if pd.isna(value):
        return pd.NA, pd.NA
    text = str(value).strip()
    if "·" in text:
        left, right = text.split("·", 1)
        return left.strip(), right.strip()
    if ":" in text:
        left, right = text.split(":", 1)
        return left.strip(), right.strip()
    return pd.NA, text


def transform_quickbooks_vendor_report(df: pd.DataFrame) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """Convert a QuickBooks vendor transaction report export into a flat table."""
    working = df.copy()
    vendor_col = "Unnamed: 1" if "Unnamed: 1" in working.columns else None
    tx_cols = [c for c in ["Type", "Date", "Num", "Memo", "Account", "Clr", "Split", "Debit", "Credit"] if c in working.columns]

    current_vendor = pd.NA
    vendors = []
    is_vendor_header = []

    for _, row in working.iterrows():
        vendor_value = row.get(vendor_col) if vendor_col else pd.NA
        transaction_present = any(pd.notna(row.get(c)) for c in tx_cols)
        if pd.notna(vendor_value) and not transaction_present:
            current_vendor = str(vendor_value).strip()
            vendors.append(current_vendor)
            is_vendor_header.append(True)
        else:
            vendors.append(current_vendor)
            is_vendor_header.append(False)

    working["Vendor"] = vendors
    working["datatrust_vendor_header_row"] = is_vendor_header

    # Keep transaction rows only. Header rows describe vendor sections and should not become records.
    transaction_mask = (~working["datatrust_vendor_header_row"]) & working[[c for c in ["Type", "Date", "Account", "Split", "Debit", "Credit"] if c in working.columns]].notna().any(axis=1)
    tx = working.loc[transaction_mask].copy()

    # Parse account and split into code/name where possible.
    if "Account" in tx.columns:
        account_parts = tx["Account"].apply(_split_code_and_name)
        tx["Account_Code"] = [p[0] for p in account_parts]
        tx["Account_Name"] = [p[1] for p in account_parts]
    if "Split" in tx.columns:
        split_parts = tx["Split"].apply(_split_code_and_name)
        tx["Split_Code"] = [p[0] for p in split_parts]
        tx["Split_Name"] = [p[1] for p in split_parts]

    for money_col in ["Debit", "Credit"]:
        if money_col in tx.columns:
            original = tx[money_col]
            normalized_text = original.astype('string').str.strip()
            missing = original.isna() | normalized_text.isin(['', ' '])
            numeric_amounts = parse_series(original)
            bad_values = ~missing & numeric_amounts.isna()
            if bad_values.any():
                raise ValueError(f"{int(bad_values.sum())} invalid {money_col} value(s) in the report. Review source data before conversion.")
            tx[money_col] = numeric_amounts

    debit = tx["Debit"] if "Debit" in tx.columns else 0
    credit = tx["Credit"] if "Credit" in tx.columns else 0
    tx["Net_Amount"] = pd.Series(credit).fillna(0) - pd.Series(debit).fillna(0)

    rename_map = {
        "Type": "Transaction_Type",
        "Date": "Transaction_Date",
        "Num": "Transaction_Number",
        "Clr": "Cleared_Status",
    }
    tx = tx.rename(columns=rename_map)
    if "Transaction_Date" in tx.columns and tx["Transaction_Date"].notna().any():
        date_check = inspect_dates(tx["Transaction_Date"])
        if date_check["status"] == "ready":
            tx["Transaction_Date"] = date_check["parsed"]
        # Otherwise preserve original date strings for manual review.


    desired = [
        "Vendor", "Transaction_Type", "Transaction_Date", "Transaction_Number", "Memo",
        "Account", "Account_Code", "Account_Name", "Split", "Split_Code", "Split_Name",
        "Debit", "Credit", "Net_Amount", "Cleared_Status",
    ]
    available = [c for c in desired if c in tx.columns]
    clean = tx[available].reset_index(drop=True)

    vendor_summary = []
    if not clean.empty and {"Vendor", "Net_Amount"}.issubset(set(clean.columns)):
        vendor_summary_df = (
            clean.groupby("Vendor", dropna=True)
                 .agg(
                     transaction_count=("Net_Amount", "size"),
                     total_net_amount=("Net_Amount", "sum"),
                     average_net_amount=("Net_Amount", "mean"),
                 )
                 .reset_index()
                 .sort_values("total_net_amount", ascending=False)
                 .head(15)
        )
        vendor_summary = vendor_summary_df.to_dict(orient="records")

    debit_total = float(clean["Debit"].fillna(0).sum()) if "Debit" in clean.columns else 0.0
    credit_total = float(clean["Credit"].fillna(0).sum()) if "Credit" in clean.columns else 0.0
    net_total = float(clean["Net_Amount"].fillna(0).sum()) if "Net_Amount" in clean.columns else 0.0

    summary = {
        "original_rows": int(df.shape[0]),
        "original_columns": int(df.shape[1]),
        "final_rows": int(clean.shape[0]),
        "final_columns": int(clean.shape[1]),
        "vendor_header_rows_detected": int(sum(is_vendor_header)),
        "vendors_detected": int(pd.Series(vendors).dropna().nunique()),
        "transactions_extracted": int(clean.shape[0]),
        "rows_removed_as_report_headers": int(sum(is_vendor_header)),
        "columns_removed_as_report_spacers": int(sum("unnamed" in str(c).lower() and df[c].isna().all() for c in df.columns)),
        "debit_total": round(debit_total, 2),
        "credit_total": round(credit_total, 2),
        "net_amount_total": round(net_total, 2),
        "top_vendors": vendor_summary,
    }
    return clean, summary


def transform_report_if_applicable(df: pd.DataFrame, report_profile: Dict[str, Any] | None = None) -> Tuple[pd.DataFrame, Dict[str, Any] | None]:
    report_profile = report_profile or detect_report_structure(df)
    if report_profile.get("report_type") == "quickbooks_vendor_transaction_report":
        return transform_quickbooks_vendor_report(df)
    return df.copy(), None
