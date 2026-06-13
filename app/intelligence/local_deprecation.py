import re
from typing import Dict, List, Optional, Tuple
from app.utils.logger import get_logger

logger = get_logger(__name__)


def parse_version(v: str):
    if not v or v == "unknown":
        return None
    match = re.search(r"\d+(?:\.\d+){0,2}", str(v))
    if not match:
        return None
    parts = [int(part) for part in match.group(0).split(".")]
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])


LOCAL_KNOWLEDGE: Dict[str, List[Dict]] = {
    "pandas": [
        {
            "symbol": "pandas.DataFrame.append",
            "deprecated_in": "2.0.0",
            "removed_in": None,
            "replacement": "pandas.concat",
            "match_patterns": ["DataFrame.append", ".append"],
        },
        {
            "symbol": "pandas.Series.append",
            "deprecated_in": "2.0.0",
            "removed_in": None,
            "replacement": "pandas.concat",
            "match_patterns": ["Series.append", ".append"],
        },
    ],
    "numpy": [
        {
            "symbol": "numpy.asscalar",
            "deprecated_in": "1.16.0",
            "removed_in": "1.24.0",
            "replacement": "numpy.ndarray.item",
            "match_patterns": ["asscalar", ".asscalar"],
        },
        {
            "symbol": "numpy.histogramdd",
            "deprecated_in": "1.24.0",
            "removed_in": None,
            "replacement": None,
            "match_patterns": ["histogramdd"],
        },
    ],
    "sklearn": [
        {
            "symbol": "sklearn.cross_validation",
            "deprecated_in": "0.20.0",
            "removed_in": "1.0.0",
            "replacement": "sklearn.model_selection",
            "match_patterns": ["cross_validation"],
        },
    ],
}


def _version_lte(v1_str: str, v2_str: str) -> bool:
    v1 = parse_version(v1_str)
    v2 = parse_version(v2_str)
    if v1 is None or v2 is None:
        return False
    return v1 <= v2


def _version_gte(v1_str: str, v2_str: str) -> bool:
    v1 = parse_version(v1_str)
    v2 = parse_version(v2_str)
    if v1 is None or v2 is None:
        return False
    return v1 >= v2


def _symbol_matches(symbol: str, patterns: List[str]) -> bool:
    symbol_lower = symbol.lower()
    for pat in patterns:
        if pat.lower() in symbol_lower:
            return True
    return False


def check_local_deprecation(
    library: str,
    symbol: str,
    installed_version: str,
    latest_version: str,
) -> Optional[Dict]:
    entries = LOCAL_KNOWLEDGE.get(library, [])
    for entry in entries:
        if _symbol_matches(symbol, entry["match_patterns"]):
            dep_in = entry["deprecated_in"]
            rem_in = entry["removed_in"]

            status = "at_risk"
            if rem_in and _version_gte(installed_version, rem_in):
                status = "breaking"
            elif dep_in and _version_gte(installed_version, dep_in):
                status = "deprecated"

            return {
                "library": library,
                "symbol": entry["symbol"],
                "installed_version": installed_version,
                "latest_version": latest_version,
                "status": status,
                "intelligence_source": "local_kb",
                "relationships": [
                    {
                        "relation": "deprecated_in_favor_of" if entry.get("replacement") else "deprecated_in",
                        "target": entry["replacement"] or "",
                        "status": status,
                        "confidence": 0.95,
                    }
                ],
                "version_distance": {
                    "installed": installed_version,
                    "latest": latest_version,
                    "deprecated_in": dep_in,
                    "removed_in": rem_in,
                    "major_diff": 0,
                    "minor_diff": 0,
                    "patch_diff": 0,
                },
            }
    return None


def apply_local_fallback(
    fingerprints: Dict,
    dependency_graph: Dict,
    existing_assessments: List,
) -> List[Dict]:
    existing_keys = set()
    for a in existing_assessments:
        key = (a.get("library"), a.get("symbol"))
        existing_keys.add(key)

    new_assessments = []
    for library, fp_data in fingerprints.items():
        symbols = fp_data.get("symbols", [])
        dep_info = dependency_graph.get(library, {})
        installed_version = fp_data.get("version") or dep_info.get("version", "unknown")
        latest_version = dep_info.get("latest_version", "unknown")

        for symbol in symbols:
            key = (library, symbol)
            if key in existing_keys:
                continue

            result = check_local_deprecation(library, symbol, installed_version, latest_version)
            if result:
                new_assessments.append(result)
                logger.info(
                    f"Local deprecation detected: {library}.{symbol} "
                    f"(installed={installed_version}, status={result['status']})"
                )

    return new_assessments
