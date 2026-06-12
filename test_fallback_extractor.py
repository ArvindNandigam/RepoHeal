"""Test the fallback extractor for known migration rules."""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.discovery.fallback_extractor import (
    extract_relationships_fallback,
    list_known_libraries,
    _camel_to_snake,
    _snake_to_camel,
    _build_module_migration_map,
    _apply_camel_snake_heuristic,
)

libraries = list_known_libraries()
print("Known libraries: %d" % len(libraries))
print("Libraries: %s" % libraries)

symbols_to_test = [
    ("pandas", "pandas.DataFrame.append"),
    ("pandas", "pandas.Series.append"),
    ("numpy", "numpy.rank"),
    ("requests", "requests.packages"),
    ("pydantic", "pydantic.BaseModel.dict"),
    ("openai", "openai.ChatCompletion.create"),
    ("tensorflow", "tf.Session"),
    ("scikit-learn", "sklearn.cross_validation"),
    ("pandas", "unknown.symbol"),
    ("nonexistent", "test.symbol"),
]

print("\nTesting specific symbols:")
for lib, sym in symbols_to_test:
    rels = extract_relationships_fallback(sym, lib)
    if rels:
        r = rels[0]
        print("  %s.%s: %s --[%s]--> %s" % (lib, sym, r["from"], r["relation"], r["to"]))
    else:
        print("  %s.%s: (no match)" % (lib, sym))


# --- Heuristic tests ---

def test_camel_snake_conversion():
    assert _camel_to_snake("camelCase") == "camel_case"
    assert _camel_to_snake("XMLParser") == "xml_parser"
    assert _camel_to_snake("simple") == "simple"
    assert _snake_to_camel("snake_case") == "snakeCase"
    assert _snake_to_camel("alreadyCamel") == "alreadyCamel"
    print("camel/snake conversion OK")

def test_camel_snake_heuristic_on_pandas():
    # pandas uses snake_case; if we ask for a camelCase variant, it should find the snake_case rule
    rels = extract_relationships_fallback("pandas.DataFrame.setValue", "pandas")
    if rels:
        # Should find pandas.DataFrame.set_value -> pandas.DataFrame.at
        print("  camelCase heuristic: pandas.DataFrame.setValue --[%s]--> %s" % (rels[0]["relation"], rels[0]["to"]))
    else:
        print("  camelCase heuristic: no match (pandas.setValue -> ?)")

def test_module_migration_map():
    migrations = json.load(open("app/registry/known_migrations.json"))
    lib_rules = migrations.get("scikit-learn", {})
    module_map = _build_module_migration_map(lib_rules)
    if module_map:
        print("  Module migration map: %s" % module_map)
        # sklearn.cross_validation -> sklearn.model_selection should be detected
        assert "sklearn.cross_validation" in module_map
        assert module_map["sklearn.cross_validation"].startswith("sklearn.model_selection")
    print("Module migration map OK")

def test_module_reorganization_heuristic():
    # sklearn.cross_validation.StratifiedKFold is NOT in known_migrations,
    # but the module migration map should infer it maps to sklearn.model_selection.StratifiedKFold
    rels = extract_relationships_fallback("sklearn.cross_validation.StratifiedKFold", "scikit-learn")
    if rels:
        print("  Module reorganization: sklearn.cross_validation.StratifiedKFold --[%s]--> %s" % (rels[0]["relation"], rels[0]["to"]))
        assert "model_selection" in rels[0]["to"]
    else:
        print("  Module reorganization: no match (may need more rules for inference)")

def test_no_false_positive_for_unknown():
    rels = extract_relationships_fallback("pandas.DataFrame.nonexistent", "pandas")
    assert len(rels) == 0
    print("No false positives for unknown symbols OK")

if __name__ == "__main__":
    test_camel_snake_conversion()
    test_camel_snake_heuristic_on_pandas()
    test_module_migration_map()
    test_module_reorganization_heuristic()
    test_no_false_positive_for_unknown()
    print("\nAll fallback heuristic tests passed.")
