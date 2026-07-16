from __future__ import annotations

import json
import logging
import os
import re
from collections import defaultdict
from typing import Any

logger = logging.getLogger(__name__)

_MIGRATIONS_PATH = os.path.join(os.path.dirname(__file__), "..", "registry", "known_migrations.json")

_known_migrations: dict[str, dict[str, dict[str, Any]]] | None = None


def _load_known_migrations() -> dict[str, dict[str, dict[str, Any]]]:
    global _known_migrations
    if _known_migrations is not None:
        return _known_migrations
    try:
        with open(_MIGRATIONS_PATH) as f:
            _known_migrations = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        logger.warning("Could not load known_migrations.json: %s", e)
        _known_migrations = {}

    # Merge knowledge base files (Level 3) into fallback
    try:
        from app.knowledge.knowledge_base import load_knowledge_base
        kb = load_knowledge_base()
        for lib, symbols in kb.items():
            if lib not in _known_migrations:
                _known_migrations[lib] = {}
            for symbol, entry in symbols.items():
                if "kb" not in _known_migrations[lib]:
                    _known_migrations[lib]["kb"] = {}
                _known_migrations[lib]["kb"][symbol] = {
                    "to": entry.get("to", ""),
                    "relation": entry.get("relation", "deprecated_in_favor_of"),
                }
    except Exception as e:
        logger.warning("Could not load knowledge base files: %s", e)

    return _known_migrations


def _get_symbol_parts(symbol: str) -> tuple[str, str] | None:
    """Split symbol into (parent_path, name). Returns None if no dot."""
    if "." not in symbol:
        return None
    parts = symbol.rsplit(".", 1)
    return (parts[0], parts[1])


def _camel_to_snake(name: str) -> str:
    """Convert camelCase to snake_case."""
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", name)
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s)
    return s.lower()


def _snake_to_camel(name: str) -> str:
    """Convert snake_case to camelCase."""
    parts = name.split("_")
    return parts[0] + "".join(p.capitalize() for p in parts[1:])


def _build_module_migration_map(lib_rules: dict) -> dict[str, str]:
    """
    From known migrations for a library, identify common module path
    replacements (e.g., sklearn.cross_validation -> sklearn.model_selection).

    Only records prefix pairs where the trailing segments (after the
    divergent prefix) are identical — this avoids false positives from
    unrelated function renames.

    Returns a dict mapping old_module_prefix -> new_module_prefix.
    """
    prefix_pairs: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    for version, symbols in lib_rules.items():
        for old_sym, rule in symbols.items():
            to_sym = rule.get("to", "")
            if not to_sym or "." not in old_sym or "." not in to_sym:
                continue
            old_parts = old_sym.split(".")
            new_parts = to_sym.split(".")

            # Find the first index where the paths diverge
            min_len = min(len(old_parts), len(new_parts))
            diff_idx = None
            for i in range(min_len):
                if old_parts[i] != new_parts[i]:
                    diff_idx = i
                    break
            if diff_idx is None:
                continue

            # Only record if trailing segments match (e.g., both end with
            # "train_test_split" in sklearn.cross_validation -> model_selection).
            # This avoids false positives like pandas.DataFrame.append -> pandas.concat.
            old_tail = old_parts[diff_idx + 1:]
            new_tail = new_parts[diff_idx + 1:]
            if old_tail != new_tail:
                continue

            old_prefix = ".".join(old_parts[:diff_idx + 1])
            new_prefix = ".".join(new_parts[:diff_idx + 1])
            if old_prefix != new_prefix:
                prefix_pairs[old_prefix][new_prefix] += 1

    # Return only sufficiently supported module migrations
    result: dict[str, str] = {}
    for old_prefix, candidates in prefix_pairs.items():
        best_new = max(candidates, key=candidates.get)
        score = candidates[best_new]
        if score >= 2:
            result[old_prefix] = best_new
    return result


def _apply_camel_snake_heuristic(symbol: str, lib_rules: dict) -> str | None:
    """
    If the symbol contains a camelCase component, try converting to
    snake_case (or vice versa) and check known migrations.
    """
    parts = symbol.rsplit(".", 1)
    if len(parts) != 2:
        return None
    parent, name = parts

    variants = []

    camel = _snake_to_camel(name)
    if camel != name:
        variants.append(f"{parent}.{camel}")

    snake = _camel_to_snake(name)
    if snake != name:
        variants.append(f"{parent}.{snake}")

    for variant in variants:
        for version, symbols in lib_rules.items():
            rule = symbols.get(variant)
            if rule is not None:
                to_sym = rule.get("to", "")
                if to_sym:
                    return to_sym
    return None


def _find_module_reorganization(symbol: str, lib_rules: dict, module_map: dict[str, str]) -> str | None:
    """
    If a module reorganization is detected (e.g., sklearn.cross_validation.* -> sklearn.model_selection.*),
    try applying the module prefix replacement to the unknown symbol.
    """
    if "." not in symbol:
        return None

    sorted_prefixes = sorted(module_map.keys(), key=len, reverse=True)
    for old_prefix in sorted_prefixes:
        if symbol.startswith(old_prefix + ".") or symbol == old_prefix:
            suffix = symbol[len(old_prefix):]
            new_prefix = module_map[old_prefix]
            candidate = new_prefix + suffix
            return candidate

    return None


def extract_relationships_fallback(symbol: str, library: str) -> list[dict]:
    """
    Fallback extractor using known migration rules (curated database).
    Matches the symbol against known deprecations for the given library.

    Falls through three strategies in order:
    1. Exact lookup in known_migrations.json
    2. Convention-based heuristics:
       a. camelCase <-> snake_case conversion
       b. Module reorganization prefix replacement
    3. Simple name-based heuristics

    Returns relationships in the same format as extract_relationships_groq.
    """
    migrations = _load_known_migrations()
    lib_rules = migrations.get(library)
    if not lib_rules:
        return []

    rels: list[dict] = []

    # Strategy 1: Exact lookup
    for version, symbols in lib_rules.items():
        rule = symbols.get(symbol)
        if rule is None:
            continue
        to_sym = rule.get("to", version)
        relation = rule.get("relation", "deprecated_in_favor_of")

        rels.append({
            "from": symbol,
            "relation": relation,
            "to": to_sym,
            "confidence": 1.0,
            "extraction_method": "fallback",
            "deprecated_in_version": version if relation in ("deprecated_in", "removed_in") else None,
        })

    if rels:
        return rels

    # Strategy 2a: Case-convention heuristic
    case_to = _apply_camel_snake_heuristic(symbol, lib_rules)
    if case_to:
        rels.append({
            "from": symbol,
            "relation": "deprecated_in_favor_of",
            "to": case_to,
            "confidence": 0.7,
            "extraction_method": "fallback",
        })
        return rels

    # Strategy 2b: Module reorganization heuristic
    module_map = _build_module_migration_map(lib_rules)
    module_to = _find_module_reorganization(symbol, lib_rules, module_map)
    if module_to:
        rels.append({
            "from": symbol,
            "relation": "deprecated_in_favor_of",
            "to": module_to,
            "confidence": 0.6,
            "extraction_method": "fallback",
        })
        return rels

    # Strategy 2c: Internal module stripping heuristic (e.g., library._internal.symbol -> library.symbol)
    if "._" in symbol or ".internal." in symbol:
        stripped = re.sub(r"\._[^.]+\.", ".", symbol)
        stripped = stripped.replace(".internal.", ".")
        if stripped != symbol:
            rels.append({
                "from": symbol,
                "relation": "replaced_by",
                "to": stripped,
                "confidence": 0.6,
                "extraction_method": "fallback",
            })
            return rels

    # Strategy 3: Name-based heuristics (version suffix stripping, etc.)
    parts = _get_symbol_parts(symbol)
    if parts:
        parent, name = parts
        # Try stripping "V1", "v1", "_v1", "V2" suffixes
        stripped = re.sub(r"[_\.-]?[Vv]\d+$", "", name)
        if stripped and stripped != name:
            candidate = f"{parent}.{stripped}"
            for version, symbols in lib_rules.items():
                rule = symbols.get(candidate)
                if rule is not None:
                    to_sym = rule.get("to", "")
                    if to_sym:
                        rels.append({
                            "from": symbol,
                            "relation": "deprecated_in_favor_of",
                            "to": to_sym,
                            "confidence": 0.5,
                            "extraction_method": "fallback",
                        })
                        return rels

    return rels


def list_known_libraries() -> list[str]:
    migrations = _load_known_migrations()
    return sorted(migrations.keys())
