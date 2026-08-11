"""Professor-managed web-search allowlist, stored per course.

The standalone repo kept one global ``trusted-sites.json``. Inside the course
agent the allowlist belongs to a course, so each course gets its own file and
falls back to the shared academic defaults until a professor edits it.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from urllib.parse import urlparse

from app.services.voice.storage import safe_key, voice_storage_dir

log = logging.getLogger(__name__)

DEFAULT_TRUSTED_WEB_DOMAINS = (
    "skku.edu",
    "arxiv.org",
    "aclanthology.org",
    "proceedings.neurips.cc",
    "jmlr.org",
)


def normalize_domain(value: str) -> str:
    """Normalize a URL or hostname to a lowercase domain.

    Args:
        value: HTTPS URL or bare hostname supplied by a professor.

    Returns:
        Lowercase hostname accepted by xAI web-search filters.
    """
    raw = (value or "").strip()
    parsed = urlparse(raw if "://" in raw else f"https://{raw}")
    domain = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme not in {"http", "https"} or "." not in domain:
        raise ValueError("valid HTTP(S) site is required")
    return domain


def _course_file(course_id: str) -> Path:
    directory = voice_storage_dir() / "trusted-sites"
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"{safe_key(course_id)}.json"


def get_trusted_domains(course_id: str) -> list[str]:
    """Load the current allowlist for one course."""
    path = _course_file(course_id)
    if not path.exists():
        return sorted(DEFAULT_TRUSTED_WEB_DOMAINS)
    try:
        values = json.loads(path.read_text(encoding="utf-8"))
        return sorted({normalize_domain(value) for value in values})
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        log.exception("failed to load trusted sites for %s; using defaults", course_id)
        return sorted(DEFAULT_TRUSTED_WEB_DOMAINS)


def _save(course_id: str, domains: list[str]) -> None:
    _course_file(course_id).write_text(
        json.dumps(sorted(set(domains)), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def add_trusted_domain(course_id: str, value: str) -> list[str]:
    """Add one professor-approved domain and return the updated allowlist."""
    domains = set(get_trusted_domains(course_id))
    domains.add(normalize_domain(value))
    result = sorted(domains)
    _save(course_id, result)
    return result


def remove_trusted_domain(course_id: str, value: str) -> list[str]:
    """Remove one domain and return the updated allowlist."""
    domain = normalize_domain(value)
    result = [item for item in get_trusted_domains(course_id) if item != domain]
    _save(course_id, result)
    return result
