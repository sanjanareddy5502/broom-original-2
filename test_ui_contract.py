"""Basic five-page program-flow smoke test using a Streamlit facade.

Not a replacement for real-browser or production tests; checks page code paths
when Streamlit is absent from the verification environment.
"""
import runpy
import sys
from pathlib import Path
from types import ModuleType
import pandas as pd

from broom_core.pipeline import diagnose

class Session(dict):
    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError:
            raise AttributeError(name) from None
    def __setattr__(self, key, value):
        self[key] = value

class Block:
    def __init__(self, shared):
        self.session_state = shared
        self.sidebar = self
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def __getattr__(self, name):
        if name in ('columns',):
            return lambda amount, **kw: [self for _ in range(amount if isinstance(amount, int) else len(amount))]
        if name in ('expander','spinner'):
            return lambda *args,**kw: self
        if name in ('file_uploader','button'):
            return lambda *args,**kw: None
        if name == 'checkbox':
            return lambda *args,**kw: bool(kw.get('value',False))
        if name == 'selectbox':
            return lambda *args,**kw: args[1][kw.get('index',0)]
        if name == 'stop':
            return lambda: None
        if name == 'rerun':
            return lambda: None
        if name == 'download_button':
            return lambda *args,**kw: None
        return lambda *args,**kw: None


def test_five_stages_import_and_run_through(monkeypatch):
    shared = Session()
    mock = Block(shared)
    shim = ModuleType('streamlit')
    shim.__getattr__ = mock.__getattr__
    shim.session_state = shared
    shim.sidebar = mock
    monkeypatch.setitem(sys.modules,'streamlit',shim)

    raw = pd.DataFrame({'order_date':['2026-01-01','2026-02-01','2026-03-01'],
                        'amount':['$20','$30','$40'], 'customer':['A','B','C']})
    diag = diagnose(raw)
    shared.raw = raw
    shared.filename = 'test.csv'
    shared.profile = diag.profile
    shared.problems = diag.problems
    shared.column_report = diag.column_report
    shared.missing_intelligence = diag.missing_report
    shared.intelligence = diag.intelligence
    shared.diagnosis = diag
    shared.decisions = diag.plan

    src = str(Path(__file__).resolve().parents[1] / 'app.py')
    for step in (1,2,3,4,5):
        shared.step = step
        runpy.run_path(src, run_name='__main__')
    assert 'outputs' in shared
    assert shared.outputs['excel'].getbuffer().nbytes > 1000
