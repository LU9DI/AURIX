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

    monkeypatch.setattr(research, "_assert_public_http_url", lambda url: None)
    transport = httpx.MockTransport(lambda request: httpx.Response(404, content=b"missing"))
    with httpx.Client(transport=transport) as client:
        assert research._robots_allows(client, "https://example.org/page", 2.0) is True
