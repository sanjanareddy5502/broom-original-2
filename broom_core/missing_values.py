"""Explicit missing-value policy: preserve ambiguous business text."""
import pandas as pd

AMBIGUOUS_TOKENS = frozenset({"NA", "N/A", "NULL", "NONE", "NAN", "-", "--"})


def normalize_definite_blanks(series: pd.Series) -> pd.Series:
    """Only whitespace-only string cells become missing; preserve all other values."""
    return series.map(
        lambda value: pd.NA if isinstance(value, str) and value.strip() == "" else value
    )


def detect_ambiguous_tokens(series: pd.Series) -> pd.Series:
    """Flag, but never modify, possible missing-value placeholders."""
    return series.map(
        lambda value: isinstance(value, str)
        and value.strip().upper() in AMBIGUOUS_TOKENS
    )
