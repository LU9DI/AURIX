from pathlib import Path

from aurix.evaluation.autonomous import load_autonomous_suite


def test_diffusion_research_suite_has_unique_tasks_and_local_fixtures():
    suite = (
        Path(__file__).resolve().parents[1]
        / "research"
        / "diffusion-agent-benchmark"
        / "suite"
        / "suite.json"
    )
    root, cases = load_autonomous_suite(suite)

    assert len(cases) == 3
    assert len({case["id"] for case in cases}) == len(cases)
    for case in cases:
        fixture = Path(case["fixture"])
        assert fixture.is_relative_to(root)
        assert (fixture / "calculator.py").is_file()
        assert (fixture / "test_calculator.py").is_file()
        assert case["expect_baseline_passed"] is False
        assert case["expect_candidate_passed"] is True
        assert "propose_patch" in case["task"]
