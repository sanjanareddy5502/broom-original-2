"""Conservative numeric parsing. Never strip unknown symbols and hope for the best."""
from __future__ import annotations
import re
import math
import pandas as pd

NUMBER_PATTERN = re.compile(r"^[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?$")
NULLS = {'', 'null', 'none', 'n/a', 'na', 'nan', '--'}


def parse_number(value):
    """Return float or pd.NA; requires a known currency/number format."""
    if pd.isna(value):
        return pd.NA
    if isinstance(value, bool):
        return pd.NA
    if isinstance(value, (int, float)):
        return value if math.isfinite(value) else pd.NA
    text = str(value).strip()
    if text.lower() in NULLS:
        return pd.NA
    if '%' in text:
        return pd.NA  # 12% = 12 or 0.12? require policy
    if text.startswith('(') and text.endswith(')'):
        text = '-' + text[1:-1].strip()
    if text.startswith('$'):
        text = text[1:].strip()
    elif text.startswith('-$'):
        text = '-' + text[2:].strip()
    elif text.startswith('+$'):
        text = '+' + text[2:].strip()
    if not NUMBER_PATTERN.fullmatch(text):
        return pd.NA
    # Leading zeros can indicate account IDs; do not coerce them away.
    digits = text.lstrip('+-').split('.')[0]
    if not ',' in digits and len(digits) > 1 and digits.startswith('0'):
        return pd.NA
    try:
        numeric = float(text.replace(',', ''))
        return numeric if math.isfinite(numeric) else pd.NA
    except (OverflowError, ValueError):
        return pd.NA


def parse_series(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series.map(parse_number), errors='coerce')
