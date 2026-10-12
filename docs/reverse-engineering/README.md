# REA-assisted open-source agent research

This workstream studies **publicly available source code and documented behavior** of AI coding agents and model harnesses so AURIX can adopt proven engineering patterns. It does not require extracting proprietary model weights or bypassing access controls.

## Scope

- Agent loops: planning, tool dispatch, context assembly, retries, stop conditions, and recovery.
- Harnesses: provider adapters, prompt construction, model routing, context windows, structured output, and tool permissions.
- Engineering controls: patch validation, tests, sandbox boundaries, telemetry, provenance, and human approvals.
- Reproducible comparisons: fixed tasks, repeated runs, baselines, regressions, and measured cost/latency.

Out of scope: credential theft, access-control bypass, private repositories without authorization, evading rate limits, and executing untrusted target code on the host.

## Upstream REA repository and correct division of labor

- Upstream REA is [morluto/rea](https://github.com/morluto/rea), an MIT-licensed TypeScript/Node.js CLI and MCP server. The inspected upstream `main` revision on 2026-10-12 was `1c37914306b3ff257d7a0360f11c9bf2a3f2cac7` (package `rea-agents` version `6.4.0`; Node.js `22.19+/24.11+/26+` per its `package.json`). These are observations of the upstream repository, not a claim that this runtime has REA installed or connected.
- REA's own `reverse-engineer-anything` skill explicitly says to skip REA for ordinary architecture analysis of a complete source repository. For open-source harnesses, use pinned Git source, tests and CI first; use REA when the question concerns a shipped binary, packaged application, Electron/ASAR artifact, or runtime evidence that source inspection cannot establish.
- The AURIX adapter `aurix.tools.rea` is not a full wrapper for every upstream MCP tool. It invokes the CLI and is neither an execution sandbox nor proof of runtime isolation.

## Current AURIX capabilities and limits

- Use AURIX's repository tools for source maps, bounded reads, literal search, and Git inspection.
- `aurix.tools.rea` is an adapter for the external REA CLI. Its application-analysis command targets JavaScript/Electron directories and ASAR files; other allowlisted commands may require configured native-analysis providers.
- The adapter invokes an installed executable. It does not itself prove that the executable or its providers are safe. Keep REA updated, review its provenance, and run it with least privilege.
- Static analysis is not a complete program understanding and does not establish runtime behavior. Any experiment involving execution must use a disposable, isolated environment.

## Investigation workflow

1. Select a public repository and pin a commit/tag; record license, date, and source URL.
2. Inventory entry points, package manifests, dependencies, tool permissions, and test commands before reading deeply.
3. Trace a small number of end-to-end paths: user task -> context -> model request -> tool call -> validation -> result.
4. Record each conclusion with a file/function/line reference and distinguish direct evidence from inference.
5. Build a minimal hypothesis and a controlled experiment. Keep baseline and candidate behavior comparable.
6. Run targeted tests first, then the full suite; record failures and environment limitations.
7. Decide **adopt**, **adapt**, **defer**, or **reject** each pattern, with a rationale.
8. Revisit licenses and attribution before copying code. Prefer reimplementation of ideas where practical; never assume a public repository has a permissive license.

## Required artifacts

- [Target catalogue](target-catalog.md)
- [Methodology and safety rules](methodology.md)
- [Evidence record schema](evidence-schema.md)

An investigation is not complete merely because a model summarized a repository. It is complete when evidence, uncertainty, experiment results, and a decision are recorded.
