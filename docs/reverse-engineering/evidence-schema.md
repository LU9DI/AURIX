# Evidence record schema

Store one Markdown or JSON record per investigation under a dedicated research directory (for example `research/agent-harnesses/<slug>/<commit-sha>/`). Do not store credentials, private prompts, private user documents, or proprietary source dumps in the evidence record.

## Required fields

| Field | Meaning |
|---|---|
| `id` | Stable investigation identifier |
| `target_name` | Project and component being studied |
| `source_url` | Canonical upstream URL |
| `revision` | Immutable commit SHA or release tag |
| `retrieved_at` | UTC date of inspection |
| `license` | SPDX identifier if verified, otherwise `unknown` |
| `question` | Specific engineering question |
| `observations` | Direct facts supported by code or tests |
| `evidence` | Paths, symbols, line ranges, test names, and immutable source links |
| `inferences` | Interpretation clearly separated from facts |
| `confidence` | High, medium, or low with rationale |
| `limitations` | Missing tests, platform assumptions, or unverified runtime claims |
| `experiment` | Reproduction steps, environment, baseline, candidate |
| `results` | Measurements and failures; use `not_measured` where appropriate |
| `decision` | Adopt, adapt, defer, or reject |
| `decision_rationale` | Why the result benefits AURIX and what trade-offs remain |
| `follow_ups` | Open questions or next experiments |

## Example (illustrative, not a completed audit)

```yaml
id: HARNESS-EXAMPLE-001
target_name: example-agent
source_url: https://github.com/example/example-agent
revision: "<immutable-commit-sha>"
retrieved_at: "YYYY-MM-DD"
license: unknown
question: "How are tool calls authorized before execution?"
observations:
  - "The dispatcher validates tool names against an explicit registry."
evidence:
  - path: "src/dispatcher.py"
    symbol: "dispatch_tool"
    lines: "40-78"
    kind: source
confidence:
  level: medium
  rationale: "Static path inspected; negative cases not yet executed."
limitations:
  - "Runtime behavior not validated."
experiment:
  status: not_run
results:
  status: not_measured
decision: defer
decision_rationale: "Await negative-case tests and license verification."
follow_ups:
  - "Test unknown tool names and malformed arguments."
```

Evidence must be reproducible and falsifiable. Never mark an inference as a source fact, and never fabricate a revision, benchmark result, or test outcome.
