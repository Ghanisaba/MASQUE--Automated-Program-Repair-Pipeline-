import re
import subprocess
from dataclasses import dataclass
from typing import Optional, List


@dataclass
class GitPushResult:
    status: str                 # "SUCCESS" | "FAIL" | "SKIPPED"
    branch_name: Optional[str] = None
    commit_sha: Optional[str] = None
    error: Optional[str] = None


class GitPushAgent:
    """
    MASQUE Git Integration Agent (Push branch only).
    Trigger: ONLY after unit tests pass.
    Actions: create branch -> stage -> commit -> push to remote.
    """

    def __init__(self, repo_path: str, remote_name: str = "origin", base_branch: str = "master"):
        self.repo_path = repo_path
        self.remote_name = remote_name
        self.base_branch = base_branch

    def _run(self, cmd: List[str]) -> str:
        p = subprocess.run(cmd, cwd=self.repo_path, capture_output=True, text=True)
        if p.returncode != 0:
            raise RuntimeError(
                f"Command failed: {' '.join(cmd)}\n"
                f"STDOUT:\n{p.stdout.strip()}\n"
                f"STDERR:\n{p.stderr.strip()}"
            )
        return p.stdout.strip()

    def _safe_branch(self, bug_id: str) -> str:
        safe = re.sub(r"[^a-zA-Z0-9._-]+", "-", bug_id).strip("-").lower()
        return f"masque/fix-{safe or 'unknown'}"

    def push_branch(self, bug_id: str, commit_message: str) -> GitPushResult:
        try:
            # Ensure we're in a git repo
            self._run(["git", "rev-parse", "--is-inside-work-tree"])

            branch = self._safe_branch(bug_id)

            # Checkout base branch
            self._run(["git", "checkout", self.base_branch])

            # Create & switch to branch (if already exists locally, just checkout)
            try:
                self._run(["git", "checkout", "-b", branch])
            except RuntimeError:
                self._run(["git", "checkout", branch])

            # Stage everything changed by the patch
            self._run(["git", "add", "-A"])

            # If nothing to commit, skip
            status = self._run(["git", "status", "--porcelain"])
            if not status.strip():
                return GitPushResult(status="SKIPPED", error="No changes detected to commit.")

            # Commit
            self._run(["git", "commit", "-m", commit_message])

            sha = self._run(["git", "rev-parse", "HEAD"])

            # Push branch to remote
            self._run(["git", "push", "-u", self.remote_name, branch])

            return GitPushResult(status="SUCCESS", branch_name=branch, commit_sha=sha)

        except Exception as e:
            return GitPushResult(status="FAIL", error=str(e))
