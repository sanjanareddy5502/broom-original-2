"""Explainable business relationship checks. These detect potential errors, never edit rows."""
from __future__ import annotations
import pandas as pd


def _pick(columns, candidates):
    lowered = {str(c).lower().replace(' ', '_'): c for c in columns}
    for candidate in candidates:
        if candidate in lowered:
            return lowered[candidate]
    return None


def check_order_totals(df: pd.DataFrame) -> list[dict]:
    """Check quantity × unit_price ≈ recorded line_total when explicitly named.

    No business assumption is made for discounts, tax or freight; discrepancies
    are observations for review, not evidence of incorrect data.
    """
    qty = _pick(df.columns, ('quantity', 'qty', 'units'))
    price = _pick(df.columns, ('unit_price', 'price_per_unit'))
    amount = _pick(df.columns, ('line_total', 'line_amount', 'extended_amount'))
    if any(col is None for col in (qty, price, amount)):
        return []
    if not all(pd.api.types.is_numeric_dtype(df[col]) for col in (qty, price, amount)):
        return [{'type': 'review_required', 'columns': [str(qty), str(price), str(amount)],
                 'message': 'Quantity, unit price, and line total are not all numeric; arithmetic consistency was not checked.'}]
    q = pd.to_numeric(df[qty], errors='coerce')
    p = pd.to_numeric(df[price], errors='coerce')
    a = pd.to_numeric(df[amount], errors='coerce')
    checked = q.notna() & p.notna() & a.notna()
    if not checked.any():
        return []
    expected = q[checked] * p[checked]
    difference = (a[checked] - expected).abs()
    tolerance = 0.02 + expected.abs() * 0.00001
    mismatches = int((difference > tolerance).sum())
    return [{'type':'order_total_reconciliation', 'columns':[str(qty),str(price),str(amount)],
             'checked_rows': int(checked.sum()), 'mismatched_rows': mismatches,
             'message': (f'{mismatches:,} of {int(checked.sum()):,} rows differ from quantity × unit price. '
                         'Discounts, taxes, unit conventions, or genuine data problems may explain this; review before changing.')
             if mismatches else f'All {int(checked.sum()):,} checked rows match quantity × unit price within tolerance.'}]
