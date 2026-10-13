import pytest

from aurix.research import SearxResearchAdapter, _assert_public_http_url, clean_html


def test_clean_html_removes_scripts_styles_and_tags():
    result = clean_html(
        "<html><style>bad css</style><script>secret()</script><main><h1>Title</h1><p>Hello <b>world</b>.</p></main></html>"
    )
    assert "Title" in result
    assert "Hello world." in result
    assert "bad css" not in result
    assert "secret()" not in result


def test_research_adapter_requires_absolute_http_endpoint():
    with pytest.raises(ValueError):
        SearxResearchAdapter("searx.local")


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "http://localhost/admin",
        "http://127.0.0.1:5432/",
        "http://192.168.1.2/",
        "http://user:pass@example.com/",
        "http://service.internal/",
        "https://example.org:8443/",
        "http://example.org:8080/",
    ],
)
def test_rejects_non_public_research_targets(url):
    with pytest.raises(ValueError):
        _assert_public_http_url(url)


def test_clean_html_has_output_bound():
    assert len(clean_html("<p>" + ("x" * 1000) + "</p>", max_chars=120)) <= 120


def test_limited_reader_caps_streamed_body():
    import httpx

    from aurix.research import _get_limited

    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=b"abcdefghij"))
    with httpx.Client(transport=transport) as client:
        with pytest.raises(ValueError, match="byte limit"):
            _get_limited(client, "https://example.org/", max_bytes=5)


def test_missing_robots_file_is_allowed(monkeypatch):
    import httpx

    from aurix import research

    monkeypatch.setattr(research, "_assert_public_http_url", lambda url: None)
    transport = httpx.MockTransport(lambda request: httpx.Response(404, content=b"missing"))
    with httpx.Client(transport=transport) as client:
        assert research._robots_allows(client, "https://example.org/page", 2.0) is True


def test_robots_disallow_is_reported_without_crashing(monkeypatch):
    import json

    from aurix import research

    monkeypatch.setattr(research, "_assert_public_http_url", lambda url: None)

    class DummyClient:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(research.httpx, "Client", lambda **kwargs: DummyClient())

    def fake_get_limited(client, url, **kwargs):
        if "/search?" in url:
            return (
                200,
                {"content-type": "application/json"},
                json.dumps(
                    {
                        "results": [
                            {
                                "url": "https://example.org/private",
                                "title": "Private page",
                                "content": "snippet",
                            }
                        ]
                    }
                ).encode(),
            )
        if url.endswith("/robots.txt"):
            return 200, {"content-type": "text/plain"}, b"User-agent: *\nDisallow: /\n"
        raise AssertionError(f"Page should not be fetched when robots.txt disallows it: {url}")

    monkeypatch.setattr(research, "_get_limited", fake_get_limited)
    result = research.SearxResearchAdapter("https://search.example", fetch_pages=True)("test query")
    assert "Skipped because robots.txt disallows" in result
    assert "Private page" in result


def test_public_ip_pinning_transport_rejects_private_dns_answer(monkeypatch):
    import socket

    import httpx

    from aurix import research

    monkeypatch.setattr(
        research.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.8", 443))],
    )
    connect_calls = []
    monkeypatch.setattr(
        research.socket, "create_connection", lambda *a, **k: connect_calls.append((a, k))
    )
    with pytest.raises(ValueError, match="public IP"):
        research.PublicIPPinningTransport().handle_request(
            httpx.Request("GET", "https://example.org/")
        )
    assert connect_calls == []



def test_direct_url_fetch_requires_explicit_host_allowlist():
    from aurix.research import fetch_authorized_public_url

    with pytest.raises(PermissionError, match="AURIX_WEB_ALLOWED_DOMAINS"):
        fetch_authorized_public_url(
            "https://docs.example.org/guide",
            allowed_domains=[],
        )


def test_domain_allowlist_matches_exact_hosts_and_subdomain_wildcards():
    from aurix.research import _domain_is_allowed

    assert _domain_is_allowed("docs.example.org", ["docs.example.org"])
    assert not _domain_is_allowed("sub.example.org", ["example.org"])
    assert _domain_is_allowed("sub.example.org", ["*.example.org"])
    assert not _domain_is_allowed("example.org.attacker.test", ["*.example.org"])


def test_direct_url_fetch_returns_bounded_untrusted_text(monkeypatch):
    from aurix import research

    class DummyClient:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(research, "_assert_public_http_url", lambda url: None)
    monkeypatch.setattr(research, "_robots_allows", lambda *args: True)
    monkeypatch.setattr(research.httpx, "Client", lambda **kwargs: DummyClient())
    monkeypatch.setattr(
        research,
        "_get_limited",
        lambda *args, **kwargs: (
            200,
            {"content-type": "text/html; charset=utf-8"},
            b"<html><script>ignore me</script><main><h1>Public docs</h1><p>Useful text.</p></main></html>",
        ),
    )
    result = research.fetch_authorized_public_url(
        "https://docs.example.org/guide",
        allowed_domains=["docs.example.org"],
    )
    assert result["status"] == 200
    assert "Public docs" in result["content"]
    assert "Useful text." in result["content"]
    assert "ignore me" not in result["content"]
    assert result["untrusted_content"] is True

 

@pytest.mark.parametrize("status", [301, 302, 307, 308, 404, 500])
def test_direct_url_fetch_rejects_redirects_and_non_success_statuses(monkeypatch, status):
    from aurix import research

    class DummyClient:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(research, "_assert_public_http_url", lambda url: None)
    monkeypatch.setattr(research, "_robots_allows", lambda *args: True)
    monkeypatch.setattr(research.httpx, "Client", lambda **kwargs: DummyClient())
    calls = []

    def fake_get_limited(client, url, **kwargs):
        calls.append((url, kwargs))
        if url.endswith("/robots.txt"):
            return 404, {}, b""
        return status, {"location": "https://attacker.example/steal", "content-type": "text/html"}, b""

    monkeypatch.setattr(research, "_get_limited", fake_get_limited)
    with pytest.raises(ValueError, match=f"HTTP status {status}"):
        research.fetch_authorized_public_url(
            "https://docs.example.org/guide",
            allowed_domains=["docs.example.org"],
        )
    page_requests = [call for call in calls if not call[0].endswith("/robots.txt")]
    assert len(page_requests) == 1
    assert page_requests[0][1]["raise_for_status"] is False


@pytest.mark.parametrize("content_type", ["application/pdf", "image/svg+xml", "application/octet-stream"])
def test_direct_url_fetch_rejects_unsupported_content_types(monkeypatch, content_type):
    from aurix import research

    class DummyClient:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(research, "_assert_public_http_url", lambda url: None)
    monkeypatch.setattr(research, "_robots_allows", lambda *args: True)
    monkeypatch.setattr(research.httpx, "Client", lambda **kwargs: DummyClient())
    monkeypatch.setattr(
        research,
        "_get_limited",
        lambda *args, **kwargs: (
            200,
            {"content-type": content_type},
            b"untrusted binary-like body",
        ),
    )
    with pytest.raises(ValueError, match="Only HTML, plain text, and Markdown"):
        research.fetch_authorized_public_url(
            "https://docs.example.org/file",
            allowed_domains=["docs.example.org"],
        )


@pytest.mark.parametrize("status", [200 + 6, 206, 301, 302, 304, 401, 403, 429, 500, 503])
def test_robots_policy_fails_closed_on_unexpected_statuses(monkeypatch, status):
    import httpx

    from aurix import research

    monkeypatch.setattr(research, "_assert_public_http_url", lambda url: None)
    transport = httpx.MockTransport(
        lambda request: httpx.Response(status, content=b"not available")
    )
    with httpx.Client(transport=transport) as client:
        assert research._robots_allows(client, "https://example.org/page", 2.0) is False

def test_direct_url_tool_is_listed_in_agent_protocol():
    from aurix.orchestrator import SYSTEM_PROMPT

    protocol = SYSTEM_PROMPT.split("- tool request:", 1)[1]
    assert "read_public_url" in protocol


@pytest.mark.parametrize("content_type", ["text/html", "application/json", ""])
def test_robots_policy_rejects_unexpected_content_type(monkeypatch, content_type):
    import httpx

    from aurix import research

    monkeypatch.setattr(research, "_assert_public_http_url", lambda url: None)
    headers = {"content-type": content_type} if content_type else {}
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            headers=headers,
            content=b"<html><body>challenge page</body></html>",
        )
    )
    with httpx.Client(transport=transport) as client:
        assert research._robots_allows(client, "https://example.org/page", 2.0) is False


def test_robots_policy_accepts_plain_text_rules(monkeypatch):
    import httpx

    from aurix import research

    monkeypatch.setattr(research, "_assert_public_http_url", lambda url: None)
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            headers={"content-type": "text/plain; charset=utf-8"},
            content=b"User-agent: *\nDisallow: /private\n",
        )
    )
    with httpx.Client(transport=transport) as client:
        assert research._robots_allows(client, "https://example.org/public", 2.0) is True
        assert research._robots_allows(client, "https://example.org/private/data", 2.0) is False
