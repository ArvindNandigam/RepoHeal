from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

import gspread
from google.oauth2.service_account import Credentials

from app.config import get_settings

logger = logging.getLogger(__name__)

_COLUMNS = ["symbol", "to", "relation", "confidence", "source", "first_seen", "explanation"]

_kb_cache: dict[str, dict[str, dict[str, Any]]] | None = None
_client: gspread.Client | None = None
_sheet_id: str | None = None


def _get_client() -> gspread.Client | None:
    global _client
    if _client is not None:
        return _client
    settings = get_settings()
    key_json = settings.google_service_account_json
    if not key_json:
        logger.warning("GOOGLE_SERVICE_ACCOUNT_JSON not set — KB disabled")
        return None
    try:
        creds = Credentials.from_service_account_info(
            json.loads(key_json),
            scopes=["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"],
        )
        _client = gspread.authorize(creds)
        return _client
    except Exception as e:
        logger.warning("Could not authorize Google Sheets: %s", e)
        return None


def _get_or_create_sheet(client: gspread.Client) -> gspread.Spreadsheet | None:
    global _sheet_id
    settings = get_settings()
    title = settings.google_sheet_title

    if _sheet_id:
        try:
            return client.open_by_key(_sheet_id)
        except Exception:
            _sheet_id = None

    try:
        sheet = client.open(title)
        _sheet_id = sheet.id
        return sheet
    except gspread.SpreadsheetNotFound:
        try:
            sheet = client.create(title)
            _sheet_id = sheet.id
            ws = sheet.get_worksheet(0)
            ws.update_title("_metadata")
            ws.append_row(["library", "updated", "__created__", datetime.now(timezone.utc).date().isoformat()])
            return sheet
        except Exception as e:
            logger.warning("Could not create Google Sheet: %s", e)
            return None
    except Exception as e:
        logger.warning("Could not open Google Sheet: %s", e)
        return None


def _ensure_sheet_for_library(sheet: gspread.Spreadsheet, library: str) -> gspread.Worksheet | None:
    try:
        return sheet.worksheet(library)
    except gspread.WorksheetNotFound:
        try:
            ws = sheet.add_worksheet(title=library, rows=100, cols=20)
            ws.append_row(_COLUMNS)
            return ws
        except Exception as e:
            logger.warning("Could not create sheet for %s: %s", library, e)
            return None


def _find_symbol_row(ws: gspread.Worksheet, symbol: str) -> int | None:
    try:
        col_a = ws.col_values(1)
    except Exception:
        return None
    for i, val in enumerate(col_a):
        if val == symbol:
            return i + 1
    return None


def load_knowledge_base() -> dict[str, dict[str, dict[str, Any]]]:
    global _kb_cache
    if _kb_cache is not None:
        return _kb_cache
    _kb_cache = {}

    client = _get_client()
    if not client:
        return _kb_cache

    sheet = _get_or_create_sheet(client)
    if not sheet:
        return _kb_cache

    for ws in sheet.worksheets():
        lib = ws.title
        if lib == "_metadata":
            continue
        try:
            rows = ws.get_all_values()
        except Exception as e:
            logger.warning("Could not read sheet %s: %s", lib, e)
            continue
        if not rows or rows[0][0] != "symbol":
            continue

        symbols: dict[str, dict[str, Any]] = {}
        for row in rows[1:]:
            if not row or not row[0]:
                continue
            symbol = row[0]
            entry = {
                "to": row[1] if len(row) > 1 else "",
                "relation": row[2] if len(row) > 2 else "deprecated_in_favor_of",
                "confidence": float(row[3]) if len(row) > 3 and row[3] else 1.0,
                "source": row[4] if len(row) > 4 else "curated",
                "first_seen": row[5] if len(row) > 5 else "",
                "explanation": row[6] if len(row) > 6 else "",
            }
            symbols[symbol] = entry

        if symbols:
            _kb_cache[lib] = symbols

    logger.info("Loaded %d libraries from Google Sheets KB", len(_kb_cache))
    return _kb_cache


def add_to_knowledge_base(library: str, symbol: str, entry: dict[str, Any]) -> bool:
    client = _get_client()
    if not client:
        return False

    sheet = _get_or_create_sheet(client)
    if not sheet:
        return False

    ws = _ensure_sheet_for_library(sheet, library)
    if not ws:
        return False

    if _find_symbol_row(ws, symbol) is not None:
        return False

    try:
        ws.append_row([
            symbol,
            entry.get("to", ""),
            entry.get("relation", "deprecated_in_favor_of"),
            entry.get("confidence", 1.0),
            entry.get("source", "groq"),
            entry.get("first_seen", datetime.now(timezone.utc).date().isoformat()),
            entry.get("explanation", ""),
        ])
    except Exception as e:
        logger.warning("Could not append row to Google Sheet: %s", e)
        return False

    if _kb_cache is not None:
        if library not in _kb_cache:
            _kb_cache[library] = {}
        _kb_cache[library][symbol] = entry

    logger.info("Added to knowledge base: %s/%s -> %s", library, symbol, entry.get("to", ""))
    return True
