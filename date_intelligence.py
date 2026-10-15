"""Safe date inference: ambiguous, conflicting and partial dates are NOT invented."""
from __future__ import annotations
from datetime import datetime
import re
import pandas as pd

NUMERIC_DATE = re.compile(r'^\s*(\d{1,2})[/-](\d{1,2})[/-](\d{4})\s*$')
ISO_DATE = re.compile(r'^\s*(\d{4})[-/](\d{1,2})[-/](\d{1,2})(?:[ T](\d{2}):(\d{2})(?::(\d{2}))?)?\s*$')
MONTH_WORD = re.compile(r'\b(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\b', re.I)


def inspect_dates(series: pd.Series, preference: str = 'infer') -> dict:
    """All-or-nothing conversion; never overwrite a single unparseable original value.

    Explicit day/month preferences must come from a user's confirmation.
    Evidence is column-wide; conflicting evidence is flagged, not guessed.
    """
    if preference not in {'infer', 'day_first', 'month_first'}:
        raise ValueError('Invalid date preference.')
    n = int(series.notna().sum())
    base = {'ambiguous': [], 'invalid': [], 'ambiguous_count': 0,
            'invalid_count': 0, 'nonmissing': n, 'format': None,
            'day_evidence': False, 'month_evidence': False}
    if pd.api.types.is_datetime64_any_dtype(series):
        return {**base, 'status': 'already_date', 'parsed': series.copy(), 'format': 'datetime'}
    if pd.api.types.is_numeric_dtype(series) or pd.api.types.is_bool_dtype(series):
        return {**base, 'status': 'not_date', 'parsed': None}

    values = series.astype('string').str.strip().replace({'': pd.NA, 'null': pd.NA, 'NULL': pd.NA, 'N/A': pd.NA})
    present = values.dropna()
    if present.empty:
        return {**base, 'status': 'not_date', 'parsed': None, 'nonmissing': 0}

    day_evidence = month_evidence = False
    for s in present:
        m = NUMERIC_DATE.fullmatch(str(s))
        if m:
            first, second = int(m[1]), int(m[2])
            day_evidence |= first > 12 and second <= 12
            month_evidence |= second > 12 and first <= 12
    conflict = day_evidence and month_evidence
    order = (preference if preference != 'infer' else
             ('day_first' if day_evidence and not conflict else
              'month_first' if month_evidence and not conflict else None))

    parsed = pd.Series(pd.NaT, index=series.index, dtype='datetime64[ns]')
    ambiguous, invalid = [], []
    for position, raw in enumerate(values):
        if pd.isna(raw):
            continue
        s = str(raw)
        nm = NUMERIC_DATE.fullmatch(s)
        iso = ISO_DATE.fullmatch(s)
        try:
            if iso:
                y, mo, day = (int(iso[i]) for i in (1, 2, 3))
                hr, minute, second = (int(iso[i] or 0) for i in (4, 5, 6))
                parsed.iloc[position] = pd.Timestamp(datetime(y, mo, day, hr, minute, second))
            elif nm:
                a, b, year = (int(nm[i]) for i in (1, 2, 3))
                if conflict and preference == 'infer':
                    ambiguous.append({'row': str(series.index[position]), 'value': s})
                    continue
                if order == 'day_first':
                    day, mo = a, b
                elif order == 'month_first':
                    mo, day = a, b
                elif a == b:
                    day, mo = a, b
                else:
                    ambiguous.append({'row': str(series.index[position]), 'value': s})
                    continue
                parsed.iloc[position] = pd.Timestamp(datetime(year, mo, day))
            elif MONTH_WORD.search(s) and re.search(r'\b\d{4}\b', s):
                timestamp = pd.to_datetime(s, errors='raise')
                if getattr(timestamp, 'tzinfo', None) is not None:
                    raise ValueError('Timezone conversion requires review')
                parsed.iloc[position] = timestamp
            else:
                invalid.append({'row': str(series.index[position]), 'value': s})
        except (ValueError, TypeError, OverflowError, pd.errors.OutOfBoundsDatetime):
            invalid.append({'row': str(series.index[position]), 'value': s})
    status = 'ready' if not ambiguous and not invalid else 'review'
    return {**base, 'status': status, 'parsed': parsed if status == 'ready' else None,
            'ambiguous': ambiguous[:30], 'invalid': invalid[:30],
            'ambiguous_count': len(ambiguous), 'invalid_count': len(invalid),
            'nonmissing': int(len(present)), 'format': order or 'mixed/unconfirmed',
            'day_evidence': day_evidence, 'month_evidence': month_evidence}
