# unit_test_evaluation_agent.py

from __future__ import annotations

import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Union


@dataclass
class UnitTestEvalResult:
    scanned_file: str
    test_file: str
    runner: str                 # "pytest" | "python-file" | "python-module" | "none"
    passed: bool
    exit_code: int
    stdout: str
    stderr: str
    notes: str


class UnitTestEvaluationAgent:
    """
    Runs unit tests for a scanned file.

    New rule:
      - Tests are stored under a dedicated folder: python_testcases/
      - Test filenames can be either:
          1) <stem>_test.py   (suffix style)
          2) test_<stem>.py   (prefix style)

    Execution:
      - If test looks like pytest -> run: python -m pytest <test_file>
      - Else if driver + relative imports -> run: python -m <module>
      - Else -> run: python <test_file>
    """

    def __init__(
        self,
        repo_root: Union[str, Path],
        tests_dir: str = "python_testcases",
        timeout_seconds: int = 120,
    ) -> None:
        self.repo_root = Path(repo_root).resolve()
        self.tests_dir = tests_dir
        self.timeout_seconds = timeout_seconds

    # -------------------- locating tests --------------------

    def _candidate_test_paths(self, scanned_file: Path) -> List[Path]:
        """
        For scanned file X.py, return candidate test paths:
          python_testcases/X_test.py
          python_testcases/test_X.py
        """
        stem = scanned_file.stem
        tests_root = (self.repo_root / self.tests_dir).resolve()
        return [
            tests_root / f"{stem}_test.py",
            tests_root / f"test_{stem}.py",
        ]

    def _find_test_file(self, scanned_file: Path) -> Optional[Path]:
        for p in self._candidate_test_paths(scanned_file):
            if p.exists():
                return p
        return None

    # -------------------- execution helpers --------------------

    def _looks_like_relative_import_test(self, text: str) -> bool:
        # handles "from .x import" OR "from ..x import"
        return bool(re.search(r"^\s*from\s+\.\.?\S*\s+import\s+", text, flags=re.MULTILINE))

    def _looks_like_pytest_test(self, text: str, test_file: Path) -> bool:
        if "import pytest" in text:
            return True
        if re.search(r"^\s*def\s+test", text, flags=re.MULTILINE):
            return True
        # pytest also collects *_test.py/test_*.py, but this is a good heuristic
        return test_file.name.startswith("test_") or test_file.name.endswith("_test.py")

    def _module_name_for_file(self, file_path: Path) -> str:
        """
        Build a dotted module name for `python -m ...` by walking upward through package dirs.
        This requires __init__.py in python_testcases/ (and parents if you want deeper packages).
        """
        parts = [file_path.stem]
        cur = file_path.parent

        while cur != self.repo_root and (cur / "__init__.py").exists():
            parts.append(cur.name)
            cur = cur.parent

        if cur == self.repo_root and (cur / "__init__.py").exists():
            parts.append(cur.name)

        return ".".join(reversed(parts))

    def _run(self, cmd: List[str]) -> subprocess.CompletedProcess:
        env = os.environ.copy()
        # ensure imports from repo root work
        env["PYTHONPATH"] = str(self.repo_root)

        return subprocess.run(
            cmd,
            cwd=str(self.repo_root),
            env=env,
            capture_output=True,
            text=True,
            timeout=self.timeout_seconds,
        )

    # -------------------- public API --------------------

    def evaluate(self, scanned_file_path: Union[str, Path]) -> UnitTestEvalResult:
        scanned_file = Path(scanned_file_path).resolve()

        if not scanned_file.exists():
            return UnitTestEvalResult(
                scanned_file=str(scanned_file),
                test_file="",
                runner="none",
                passed=False,
                exit_code=2,
                stdout="",
                stderr="",
                notes="Scanned file does not exist.",
            )

        test_file = self._find_test_file(scanned_file)
        if not test_file:
            cands = [str(p) for p in self._candidate_test_paths(scanned_file)]
            return UnitTestEvalResult(
                scanned_file=str(scanned_file),
                test_file="",
                runner="none",
                passed=False,
                exit_code=3,
                stdout="",
                stderr="",
                notes=f"Unit test not found in {self.tests_dir}. Tried: {cands}",
            )

        test_text = test_file.read_text(encoding="utf-8", errors="replace")

        # Decide execution mode
        if self._looks_like_pytest_test(test_text, test_file):
            runner = "pytest"
            cmd = [sys.executable, "-m", "pytest", str(test_file)]
        elif self._looks_like_relative_import_test(test_text):
            runner = "python-module"
            module = self._module_name_for_file(test_file)
            cmd = [sys.executable, "-m", module]
        else:
            runner = "python-file"
            cmd = [sys.executable, str(test_file)]

        try:
            cp = self._run(cmd)
        except subprocess.TimeoutExpired as e:
            return UnitTestEvalResult(
                scanned_file=str(scanned_file),
                test_file=str(test_file),
                runner=runner,
                passed=False,
                exit_code=124,
                stdout=(e.stdout or ""),
                stderr=(e.stderr or ""),
                notes=f"Timed out after {self.timeout_seconds}s running: {' '.join(cmd)}",
            )

        passed = (cp.returncode == 0)
        notes = "OK" if passed else f"Failed (exit={cp.returncode}). Command: {' '.join(cmd)}"

        return UnitTestEvalResult(
            scanned_file=str(scanned_file),
            test_file=str(test_file),
            runner=runner,
            passed=passed,
            exit_code=cp.returncode,
            stdout=cp.stdout or "",
            stderr=cp.stderr or "",
            notes=notes,
        )


if __name__ == "__main__":
    # Run only the unit test agent:
    #   python unit_test_evaluation_agent.py <repo_root> <scanned_file>
    #
    # Example:
    #   python unit_test_evaluation_agent.py . python_programs/breadth_first_search.py
    if len(sys.argv) < 3:
        print("Usage: python unit_test_evaluation_agent.py <repo_root> <scanned_file>")
        sys.exit(2)

    repo_root = sys.argv[1]
    scanned_file = sys.argv[2]

    agent = UnitTestEvaluationAgent(repo_root=repo_root, tests_dir="python_testcases", timeout_seconds=120)
    res = agent.evaluate(scanned_file)

    print(f"runner={res.runner}")
    print(f"test_file={res.test_file}")
    print(f"passed={res.passed} exit_code={res.exit_code}")
    if res.stdout:
        print("---- stdout ----")
        print(res.stdout)
    if res.stderr:
        print("---- stderr ----")
        print(res.stderr)

    sys.exit(0 if res.passed else 1)
