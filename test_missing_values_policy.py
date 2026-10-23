import pandas as pd
from broom_core.security import read_uploaded_file
from broom_core.missing_values import detect_ambiguous_tokens
from profiler import profile_dataset
from report_intelligence import detect_report_structure


def test_csv_blank_count_preserves_literal_tokens():
    data = b"Name,Amount,Code\nJohn,100,NA\nMary, ,NULL\nDavid,250,-\nEve,0,00120\n"
    df = read_uploaded_file(data, "customers.csv")
    assert pd.isna(df.loc[1, "Amount"])
    assert df["Code"].tolist() == ["NA", "NULL", "-", "00120"]
    profile, *_ = profile_dataset(df)
    assert profile["total_missing_values"] == 1
    assert detect_ambiguous_tokens(df["Code"]).tolist() == [True, True, True, False]


def test_quickbooks_style_csv_detected_after_blank_normalization():
    header = "Unnamed: 1,Type,Date,Account,Split,Debit,Credit,Unnamed: 8,Unnamed: 9\n"
    rows = []
    for vendor in ("Acme", "Bravo", "Cyan"):
        rows.append(f"{vendor},,,,,,,,\n")
        rows.append(",Bill,2026-02-01,Expense,Other,1200,,,\n")
    df = read_uploaded_file((header + "".join(rows)).encode(), "qb.csv")
    detection = detect_report_structure(df)
    assert detection["detected"] is True
    assert detection["vendor_header_rows"] == 3
