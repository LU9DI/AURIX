import argparse
import asyncio
import json
import os
from pathlib import Path

from aurix.agents import ROLES, AgentManager
from aurix.audit import audit_proposal
from aurix.autonomy import AutonomousKernel, StudyQueue
from aurix.config import get_max_steps
from aurix.diagnostics import run_diagnostics
from aurix.documents import analyze_document
from aurix.evaluation.autonomous import run_autonomous_benchmark
from aurix.evaluation.benchmark import compare_reports, load_cases, run_benchmark
from aurix.evaluation.functional import run_functional_benchmark
from aurix.knowledge import KnowledgeIndex
from aurix.learning import LearningStore
from aurix.memory import create_memory, retrieve_memories
from aurix.orchestrator import Orchestrator
from aurix.providers.factory import create_provider
from aurix.reports import attach_audit_to_run_report, verify_run_report, write_run_report
from aurix.research import SearxResearchAdapter
from aurix.research_memory import ResearchMemory
from aurix.tools.execution import run_test_suite
from aurix.tools.patches import (
    apply_proposal,
    create_recovery_anchor,
    finalize_interrupted_recovery,
    inspect_operation_lock,
    inspect_transactions,
    plan_transaction_recovery,
    recover_transaction,
    revert_proposal,
    verify_recovery_histories,
)
from aurix.tools.review import review_proposal
from aurix.tools.verification import verify_proposal
from aurix.tools.workspace import build_workspace_context


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="aurix", description="AURIX local-first engineering agent"
    )
    parser.add_argument("task", nargs="?", help="Task to reason about")
    parser.add_argument("--workspace", default=".")
    parser.add_argument(
        "--analyze-document",
        metavar="PATH",
        help="Analyze a large PDF or text document hierarchically",
    )
    parser.add_argument(
        "--document-output", metavar="PATH", help="Save document analysis JSON to this path"
    )
    parser.add_argument(
        "--document-workers", type=int, default=4, help="Parallel document-analysis requests (1-16)"
    )
    parser.add_argument(
        "--document-chunk-chars",
        type=int,
        default=24000,
        help="Approximate characters per analysis chunk (2000-80000)",
    )
    parser.add_argument(
        "--doctor", action="store_true", help="Run read-only installation/readiness checks"
    )
    parser.add_argument(
        "--probe-provider",
        action="store_true",
        help="Make a live model request (may consume compute/API credits)",
    )
    parser.add_argument("--benchmark", help="Run a JSON benchmark file instead of a single task")
    parser.add_argument(
        "--functional-benchmark",
        metavar="SUITE.json",
        help="Evaluate supplied patches against disposable known-defect fixtures",
    )
    parser.add_argument(
        "--confirm-functional-benchmark",
        action="store_true",
        help="Explicitly approve executing fixture tests and supplied patches",
    )
    parser.add_argument(
        "--autonomous-benchmark",
        metavar="SUITE.json",
        help="Ask the configured model to propose fixes for disposable known-defect fixtures",
    )
    parser.add_argument(
        "--confirm-autonomous-benchmark",
        action="store_true",
        help="Explicitly approve model requests and execution of benchmark fixture tests",
    )
    parser.add_argument(
        "--benchmark-repetitions",
        type=int,
        default=1,
        help="Repeat each benchmark case (1-10; may incur extra compute/API cost)",
    )
    parser.add_argument(
        "--benchmark-compare",
        metavar="REPORT.json",
        help="Compare this run with a previous schema-v5 benchmark report",
    )
    parser.add_argument(
        "--benchmark-output",
        metavar="PATH",
        help="Save the benchmark report or comparison JSON to this path",
    )
    parser.add_argument(
        "--report-run",
        metavar="PATH",
        help="Explicitly save a local JSON run report inside the workspace (includes task text)",
    )
    parser.add_argument(
        "--verify-run-report",
        metavar="PATH",
        help="Verify the SHA-256 integrity digest of an existing run report",
    )
    parser.add_argument("--json", action="store_true", help="Print machine-readable output")
    parser.add_argument(
        "--allow-agent-verification",
        action="store_true",
        help="Allow model-requested pytest/ruff verification; trusted mode is not OS-sandboxed",
    )
    parser.add_argument(
        "--test-isolation",
        choices=("trusted", "docker"),
        default="trusted",
        help="Execution boundary for --run-tests and proposal verification",
    )
    parser.add_argument(
        "--sandbox-image",
        help="Locally available, operator-reviewed Docker image with project test dependencies; never pulled automatically",
    )
    parser.add_argument("--apply-proposal", metavar="ID", help="Apply a reviewed patch proposal")
    parser.add_argument(
        "--confirm-apply", action="store_true", help="Explicitly confirm patch application"
    )
    parser.add_argument(
        "--require-audit-gate",
        action="store_true",
        help="Require a passing audit and tests for the exact patch before applying",
    )
    parser.add_argument(
        "--inspect-transactions",
        action="store_true",
        help="Read-only inspection of patch transaction journals",
    )
    parser.add_argument(
        "--inspect-operation-lock",
        action="store_true",
        help="Read-only inspection of the AURIX workspace operation lock; never removes it",
    )
    parser.add_argument(
        "--verify-recovery-history",
        action="store_true",
        help="Independently verify recovery-history hash chains without mutation",
    )
    parser.add_argument(
        "--recovery-anchor",
        metavar="PATH",
        help="Compare recovery journals with an external SHA-256 snapshot during verification",
    )
    parser.add_argument(
        "--create-recovery-anchor",
        metavar="PATH",
        help="Create a new external snapshot of valid transaction journals (never overwrites)",
    )
    parser.add_argument(
        "--confirm-create-recovery-anchor",
        action="store_true",
        help="Explicitly approve creating the external recovery snapshot",
    )
    parser.add_argument(
        "--plan-transaction-recovery",
        action="store_true",
        help="Build a read-only, non-executing recovery plan for transaction journals",
    )
    parser.add_argument(
        "--recover-transaction",
        metavar="ID",
        help="Recover an interrupted patch_applied transaction by exact inverse patch",
    )
    parser.add_argument(
        "--confirm-recovery",
        action="store_true",
        help="Explicitly confirm exact-patch transaction recovery",
    )
    parser.add_argument(
        "--finalize-interrupted-recovery",
        metavar="ID",
        help="Finalize a journal-only recovery after independently verified rollback",
    )
    parser.add_argument("--revert-proposal", metavar="ID", help="Reverse an applied patch proposal")
    parser.add_argument(
        "--confirm-revert", action="store_true", help="Explicitly confirm patch reversal"
    )
    parser.add_argument(
        "--verify-proposal", metavar="ID", help="Test a proposal in a disposable Git worktree"
    )
    parser.add_argument(
        "--review-proposal",
        metavar="ID",
        help="Run a deterministic heuristic review of a patch proposal",
    )
    parser.add_argument(
        "--audit-proposal",
        metavar="ID",
        help="Review a proposal and report one combined audit result",
    )
    parser.add_argument(
        "--confirm-audit-verify",
        action="store_true",
        help="Explicitly run tests for the audited proposal in a disposable Git worktree",
    )
    parser.add_argument(
        "--attach-audit-to-report",
        metavar="PATH",
        help="Attach compact audit evidence to an existing schema-v2 run report",
    )
    parser.add_argument(
        "--confirm-verify", action="store_true", help="Explicitly confirm proposal verification"
    )
    parser.add_argument(
        "--verify-suite",
        choices=("pytest", "ruff", "auto"),
        default="pytest",
        help="Suite for proposal verification (auto requires explicit .aurix/test-map.json mappings; otherwise runs full pytest suite)",
    )
    parser.add_argument(
        "--run-tests", choices=("pytest", "ruff"), help="Run a fixed test/lint command"
    )
    parser.add_argument(
        "--confirm-run-tests",
        action="store_true",
        help="Confirm execution in this trusted workspace",
    )
    parser.add_argument(
        "--test-timeout", type=int, default=120, help="Test timeout in seconds (max 120)"
    )
    parser.add_argument("--memory-add", metavar="TEXT", help="Explicitly store a memory record")
    parser.add_argument(
        "--memory-kind",
        choices=("fact", "hypothesis", "decision", "test_result", "observation"),
        default="observation",
        help="Evidence type for --memory-add",
    )
    parser.add_argument(
        "--memory-confidence",
        type=float,
        help="Optional confidence from 0.0 to 1.0 for --memory-add",
    )
    parser.add_argument("--memory-search", metavar="QUERY", help="Search stored memory records")
    parser.add_argument(
        "--memory-scope", default="default", help="Memory isolation scope (default: default)"
    )
    parser.add_argument(
        "--use-memory-context",
        action="store_true",
        help="Explicitly retrieve scoped memories and include bounded evidence in a task prompt",
    )
    parser.add_argument(
        "--memory-backend", choices=("sqlite", "postgres"), help="Override AURIX_MEMORY_BACKEND"
    )
    parser.add_argument(
        "--memory-limit", type=int, default=10, help="Maximum ranked memory results (1-50)"
    )
    parser.add_argument(
        "--memory-candidates", type=int, default=100, help="Recent scoped memories to rank (1-500)"
    )
    parser.add_argument(
        "--memory-max-content-chars",
        type=int,
        default=4000,
        help="Maximum characters per returned memory (100-20000)",
    )
    parser.add_argument(
        "--learning-add",
        metavar="TEXT",
        help="Record a learning candidate; it is not trusted automatically",
    )
    parser.add_argument(
        "--learning-source",
        choices=("user_feedback", "task_outcome", "peer_model", "web_research", "local_tool"),
        default="task_outcome",
    )
    parser.add_argument(
        "--learning-quality", type=float, help="Quality score from 0 to 1 for a learning candidate"
    )
    parser.add_argument(
        "--learning-consent-to-train",
        action="store_true",
        help="Explicitly allow this record to be considered for training export",
    )
    parser.add_argument(
        "--learning-review", type=int, metavar="ID", help="Review a candidate learning record"
    )
    parser.add_argument(
        "--learning-decision",
        choices=("accepted", "rejected"),
        help="Decision for --learning-review",
    )
    parser.add_argument(
        "--learning-list", action="store_true", help="List learning candidates and reviewed records"
    )
    parser.add_argument(
        "--learning-status",
        choices=("candidate", "accepted", "rejected"),
        help="Filter --learning-list by status",
    )
    parser.add_argument(
        "--learning-export",
        metavar="PATH",
        help="Export accepted, consented, high-quality records as JSONL",
    )
    parser.add_argument(
        "--learning-min-quality",
        type=float,
        default=0.8,
        help="Minimum quality required for training export",
    )
    parser.add_argument("--learning-scope", default="default", help="Logical learning scope")
    parser.add_argument(
        "--index-add",
        metavar="PATH",
        help="Index or incrementally refresh a text/code file or directory; no model calls",
    )
    parser.add_argument(
        "--index-sync",
        metavar="PATH",
        help="Synchronize the index with a directory, removing stale entries after a complete scan",
    )
    parser.add_argument(
        "--index-search",
        metavar="QUERY",
        help="Search the local knowledge index without model tokens",
    )
    parser.add_argument(
        "--index-stats", action="store_true", help="Show local knowledge index statistics"
    )
    parser.add_argument(
        "--index-limit", type=int, default=5, help="Maximum retrieval results (1-20)"
    )
    parser.add_argument(
        "--research-memory-list",
        action="store_true",
        help="List durable autonomous research discoveries",
    )
    parser.add_argument(
        "--research-memory-review",
        type=int,
        metavar="ID",
        help="Review a research discovery candidate",
    )
    parser.add_argument(
        "--research-memory-decision",
        choices=("accepted", "rejected"),
        help="Decision for --research-memory-review",
    )
    parser.add_argument(
        "--research-memory-status",
        choices=("candidate", "accepted", "rejected"),
        help="Filter --research-memory-list",
    )
    parser.add_argument(
        "--research-memory-topic", help="Filter research discoveries by topic substring"
    )
    parser.add_argument(
        "--study-enqueue", metavar="TOPIC", help="Queue a topic for autonomous study; no model call"
    )
    parser.add_argument(
        "--study-priority", type=int, default=0, help="Study topic priority (-100 to 100)"
    )
    parser.add_argument(
        "--study-list", action="store_true", help="Show autonomous study queue and daemon state"
    )
    parser.add_argument(
        "--study-once",
        action="store_true",
        help="Run one queued study cycle using the configured model",
    )
    parser.add_argument(
        "--study-daemon",
        action="store_true",
        help="Run the bounded-resource autonomous study daemon",
    )
    parser.add_argument(
        "--study-min-interval",
        type=int,
        default=1800,
        help="Minimum idle interval in seconds (minimum 60)",
    )
    parser.add_argument(
        "--study-max-interval", type=int, default=7200, help="Maximum idle interval in seconds"
    )
    parser.add_argument(
        "--study-max-cycles",
        type=int,
        help="Stop daemon after this many cycles; useful for supervised runs",
    )
    parser.add_argument(
        "--agent-create", metavar="NAME", help="Create a persistent specialist agent profile"
    )
    parser.add_argument("--agent-role", choices=sorted(ROLES), help="Role for --agent-create")
    parser.add_argument(
        "--agent-description",
        default="",
        help="Specialization details for --agent-create (max 2000 chars)",
    )
    parser.add_argument(
        "--agent-list", action="store_true", help="List persistent specialist agents"
    )
    parser.add_argument(
        "--agent-run", metavar="NAME", help="Run a task with a named specialist agent"
    )
    parser.add_argument("--agent-task", help="Task text for --agent-run or --agent-team")
    parser.add_argument(
        "--agent-team",
        action="store_true",
        help="Create and coordinate architect, researcher, and reviewer agents for a task (parallel by default)",
    )
    parser.add_argument(
        "--agent-team-sequential",
        action="store_true",
        help="Run team specialists sequentially instead of in parallel",
    )
    parser.add_argument(
        "--agent-team-workers",
        type=int,
        default=3,
        help="Maximum concurrent specialist calls (1-4)",
    )
    args = parser.parse_args()
    agent_ops = (
        args.agent_create is not None,
        args.agent_list,
        args.agent_run is not None,
        args.agent_team,
    )
    if not 1 <= args.agent_team_workers <= 4:
        parser.error("--agent-team-workers must be between 1 and 4")
    if args.agent_team_sequential and not args.agent_team:
        parser.error("--agent-team-sequential requires --agent-team")
    if any(agent_ops):
        if sum(bool(item) for item in agent_ops) != 1:
            parser.error("Choose exactly one agent operation")
        if (
            args.task
            or args.study_enqueue is not None
            or args.study_list
            or args.study_once
            or args.study_daemon
            or args.index_add is not None
            or args.index_sync is not None
            or args.index_search is not None
            or args.index_stats
            or args.learning_add is not None
            or args.learning_review is not None
            or args.learning_list
            or args.learning_export is not None
            or args.research_memory_list
            or args.research_memory_review is not None
        ):
            parser.error(
                "Agent operations cannot be combined with another task or subsystem operation"
            )
        if args.agent_create is not None and not args.agent_role:
            parser.error("--agent-create requires --agent-role")
        if args.agent_create is None and (args.agent_role is not None or args.agent_description):
            parser.error("--agent-role and --agent-description require --agent-create")
        if args.agent_run is not None and not args.agent_task:
            parser.error("--agent-run requires --agent-task")
        if args.agent_team and not args.agent_task:
            parser.error("--agent-team requires --agent-task")
        if args.agent_list and (args.agent_task or args.agent_role or args.agent_description):
            parser.error("--agent-list does not accept task or creation options")
        try:
            manager = AgentManager(
                Path(args.workspace).expanduser().resolve() / ".aurix" / "agents.db"
            )
            if args.agent_create is not None:
                result = {
                    "status": "created",
                    "agent": manager.create(
                        args.agent_create, args.agent_role, args.agent_description
                    ),
                }
            elif args.agent_list:
                agents = manager.list()
                result = {
                    "status": "ok",
                    "count": len(agents),
                    "agents": agents,
                    "available_roles": sorted(ROLES),
                }
            elif args.agent_run is not None:
                result = manager.run(
                    args.agent_run,
                    args.agent_task,
                    create_provider,
                    workspace=Path(args.workspace).expanduser().resolve(),
                )
            else:
                result = manager.create_team(
                    args.agent_task,
                    create_provider,
                    parallel=not args.agent_team_sequential,
                    max_workers=args.agent_team_workers,
                    workspace=Path(args.workspace).expanduser().resolve(),
                )
        except (ValueError, OSError, RuntimeError, TypeError) as exc:
            parser.exit(2, f"AURIX agent operation failed: {type(exc).__name__}: {exc}\n")
        print(
            json.dumps(result, ensure_ascii=False, indent=2)
            if args.json
            else json.dumps(result, ensure_ascii=False)
        )
        return
    research_memory_ops = (args.research_memory_list, args.research_memory_review is not None)
    if any(research_memory_ops):
        if sum(bool(item) for item in research_memory_ops) != 1:
            parser.error("Choose exactly one research-memory operation")
        if (
            args.task
            or args.study_enqueue is not None
            or args.study_list
            or args.study_once
            or args.study_daemon
            or args.index_add is not None
            or args.index_sync is not None
            or args.index_search is not None
            or args.index_stats
            or args.learning_add is not None
            or args.learning_review is not None
            or args.learning_list
            or args.learning_export is not None
        ):
            parser.error("Research-memory operations cannot be combined with other operations")
        if args.research_memory_review is not None and args.research_memory_decision is None:
            parser.error("--research-memory-review requires --research-memory-decision")
        if args.research_memory_list and args.research_memory_decision is not None:
            parser.error("--research-memory-decision requires --research-memory-review")
        try:
            memory = ResearchMemory(
                Path(args.workspace).expanduser().resolve() / ".aurix" / "research_memory.db"
            )
            if args.research_memory_review is not None:
                changed = memory.review(
                    args.research_memory_review, decision=args.research_memory_decision
                )
                result = {
                    "status": "reviewed" if changed else "unchanged_or_missing",
                    "id": args.research_memory_review,
                    "decision": args.research_memory_decision,
                    "note": "Accepted records are classified as validated knowledge; rejection preserves provenance.",
                }
            else:
                records = memory.list_records(
                    status=args.research_memory_status, topic=args.research_memory_topic
                )
                result = {
                    "status": "ok",
                    "count": len(records),
                    "stats": memory.stats(),
                    "records": records,
                }
        except (ValueError, OSError, RuntimeError) as exc:
            parser.exit(2, f"AURIX research memory failed: {type(exc).__name__}: {exc}\n")
        print(
            json.dumps(result, ensure_ascii=False, indent=2)
            if args.json
            else json.dumps(result, ensure_ascii=False)
        )
        return

    study_ops = (
        args.study_enqueue is not None,
        args.study_list,
        args.study_once,
        args.study_daemon,
    )
    if any(study_ops):
        if sum(bool(item) for item in study_ops) != 1:
            parser.error("Choose exactly one study operation")
        if (
            args.task
            or args.analyze_document
            or args.doctor
            or args.benchmark
            or args.learning_add is not None
            or args.learning_review is not None
            or args.learning_list
            or args.learning_export is not None
            or args.index_add is not None
            or args.index_sync is not None
            or args.index_search is not None
            or args.index_stats
            or args.memory_add is not None
            or args.memory_search is not None
        ):
            parser.error("Study operations cannot be combined with tasks or other operations")
        try:
            workspace = Path(args.workspace).expanduser().resolve()
            queue = StudyQueue(workspace / ".aurix" / "autonomy.db")
            if args.study_enqueue is not None:
                result = {
                    "status": "queued",
                    **queue.enqueue(args.study_enqueue, priority=args.study_priority),
                }
            elif args.study_list:
                result = {"status": "ok", **queue.status()}
            else:
                research_adapter = None
                searx_url = os.getenv("AURIX_SEARXNG_URL", "").strip()
                if searx_url:
                    research_adapter = SearxResearchAdapter(
                        searx_url,
                        max_results=int(os.getenv("AURIX_RESEARCH_MAX_RESULTS", "3")),
                        max_chars=int(os.getenv("AURIX_RESEARCH_MAX_CHARS", "12000")),
                        fetch_pages=os.getenv("AURIX_RESEARCH_FETCH_PAGES", "true").lower()
                        not in {"0", "false", "no", "off"},
                    )
                kernel = AutonomousKernel(
                    create_provider(),
                    workspace,
                    min_interval_seconds=args.study_min_interval,
                    max_interval_seconds=args.study_max_interval,
                    max_cycles=args.study_max_cycles,
                    research_adapter=research_adapter,
                )
                if args.study_once:
                    result = kernel.study_once()
                else:
                    result = asyncio.run(kernel.run())
        except (ValueError, PermissionError, OSError, RuntimeError, TypeError) as exc:
            parser.exit(2, f"AURIX autonomous study failed: {type(exc).__name__}: {exc}\n")
        print(
            json.dumps(result, ensure_ascii=False, indent=2)
            if args.json
            else json.dumps(result, ensure_ascii=False)
        )
        return
    index_ops = (
        args.index_add is not None,
        args.index_sync is not None,
        args.index_search is not None,
        args.index_stats,
    )
    if any(index_ops):
        if sum(bool(item) for item in index_ops) != 1:
            parser.error("Choose exactly one knowledge-index operation")
        if (
            args.task
            or args.learning_add is not None
            or args.learning_review is not None
            or args.learning_list
            or args.learning_export is not None
            or args.analyze_document
            or args.benchmark
            or args.doctor
        ):
            parser.error(
                "Knowledge-index operations cannot be combined with tasks or other operations"
            )
        try:
            index = KnowledgeIndex(
                Path(args.workspace).expanduser().resolve() / ".aurix" / "knowledge.db"
            )
            if args.index_add is not None:
                result = {"status": "indexed", **index.index_path(args.index_add)}
            elif args.index_sync is not None:
                result = {"status": "synchronized", **index.index_path(args.index_sync)}
            elif args.index_search is not None:
                result = {
                    "status": "ok",
                    "query": args.index_search,
                    "results": index.search(args.index_search, limit=args.index_limit),
                }
            else:
                result = {"status": "ok", **index.stats()}
        except (ValueError, OSError, RuntimeError) as exc:
            parser.exit(2, f"AURIX knowledge-index operation failed: {type(exc).__name__}: {exc}\n")
        print(
            json.dumps(result, ensure_ascii=False, indent=2)
            if args.json
            else json.dumps(result, ensure_ascii=False)
        )
        return

    learning_ops = (
        args.learning_add is not None,
        args.learning_review is not None,
        args.learning_list,
        args.learning_export is not None,
    )
    if any(learning_ops):
        if sum(bool(item) for item in learning_ops) != 1:
            parser.error("Choose exactly one learning operation")
        if (
            args.task
            or args.benchmark
            or args.functional_benchmark
            or args.autonomous_benchmark
            or args.analyze_document
            or args.doctor
            or args.run_tests
            or args.memory_add is not None
            or args.memory_search is not None
        ):
            parser.error("Learning operations cannot be combined with tasks or other operations")
        if not args.learning_scope.strip():
            parser.error("--learning-scope must not be empty")
        if args.learning_review is not None and args.learning_decision is None:
            parser.error("--learning-review requires --learning-decision")
        if args.learning_decision is not None and args.learning_review is None:
            parser.error("--learning-decision requires --learning-review")
        if args.learning_add is None and (
            args.learning_quality is not None
            or args.learning_source != "task_outcome"
            or args.learning_consent_to_train
        ):
            parser.error(
                "--learning-source, --learning-quality, and --learning-consent-to-train require --learning-add"
            )
        if args.learning_add is not None and args.learning_status is not None:
            parser.error("--learning-status requires --learning-list")
        try:
            learning = LearningStore(
                Path(args.workspace).expanduser().resolve() / ".aurix" / "learning.db"
            )
            if args.learning_add is not None:
                record_id = learning.add_candidate(
                    args.learning_add,
                    scope=args.learning_scope,
                    source=args.learning_source,
                    quality=args.learning_quality,
                    consent_to_train=args.learning_consent_to_train,
                )
                result = {
                    "status": "candidate",
                    "id": record_id,
                    "scope": args.learning_scope,
                    "consent_to_train": args.learning_consent_to_train,
                    "note": "Candidate is not trusted or used for training until reviewed and quality-gated.",
                }
            elif args.learning_review is not None:
                changed = learning.review(
                    args.learning_review,
                    decision=args.learning_decision,
                    quality=args.learning_quality,
                )
                result = {
                    "status": "reviewed" if changed else "unchanged_or_missing",
                    "id": args.learning_review,
                    "decision": args.learning_decision,
                }
            elif args.learning_list:
                records = learning.list_records(
                    scope=args.learning_scope, status=args.learning_status
                )
                result = {
                    "status": "ok",
                    "scope": args.learning_scope,
                    "count": len(records),
                    "records": records,
                }
            else:
                destination = Path(args.learning_export).expanduser()
                if not destination.is_absolute():
                    destination = Path(args.workspace).expanduser().resolve() / destination
                destination = destination.resolve()
                workspace_root = Path(args.workspace).expanduser().resolve()
                if destination == workspace_root or workspace_root not in destination.parents:
                    raise ValueError("--learning-export must target a file inside the workspace")
                count = learning.export_training_jsonl(
                    destination, min_quality=args.learning_min_quality, scope=args.learning_scope
                )
                result = {
                    "status": "exported",
                    "count": count,
                    "path": str(destination),
                    "minimum_quality": args.learning_min_quality,
                    "note": "Export contains only accepted records with explicit training consent.",
                }
        except (ValueError, PermissionError, OSError, RuntimeError) as exc:
            parser.exit(2, f"AURIX learning operation failed: {type(exc).__name__}: {exc}\n")
        print(
            json.dumps(result, ensure_ascii=False, indent=2)
            if args.json
            else json.dumps(result, ensure_ascii=False)
        )
        return

    if args.document_output and not args.analyze_document:
        parser.error("--document-output requires --analyze-document")
    if args.analyze_document:
        conflicting = (
            args.task
            or args.benchmark
            or args.functional_benchmark
            or args.autonomous_benchmark
            or args.doctor
            or args.run_tests
            or args.apply_proposal
            or args.revert_proposal
            or args.verify_proposal
            or args.review_proposal
            or args.audit_proposal
            or args.memory_add is not None
            or args.memory_search is not None
            or args.report_run
            or args.benchmark_compare
            or args.benchmark_output
            or args.verify_run_report
            or args.attach_audit_to_report
            or args.confirm_apply
            or args.confirm_revert
            or args.confirm_verify
            or args.confirm_audit_verify
        )
        if conflicting:
            parser.error("--analyze-document cannot be combined with another operation")
        try:
            provider = create_provider()
            result = analyze_document(
                args.analyze_document,
                provider,
                max_chunk_chars=args.document_chunk_chars,
                max_workers=args.document_workers,
            )
            rendered = json.dumps(result, ensure_ascii=False, indent=2)
            if args.document_output:
                output_path = Path(args.document_output).expanduser().resolve()
                source_path = Path(args.analyze_document).expanduser().resolve()
                if output_path == source_path:
                    parser.error("--document-output must not overwrite the source document")
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_text(rendered + "\n", encoding="utf-8")
        except (ValueError, PermissionError, OSError, RuntimeError, TypeError) as exc:
            parser.exit(2, f"AURIX document analysis failed: {type(exc).__name__}: {exc}\n")
        if args.json or args.document_output:
            print(rendered if args.json else f"Document analysis saved: {output_path}")
        else:
            print(
                f"AURIX document analysis: {result['page_count']} pages, {result['chunk_count']} chunks, "
                f"{result['model_calls']} model calls\n\n{result['summary']}"
            )
        return
    if args.autonomous_benchmark and (
        args.functional_benchmark
        or args.benchmark
        or args.benchmark_compare
        or args.benchmark_output
        or args.task
        or args.run_tests
        or args.apply_proposal
        or args.revert_proposal
        or args.verify_proposal
        or args.review_proposal
        or args.audit_proposal
        or args.doctor
        or args.report_run
        or args.verify_run_report
        or args.memory_add is not None
        or args.memory_search is not None
    ):
        parser.error("--autonomous-benchmark cannot be combined with a task or another operation")
    if args.confirm_autonomous_benchmark and not args.autonomous_benchmark:
        parser.error("--confirm-autonomous-benchmark requires --autonomous-benchmark")
    if args.autonomous_benchmark:
        if not args.confirm_autonomous_benchmark:
            parser.error(
                "--autonomous-benchmark requires --confirm-autonomous-benchmark because it executes tests and invokes the configured model"
            )
        try:
            provider = create_provider()
            result = run_autonomous_benchmark(
                args.autonomous_benchmark,
                provider,
                confirm=args.confirm_autonomous_benchmark,
                timeout_seconds=args.test_timeout,
                isolation=args.test_isolation,
                sandbox_image=args.sandbox_image,
                max_steps=get_max_steps(),
            )
        except (ValueError, PermissionError, OSError, RuntimeError) as exc:
            parser.exit(
                2, f"AURIX autonomous benchmark refused/failed: {type(exc).__name__}: {exc}\n"
            )
        print(
            json.dumps(result, ensure_ascii=False, indent=2)
            if args.json
            else f"AURIX autonomous benchmark: {result['passed']}/{result['cases']} cases passed; "
            f"demonstrated fixes={result['demonstrated_fixes']}"
        )
        if result["failed"]:
            raise SystemExit(1)
        return
    if args.functional_benchmark and (
        args.benchmark
        or args.benchmark_compare
        or args.benchmark_output
        or args.task
        or args.run_tests
        or args.apply_proposal
        or args.revert_proposal
        or args.verify_proposal
        or args.review_proposal
        or args.audit_proposal
        or args.doctor
        or args.report_run
        or args.verify_run_report
        or args.memory_add is not None
        or args.memory_search is not None
    ):
        parser.error("--functional-benchmark cannot be combined with a task or another operation")
    if args.confirm_functional_benchmark and not args.functional_benchmark:
        parser.error("--confirm-functional-benchmark requires --functional-benchmark")
    if args.functional_benchmark:
        try:
            result = run_functional_benchmark(
                args.functional_benchmark,
                confirm=args.confirm_functional_benchmark,
                timeout_seconds=args.test_timeout,
                isolation=args.test_isolation,
                sandbox_image=args.sandbox_image,
            )
        except (ValueError, PermissionError, OSError, RuntimeError) as exc:
            parser.exit(
                2, f"AURIX functional benchmark refused/failed: {type(exc).__name__}: {exc}\n"
            )
        print(
            json.dumps(result, ensure_ascii=False, indent=2)
            if args.json
            else f"AURIX functional benchmark: {result['passed']}/{result['cases']} cases passed; "
            f"demonstrated fixes={result['demonstrated_fixes']}"
        )
        if result["failed"]:
            raise SystemExit(1)
        return
    if args.benchmark_compare and not args.benchmark:
        parser.error("--benchmark-compare requires --benchmark")
    if args.benchmark_output and not args.benchmark:
        parser.error("--benchmark-output requires --benchmark")
    if args.sandbox_image and args.test_isolation != "docker":
        parser.error("--sandbox-image requires --test-isolation docker")
    if args.test_isolation == "docker" and not args.sandbox_image:
        parser.error("--test-isolation docker requires --sandbox-image")

    if args.use_memory_context and (args.memory_add is not None or args.memory_search is not None):
        parser.error("--use-memory-context cannot be combined with --memory-add or --memory-search")

    if args.memory_add is not None or args.memory_search is not None:
        if args.memory_add is not None and args.memory_search is not None:
            parser.error("Choose either --memory-add or --memory-search")
        if args.memory_search is not None and (
            args.memory_kind != "observation" or args.memory_confidence is not None
        ):
            parser.error("--memory-kind and --memory-confidence require --memory-add")
        if (
            args.task
            or args.benchmark
            or args.functional_benchmark
            or args.report_run
            or args.apply_proposal
            or args.revert_proposal
            or args.verify_proposal
            or args.review_proposal
            or args.audit_proposal
            or args.run_tests
            or args.doctor
            or args.verify_run_report
        ):
            parser.error("Memory operations cannot be combined with a task or another operation")
        if not args.memory_scope.strip():
            parser.error("--memory-scope must not be empty")
        try:
            store = create_memory(args.memory_backend, workspace=args.workspace)
            if args.memory_add is not None:
                if args.memory_confidence is not None and not 0.0 <= args.memory_confidence <= 1.0:
                    raise ValueError("--memory-confidence must be between 0 and 1")
                metadata = {"source": "cli", "kind": args.memory_kind}
                if args.memory_confidence is not None:
                    metadata["confidence"] = args.memory_confidence
                record_id = store.add(args.memory_scope, args.memory_add, metadata)
                result = {
                    "status": "stored",
                    "id": record_id,
                    "scope": args.memory_scope,
                    "metadata": metadata,
                }
            else:
                records = retrieve_memories(
                    store,
                    args.memory_search,
                    scope=args.memory_scope,
                    limit=args.memory_limit,
                    candidate_limit=args.memory_candidates,
                    max_content_chars=args.memory_max_content_chars,
                )
                result = {
                    "status": "ok",
                    "scope": args.memory_scope,
                    "count": len(records),
                    "records": records,
                    "retrieval": "lexical_overlap",
                    "semantic_search": False,
                }
        except (ValueError, PermissionError, OSError, RuntimeError) as exc:
            parser.exit(2, f"AURIX memory operation failed: {type(exc).__name__}: {exc}\n")
        print(
            json.dumps(result, ensure_ascii=False, indent=2)
            if args.json
            else (
                f"Memory record {result['id']} stored in scope {result['scope']}"
                if args.memory_add is not None
                else f"Found {result['count']} memory record(s) in scope {result['scope']}"
            )
        )
        return

    if args.verify_run_report:
        try:
            result = verify_run_report(args.workspace, args.verify_run_report)
        except (ValueError, PermissionError, OSError) as exc:
            parser.exit(2, f"AURIX report verification failed: {exc}\n")
        print(
            json.dumps(result, ensure_ascii=False, indent=2)
            if args.json
            else f"Run report {result['status']}: {result['path']}"
        )
        if not result["valid"]:
            raise SystemExit(1)
        return

    if args.attach_audit_to_report and not args.audit_proposal:
        parser.error("--attach-audit-to-report requires --audit-proposal")
    if args.probe_provider and not args.doctor:
        parser.error("--probe-provider requires --doctor")
    if args.doctor:
        try:
            provider = create_provider() if args.probe_provider else None
            result = run_diagnostics(
                args.workspace, probe_provider=args.probe_provider, provider=provider
            )
        except (ValueError, OSError, RuntimeError) as exc:
            parser.exit(2, f"AURIX diagnostics failed: {type(exc).__name__}\n")
        print(
            json.dumps(result, ensure_ascii=False, indent=2)
            if args.json
            else f"AURIX doctor: {result['status']}\n"
            + "\n".join(
                f"[{item['status']}] {item['name']}: {item['detail']}" for item in result["checks"]
            )
        )
        return

    if args.run_tests:
        if (
            args.apply_proposal
            or args.revert_proposal
            or args.verify_proposal
            or args.review_proposal
            or args.audit_proposal
            or args.confirm_apply
            or args.confirm_revert
            or args.confirm_verify
            or args.confirm_audit_verify
        ):
            parser.error(
                "Test execution cannot be combined with patch operations or proposal verification"
            )
        try:
            result = run_test_suite(
                args.workspace,
                args.run_tests,
                confirm=args.confirm_run_tests,
                timeout_seconds=args.test_timeout,
                isolation=args.test_isolation,
                sandbox_image=args.sandbox_image,
            )
        except (ValueError, PermissionError, OSError, RuntimeError) as exc:
            parser.exit(2, f"AURIX test execution refused/failed: {exc}\n")
        print(
            json.dumps(result, ensure_ascii=False, indent=2)
            if args.json
            else f"{result['suite']}: {'PASSED' if result['passed'] else 'FAILED'} "
            f"(exit={result['returncode']}, timeout={result['timed_out']})\n"
            f"{result['stdout']}\n{result['stderr']}"
        )
        return
    if args.confirm_run_tests and not args.run_tests:
        parser.error("--confirm-run-tests requires --run-tests")
    if args.finalize_interrupted_recovery:
        conflicting = (
            args.task
            or args.benchmark
            or args.functional_benchmark
            or args.autonomous_benchmark
            or args.analyze_document
            or args.doctor
            or args.run_tests
            or args.apply_proposal
            or args.revert_proposal
            or args.verify_proposal
            or args.review_proposal
            or args.audit_proposal
            or args.inspect_transactions
            or args.plan_transaction_recovery
            or args.recover_transaction
            or args.memory_add is not None
            or args.memory_search is not None
            or args.report_run
            or args.verify_run_report
            or args.confirm_apply
            or args.confirm_revert
            or args.confirm_verify
            or args.confirm_audit_verify
        )
        if conflicting:
            parser.error(
                "--finalize-interrupted-recovery cannot be combined with another operation"
            )
        if not args.confirm_recovery:
            parser.error("--finalize-interrupted-recovery requires --confirm-recovery")
        try:
            result = finalize_interrupted_recovery(
                args.workspace, args.finalize_interrupted_recovery, confirm=args.confirm_recovery
            )
        except (ValueError, PermissionError, OSError, RuntimeError) as exc:
            parser.exit(2, f"AURIX recovery finalization refused/failed: {exc}\n")
        print(
            json.dumps(result, ensure_ascii=False, indent=2)
            if args.json
            else f"Transaction recovery finalized: {result['proposal_id']} ({result['transaction']})"
        )
        return

    if args.recover_transaction:
        conflicting = (
            args.task
            or args.benchmark
            or args.functional_benchmark
            or args.autonomous_benchmark
            or args.analyze_document
            or args.doctor
            or args.run_tests
            or args.apply_proposal
            or args.revert_proposal
            or args.verify_proposal
            or args.review_proposal
            or args.audit_proposal
            or args.inspect_transactions
            or args.plan_transaction_recovery
            or args.memory_add is not None
            or args.memory_search is not None
            or args.report_run
            or args.verify_run_report
            or args.confirm_apply
            or args.confirm_revert
            or args.confirm_verify
            or args.confirm_audit_verify
        )
        if conflicting:
            parser.error("--recover-transaction cannot be combined with another operation")
        if not args.confirm_recovery:
            parser.error("--recover-transaction requires --confirm-recovery")
        try:
            result = recover_transaction(
                args.workspace, args.recover_transaction, confirm=args.confirm_recovery
            )
        except (ValueError, PermissionError, OSError, RuntimeError) as exc:
            parser.exit(2, f"AURIX transaction recovery refused/failed: {exc}\n")
        print(
            json.dumps(result, ensure_ascii=False, indent=2)
            if args.json
            else f"Transaction recovery: {result['status']} ({result['proposal_id']}); state={result['transaction']}"
        )
        return

    if args.inspect_operation_lock:
        conflicting = (
            args.task
            or args.benchmark
            or args.functional_benchmark
            or args.autonomous_benchmark
            or args.analyze_document
            or args.doctor
            or args.run_tests
            or args.apply_proposal
            or args.revert_proposal
            or args.verify_proposal
            or args.review_proposal
            or args.audit_proposal
            or args.inspect_transactions
            or args.create_recovery_anchor
            or args.recover_transaction
            or args.finalize_interrupted_recovery
            or args.verify_recovery_history
            or args.memory_add is not None
            or args.memory_search is not None
            or args.report_run
            or args.verify_run_report
        )
        if conflicting:
            parser.error("--inspect-operation-lock cannot be combined with another operation")
        try:
            result = inspect_operation_lock(args.workspace)
        except (ValueError, PermissionError, OSError, RuntimeError) as exc:
            parser.exit(2, f"AURIX operation-lock inspection failed: {exc}\n")
        print(
            json.dumps(result, ensure_ascii=False, indent=2)
            if args.json
            else f"Operation lock: {result['status']}"
            + (
                f" (owner={result.get('owner_status')}; stale not proven)"
                if result["status"] == "present"
                else ""
            )
        )
        return

    if args.create_recovery_anchor:
        conflicting = (
            args.task
            or args.benchmark
            or args.functional_benchmark
            or args.autonomous_benchmark
            or args.analyze_document
            or args.doctor
            or args.run_tests
            or args.apply_proposal
            or args.revert_proposal
            or args.verify_proposal
            or args.review_proposal
            or args.audit_proposal
            or args.inspect_transactions
            or args.plan_transaction_recovery
            or args.recover_transaction
            or args.finalize_interrupted_recovery
            or args.verify_recovery_history
            or args.memory_add is not None
            or args.memory_search is not None
            or args.report_run
            or args.verify_run_report
        )
        if conflicting:
            parser.error("--create-recovery-anchor cannot be combined with another operation")
        if not args.confirm_create_recovery_anchor:
            parser.error("--create-recovery-anchor requires --confirm-create-recovery-anchor")
        try:
            result = create_recovery_anchor(args.workspace, args.create_recovery_anchor)
        except (ValueError, PermissionError, OSError, RuntimeError) as exc:
            parser.exit(2, f"AURIX recovery anchor creation failed: {exc}\n")
        print(
            json.dumps(result, ensure_ascii=False, indent=2)
            if args.json
            else f"Recovery anchor created: {result['anchor']} ({result['journals']} journals)"
        )
        return

    if args.verify_recovery_history:
        conflicting = (
            args.task
            or args.benchmark
            or args.functional_benchmark
            or args.autonomous_benchmark
            or args.analyze_document
            or args.doctor
            or args.run_tests
            or args.apply_proposal
            or args.revert_proposal
            or args.verify_proposal
            or args.review_proposal
            or args.audit_proposal
            or args.inspect_transactions
            or args.plan_transaction_recovery
            or args.recover_transaction
            or args.finalize_interrupted_recovery
            or args.memory_add is not None
            or args.memory_search is not None
            or args.report_run
            or args.verify_run_report
            or args.confirm_apply
            or args.confirm_revert
            or args.confirm_verify
            or args.confirm_audit_verify
        )
        if conflicting:
            parser.error("--verify-recovery-history cannot be combined with another operation")
        try:
            result = verify_recovery_histories(args.workspace, args.recovery_anchor)
        except (ValueError, PermissionError, OSError, RuntimeError) as exc:
            parser.exit(2, f"AURIX recovery-history verification failed: {exc}\n")
        print(
            json.dumps(result, ensure_ascii=False, indent=2)
            if args.json
            else f"Recovery history verification: {result['status']} ({result['valid']}/{result['count']} valid)"
        )
        if result["invalid"]:
            raise SystemExit(2)
        return

    if args.plan_transaction_recovery:
        conflicting = (
            args.task
            or args.benchmark
            or args.functional_benchmark
            or args.autonomous_benchmark
            or args.analyze_document
            or args.doctor
            or args.run_tests
            or args.apply_proposal
            or args.revert_proposal
            or args.verify_proposal
            or args.review_proposal
            or args.audit_proposal
            or args.inspect_transactions
            or args.memory_add is not None
            or args.memory_search is not None
            or args.report_run
            or args.verify_run_report
            or args.confirm_apply
            or args.confirm_revert
            or args.confirm_verify
            or args.confirm_audit_verify
        )
        if conflicting:
            parser.error("--plan-transaction-recovery cannot be combined with another operation")
        try:
            result = plan_transaction_recovery(args.workspace)
        except (ValueError, PermissionError, OSError, RuntimeError) as exc:
            parser.exit(2, f"AURIX recovery planning failed: {exc}\n")
        print(
            json.dumps(result, ensure_ascii=False, indent=2)
            if args.json
            else f"Recovery planning: {result['status']} ({result['count']} journals)\n"
            + "\n".join(
                f"[{row['action']}] {row.get('proposal_id')}: {row.get('reason', '')}"
                for row in result["plans"]
            )
        )
        return

    if args.inspect_transactions:
        conflicting = (
            args.task
            or args.benchmark
            or args.functional_benchmark
            or args.autonomous_benchmark
            or args.analyze_document
            or args.doctor
            or args.run_tests
            or args.apply_proposal
            or args.revert_proposal
            or args.verify_proposal
            or args.review_proposal
            or args.audit_proposal
            or args.memory_add is not None
            or args.memory_search is not None
            or args.report_run
            or args.verify_run_report
            or args.confirm_apply
            or args.confirm_revert
            or args.confirm_verify
            or args.confirm_audit_verify
        )
        if conflicting:
            parser.error("--inspect-transactions cannot be combined with another operation")
        try:
            result = inspect_transactions(args.workspace)
        except (ValueError, PermissionError, OSError, RuntimeError) as exc:
            parser.exit(2, f"AURIX transaction inspection failed: {exc}\n")
        print(
            json.dumps(result, ensure_ascii=False, indent=2)
            if args.json
            else f"Transaction inspection: {result['status']} ({result['count']} journals)\n"
            + "\n".join(
                f"[{row['status']}] {row.get('proposal_id')}: {row.get('reason', row.get('state', ''))}"
                for row in result["transactions"]
            )
        )
        return

    operations = [
        bool(args.apply_proposal),
        bool(args.revert_proposal),
        bool(args.verify_proposal),
        bool(args.review_proposal),
        bool(args.audit_proposal),
    ]
    if any(operations):
        if sum(operations) > 1:
            parser.error("Choose only one proposal operation")
        if args.apply_proposal and (args.confirm_revert or args.confirm_verify):
            parser.error("Confirmation flag does not match the requested operation")
        if args.revert_proposal and (args.confirm_apply or args.confirm_verify):
            parser.error("Confirmation flag does not match the requested operation")
        if args.verify_proposal and (args.confirm_apply or args.confirm_revert):
            parser.error("Confirmation flag does not match the requested operation")
        if args.review_proposal and (
            args.confirm_apply
            or args.confirm_revert
            or args.confirm_verify
            or args.confirm_audit_verify
        ):
            parser.error("Review cannot be combined with operation confirmation flags")
        if args.audit_proposal and (
            args.confirm_apply or args.confirm_revert or args.confirm_verify
        ):
            parser.error("Proposal audit cannot be combined with unrelated confirmation flags")
        if args.confirm_audit_verify and not args.audit_proposal:
            parser.error("--confirm-audit-verify requires --audit-proposal")
        if args.attach_audit_to_report and not args.audit_proposal:
            parser.error("--attach-audit-to-report requires --audit-proposal")
        try:
            if args.apply_proposal:
                result = apply_proposal(
                    args.workspace,
                    args.apply_proposal,
                    confirm=args.confirm_apply,
                    require_audit_gate=args.require_audit_gate,
                )
            elif args.revert_proposal:
                result = revert_proposal(
                    args.workspace, args.revert_proposal, confirm=args.confirm_revert
                )
            elif args.verify_proposal:
                result = verify_proposal(
                    args.workspace,
                    args.verify_proposal,
                    confirm=args.confirm_verify,
                    suite=args.verify_suite,
                    timeout_seconds=args.test_timeout,
                    isolation=args.test_isolation,
                    sandbox_image=args.sandbox_image,
                )
            elif args.review_proposal:
                result = review_proposal(args.workspace, args.review_proposal)
            else:
                result = audit_proposal(
                    args.workspace,
                    args.audit_proposal,
                    confirm_verify=args.confirm_audit_verify,
                    suite=args.verify_suite,
                    timeout_seconds=args.test_timeout,
                    isolation=args.test_isolation,
                    sandbox_image=args.sandbox_image,
                )
                if args.attach_audit_to_report:
                    result["report_attachment"] = attach_audit_to_run_report(
                        args.workspace, args.attach_audit_to_report, audit_result=result
                    )
        except (ValueError, PermissionError, OSError, RuntimeError) as exc:
            parser.exit(2, f"AURIX patch operation refused/failed: {exc}\n")
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        elif args.verify_proposal:
            test_result = result["test_result"]
            print(
                f"Proposal {result['proposal_id']}: {result['status']} "
                f"(suite={result['suite']}, regression={result.get('regression_status', 'unknown')}, "
                f"exit={test_result['returncode']}, duration_ms={test_result['duration_ms']})"
            )
            baseline = result.get("baseline_result")
            if isinstance(baseline, dict):
                print(
                    f"Baseline: {'PASS' if baseline.get('passed') else 'FAIL'} "
                    f"(exit={baseline.get('returncode')}, duration_ms={baseline.get('duration_ms')})"
                )
            print(str(test_result.get("stdout", "")))
            if test_result.get("stderr"):
                print(str(test_result["stderr"]))
            print(str(result["security_note"]))
        elif args.audit_proposal:
            review = result["review"]
            print(
                f"Proposal {result['proposal_id']}: {result['status']} "
                f"(heuristic risk={review['risk_level']}, findings={review['finding_count']}, "
                f"verification={result['verification']['status']})"
            )
            print("No patch was applied. Review findings and limitations before proceeding.")
            if result.get("report_attachment"):
                print(
                    f"Audit evidence attached to run report: {result['report_attachment']['path']}"
                )
        elif args.review_proposal:
            print(
                f"Proposal {result['proposal_id']}: heuristic risk={result['risk_level']} "
                f"({result['finding_count']} finding(s)); manual review still required"
            )
            for finding in result["findings"]:
                print(
                    f"[{finding['severity']}] {finding['file']}:{finding['patch_line']} "
                    f"{finding['rule']}: {finding['summary']}"
                )
        else:
            print(f"Proposal {result['proposal_id']}: {result['status']} ({result['files']})")
        return
    if args.require_audit_gate and not args.apply_proposal:
        parser.error("--require-audit-gate requires --apply-proposal")
    if (
        args.confirm_apply
        or args.confirm_revert
        or args.confirm_verify
        or args.confirm_audit_verify
    ):
        parser.error("A confirmation flag requires its matching proposal operation")
    provider = create_provider()
    memory_store = (
        create_memory(args.memory_backend, workspace=args.workspace)
        if args.use_memory_context
        else None
    )
    orchestrator = Orchestrator(
        provider,
        max_steps=get_max_steps(),
        workspace=args.workspace,
        memory_store=memory_store if args.use_memory_context else None,
        memory_scope=args.memory_scope,
        memory_limit=min(args.memory_limit, 10),
        allow_agent_verification=args.allow_agent_verification,
        verification_isolation=args.test_isolation,
        sandbox_image=args.sandbox_image,
    )

    if args.benchmark:
        try:
            report = run_benchmark(
                orchestrator, load_cases(args.benchmark), repetitions=args.benchmark_repetitions
            )
            output = report
            if args.benchmark_compare:
                baseline = json.loads(Path(args.benchmark_compare).read_text(encoding="utf-8"))
                output = compare_reports(report, baseline)
            if args.benchmark_output:
                output_path = Path(args.benchmark_output).expanduser()
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_text(
                    json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
                )
        except (ValueError, OSError, json.JSONDecodeError) as exc:
            parser.error(f"Benchmark failed: {exc}")
        if args.json:
            print(json.dumps(output, ensure_ascii=False, indent=2))
        elif args.benchmark_compare:
            print(
                f"AURIX benchmark comparison: {output['baseline_pass_rate']:.0%} -> {output['current_pass_rate']:.0%} "
                f"(delta={output['pass_rate_delta']:+.1%}); descriptive only"
            )
        else:
            print(
                f"AURIX benchmark: {report['passed']}/{report['executions']} executions passed ({report['pass_rate']:.0%}); "
                f"consistently passing cases={report['consistently_passing_cases']}/{report['cases']}, repetitions={report['repetitions']}"
            )
        return

    workspace = Path(args.workspace).expanduser().resolve()
    task = args.task or input("AURIX task> ").strip()
    context = build_workspace_context(workspace)
    result = orchestrator.run(task, context)
    report_info = None
    if args.report_run:
        try:
            report_info = write_run_report(
                args.workspace,
                args.report_run,
                task=task,
                result=result,
                provider=type(provider).__name__,
            )
        except (ValueError, PermissionError, OSError) as exc:
            parser.exit(2, f"AURIX report could not be written: {exc}\n")
    if args.json:
        output = {
            "status": result.status,
            "steps": result.steps,
            "message": result.message,
            "trace": result.trace,
            "memory_context": {
                "enabled": args.use_memory_context,
                "scope": args.memory_scope if args.use_memory_context else None,
                "evidence_count": len(result.memory_evidence),
                "evidence": result.memory_evidence,
            },
            "knowledge_context": {
                "enabled": os.getenv("AURIX_RAG_ENABLED", "true").lower()
                not in {"0", "false", "no", "off"},
                "evidence_count": len(result.knowledge_evidence),
                "evidence": result.knowledge_evidence,
            },
        }
        if report_info is not None:
            output["report"] = report_info
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        print(f"\nAURIX [{result.status}] after {result.steps} step(s)\n{result.message}")
        print("\nNo autonomous file edits or arbitrary shell execution are enabled.")
        if args.allow_agent_verification:
            print(
                "Agent proposal verification is enabled; tests run in a disposable worktree, not an OS sandbox."
            )
        if args.use_memory_context:
            print(
                f"Scoped memory context enabled: {args.memory_scope} (retrieved records are treated as untrusted evidence)."
            )
        if report_info is not None:
            print(f"Run report saved: {report_info['path']} (run_id={report_info['run_id']})")


if __name__ == "__main__":
    main()
