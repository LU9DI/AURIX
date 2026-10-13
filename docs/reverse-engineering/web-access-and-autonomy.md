# Web access and bounded autonomy design

## Status

- Direct public-page retrieval without MCP: **implemented** through `read_public_url`.
- Host authorization: **operator-configured allowlist** via `AURIX_WEB_ALLOWED_DOMAINS`.
- Browser interaction (click/type/forms/JavaScript-rendered sites): **not implemented** by this adapter.
- Authenticated web sessions: **not implemented** and intentionally not inherited from the user's personal browser.
- Autonomous self-update/publish: **not implemented as a trusted end-to-end pipeline**.

## What the source review found

### AURIX's existing research path

The existing `aurix/research.py` already used a bounded SearXNG adapter, a response-byte ceiling, public-IP validation/pinning, and a fail-closed robots check. However, the interface was query-first: a user or study worker could not ask the orchestrator to retrieve one known URL directly. The new `fetch_authorized_public_url` reuses those protections and exposes a narrow read-only tool.

### Patterns adapted from other browser agents

Browser Use documents explicit allowed-domain controls for browser navigation and warns that browser sessions, storage state, permissions, and cross-origin frames are powerful capabilities. AURIX adopts the principle of an explicit domain boundary, but deliberately does **not** adopt broad browser session reuse in this HTTP-only phase.

Chrome's agent security guidance describes indirect prompt injection through website text and recommends restricting origins and confirming consequential actions. AURIX therefore treats every retrieved page as untrusted evidence, only performs GET requests, and does not let a page authorize its own navigation or actions.

Reference material:
- Browser Use repository and domain controls: https://github.com/browser-use/browser-use
- Chrome agent security considerations: https://developer.chrome.com/docs/agents/security/
- Playwright documentation: https://playwright.dev/docs/best-practices

This is a targeted design adaptation, not a claim that the upstream projects were fully audited or that their code was copied.

## Current contract

1. The operator configures `AURIX_WEB_ALLOWED_DOMAINS` as a comma-separated allowlist of exact hostnames and optional `*.example.org` subdomain patterns.
2. The model may request `read_public_url({"url":"https://approved.example.org/path"})`; the implementation independently checks the hostname against the allowlist.
3. Only absolute HTTP(S) URLs without embedded credentials are accepted.
4. DNS results must be public; the actual connection pins to a validated address. Only the scheme's default port (HTTP 80 / HTTPS 443) is accepted, preventing an approved hostname from becoming a tunnel to unrelated public services on arbitrary ports.
5. `robots.txt` is checked; transport/policy uncertainty fails closed.
6. Redirects are not followed. A redirected target must be explicitly requested and independently pass the allowlist and network checks.
7. Responses are bounded to 2 MB and output is capped at 16,000 characters. Only HTML, plain text, and Markdown are accepted.
8. Retrieved page text is returned as untrusted data. It cannot change the tool allowlist or authorize a write/action.
9. No cookies, passwords, browser profile, form submission, or website mutation are supported.
10. The allowlist grants access to read public pages on those hosts; it does not grant permission to access private services or bypass access controls.

## Known limitations and next steps

- The allowlist is configured at process level, not per task/session. For stronger UX, add a per-run one-time grant that binds the approved exact URL (including scheme/host/path policy), expires automatically, and is recorded in audit telemetry.
- The tool is HTTP-only and cannot reliably read pages that require client-side JavaScript. A browser adapter should be a separate optional extra with its own process boundary, fresh isolated profile, strict domain allowlist enforced on navigations **and subresources**, download controls, request/time/step budgets, and explicit confirmation before state-changing actions.
- Authenticated access should use a dedicated, user-approved profile or OAuth/API integration with narrowly scoped permissions—not ambient personal cookies. Sensitive actions such as sending messages, purchases, account changes, or submitting forms must require an explicit confirmation at the moment of action.
- Add independent SSRF tests for redirects, IPv4/IPv6 edge cases, DNS rebinding resistance, malformed URLs, oversized and compressed responses, robots failures, and MIME-type confusion.
- Add a source-grounded prompt-injection test suite with pages that ask the agent to reveal secrets, change allowlists, or follow off-domain links; expected behavior is to treat those strings as data and reject unauthorized navigation.
- Autonomous learning should create evidence-backed candidates, evaluate them against pinned regression benchmarks, and promote only reproducible improvements. Model output or web content must never directly update trusted policy, code, or credentials.
- Self-update should remain a separate signed release pipeline: isolated candidate build, tests/security checks, artifact provenance, operator policy, staged rollout, health checks, and rollback. Do not let the same agent write, approve, and deploy its own change without independent controls.

## Acceptance criteria for a future browser adapter

- Disabled by default; no automatic personal browser attachment.
- Domain and subresource allowlist enforced outside model reasoning.
- No arbitrary shell, JavaScript evaluation, file upload/download, or credential access by default.
- Bounded navigation count, page bytes, wall time, token budget, and spend.
- Read-only actions are separated from state-changing actions in the schema.
- User confirmation required before any irreversible or externally visible change.
- All actions logged with redacted arguments, destination origin, result, and policy decision.
- Integration tests cover malicious page content and denied cross-origin requests.
