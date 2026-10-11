import pytest

from aurix.research import SearxResearchAdapter, _assert_public_http_url, clean_html


def test_clean_html_removes_scripts_styles_and_tags():
    result = clean_html('<html><style>bad css</style><script>secret()</script><main><h1>Title</h1><p>Hello <b>world</b>.</p></main></html>')
    assert 'Title' in result
    assert 'Hello world.' in result
    assert 'bad css' not in result
    assert 'secret()' not in result


def test_research_adapter_requires_absolute_http_endpoint():
    with pytest.raises(ValueError):
        SearxResearchAdapter('searx.local')


@pytest.mark.parametrize('url', [
    'file:///etc/passwd', 'http://localhost/admin', 'http://127.0.0.1:5432/',
    'http://192.168.1.2/', 'http://user:pass@example.com/', 'http://service.internal/',
])
def test_rejects_non_public_research_targets(url):
    with pytest.raises(ValueError):
        _assert_public_http_url(url)


def test_clean_html_has_output_bound():
    assert len(clean_html('<p>' + ('x' * 1000) + '</p>', max_chars=120)) <= 120


def test_limited_reader_caps_streamed_body():
    import httpx
    from aurix.research import _get_limited

    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=b"abcdefghij"))
    with httpx.Client(transport=transport) as client:
        with pytest.raises(ValueError, match="byte limit"):
            _get_limited(client, "https://example.org/", max_bytes=5)


def test_missing_robots_file_is_allowed(monkeypatch):
    import httpx
    import aurix.research as research

    monkeypatch.setattr(research, "_resolve_public_ips", lambda url: ("93.184.216.34",))
    transport = httpx.MockTransport(lambda request: httpx.Response(404, content=b"missing"))
    with httpx.Client(transport=transport) as client:
        assert research._robots_allows(client, "https://example.org/page", 2.0) is True


def test_robots_blocked_page_is_reported_with_its_own_source(monkeypatch):
    """Regression: the robots.txt branch used `section` before assignment (UnboundLocalError)."""
    import json
    import httpx
    import aurix.research as research

    monkeypatch.setattr(research, "_resolve_public_ips", lambda url: ("93.184.216.34",))

    def handler(request: httpx.Request) -> httpx.Response:
        host = request.headers["host"]
        if request.url.path == "/search":
            results = [
                {"url": "https://blocked.example/page", "title": "Blocked", "content": "snippet-b"},
                {"url": "https://other.example/page", "title": "Other", "content": "snippet-o"},
            ]
            return httpx.Response(200, content=json.dumps({"results": results}).encode())
        if request.url.path == "/robots.txt":
            if host == "blocked.example":
                return httpx.Response(200, content=b"User-agent: *\nDisallow: /\n")
            return httpx.Response(404, content=b"missing")
        return httpx.Response(200, headers={"content-type": "text/plain"}, content=b"page body")

    real_client = httpx.Client
    monkeypatch.setattr(research.httpx, "Client", lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw))

    out = research.SearxResearchAdapter("https://searx.example")("query")

    blocked, other = out.split("\n\n---\n\n")
    assert "SOURCE: https://blocked.example/page" in blocked
    assert "TITLE: Blocked" in blocked
    assert "robots.txt disallows" in blocked
    assert "SOURCE: https://other.example/page" in other
    assert "PAGE EXTRACT: page body" in other


def test_fetch_connects_to_the_validated_ip_and_keeps_hostname(monkeypatch):
    """DNS rebinding defence: resolve once, then connect to that exact IP (Host/SNI keep the name)."""
    import httpx
    import aurix.research as research

    lookups = []

    def fake_resolve(url):
        lookups.append(url)
        return ("93.184.216.34",)

    monkeypatch.setattr(research, "_resolve_public_ips", fake_resolve)
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url_host"] = request.url.host
        seen["host_header"] = request.headers["host"]
        seen["sni"] = request.extensions.get("sni_hostname")
        return httpx.Response(200, content=b"ok")

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        status, _, body = research._get_limited(client, "https://docs.example.org:8443/a?b=1", max_bytes=100, pin_public_ip=True)

    assert (status, body) == (200, b"ok")
    assert len(lookups) == 1
    assert seen == {"url_host": "93.184.216.34", "host_header": "docs.example.org:8443", "sni": "docs.example.org"}


def test_pinned_fetch_uses_brackets_for_ipv6(monkeypatch):
    import httpx
    import aurix.research as research

    monkeypatch.setattr(research, "_resolve_public_ips", lambda url: ("2606:2800:220:1:248:1893:25c8:1946",))
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["host_header"] = request.headers["host"]
        seen["url_host"] = request.url.host
        return httpx.Response(200, content=b"ok")

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        research._get_limited(client, "http://docs.example.org/", max_bytes=100, pin_public_ip=True)
    assert seen == {"host_header": "docs.example.org", "url_host": "2606:2800:220:1:248:1893:25c8:1946"}


def test_hostname_resolving_to_a_private_address_is_rejected(monkeypatch):
    import socket
    import httpx
    import aurix.research as research

    private = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.5", 443))]
    public = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]
    monkeypatch.setattr(research.socket, "getaddrinfo", lambda *a, **k: private + public)  # any private answer blocks
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200))) as client:
        with pytest.raises(ValueError, match="public IP"):
            research._get_limited(client, "https://mixed.example.org/", max_bytes=10, pin_public_ip=True)
