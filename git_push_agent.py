# Agents/git_push_agent.py

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import List, Optional


class GitPushAgent:
    """
    Handles Git operations for MASQUE:
      - checkout base branch (auto-detected)
      - create or checkout branch
      - stage selected files
      - commit (no-op if nothing staged)
      - push to origin
    """

    def __init__(self, repo_root: Path) -> None:
        self.repo_root = Path(repo_root).resolve()

    def _run(self, cmd: List[str]) -> str:
        p = subprocess.run(
            cmd,
            cwd=str(self.repo_root),
            capture_output=True,
            text=True,
        )
        if p.returncode != 0:
            raise subprocess.CalledProcessError(
                p.returncode, cmd, output=p.stdout, stderr=p.stderr
            )
        return (p.stdout or "").strip()

    def _detect_base_branch(self) -> str:
        # Best case: origin/HEAD points to default branch
        try:
            ref = self._run(["git", "symbolic-ref", "refs/remotes/origin/HEAD"])
            # e.g. refs/remotes/origin/master -> master
            return ref.split("/")[-1]
        except Exception:
            pass

        # Fallback: common names
        for b in ("main", "master"):
            try:
                self._run(["git", "rev-parse", "--verify", b])
                return b
            except Exception:
                continue

        raise RuntimeError("Could not detect base branch (tried origin/HEAD, main, master).")

    def create_branch(self, branch_name: str, base_branch: Optional[str] = None) -> None:
        if base_branch is None:
            base_branch = self._detect_base_branch()

        # Checkout base branch
        self._run(["git", "checkout", base_branch])

        # Create new branch; if it already exists locally, checkout
        try:
            self._run(["git", "checkout", "-b", branch_name])
        except subprocess.CalledProcessError:
            self._run(["git", "checkout", branch_name])

    def stage_files(self, files: List[str]) -> None:
        if not files:
            raise ValueError("No files provided to stage.")
        self._run(["git", "add", "--"] + files)

    def _has_staged_changes(self) -> bool:
        out = self._run(["git", "diff", "--cached", "--name-only"])
        return bool(out.strip())

    def commit(self, message: str) -> None:
        if not self._has_staged_changes():
            return  # nothing staged -> no-op
        self._run(["git", "commit", "-m", message])

    def push(self, branch_name: str) -> None:
        self._run(["git", "push", "-u", "origin", branch_name])
