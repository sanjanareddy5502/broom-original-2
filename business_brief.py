"""Deterministic business analyst brief from validated aggregates (not predictions)."""
from __future__ import annotations
import pandas as pd
from date_intelligence import inspect_dates
from broom_core.relationships import check_order_totals

MEASURE_WORDS = ('amount', 'revenue', 'sales', 'net_amount', 'spend', 'cost', 'price', 'total', 'quantity')
ID_WORDS = ('id', 'sku', 'zip', 'postal', 'phone', 'code', 'invoice_number', 'account', 'reference')
DATE_WORDS = ('date', 'created', 'updated', 'timestamp')


def _choose_date(df):
    for c in df.columns:
        name = str(c).lower()
        if not any(t in name for t in DATE_WORDS):
            continue
        col = df[c]
        if pd.api.types.is_datetime64_any_dtype(col):
            values = col
        else:
            result = inspect_dates(col)
            if result['status'] != 'ready':
                continue
            values = result['parsed']
        dates = pd.to_datetime(values, errors='coerce')
        if dates.notna().any():
            return str(c), dates
    return None, None


def _choose_measure(df):
    for c in df.columns:
        name = str(c).lower()
        if any(w in name for w in ID_WORDS):
            continue
        if not any(w in name for w in MEASURE_WORDS):
            continue
        if pd.api.types.is_numeric_dtype(df[c]) and not pd.api.types.is_bool_dtype(df[c]):
            return str(c), pd.to_numeric(df[c], errors='coerce')
    return None, None


def build_business_brief(df: pd.DataFrame, profile: dict | None = None) -> dict:
    """Returns structured observations with stated limits; no guessing root causes."""
    profile = profile or {}
    notes = []
    checks = []
    date_name, dates = _choose_date(df)
    metric_name, metric = _choose_measure(df)
    metrics = {'rows': len(df), 'duplicates': int(df.duplicated().sum()),
               'missing_cells': int(df.isna().sum().sum())}
    if metrics['duplicates']:
        checks.append(f"{metrics['duplicates']:,} exact repeated rows need business confirmation before deletion.")
    if metric_name and metric is not None:
        metrics['measure'] = metric_name
        metrics['measure_nonmissing'] = int(metric.notna().sum())
        notes.append(f"Observed total {metric_name}: {metric.sum():,.2f} across {metric.notna().sum():,} nonblank values. Verify whether this measure should be summed.")
        if metric.isna().any():
            checks.append(f"{int(metric.isna().sum()):,} records lack a usable {metric_name}; totals may be incomplete.")
    monthly = pd.DataFrame(columns=['month', 'records', 'measure_total'])
    if dates is not None:
        good = dates.notna()
        metrics['date_column'] = date_name
        metrics['dated_records'] = int(good.sum())
        metrics['undated_records'] = int((~good).sum())
        if int((~good).sum()):
            checks.append(f"{int((~good).sum()):,} records cannot be placed on a timeline.")
        f = pd.DataFrame({'month': dates[good].dt.to_period('M').astype(str), 'records': 1}, index=df.index[good])
        if metric is not None:
            f['value'] = metric.loc[good]
            monthly = f.groupby('month', as_index=False).agg(records=('records', 'sum'), measure_total=('value', 'sum'))
        else:
            monthly = f.groupby('month', as_index=False).agg(records=('records', 'sum'))
        monthly = monthly.sort_values('month').tail(24).reset_index(drop=True)
        if not monthly.empty:
            notes.append(f"Time coverage: {dates[good].min():%Y-%m-%d} through {dates[good].max():%Y-%m-%d}.")
            if len(monthly) > 1:
                previous, latest = monthly.iloc[-2], monthly.iloc[-1]
                notes.append(f"Recorded rows by month: {previous['month']} had {int(previous['records']):,}; {latest['month']} had {int(latest['records']):,}. These may be partial months.")
    else:
        checks.append('Choose or clarify a date field before comparing performance over time.')
    relationship_checks = check_order_totals(df)
    for relationship in relationship_checks:
        if relationship.get('mismatched_rows', 0):
            checks.append(relationship['message'])
        elif relationship.get('type') == 'order_total_reconciliation':
            notes.append(relationship['message'])
        else:
            checks.append(relationship['message'])
    if not notes:
        notes.append('Broom has not confirmed enough data meaning to produce a business trend. That is safer than guessing.')
    return {'observations': notes[:5], 'questions': checks[:5], 'monthly': monthly,
            'measure': metric_name, 'date_column': date_name, 'metrics': metrics,
            'relationships': relationship_checks,
            'limitations': 'Descriptive only. No causal inference, forecast, or guarantee of complete records.'}
