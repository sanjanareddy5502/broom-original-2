"""Optional human-approved external language-model explanation of aggregate metadata.

No data or API call is sent unless the user opts in explicitly in the UI.
AI NEVER executes data edits, chooses approvals, or determines whether export is safe.
"""
import json
import os
from business_intelligence import summarize_for_ai


def ai_explanation(intelligence: dict, profile: dict) -> str:
    if not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError("Set OPENAI_API_KEY on your own computer to enable optional AI explanations.")
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError("Install the optional openai package first.") from exc
    safe = summarize_for_ai(intelligence, profile)
    # Do not share field names, raw rows, customer records, or arbitrary examples.
    timeline = safe.get("time_coverage")
    if timeline:
        safe["time_coverage"] = {k: v for k, v in timeline.items() if k != "column"}
    safe["observations"] = []
    safe["review_questions"] = []
    model = os.getenv("BROOM_AI_MODEL", "gpt-4.1-mini")
    result = OpenAI().responses.create(
        model=model,
        instructions=("You are a cautious business-data analyst. Given ONLY aggregated metadata, "
                      "write no more than 120 words in plain English. Describe potential business context, "
                      "two useful follow-up questions, and what cannot be inferred. Never claim you have "
                      "seen rows, validated data, or found business trends you have not seen. "
                      "Do not recommend filling missing business values or deleting duplicates automatically."),
        input=json.dumps(safe, default=str),
        max_output_tokens=250,
    )
    return result.output_text
