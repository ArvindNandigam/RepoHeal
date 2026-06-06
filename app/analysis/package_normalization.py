PACKAGE_ALIASES = {
    "bs4": "beautifulsoup4",
    "crypto": "pycryptodome",
    "cv2": "opencv-python",
    "dateutil": "python-dateutil",
    "pil": "pillow",
    "pyyaml": "pyyaml",
    "skimage": "scikit-image",
    "sklearn": "scikit-learn",
    "yaml": "pyyaml",
}


def normalize_package_name(name: str) -> str:
    if not name:
        return name

    root = name.split(".")[0].strip().replace("_", "-")
    return PACKAGE_ALIASES.get(root.lower(), root.lower())


def split_namespace_parts(name: str):
    if not name:
        return []

    return [part for part in name.strip(".").split(".") if part]


def build_namespace_hierarchy(import_name: str, symbol_name: str = None):
    module_parts = split_namespace_parts(import_name)

    if not module_parts:
        return {
            "root": None,
            "module_path": None,
            "leaf_path": None,
            "nodes": []
        }

    nodes = []
    cumulative_parts = []

    for depth, part in enumerate(module_parts):
        cumulative_parts.append(part)
        current_path = ".".join(cumulative_parts)

        nodes.append(
            {
                "path": current_path,
                "label": part,
                "kind": "Package" if depth == 0 else "Module",
                "depth": depth,
                "parent_path": ".".join(cumulative_parts[:-1]) or None,
                "relationship": "CONTAINS" if depth > 0 else None
            }
        )

    leaf_path = ".".join(module_parts)

    if symbol_name:
        clean_symbol_name = symbol_name.strip()

        if clean_symbol_name:
            leaf_path = f"{leaf_path}.{clean_symbol_name}"
            nodes.append(
                {
                    "path": leaf_path,
                    "label": clean_symbol_name,
                    "kind": "Symbol",
                    "depth": len(module_parts),
                    "parent_path": ".".join(module_parts),
                    "relationship": "EXPOSES"
                }
            )

    return {
        "root": module_parts[0],
        "module_path": ".".join(module_parts),
        "leaf_path": leaf_path,
        "nodes": nodes
    }


def build_module_name(file_path: str, repo_path: str) -> str:
    from pathlib import Path

    relative_path = Path(file_path).resolve().relative_to(
        Path(repo_path).resolve()
    )

    parts = list(relative_path.parts)

    if not parts:
        return Path(file_path).stem

    if parts[-1] == "__init__.py":
        parts = parts[:-1]
    else:
        parts[-1] = Path(parts[-1]).stem

    return ".".join(part for part in parts if part)


def is_local_import(import_name: str, module_index) -> bool:
    if not import_name:
        return False

    normalized_import = import_name.lstrip(".")

    for module_name in module_index:
        if (
            module_name == normalized_import
            or module_name.startswith(f"{normalized_import}.")
            or normalized_import.startswith(f"{module_name}.")
        ):
            return True

    return False