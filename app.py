"""Broom / DataTrust: five-step approachable interface with safe, traceable changes."""
from __future__ import annotations
import hashlib
import os

import pandas as pd
import streamlit as st

from decision_engine import decide_cleaning_actions
from business_brief import build_business_brief
from date_intelligence import inspect_dates
from broom_core.security import read_uploaded_file, InputRejected
from broom_core.pipeline import diagnose as run_diagnosis, execute as run_cleaning, plan_signature
from broom_core.recipes import export_recipe, import_recipe

st.set_page_config(page_title="Broom | Understand and clean your data", page_icon="🧹", layout="wide", initial_sidebar_state="expanded")
st.markdown("""
<style>
.block-container {max-width: 1120px; padding-top: 2rem;}
h1,h2,h3 {letter-spacing: -.025em;}
[data-testid="stSidebar"] {background: #f8fafc;}
[data-testid="stMetric"] {border: 1px solid #e5e7eb; border-radius: 12px; padding: .8rem;}
div.stButton > button[kind="primary"] {border-radius: 12px;}
</style>""", unsafe_allow_html=True)

STEPS = ["Upload Dataset", "Diagnose Problems", "Cleaning Plan & Risk Review", "Clean Data", "Validate & Export"]


def clear_results():
    for k in ("profile", "column_report", "missing_intelligence", "problems", "intelligence",
              "decisions", "approved_decisions", "cleaned", "summary", "after_profile",
              "after_problems", "validation", "outputs", "ai_notes", "diagnosis", "result_signature"):
        st.session_state.pop(k, None)
    for key in list(st.session_state):
        if key.startswith("approve_") or key.startswith("date_order_"):
            st.session_state.pop(key, None)


def go(n):
    st.session_state.step = n
    st.rerun()


def data_preview(df, title="Data preview"):
    st.caption(title + " · first 10 rows")
    st.dataframe(df.head(10), use_container_width=True, hide_index=True)


def load_bytes(data, name):
    return read_uploaded_file(data, name)


def diagnosis():
    result = run_diagnosis(st.session_state.raw)
    st.session_state.diagnosis = result
    st.session_state.profile = result.profile
    st.session_state.column_report = result.column_report
    st.session_state.missing_intelligence = result.missing_report
    st.session_state.problems = result.problems
    st.session_state.intelligence = result.intelligence
    st.session_state.decisions = result.plan


def refresh_plan():
    st.session_state.decisions = decide_cleaning_actions(st.session_state.profile)
    for key in list(st.session_state):
        if key.startswith("approve_") or key.startswith("date_order_"):
            st.session_state.pop(key, None)
    for k in ("approved_decisions", "cleaned", "summary", "validation", "outputs"):
        st.session_state.pop(k, None)


def prepare_clean():
    decisions = st.session_state.approved_decisions
    result = run_cleaning(st.session_state.raw, st.session_state.diagnosis, decisions)
    st.session_state.cleaned = result.cleaned
    st.session_state.summary = result.summary
    st.session_state.after_profile = result.after_profile
    st.session_state.after_problems = result.after_problems
    st.session_state.validation = result.validation
    st.session_state.outputs = result.outputs
    st.session_state.result_signature = plan_signature(decisions)


def friendly_action(action):
    labels = {
        "transform_quickbooks_vendor_report": "Turn the accounting report into a table",
        "remove_fully_empty_rows": "Remove completely empty rows",
        "remove_fully_empty_columns": "Remove completely empty columns",
        "preserve_and_rename": "Rename unnamed columns (keep values)",
        "flag_duplicate_columns": "Mark similar columns for review",
        "standardize_column_names": "Make column names consistent",
        "trim_text_and_standardize_nulls": "Fix extra spaces and blank-looking values",
        "convert_text_to_numeric": "Convert text numbers safely",
        "convert_text_to_datetime": "Standardize dates safely",
        "standardize_categories": "Make category labels consistent",
        "remove_exact_duplicate_rows": "Remove identical rows (review required)",
        "flag_duplicate_transactions": "Flag repeated transactions (don't delete)",
        "fill_missing_values": "Estimate missing values (high risk)",
        "flag_outliers": "Flag unusual numbers",
        "remove_constant_columns": "Remove columns with just one value",
    }
    return labels.get(action, str(action).replace("_", " ").capitalize())


st.session_state.setdefault("step", 1)
st.title("🧹 Broom")
st.caption("Understand your data. Fix what is safe. Review what is uncertain.")

with st.sidebar:
    st.markdown("### Your 5 steps")
    for i, label in enumerate(STEPS, start=1):
        ready = i == 1 or (i == 2 and "raw" in st.session_state) or (i == 3 and "profile" in st.session_state) or (i == 4 and "approved_decisions" in st.session_state) or (i == 5 and "cleaned" in st.session_state)
        if st.button(f"{'●' if i == st.session_state.step else '○'}  {i}. {label}", key=f"nav_{i}", disabled=not ready, use_container_width=True):
            go(i)
    st.divider()
    if "filename" in st.session_state:
        st.caption(f"File: {st.session_state.filename}")
    if st.button("Start with another file", use_container_width=True):
        st.session_state.clear()
        st.rerun()

st.progress((st.session_state.step - 1) / 4)
st.subheader(f"{st.session_state.step}. {STEPS[st.session_state.step - 1]}")

if st.session_state.step == 1:
    st.write("Upload your spreadsheet. Broom won't change the original file.")
    st.caption("CSV or Excel (.xlsx) · 15 MB limit · first Excel worksheet only · formula workbooks require a values-only copy")
    upload = st.file_uploader("Choose a CSV or Excel file", type=["csv", "xlsx"])
    if upload is not None:
        contents = upload.getvalue()
        fingerprint = hashlib.sha256(upload.name.encode() + b"\x00" + contents).hexdigest()
        if st.session_state.get("filehash") != fingerprint:
            try:
                raw = load_bytes(contents, upload.name)
                if raw.shape[1] == 0:
                    raise ValueError("No data columns found.")
                clear_results()
                st.session_state.raw = raw
                st.session_state.filename = upload.name
                st.session_state.filehash = fingerprint
            except InputRejected as exc:
                st.error(f"Couldn't open this file: {exc}")
            except Exception:
                st.error("This file could not be processed safely. Check its contents and try a smaller sample.")
    if "raw" in st.session_state:
        df = st.session_state.raw
        a, b = st.columns(2)
        a.metric("Rows", f"{len(df):,}")
        b.metric("Columns", f"{len(df.columns):,}")
        with st.expander("Preview uploaded data"):
            data_preview(df)
        if st.button("Understand my data →", type="primary"):
            with st.spinner("Reading data structure…"):
                diagnosis()
            go(2)

elif st.session_state.step == 2:
    st.write("Broom looks at the whole file before deciding what needs attention.")
    if "profile" not in st.session_state:
        diagnosis()
    profile = st.session_state.profile
    intel = st.session_state.intelligence
    st.info(f"**This looks like:** {intel['dataset_type']}. This is a best guess, not a confirmed classification.")
    if profile.get("duplicate_comparison_sampled"):
        st.caption("Large file: possible duplicate columns were checked using a limited sample, not every row and column.")
    a, b, c = st.columns(3)
    a.metric("Rows", f"{profile['rows']:,}")
    b.metric("Columns", profile["columns"])
    c.metric("Types of issues", profile.get("problem_count", 0))
    st.markdown("#### What Broom noticed")
    for note in intel["observations"][:3]:
        st.write("• " + note)
    for question in intel["questions"][:3]:
        st.warning(question)
    if not st.session_state.problems.empty:
        st.markdown("#### Problems to consider")
        overview = st.session_state.problems[["problem", "column", "severity"]].head(8)
        st.dataframe(overview, use_container_width=True, hide_index=True)
        if len(st.session_state.problems) > 8:
            st.caption(f"Showing 8 of {len(st.session_state.problems)} findings.")
    else:
        st.success("No obvious issues detected by the current checks. This does not guarantee perfect data.")
    with st.expander("Details for analysts"):
        st.dataframe(st.session_state.problems, use_container_width=True, hide_index=True)
        st.dataframe(st.session_state.column_report, use_container_width=True, hide_index=True)
        if not st.session_state.missing_intelligence.empty:
            st.dataframe(st.session_state.missing_intelligence, use_container_width=True, hide_index=True)

    with st.expander("Optional AI explanation (experimental)"):
        st.caption("Broom's on-device analysis is already shown above. An optional external model can help phrase business questions; it does not edit data.")
        if not os.environ.get("OPENAI_API_KEY"):
            st.caption("AI API not configured. The five-step workflow works without it.")
        else:
            consent = st.checkbox("I agree to share aggregated row counts, dataset type and date coverage with an external AI provider. No spreadsheet rows are sent.", key="ai_consent")
            if st.button("Get AI explanation", disabled=not consent):
                try:
                    from ai_advisor import ai_explanation
                    st.session_state.ai_notes = ai_explanation(intel, profile)
                except Exception as exc:
                    st.error(f"AI explanation unavailable: {exc}")
            if st.session_state.get("ai_notes"):
                st.write(st.session_state.ai_notes)

    if st.button("Review suggested fixes →", type="primary"):
        if "decisions" not in st.session_state:
            refresh_plan()
        go(3)

elif st.session_state.step == 3:
    st.write("Safe fixes can be applied automatically. Changes that could alter the meaning of your data need your approval.")
    if "decisions" not in st.session_state:
        refresh_plan()
    decisions = st.session_state.decisions
    if not decisions:
        st.success("No fixes suggested for the issues currently detected.")
    with st.expander("Have cleaning preferences from an earlier file?"):
        st.caption("Optional. Broom imports date preferences only when matching columns are present. You'll still approve risky changes.")
        recipe_file = st.file_uploader("Import your saved preferences", type=["json"], key="recipe_upload")
        if recipe_file and st.button("Read preferences"):
            try:
                st.session_state.decisions = import_recipe(recipe_file.getvalue(), decisions)
                for key in list(st.session_state):
                    if key.startswith("date_order_"):
                        st.session_state.pop(key, None)
                st.success("Preferences loaded. Review the suggested changes below.")
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))
    approved = []
    safe_names = []
    for idx, decision in enumerate(decisions):
        d = dict(decision)
        risky = bool(d.get("requires_approval", False))
        title = friendly_action(d["action"])
        if risky:
            st.markdown(f"**Review: {title}**")
            st.caption(d.get("reason", ""))
            d["approved"] = st.checkbox("Allow this change", key=f"approve_{idx}", value=bool(d.get("approved", False)))
            d["approval_confirmed"] = bool(d["approved"])
        else:
            safe_names.append(title)
            d["approved"] = True
        if d["action"] == "convert_text_to_datetime" and d.get("columns"):
            for raw_col in d["columns"]:
                if raw_col in st.session_state.raw.columns:
                    state = inspect_dates(st.session_state.raw[raw_col])
                    if state["status"] != "ready":
                        st.caption(f"{raw_col}: {state.get('ambiguous_count',0)} ambiguous / {state.get('invalid_count',0)} invalid. Won't overwrite invalid entries.")
                        if state.get("ambiguous_count", 0) and not state.get("invalid_count", 0):
                            choice = st.selectbox(f"Date order for {raw_col}", ["infer", "day_first", "month_first"],
                                                  format_func=lambda x: {"infer":"Don't guess (recommended)", "day_first":"Day first (DD/MM/YYYY)", "month_first":"Month first (MM/DD/YYYY)"}[x],
                                                  index=["infer", "day_first", "month_first"].index(d.get("metadata", {}).get("date_preference", "infer")),
                                                  key=f"date_order_{idx}_{raw_col}")
                            d.setdefault("metadata", {})
                            d["metadata"] = dict(d["metadata"])
                            d["metadata"]["date_preference"] = choice
        approved.append(d)
    if safe_names:
        with st.expander(f"{len(safe_names)} low-risk suggested steps (automatically selected)"):
            for name in safe_names:
                st.write("✓ " + name)
    old_signature = plan_signature(st.session_state.get("approved_decisions", []))
    new_signature = plan_signature(approved)
    if old_signature != new_signature:
        for old in ("cleaned", "summary", "validation", "outputs", "result_signature"):
            st.session_state.pop(old, None)
    st.session_state.approved_decisions = approved
    with st.expander("Why are these fixes recommended?"):
        for d in approved:
            st.write(f"**{friendly_action(d['action'])}:** {d.get('reason', '')}")
    report_needs_ok = any(d["action"] == "transform_quickbooks_vendor_report" and not d["approved"] for d in approved)
    if report_needs_ok:
        st.info("Please approve the accounting report conversion to continue, or return to the previous step.")
    if st.button("Clean my data →", type="primary", disabled=report_needs_ok):
        for k in ("cleaned", "summary", "validation", "outputs"):
            st.session_state.pop(k, None)
        go(4)

elif st.session_state.step == 4:
    st.write("Broom applies the approved plan and checks the results.")
    if ("cleaned" not in st.session_state or st.session_state.get("result_signature") != plan_signature(st.session_state.get("approved_decisions", []))):
        with st.spinner("Cleaning and checking the data…"):
            try:
                prepare_clean()
            except Exception:
                st.error("Cleaning stopped. The input was preserved. Review the file and the requested actions before retrying.")
                st.stop()
    summary = st.session_state.summary
    a, b, c = st.columns(3)
    a.metric("Rows after", f"{summary['final_rows']:,}")
    b.metric("Columns after", summary["final_columns"])
    c.metric("Review items", st.session_state.validation.get("pending_count", 0))
    st.markdown("#### Before and after")
    before, after = st.columns(2)
    with before:
        data_preview(st.session_state.raw, "Before")
    with after:
        data_preview(st.session_state.cleaned, "After")
    with st.expander("What changed? (audit log)"):
        st.dataframe(pd.DataFrame(summary.get("cleaning_log", [])), use_container_width=True, hide_index=True)
    with st.expander("Issues still detected after cleaning"):
        problems = st.session_state.after_problems
        if problems.empty:
            st.write("No issues found by the current checks.")
        else:
            st.dataframe(problems, use_container_width=True, hide_index=True)
    c1, c2 = st.columns(2)
    if c1.button("← Change approvals"):
        go(3)
    if c2.button("See results and download →", type="primary"):
        go(5)

elif st.session_state.step == 5:
    if ("cleaned" not in st.session_state or st.session_state.get("result_signature") != plan_signature(st.session_state.get("approved_decisions", []))):
        st.warning("Your cleaning choices have changed. Please run cleaning again to update the results.")
        if st.button("Run updated cleaning"):
            go(4)
        st.stop()
    validation = st.session_state.validation
    if validation.get("issues"):
        st.error("Validation found serious problems. Review before using this output.")
    elif validation.get("pending_count", 0) or validation.get("warnings"):
        st.warning("Cleaned file prepared, but some issues still need attention.")
    else:
        st.success("Checks completed. Review the output before using it for business decisions.")
    a, b, c = st.columns(3)
    a.metric("Rows", f"{len(st.session_state.cleaned):,}")
    b.metric("Changes logged", st.session_state.summary["total_actions"])
    c.metric("Items to review", validation.get("pending_count", 0))
    brief = build_business_brief(st.session_state.cleaned, st.session_state.after_profile)
    st.markdown("#### Business overview")
    for note in brief["observations"][:3]:
        st.write("• " + note)
    for question in brief["questions"][:3]:
        st.caption("To review: " + question)
    if len(brief["monthly"]) >= 2:
        with st.expander("View the monthly breakdown (descriptive only)"):
            monthly = brief["monthly"].set_index("month")
            st.line_chart(monthly[["records"]])
            st.dataframe(brief["monthly"], use_container_width=True, hide_index=True)
    st.caption(brief["limitations"])
    if validation.get("issues") or validation.get("warnings"):
        with st.expander("Validation warnings", expanded=True):
            for message in validation.get("issues", []) + validation.get("warnings", []):
                st.write("• " + message)
    if validation.get("pending_review"):
        with st.expander("Items awaiting your review"):
            st.dataframe(pd.DataFrame(validation["pending_review"]), hide_index=True, use_container_width=True)

    outputs = st.session_state.outputs
    safe = not bool(validation.get("issues"))
    if safe:
        st.markdown("#### Download your results")
        st.download_button("Download cleaned Excel", outputs["excel"].getvalue(), "broom_cleaned_with_audit.xlsx",
                           "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", type="primary", use_container_width=True)
        st.download_button("Download cleaned CSV", outputs["csv"], "broom_cleaned.csv", "text/csv", use_container_width=True)
    else:
        st.info("Downloads are paused because serious validation checks failed. Adjust approvals and clean again.")
    with st.expander("Technical details and audit files"):
        st.caption("Quality score is experimental and heuristic. It is NOT a guaranteed accuracy rating.")
        st.json(validation.get("datatrust_score", {}))
        if safe:
            st.download_button("Download detailed audit JSON", outputs["json_report"], "broom_audit.json", "application/json")
            st.download_button("Download business summary", outputs["executive_summary"], "broom_summary.txt", "text/plain")
        st.dataframe(st.session_state.after_problems, use_container_width=True, hide_index=True)
        st.download_button("Save cleaning choices for next time (JSON)",
                           export_recipe(st.session_state.approved_decisions), "broom_preferences.json",
                           mime="application/json")
    if st.button("← Review fixes and try again"):
        go(3)
