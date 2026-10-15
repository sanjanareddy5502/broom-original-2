"""Reusable orchestration independent of Streamlit (source of truth for all 5 stages)."""
from __future__ import annotations
from dataclasses import dataclass
import hashlib
import json
from typing import Any
import pandas as pd

from profiler import profile_dataset
from decision_engine import decide_cleaning_actions
from cleaner import clean_dataset
from validator import validate_cleaned_data
from builder import build_outputs
from business_intelligence import understand_dataset

ALLOWED_ACTIONS = frozenset({
    'transform_quickbooks_vendor_report', 'remove_fully_empty_rows',
    'remove_fully_empty_columns', 'preserve_and_rename', 'flag_duplicate_columns',
    'standardize_column_names', 'trim_text_and_standardize_nulls',
    'convert_text_to_numeric', 'convert_text_to_datetime', 'standardize_categories',
    'remove_exact_duplicate_rows', 'flag_duplicate_transactions',
    'fill_missing_values', 'flag_outliers', 'remove_constant_columns',
})
NEEDS_APPROVAL = frozenset({
    'transform_quickbooks_vendor_report', 'convert_text_to_datetime',
    'standardize_categories', 'remove_exact_duplicate_rows',
    'fill_missing_values', 'remove_constant_columns',
})

@dataclass
class Diagnosis:
    profile: dict
    column_report: pd.DataFrame
    missing_report: pd.DataFrame
    problems: pd.DataFrame
    intelligence: dict
    plan: list[dict]

@dataclass
class CleaningResult:
    cleaned: pd.DataFrame
    summary: dict
    after_profile: dict
    after_problems: pd.DataFrame
    validation: dict
    intelligence: dict
    outputs: dict


def diagnose(df: pd.DataFrame) -> Diagnosis:
    profile, columns, missing, problems = profile_dataset(df)
    return Diagnosis(profile, columns, missing, problems,
                     understand_dataset(df, profile), decide_cleaning_actions(profile))


def plan_signature(decisions: list[dict]) -> str:
    """Hash the actual approved plan; prevents UI showing stale results after changes."""
    body = json.dumps(decisions, default=str, sort_keys=True).encode('utf-8')
    return hashlib.sha256(body).hexdigest()


def validate_plan(decisions: list[dict]) -> None:
    if not isinstance(decisions, list):
        raise ValueError('Cleaning plan must be a list of actions.')
    for item in decisions:
        if not isinstance(item, dict) or item.get('action') not in ALLOWED_ACTIONS:
            raise ValueError('Cleaning plan includes an unknown action.')
        if not isinstance(item.get('approved', False), bool):
            raise ValueError('Cleaning approval must be true or false.')
        if item.get('approved') and item['action'] in NEEDS_APPROVAL and not item.get('approval_confirmed'):
            raise ValueError(f"Explicit confirmation required: {item['action']}")
        preference = (item.get('metadata') or {}).get('date_preference', 'infer')
        if preference not in ('infer', 'day_first', 'month_first'):
            raise ValueError('Unsupported date interpretation.')
        if item.get('columns') and (not isinstance(item['columns'], list) or any(not isinstance(c, str) for c in item['columns'])):
            raise ValueError('Column selection must be a list of names.')


def execute(df: pd.DataFrame, diagnosis: Diagnosis, decisions: list[dict]) -> CleaningResult:
    validate_plan(decisions)
    clean, summary = clean_dataset(df.copy(deep=True), decisions)
    summary['issues_found_before'] = diagnosis.profile.get('problem_count', 0)
    profile, _, _, problems = profile_dataset(clean)
    validation = validate_cleaned_data(df, clean, summary)
    if clean is df:
        raise RuntimeError('Cleaning must not mutate the uploaded dataset.')
    outputs = build_outputs(clean, diagnosis.profile, profile, decisions, summary,
                            validation, diagnosis.problems)
    return CleaningResult(clean, summary, profile, problems, validation,
                          understand_dataset(clean, profile), outputs)
