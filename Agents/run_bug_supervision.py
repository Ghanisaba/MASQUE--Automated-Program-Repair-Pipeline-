#API_KEY = "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"
import os
import json
import re
from pathlib import Path
from typing import List, Dict, Any

from openai import OpenAI
from .bug_detection_agent import BugDetectionAgent
from .supervisor_agent import SupervisorAgent
from .bug_fix_agent import BugFixAgent
from .unit_test_evaluation_agent import UnitTestEvaluationAgent
from .git_push_agent import GitPushAgent



# ---------------------------------------------------------------------------
# OpenAI client & model names
# ---------------------------------------------------------------------------



FIX_MODEL = "gpt-4.1-mini"
BUG_DETECT_MODEL = "gpt-4.1-mini"
SUPERVISOR_MODEL = "gpt-4.1"


def _extract_json_from_text(text: str) -> str:
    t = (text or "").strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z]*\s*\n", "", t)
        t = re.sub(r"\n```$", "", t).strip()

    start = t.find("{")
    end = t.rfind("}")
    if start != -1 and end != -1 and end > start:
        return t[start:end + 1]
    return t


def _normalize_bug_report(entry: Dict[str, Any]) -> Dict[str, Any]:
    bug_report = entry.get("bug_report") or {}
    if not isinstance(bug_report, dict):
        return {}

    # If detector failed to parse JSON, try to recover from raw_response_text
    if bug_report.get("error") and bug_report.get("raw_response_text"):
        cleaned = _extract_json_from_text(bug_report["raw_response_text"])
        try:
            recovered = json.loads(cleaned)
            # preserve excerpt if detector included it
            if bug_report.get("code_excerpt") and not recovered.get("code_excerpt"):
                recovered["code_excerpt"] = bug_report["code_excerpt"]
            return recovered
        except Exception:
            return bug_report

    return bug_report


def _to_abs_path(scanned_file: str, target_dir: Path) -> str:
    sf = Path(scanned_file)
    if sf.is_absolute():
        return str(sf)
    return str((target_dir / sf).resolve())


def _as_bool(v) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return v != 0
    if isinstance(v, str):
        return v.strip().lower() in ("true", "1", "yes", "y")
    return False


def _repo_relpath(abs_path: str, repo_root: Path) -> str:
    p = Path(abs_path).resolve()
    try:
        return str(p.relative_to(repo_root))
    except Exception:
        return str(p)


def _collect_fixed_files(final_results: List[Dict[str, Any]], repo_root: Path) -> List[str]:
    fixed = set()
    for entry in final_results:
        fr = entry.get("fix_result") or {}
        if not isinstance(fr, dict):
            continue

        status = (fr.get("status") or "").lower()
        if status not in {"applied", "fixed", "success", "patched", "ok"}:
            continue

        # Your fix_result uses file_path, so include it:
        f = fr.get("file_path") or fr.get("file") or fr.get("modified_file") or fr.get("patched_file")
        if not f:
            continue

        fixed.add(_repo_relpath(f, repo_root))

    return sorted(fixed)



# ---------------------------------------------------------------------------
# Pipeline steps
# ---------------------------------------------------------------------------

def scan_repo(repo_path: str) -> List[Dict[str, Any]]:
    detector = BugDetectionAgent(client=client, model=BUG_DETECT_MODEL)

    root = Path(repo_path)
    if not root.exists():
        raise FileNotFoundError(f"Repo path not found: {repo_path}")

    py_files = sorted(root.rglob("*.py"))
    reports: List[Dict[str, Any]] = []

    for p in py_files:
        if p.name == "__init__.py":
            continue
        print(f"[Runner] Scanning file: {p}")
        rep = detector.analyze_file(p)  # Path object
        reports.append(rep)

    return reports


def run_bug_detection_with_supervision(repo_path: str) -> List[Dict[str, Any]]:
    print(f"[Runner] run_bug_detection_with_supervision called with repo_path={repo_path}")

    bug_reports = scan_repo(repo_path)
    print(f"[Runner] scan_repo returned {len(bug_reports)} reports")

    supervisor = SupervisorAgent(client=client, model=SUPERVISOR_MODEL)

    results: List[Dict[str, Any]] = []
    for report in bug_reports:
        file_name = report.get("file")
        print(f"[Runner] Sending to supervisor: {file_name}")

        review = supervisor.review_report(report)

        results.append({
            "bug_report": report,
            "supervisor_review": review,
            "fix_result": None,
            "unit_test_evaluation": None,
        })

    return results


# ---------------------------------------------------------------------------
# Main (wrapped for module execution)
# ---------------------------------------------------------------------------

def main() -> None:
    import sys

    ROOT_DIR = Path(__file__).resolve().parent.parent
    print(f"[Runner.main] ROOT_DIR={ROOT_DIR}")

    if len(sys.argv) >= 2:
        target_dir = Path(sys.argv[1]).resolve()
    else:
        target_dir = (ROOT_DIR / "python_programs").resolve()

    print(f"🔍 Scanning: {target_dir}")

    # 1) Detect + supervise
    final_results = run_bug_detection_with_supervision(str(target_dir))

    # 2) Write detection report
    out_path = ROOT_DIR / "bug_detection_with_supervision.json"
    out_path.write_text(json.dumps(final_results, indent=2), encoding="utf-8")
    print(f"✅ Results written to {out_path}")

    # 3) Ask user if we should apply fixes
    ans = input("🛠 Apply fixes now (y/N)? ").strip().lower()
    apply_fixes = ans in ("y", "yes")

    # -----------------------------------------------------------------------
    # Unit tests are in python_testcases/
    # -----------------------------------------------------------------------
    TESTS_DIR = "python_testcases"
    tests_root = (ROOT_DIR / TESTS_DIR)

    if not tests_root.exists():
        raise FileNotFoundError(f"Tests directory not found: {tests_root}")

    # make tests folder a package (driver tests with relative imports)
    init_file = tests_root / "__init__.py"
    if not init_file.exists():
        init_file.write_text("", encoding="utf-8")

    # Agents used in phase 2
    fix_agent = BugFixAgent(client=client, model=FIX_MODEL) if apply_fixes else None
    test_agent = UnitTestEvaluationAgent(
        repo_root=ROOT_DIR,
        tests_dir=TESTS_DIR,
        timeout_seconds=120
    )

    fixes_attempted = 0
    tests_run = 0
    tests_passed = 0
    passed_fixed_files: List[str] = []

    # 4) Phase 2: (optional) fix, then ALWAYS run unit tests
    for entry in final_results:
        bug_report = _normalize_bug_report(entry)
        review = entry.get("supervisor_review") or {}

        scanned_file = bug_report.get("file") or bug_report.get("file_path")
        if not scanned_file:
            entry["fix_result"] = {"status": "skipped", "reason": "bug_report file path missing"}
            entry["unit_test_evaluation"] = {"status": "skipped", "reason": "No file path; cannot run unit test"}
            continue

        # If bug_report.file_path is absolute, _to_abs_path will keep it as is
        scanned_file_abs = _to_abs_path(str(scanned_file), target_dir)

        # ✅ BUG EXISTS if supervisor OR corrected_has_bug OR detector says so
        confirmed_bug = isinstance(review, dict) and _as_bool(review.get("confirmed_bug", False))
        corrected_has_bug = isinstance(review, dict) and _as_bool(review.get("corrected_has_bug", False))
        detector_has_bug = _as_bool(bug_report.get("has_bug", False))
        bug_exists = confirmed_bug or corrected_has_bug or detector_has_bug

        # ✅ User chooses whether to apply fix (only if bug exists)
        do_fix = apply_fixes and bug_exists

        print(
            f"[Runner][Decision] file={scanned_file_abs} apply_fixes={apply_fixes} "
            f"confirmed_bug={confirmed_bug} corrected_has_bug={corrected_has_bug} "
            f"detector_has_bug={detector_has_bug} => do_fix={do_fix}"
        )

        if do_fix:
            print(f"[Runner] Applying fix for: {scanned_file_abs}")
            entry["fix_result"] = fix_agent.fix_bug({**bug_report, "file": scanned_file_abs}, dry_run=False)
            fixes_attempted += 1
        else:
            entry["fix_result"] = {
                "status": "skipped",
                "reason": "User selected N or no bug detected by supervisor/detector"
            }

        # ---- ALWAYS run unit tests (after fix attempt if any) ----
        print(f"[Runner] Running unit test for: {scanned_file_abs}")
        test_res = test_agent.evaluate(scanned_file_abs)
        fix_status = ((entry.get("fix_result") or {}).get("status") or "").lower()
        fix_applied = fix_status in {"applied", "fixed", "success", "patched", "ok"}

        if fix_applied and test_res.passed:
          passed_fixed_files.append(_repo_relpath(scanned_file_abs, ROOT_DIR))


        entry["unit_test_evaluation"] = {
            "passed": test_res.passed,
            "runner": test_res.runner,
            "test_file": test_res.test_file,
            "exit_code": test_res.exit_code,
            "notes": test_res.notes,
            "stdout": test_res.stdout,
            "stderr": test_res.stderr,
        }

        tests_run += 1
        if test_res.passed:
            tests_passed += 1

       # -----------------------------------------------------------------------
    # Git stage / optional push flow (ONLY fixes that PASSED unit tests)
    # -----------------------------------------------------------------------
    fixed_files = sorted(set(passed_fixed_files))

    if fixed_files:
        print("\n✅ Fixed files with PASSING unit tests:")
        for f in fixed_files:
            print(f"   - {f}")

        git_ans = input("\n🚀 Create branch & push to Git (y/N)? ").strip().lower()
        do_push = git_ans in ("y", "yes")

        git_agent = GitPushAgent(repo_root=ROOT_DIR)
        branch_name = f"masque/auto-fix-{Path(target_dir).name}"

        print(f"\n🌿 Creating new branch: {branch_name}")
        git_agent.create_branch(branch_name)

        print("📦 Staging PASSING fixed files...")
        git_agent.stage_files(fixed_files)

        if do_push:
            commit_msg = "MASQUE: automated fix (tests passed)"
            print("📝 Committing...")
            git_agent.commit(commit_msg)

            print("⬆️ Pushing branch to origin...")
            git_agent.push(branch_name)
            print(f"✅ Pushed to origin/{branch_name}")
        else:
            print("✅ Staged changes only (no commit/push). Review with: git status")
    else:
        print("\nℹ️ No passing fixes detected (nothing will be staged/pushed).")

    # 5) Rewrite report including fix + test results (ALWAYS)
    out_path.write_text(json.dumps(final_results, indent=2), encoding="utf-8")
    print("\n✅ Phase done.")
    print(f"   Fixes attempted: {fixes_attempted} (apply_fixes={apply_fixes})")
    print(f"   Unit tests run:  {tests_run}, passed: {tests_passed}, failed: {tests_run - tests_passed}")
    print(f"✅ Updated report written to {out_path}")



    # 5) Rewrite report including fix + test results
    out_path.write_text(json.dumps(final_results, indent=2), encoding="utf-8")
    print("\n✅ Phase done.")
    print(f"   Fixes attempted: {fixes_attempted} (apply_fixes={apply_fixes})")
    print(f"   Unit tests run:  {tests_run}, passed: {tests_passed}, failed: {tests_run - tests_passed}")
    print(f"✅ Updated report written to {out_path}")


if __name__ == "__main__":
    main()