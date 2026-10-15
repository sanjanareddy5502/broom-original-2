import pandas as pd
from date_intelligence import inspect_dates
from business_intelligence import understand_dataset
from profiler import profile_dataset
from decision_engine import decide_cleaning_actions
from cleaner import clean_dataset
from validator import validate_cleaned_data
from builder import build_outputs
from report_intelligence import detect_report_structure


def workflow(df, approvals=()):
    before, _, _, problems = profile_dataset(df)
    plan = decide_cleaning_actions(before)
    for item in plan:
        if item['action'] in approvals:
            item['approved'] = True
    after, summary = clean_dataset(df, plan)
    summary['issues_found_before'] = before['problem_count']
    report = validate_cleaned_data(df, after, summary)
    output = build_outputs(after, before, None, plan, summary, report, problems)
    return before, plan, after, summary, report, output


def test_date_inference_uses_unambiguous_evidence():
    result = inspect_dates(pd.Series(['2026-03-13', '15/03/2026', '04/05/2026']))
    assert result['status'] == 'ready'
    assert str(result['parsed'].iloc[2].date()) == '2026-05-04'


def test_ambiguous_dates_never_guessed():
    raw = pd.Series(['01/02/2026', '03/04/2026'])
    assert inspect_dates(raw)['status'] == 'review'
    assert inspect_dates(raw, 'day_first')['parsed'].iloc[0].month == 2
    assert inspect_dates(raw, 'month_first')['parsed'].iloc[0].month == 1


def test_dates_without_year_are_not_assumed_to_be_current_year():
    assert inspect_dates(pd.Series(['Mar 1', 'Apr 2']))['status'] == 'review'


def test_invalid_values_preserved_and_pending():
    raw = pd.DataFrame({'Order Date': ['2026-01-03','2026-01-04','not a date'], 'Amount':['12','$8','oops']})
    profile, *_ = workflow(raw, approvals=('convert_text_to_datetime',))
    assert profile['problem_count'] > 0
    # At minimum date can't silently overwrite bad values.
    plan = [{'action':'convert_text_to_datetime','columns':['Order Date'],'approved':True}]
    after, summary = clean_dataset(raw, plan)
    assert after['Order Date'].iloc[2] == 'not a date'
    assert any(event['action'] == 'needs_date_review' for event in summary['cleaning_log'])


def test_numeric_conversion_preserves_invalid_original():
    raw = pd.DataFrame({'sales':['$1,200', 'broken', '2,100']})
    after, summary = clean_dataset(raw, [{'action':'convert_text_to_numeric','columns':['sales'],'approved':True}])
    assert after.loc[1,'sales'] == 'broken'
    assert any(e['action']=='needs_numeric_review' for e in summary['cleaning_log'])


def test_safe_numeric_conversion():
    raw = pd.DataFrame({'sales':['$1,200', '2,100', None]})
    after, _ = clean_dataset(raw, [{'action':'convert_text_to_numeric','columns':['sales'],'approved':True}])
    assert after['sales'].iloc[0] == 1200
    assert pd.isna(after['sales'].iloc[2])


def test_business_critical_missing_not_filled_even_if_approved():
    raw = pd.DataFrame({'customer_id':['C1', None, 'C3'], 'Amount':[100, None, 300], 'Team':['A',None,'A']})
    after, summary = clean_dataset(raw, [{'action':'fill_missing_values','approved':True}])
    assert pd.isna(after.loc[1,'customer_id'])
    assert pd.isna(after.loc[1,'Amount'])
    assert after.loc[1,'Team'] == 'A'
    assert any(e['action']=='skipped_business_critical_missing' for e in summary['cleaning_log'])


def test_review_duplicates_dont_remove_by_default():
    raw = pd.DataFrame({'name':['A','A'], 'sales':[5,5]})
    _, plan, after, *_ = workflow(raw)
    assert len(after) == 2
    assert any(d['action']=='remove_exact_duplicate_rows' and not d['approved'] for d in plan)


def test_empty_column_export_and_business_insight():
    raw = pd.DataFrame({'customer':['A','B'], 'empty':[None,None], 'Order Date':['2026-03-01','2026-03-02']})
    profile, plan, after, summary, validation, outputs = workflow(raw)
    assert 'empty' not in after.columns
    assert len(outputs['excel'].getvalue()) > 1000
    assert '2026-03-01' in ' '.join(understand_dataset(after, profile)['observations'])


def test_quickbooks_report_and_money_conversion():
    rows = []
    for vendor in ('Acme', 'Bravo', 'Cyan'):
        rows.append({'Unnamed: 1':vendor,'Type':None,'Date':None,'Account':None,'Split':None,'Debit':None,'Credit':None,'Unnamed: 8':None,'Unnamed: 9':None})
        rows.append({'Unnamed: 1':None,'Type':'Bill','Date':'2026-02-01','Account':'100 · Expense','Split':'A','Debit':'($1,200.00)','Credit':None,'Unnamed: 8':None,'Unnamed: 9':None})
    raw = pd.DataFrame(rows)
    assert detect_report_structure(raw)['detected']
    _, plan, out, summary, validation, outputs = workflow(raw, approvals=("transform_quickbooks_vendor_report",))
    assert any(d['action']=='transform_quickbooks_vendor_report' for d in plan)
    assert len(out) == 3
    assert out['Debit'].iloc[0] == -1200
    assert summary['report_summary']['columns_removed_as_report_spacers'] == 2
    assert len(outputs['excel'].getvalue()) > 1000


def test_quickbooks_invalid_money_fails_closed():
    rows = []
    for vendor in ('Acme', 'Bravo', 'Cyan'):
        rows.append({'Unnamed: 1':vendor,'Type':None,'Date':None,'Account':None,'Split':None,'Debit':None,'Credit':None,'Unnamed: 8':None,'Unnamed: 9':None})
        rows.append({'Unnamed: 1':None,'Type':'Bill','Date':'2026-02-01','Account':'Expense','Split':'A','Debit':'bad-value','Credit':None,'Unnamed: 8':None,'Unnamed: 9':None})
    raw = pd.DataFrame(rows)
    _, plan = profile_dataset(raw)[0], decide_cleaning_actions(profile_dataset(raw)[0])
    for d in plan:
        if d["action"] == "transform_quickbooks_vendor_report":
            d["approved"] = True
    try:
        clean_dataset(raw, plan)
        assert False, 'Expected failure'
    except ValueError as err:
        assert 'invalid Debit' in str(err)


def test_export_escapes_spreadsheet_formulas():
    raw = pd.DataFrame({'customer':['=HYPERLINK("http://bad")', '+SUM(1,2)', '@cmd', 'Normal']})
    _, _, _, _, _, outputs = workflow(raw)
    assert "'=HYPERLINK" in outputs['csv']
    from io import BytesIO
    from openpyxl import load_workbook
    book = load_workbook(BytesIO(outputs['excel'].getvalue()))
    cell = book['cleaned_data']['A2']
    assert cell.data_type != 'f'
    assert cell.value.startswith("'=")


def test_inference_preserves_leading_zero_identifiers():
    raw = pd.DataFrame({'postal_code':['00101','00102','00103']})
    _, plan, after, *_ = workflow(raw)
    assert after['postal_code'].tolist() == ['00101','00102','00103']
