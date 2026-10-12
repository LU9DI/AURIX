# Open-source agent and harness target catalogue

This is a **starting queue**, not a claim that every target has been audited. Confirm repository availability, default branch, current commit, license, and security advisories at the start of each investigation. Prefer official upstream repositories and immutable commit URLs in evidence.

| Priority | Target | Official repository | What to inspect first | Relevance to AURIX |
|---|---|---|---|---|
| P1 | Aider | https://github.com/Aider-AI/aider | Repository map, context selection, edit formats, lint/test feedback loop | Efficient context and reliable code edits |
| P1 | OpenHands | https://github.com/All-Hands-AI/OpenHands | Runtime boundary, event stream, tool execution, workspace isolation | Agent runtime and execution isolation |
| P1 | SWE-agent | https://github.com/SWE-agent/SWE-agent | Agent-computer interface, action parsing, issue benchmark protocol | Structured tools and reproducible evaluation |
| P1 | OpenCode | https://github.com/anomalyco/opencode | Provider abstraction, sessions, tool permissions, model configuration | Harness design and provider interoperability |
| P1 | Continue | https://github.com/continuedev/continue | Context providers, indexing, model adapters, edit/apply workflows | Context engineering and IDE integrations |
| P2 | Cline | https://github.com/cline/cline | Approval gates, tool calls, diff application, state persistence | Human-in-the-loop safety patterns |
| P2 | Roo Code | https://github.com/RooCodeInc/Roo-Code | Role/mode permissions, orchestration, provider integration | Policy boundaries and agent specialization |
| P2 | LangGraph | https://github.com/langchain-ai/langgraph | Durable state, checkpointing, interrupts, retries | Recovery and resumable workflows |
| P2 | DeepSeek Coder | https://github.com/deepseek-ai/DeepSeek-Coder | Model/repository documentation, inference assumptions, supported licenses | Model capabilities and compatible harness requirements |
| P2 | vLLM | https://github.com/vllm-project/vllm | OpenAI-compatible API, serving limits, batching and telemetry | Local inference performance and integration |

## Selection criteria

Rank targets by (1) direct relevance to a current AURIX gap, (2) source availability and license clarity, (3) testability, (4) maturity and maintenance, and (5) expected benefit relative to integration cost.

Do not compare a model, inference server, IDE extension, and autonomous coding agent as if they were interchangeable products. Classify each target by layer before drawing conclusions. "DeepSeek harness" can mean a model served through a generic OpenAI-compatible harness; record the exact harness repository and model identifier rather than treating the phrase as a unique project.

## Status convention

- `queued`: not inspected.
- `in_progress`: source revision pinned and evidence collection underway.
- `reviewed`: evidence and limitations recorded.
- `experimented`: a reproducible local comparison exists.
- `decision_recorded`: adopt/adapt/defer/reject rationale documented.

No target should be labelled reviewed until its pinned revision, license, scope, and evidence records exist.
