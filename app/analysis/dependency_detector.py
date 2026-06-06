import ast
import configparser
import json
from pathlib import Path

try:
    import tomllib
except ImportError:
    try:
        import tomli as tomllib
    except ImportError:
        tomllib = None

from app.analysis.package_normalization import normalize_package_name
from app.utils.logger import get_logger

logger = get_logger(__name__)


def extract_requirements(repo_path):
    dependencies = {}
    base_path = Path(repo_path)

    # 1. poetry.lock / pyproject.toml
    if (base_path / "poetry.lock").exists() and tomllib:
        _parse_poetry_lock(base_path / "poetry.lock", dependencies)
    elif (base_path / "pyproject.toml").exists() and tomllib:
        _parse_pyproject_toml(base_path / "pyproject.toml", dependencies)
    
    # 2. Pipfile.lock / Pipfile
    if (base_path / "Pipfile.lock").exists():
        _parse_pipfile_lock(base_path / "Pipfile.lock", dependencies)
    elif (base_path / "Pipfile").exists() and tomllib:
        _parse_pipfile(base_path / "Pipfile", dependencies)
        
    # 3. requirements.txt
    if (base_path / "requirements.txt").exists():
        _parse_requirements_txt(base_path / "requirements.txt", dependencies)

    # 4. setup.cfg
    if (base_path / "setup.cfg").exists():
        _parse_setup_cfg(base_path / "setup.cfg", dependencies)

    # 5. setup.py
    if (base_path / "setup.py").exists():
        _parse_setup_py(base_path / "setup.py", dependencies)

    logger.info(f"Detected {len(dependencies)} dependencies")
    return dependencies


def _add_dependency(deps, name, version, specifier, source):
    if not name:
        return
    normalized = normalize_package_name(name)
    if normalized not in deps or deps[normalized]["version"] in ("unknown", "*", ""):
        deps[normalized] = {
            "version": version or "unknown",
            "specifier": specifier or "==",
            "source": source
        }


def _parse_requirements_txt(path, deps):
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or line.startswith("-"):
                    continue
                
                if "==" in line:
                    pkg, ver = line.split("==", 1)
                    _add_dependency(deps, pkg, ver.strip(), "==", "requirements.txt")
                elif ">=" in line:
                    pkg, ver = line.split(">=", 1)
                    _add_dependency(deps, pkg, ver.strip(), ">=", "requirements.txt")
                elif "~=" in line:
                    pkg, ver = line.split("~=", 1)
                    _add_dependency(deps, pkg, ver.strip(), "~=", "requirements.txt")
                else:
                    _add_dependency(deps, line, "unknown", "", "requirements.txt")
    except Exception as e:
        logger.warning(f"Failed to parse requirements.txt: {e}")


def _parse_poetry_lock(path, deps):
    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)
        for pkg in data.get("package", []):
            _add_dependency(deps, pkg.get("name"), pkg.get("version"), "==", "poetry.lock")
    except Exception as e:
        logger.warning(f"Failed to parse poetry.lock: {e}")


def _parse_pyproject_toml(path, deps):
    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)
            
        poetry_deps = data.get("tool", {}).get("poetry", {}).get("dependencies", {})
        for pkg, ver in poetry_deps.items():
            if pkg == "python": continue
            ver_str = str(ver.get("version") if isinstance(ver, dict) else ver)
            _add_dependency(deps, pkg, ver_str, "==", "pyproject.toml")
            
        project_deps = data.get("project", {}).get("dependencies", [])
        for dep in project_deps:
            if ">=" in dep:
                p, v = dep.split(">=", 1)
                _add_dependency(deps, p.strip(), v.strip(), ">=", "pyproject.toml")
            elif "==" in dep:
                p, v = dep.split("==", 1)
                _add_dependency(deps, p.strip(), v.strip(), "==", "pyproject.toml")
            else:
                _add_dependency(deps, dep, "unknown", "", "pyproject.toml")
    except Exception as e:
        logger.warning(f"Failed to parse pyproject.toml: {e}")


def _parse_pipfile_lock(path, deps):
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        for pkg, details in data.get("default", {}).items():
            version = details.get("version", "").lstrip("=")
            _add_dependency(deps, pkg, version, "==", "Pipfile.lock")
    except Exception as e:
        logger.warning(f"Failed to parse Pipfile.lock: {e}")


def _parse_pipfile(path, deps):
    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)
        for pkg, ver in data.get("packages", {}).items():
            ver_str = str(ver.get("version") if isinstance(ver, dict) else ver).lstrip("=")
            _add_dependency(deps, pkg, ver_str, "==", "Pipfile")
    except Exception as e:
        logger.warning(f"Failed to parse Pipfile: {e}")


def _parse_setup_cfg(path, deps):
    try:
        config = configparser.ConfigParser()
        config.read(path)
        if config.has_section("options"):
            requires = config.get("options", "install_requires", fallback="")
            for line in requires.split("\n"):
                line = line.strip()
                if line:
                    if ">=" in line:
                        p, v = line.split(">=", 1)
                        _add_dependency(deps, p.strip(), v.strip(), ">=", "setup.cfg")
                    elif "==" in line:
                        p, v = line.split("==", 1)
                        _add_dependency(deps, p.strip(), v.strip(), "==", "setup.cfg")
                    else:
                        _add_dependency(deps, line, "unknown", "", "setup.cfg")
    except Exception as e:
        logger.warning(f"Failed to parse setup.cfg: {e}")


def _parse_setup_py(path, deps):
    try:
        with open(path, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read())
            
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "setup":
                for kw in node.keywords:
                    if kw.arg == "install_requires" and isinstance(kw.value, ast.List):
                        for elt in kw.value.elts:
                            if isinstance(elt, ast.Constant):
                                val = elt.value
                                if "==" in val:
                                    p, v = val.split("==", 1)
                                    _add_dependency(deps, p.strip(), v.strip(), "==", "setup.py")
                                else:
                                    _add_dependency(deps, val, "unknown", "", "setup.py")
    except Exception as e:
        logger.warning(f"Failed to parse setup.py: {e}")