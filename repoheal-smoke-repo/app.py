"""Small static-analysis fixture for trying RepoHeal on a disposable repository.

This file is input for RepoHeal's AST scanner. It is not intended to be run as
an application: fetch_records() makes an HTTP request when explicitly called,
and build_frame() contains an intentionally obsolete pandas API call.
"""

from datetime import datetime
from typing import Any

import pandas as pd
import requests
from dateutil.parser import parse  # Intentionally missing from requirements.txt.
from flask import Flask, jsonify


def fetch_records(url: str) -> list[dict[str, Any]]:
    """Fetch JSON records; this function is never called by the fixture."""
    response = requests.get(url, timeout=3)
    response.raise_for_status()
    payload = response.json()
    return payload if isinstance(payload, list) else [payload]


def build_frame(records: list[dict[str, Any]]) -> pd.DataFrame:
    """Build a sample table using a deprecated pandas method on purpose."""
    frame = pd.DataFrame.from_records(records)
    return frame.append({"checked_at": datetime.utcnow().isoformat()}, ignore_index=True)


def parse_timestamp(value: str) -> datetime:
    """Parse a timestamp using an intentionally undeclared direct dependency."""
    return parse(value)


def create_app() -> Flask:
    """Expose a small Flask route so the scanner sees a framework relationship."""
    app = Flask(__name__)

    @app.get("/health")
    def health():
        return jsonify({"status": "demo", "rows": len(build_frame([]))})

    return app


if __name__ == "__main__":
    # Running this module is not required for RepoHeal analysis.
    create_app().run(debug=False)
