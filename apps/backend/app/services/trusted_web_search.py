"""Professor-allowlisted web search through self-hosted SearXNG."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

from app.core.config import Settings
from app.services.model_server.client import async_client


class TrustedWebSearchError(RuntimeError):
    code = "TRUSTED_WEB_SEARCH_FAILED"


@dataclass(frozen=True)
class TrustedWebResult:
    title: str
    url: str
    snippet: str


class TrustedWebSearchService:
    """Search SearXNG, then enforce the course allowlist again locally."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = async_client(settings.searxng_url, None, settings.searxng_timeout_seconds)

    async def search(
        self,
        query: str,
        allowed_domains: list[str],
    ) -> list[TrustedWebResult]:
        query = query.strip()
        allowed = [_normalize_domain(domain) for domain in allowed_domains]
        allowed = [domain for domain in allowed if domain]
        if not query:
            raise TrustedWebSearchError("신뢰 웹 검색 query가 비어 있습니다.")
        if not allowed:
            raise TrustedWebSearchError("교수가 등록한 신뢰 사이트가 없습니다.")

        try:
            response = await self.client.get(
                "search",
                params={"q": query, "format": "json"},
                timeout=self.settings.searxng_timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            raise TrustedWebSearchError("SearXNG 검색 서버를 사용할 수 없습니다.") from exc

        results: list[TrustedWebResult] = []
        for item in payload.get("results", []):
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or "").strip()
            if not _url_allowed(url, allowed):
                continue
            title = " ".join(str(item.get("title") or "").split())[:300]
            snippet = " ".join(str(item.get("content") or "").split())[:1200]
            if not title and not snippet:
                continue
            results.append(TrustedWebResult(title=title, url=url, snippet=snippet))
            if len(results) >= self.settings.searxng_max_results:
                break
        return results


def _normalize_domain(value: str) -> str:
    value = value.strip().lower().rstrip(".")
    if "://" in value:
        value = (urlparse(value).hostname or "").lower().rstrip(".")
    return value


def _url_allowed(url: str, allowed_domains: list[str]) -> bool:
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if parsed.scheme not in {"http", "https"}:
        return False
    host = (parsed.hostname or "").lower().rstrip(".")
    if not host:
        return False
    return any(host == domain or host.endswith(f".{domain}") for domain in allowed_domains)
