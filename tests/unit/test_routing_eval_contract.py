import json
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
VALIDATOR = REPO_ROOT / "scripts" / "validate-routing-evals.mjs"
EVALS = REPO_ROOT / "evals" / "skill-routing.json"


def run_validator(eval_path: Path = EVALS) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["node", str(VALIDATOR), str(eval_path)],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_routing_eval_matrix_is_release_ready() -> None:
    result = run_validator()
    assert result.returncode == 0, result.stderr
    assert "15 cases, 6 candidates" in result.stdout


def test_routing_eval_matrix_rejects_a_missing_multi_family_case(tmp_path: Path) -> None:
    suite = json.loads(EVALS.read_text(encoding="utf-8"))
    suite["cases"] = [case for case in suite["cases"] if case["id"] != "router-pickups-and-inventory-ui"]
    broken = tmp_path / "routing.json"
    broken.write_text(json.dumps(suite), encoding="utf-8")

    result = run_validator(broken)
    assert result.returncode == 1
    assert "produce-2d-assets: require at least two positive routing cases" in result.stderr
    assert "production-multi-family: require at least two routing cases" in result.stderr


def test_routing_eval_matrix_rejects_single_family_router_leakage(tmp_path: Path) -> None:
    suite = json.loads(EVALS.read_text(encoding="utf-8"))
    test_case = next(case for case in suite["cases"] if case["id"] == "background-parallax-forest")
    test_case["expectedSkill"] = "produce-2d-assets"
    test_case["excludedSkills"] = [
        skill for skill in suite["candidates"] if skill != "produce-2d-assets"
    ]
    broken = tmp_path / "routing.json"
    broken.write_text(json.dumps(suite), encoding="utf-8")

    result = run_validator(broken)
    assert result.returncode == 1
    assert "a single-family production case must select a leaf producer" in result.stderr
