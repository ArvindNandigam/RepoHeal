from app.analysis.package_normalization import normalize_package_name

# Map call suffixes / patterns to canonical symbols for intelligence lookup.
LIBRARY_SYMBOL_EXPANSIONS = {
    "pandas": {
        ".append": "pandas.DataFrame.append",
        "DataFrame.append": "pandas.DataFrame.append",
    },
    "numpy": {
        ".asscalar": "numpy.asscalar",
        "asscalar": "numpy.asscalar",
    },
    "sklearn": {
        "cross_validation": "sklearn.cross_validation",
    },
}


def expand_symbols_for_intelligence(library: str, symbols: list[str]) -> list[str]:
    """Add canonical symbol names so webtool can match deprecated APIs."""
    expanded = set(symbols)
    patterns = LIBRARY_SYMBOL_EXPANSIONS.get(library, {})

    for symbol in symbols:
        expanded.add(symbol)
        if symbol.startswith(f"{library}."):
            expanded.add(symbol)

        method = symbol.split(".")[-1] if "." in symbol else symbol
        expanded.add(f"{library}.{method}")

        for suffix, canonical in patterns.items():
            if symbol.endswith(suffix) or suffix.lstrip(".") == method:
                expanded.add(canonical)

        if library == "pandas" and method == "append":
            expanded.add("pandas.DataFrame.append")

    return sorted(expanded)


def generate_fingerprints(semantic_graph, dependencies):
    """
    Extract unique external API symbols from the semantic graph
    and group them by root library, attaching the detected version.
    """
    fingerprints = {}

    declared = dependencies if isinstance(dependencies, dict) and "declared" not in dependencies else (
        dependencies.get("declared", {}) if isinstance(dependencies, dict) else {}
    )
    if not declared and isinstance(dependencies, dict):
        declared = dependencies

    files = semantic_graph.get("files", {})

    for file_path, file_data in files.items():
        apis = file_data.get("apis", [])

        for api in apis:
            package = api.get("package")
            api_name = api.get("name")

            if not package or not api_name:
                continue

            normalized_pkg = normalize_package_name(package)

            if normalized_pkg not in fingerprints:
                dep_info = declared.get(normalized_pkg, {}) if isinstance(declared, dict) else {}
                version = dep_info.get("version", "unknown")

                fingerprints[normalized_pkg] = {
                    "version": version,
                    "symbols": set(),
                    "raw_symbols": set(),
                }

            fingerprints[normalized_pkg]["raw_symbols"].add(api_name)
            for symbol in expand_symbols_for_intelligence(normalized_pkg, [api_name]):
                fingerprints[normalized_pkg]["symbols"].add(symbol)

    for pkg, data in fingerprints.items():
        data["symbols"] = sorted(list(data["symbols"]))
        data["raw_symbols"] = sorted(list(data["raw_symbols"]))

    return fingerprints
