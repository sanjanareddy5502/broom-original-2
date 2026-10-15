"""Portable, user-controlled preferences; no automatic persistence of customer data.

Recipes contain only column names, action choices, and confirmed date orientation.
High-risk actions always require the user to confirm again on each upload.
"""
from __future__ import annotations
import json

from broom_core.pipeline import ALLOWED_ACTIONS

RECIPE_VERSION = 1
MAX_RECIPE_BYTES = 64 * 1024


def export_recipe(decisions: list[dict]) -> str:
    preferences = []
    for d in decisions:
        if d.get('action') not in ALLOWED_ACTIONS:
            continue
        entry = {'action': d['action'],
                 'columns': [str(c) for c in d.get('columns', [])][:250],
                 'selected': bool(d.get('approved', False))}
        if d['action'] == 'convert_text_to_datetime':
            preference = (d.get('metadata') or {}).get('date_preference', 'infer')
            if preference in ('day_first', 'month_first'):
                entry['date_preference'] = preference
        preferences.append(entry)
    return json.dumps({'version': RECIPE_VERSION, 'preferences': preferences}, indent=2)


def import_recipe(contents: bytes, current_plan: list[dict]) -> list[dict]:
    if len(contents) > MAX_RECIPE_BYTES:
        raise ValueError('Recipe is too large.')
    try:
        obj = json.loads(contents.decode('utf-8'))
    except (UnicodeError, ValueError) as exc:
        raise ValueError('Recipe is not valid UTF-8 JSON.') from exc
    if not isinstance(obj, dict) or obj.get('version') != RECIPE_VERSION or not isinstance(obj.get('preferences'), list):
        raise ValueError('This recipe version is not supported.')
    # Apply preferences only to matching current actions/column groups; never insert actions.
    matches = {}
    for entry in obj['preferences']:
        if not isinstance(entry, dict) or entry.get('action') not in ALLOWED_ACTIONS:
            continue
        if not isinstance(entry.get('columns'), list) or len(entry['columns']) > 250:
            continue
        key = (entry['action'], tuple(sorted(map(str, entry['columns']))))
        matches[key] = entry
    updated = []
    for original in current_plan:
        d = {**original, 'metadata': dict(original.get('metadata') or {})}
        key = (d['action'], tuple(sorted(map(str, d.get('columns', [])))))
        found = matches.get(key)
        if found and d['action'] == 'convert_text_to_datetime':
            pref = found.get('date_preference')
            if pref in ('day_first', 'month_first'):
                d['metadata']['date_preference'] = pref
        # Approval is deliberately not restored, especially for irreversible decisions.
        updated.append(d)
    return updated
