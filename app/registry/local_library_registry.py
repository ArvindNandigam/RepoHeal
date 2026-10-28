from __future__ import annotations

from typing import Any


LOCAL_LIBRARY_REGISTRY: dict[str, dict[str, Any]] = {
    "numpy": {
        "latest_version": None,
        "official_docs": "https://numpy.org/doc/stable/",
        "github_repo": "https://github.com/numpy/numpy",
        "pypi_url": "https://pypi.org/project/numpy/",
    },
    "pandas": {
        "latest_version": None,
        "official_docs": "https://pandas.pydata.org/docs/",
        "github_repo": "https://github.com/pandas-dev/pandas",
        "pypi_url": "https://pypi.org/project/pandas/",
    },
    "scikit-learn": {
        "latest_version": None,
        "official_docs": "https://scikit-learn.org/stable/",
        "github_repo": "https://github.com/scikit-learn/scikit-learn",
        "pypi_url": "https://pypi.org/project/scikit-learn/",
    },
    "flask": {
        "latest_version": None,
        "official_docs": "https://flask.palletsprojects.com/",
        "github_repo": "https://github.com/pallets/flask",
        "pypi_url": "https://pypi.org/project/Flask/",
    },
    "django": {
        "latest_version": None,
        "official_docs": "https://docs.djangoproject.com/",
        "github_repo": "https://github.com/django/django",
        "pypi_url": "https://pypi.org/project/Django/",
    },
}


def get_local_library_metadata(library: str) -> dict[str, Any] | None:
    record = LOCAL_LIBRARY_REGISTRY.get(library.lower())
    return {"library": library, **record} if record else None
