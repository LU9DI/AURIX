"""Policy-aware public-web research adapter for autonomous study.

Uses a user-configured SearXNG endpoint and bounded HTTP retrieval. It does not
use browser stealth, log into accounts, bypass CAPTCHAs, or evade access controls.
All fetched content is untrusted evidence and must be reviewed by the study model.
"""
from __future__ import annotations

import ipaddress
import json
import re
import socket
import urllib.robotparser
from html.parser import HTMLParser
from urllib.parse import urlencode, urlparse

import httpx


class _TextExtractor(HTMLParser):
    BLOCKED = {"script", "style", "noscript", "svg", "canvas", "iframe", "form", "nav", "footer", "header"}
    BLOCK = {"p", "div", "article", "section", "main", "li", "h1", "h2", "h3", "br", "tr"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in self.BLOCKED:
            self.depth += 1
        elif self.depth == 0 and tag.lower() in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in self.BLOCKED and self.depth:
            self.depth -= 1
        elif self.depth == 0 and tag.lower() in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self.depth == 0 and data.strip():
            self.parts.append(data.strip())


def clean_html(html: str, *, max_chars: int = 6000) -> str:
    parser = _TextExtractor()
    parser.feed(html[:2_000_000])
    text = re.sub(r"[ \t\xa0]+", " ", " ".join(parser.parts))
    text = re.sub(r"\s*\n\s*", "\n", text)
    text = re.sub(r"\s+([.,;:!?])", r"\1", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text[:max(100, min(int(max_chars), 20000))]


def _assert_public_http_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Only absolute HTTP(S) URLs without credentials are allowed")
    host = parsed.hostname.rstrip(".").lower()
    if host in {"localhost", "localhost.localdomain"} or host.endswith((".local", ".internal", ".localhost")):
        raise ValueError("Private/local hostnames are not allowed as research targets")
    try:
        addresses = {ipaddress.ip_address(host)} if _is_ip(host) else {
            ipaddress.ip_address(item[4][0]) for item in socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)
        }
    except (OSError, ValueError) as exc:
        raise ValueError("Research target hostname could not be resolved safely") from exc
    if not addresses or any(not addr.is_global for addr in addresses):
        raise ValueError("Research targets must resolve only to public IP addresses")


def _is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


def _get_limited(client: httpx.Client, url: str, *, max_bytes: int,
                 headers: dict[str, str] | None = None, timeout: float | None = None,
                 raise_for_status: bool = True) -> tuple[int, dict[str, str], bytes]:
    """Read a response incrementally and abort before unbounded body buffering."""
    chunks: list[bytes] = []
    total = 0
    with client.stream("GET", url, headers=headers, timeout=timeout) as response:
        if raise_for_status:
            response.raise_for_status()
        length = response.headers.get("content-length")
        if length:
            try:
                if int(length) > max_bytes:
                    raise ValueError("Research response exceeds configured byte limit")
            except ValueError as exc:
                if str(exc) == "Research response exceeds configured byte limit":
                    raise
        for chunk in response.iter_bytes():
            total += len(chunk)
            if total > max_bytes:
                raise ValueError("Research response exceeds configured byte limit")
            chunks.append(chunk)
        return response.status_code, dict(response.headers), b"".join(chunks)


class SearxResearchAdapter:
    """Query a configured SearXNG instance and fetch a small number of public pages."""

    def __init__(self, base_url: str, *, max_results: int = 3, max_chars: int = 12000,
                 timeout_seconds: float = 8.0, fetch_pages: bool = True) -> None:
        parsed = urlparse(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password:
            raise ValueError("AURIX_SEARXNG_URL must be an absolute HTTP(S) URL")
        self.base_url = base_url.rstrip("/")
        self.max_results = max(1, min(int(max_results), 5))
        self.max_chars = max(1000, min(int(max_chars), 16000))
        self.timeout_seconds = max(2.0, min(float(timeout_seconds), 20.0))
        self.fetch_pages = bool(fetch_pages)

    def __call__(self, query: str) -> str:
        query = " ".join(str(query).split())[:500]
        if not query:
            return ""
        timeout = httpx.Timeout(self.timeout_seconds, connect=min(4.0, self.timeout_seconds))
        with httpx.Client(timeout=timeout, follow_redirects=False, headers={"User-Agent": "AURIX-Research/0.50 (+public documentation research)"}) as client:
            _, _, search_bytes = _get_limited(
                client, self.base_url + "/search?" + urlencode({"q": query, "format": "json", "language": "en"}),
                max_bytes=1_500_000, headers={"Accept": "application/json"}, timeout=self.timeout_seconds)
            payload = json.loads(search_bytes)
            results = payload.get("results", []) if isinstance(payload, dict) else []
            blocks: list[str] = []
            for item in results[:self.max_results]:
                if not isinstance(item, dict):
                    continue
                url = item.get("url")
                if not isinstance(url, str):
                    continue
                title = str(item.get("title", "Untitled"))[:300]
                snippet = str(item.get("content", ""))[:1200]
                body = ""
                if self.fetch_pages:
                    try:
                        _assert_public_http_url(url)
                        if not _robots_allows(client, url, self.timeout_seconds):
                            blocks.append(section + "\nPAGE EXTRACT: Skipped because robots.txt disallows this crawler or could not be checked safely.")
                            continue
                        # No redirect following: every redirect target requires a fresh policy check.
                        page_status, page_headers, page_bytes = _get_limited(
                            client, url, max_bytes=2_000_000,
                            headers={"Accept": "text/html,text/plain,text/markdown,application/xhtml+xml"},
                            timeout=self.timeout_seconds)
                        if page_status == 200:
                            content_type = page_headers.get("content-type", "").lower()
                            if "text/html" in content_type or "application/xhtml+xml" in content_type:
                                body = clean_html(page_bytes.decode("utf-8", errors="replace"),
                                                  max_chars=min(5000, self.max_chars // self.max_results))
                            elif "text/plain" in content_type or "text/markdown" in content_type:
                                body = page_bytes.decode("utf-8", errors="replace")[:5000]
                    except (ValueError, httpx.HTTPError, UnicodeError):
                        body = ""
                section = f"SOURCE: {url}\nTITLE: {title}\nSEARCH SNIPPET: {snippet}"
                if body:
                    section += f"\nPAGE EXTRACT: {body}"
                blocks.append(section)
            return "\n\n---\n\n".join(blocks)[:self.max_chars]


def _robots_allows(client: httpx.Client, url: str, timeout_seconds: float) -> bool:
    """Fail closed on robots.txt transport errors; a missing robots.txt permits fetching."""
    parsed = urlparse(url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    _assert_public_http_url(robots_url)
    try:
        robots_status, _, robots_bytes = _get_limited(
            client, robots_url, max_bytes=200_000, timeout=min(timeout_seconds, 5.0), raise_for_status=False)
    except (httpx.HTTPError, ValueError):
        return False
    if robots_status == 404:
        return True
    if robots_status != 200:
        return False
    parser = urllib.robotparser.RobotFileParser()
    parser.set_url(robots_url)
    parser.parse(robots_bytes.decode("utf-8", errors="replace").splitlines())
    return parser.can_fetch("AURIX-Research", url)
