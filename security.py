"""Upload limits, read-time protections and explicit safety policy.

A local desktop Streamlit proof-of-concept is NOT a hardened multi-tenant service.
Deployment must also enforce reverse-proxy limits, TLS, authentication and isolation.
"""
from __future__ import annotations
from io import BytesIO
from pathlib import Path
import re
from zipfile import BadZipFile, ZipFile
import pandas as pd

MAX_UPLOAD_BYTES = 15 * 1024 * 1024
MAX_ROWS = 100_000
MAX_COLUMNS = 250
MAX_CELLS = 2_000_000
MAX_XLSX_EXPANDED = 75 * 1024 * 1024
MAX_XLSX_PARTS = 1_000

class InputRejected(ValueError):
    """File rejected before analysis or cleaning."""


def _check_frame(df: pd.DataFrame) -> pd.DataFrame:
    rows, cols = df.shape
    if not rows or not cols:
        raise InputRejected("This file has no usable rows or columns.")
    if rows > MAX_ROWS or cols > MAX_COLUMNS or rows * cols > MAX_CELLS:
        raise InputRejected(f"Demo limit: {MAX_ROWS:,} rows, {MAX_COLUMNS} columns, and {MAX_CELLS:,} cells.")
    if df.columns.duplicated().any():
        raise InputRejected("Duplicate column names need manual review before uploading. Rename them in the source file.")
    return df


def _check_xlsx(data: bytes) -> None:
    try:
        with ZipFile(BytesIO(data)) as archive:
            parts = archive.infolist()
            if len(parts) > MAX_XLSX_PARTS:
                raise InputRejected("Excel contains too many internal parts.")
            if sum(part.file_size for part in parts) > MAX_XLSX_EXPANDED:
                raise InputRejected("Excel expands beyond the demo safety limit.")
            if any(part.file_size > 25 * 1024 * 1024 or
                   (part.compress_size and part.file_size / part.compress_size > 250)
                   for part in parts):
                raise InputRejected("Excel contains an unusually compressed or oversized component.")
            names = {part.filename.lower() for part in parts}
            if 'xl/workbook.xml' not in names or '[content_types].xml' not in names:
                raise InputRejected("Not a valid .xlsx workbook.")
            if any('vbaproject.bin' in name or name.startswith('xl/externallinks/') for name in names):
                raise InputRejected("Macros or external workbook links are unsupported in this demo.")
            # Pandas/openpyxl may otherwise read empty cached values for Excel
            # formulas. Fail closed: we must not silently erase spreadsheet data.
            for part in parts:
                path = part.filename.lower()
                if path.startswith('xl/worksheets/') and path.endswith('.xml'):
                    xml = archive.read(part)
                    if re.search(rb'<(?:[a-z0-9_]+:)?f(?:[\s>])', xml, flags=re.I):
                        raise InputRejected("This workbook contains formulas. Save a values-only copy before uploading so Broom won't lose formula results.")
    except BadZipFile as exc:
        raise InputRejected("Excel workbook is invalid or damaged.") from exc


def read_uploaded_file(data: bytes, filename: str) -> pd.DataFrame:
    """Read one data sheet; preserve CSV identifiers and detect oversized input.

    For file validation on a public server use additional sandboxing and budgets.
    """
    if not isinstance(data, bytes) or not data:
        raise InputRejected("The file is empty.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise InputRejected("The demo accepts files up to 15 MB.")
    extension = Path(filename).suffix.lower()
    try:
        if extension == '.xlsx':
            _check_xlsx(data)
            df = pd.read_excel(BytesIO(data), engine='openpyxl', sheet_name=0)
        elif extension == '.csv':
            if b'\x00' in data[:4096]:
                raise InputRejected("This is not a supported plain-text CSV file.")
            # No dtype inference on CSV: '00120' must stay '00120'.
            errors = []
            for encoding in ('utf-8-sig', 'cp1252'):
                try:
                    df = pd.read_csv(BytesIO(data), encoding=encoding, dtype=str,
                                     keep_default_na=False, on_bad_lines='error', low_memory=False)
                    break
                except UnicodeDecodeError as exc:
                    errors.append(exc)
            else:
                raise InputRejected("CSV text encoding unsupported. Save as UTF-8 CSV.")
        else:
            raise InputRejected("Use a CSV or .xlsx file only.")
    except InputRejected:
        raise
    except (ValueError, UnicodeError, pd.errors.ParserError, EOFError, OSError) as exc:
        raise InputRejected("Could not read the file. Check the CSV structure or Excel sheet.") from exc
    return _check_frame(df)
