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

    root = name.split(".")[0].strip()
    return PACKAGE_ALIASES.get(root.lower(), root)


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