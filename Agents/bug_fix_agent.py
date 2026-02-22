# bug_fix_agent.py
import json
import re
import shutil
import hashlib
from pathlib import Path
from typing import Dict, Any, List, Optional

from openai import OpenAI


def _clean_json(text: str) -> str:
    t = (text or "").strip()

    # Strip ```json ... ``` fences
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z]*\s*\n", "", t)
        t = re.sub(r"\n```$", "", t).strip()

    # Extract first JSON object if extra text exists
    start = t.find("{")
    end = t.rfind("}")
    if start != -1 and end != -1 and end > start:
        return t[start:end + 1]

    return t


def _sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8", errors="ignore")).hexdigest()


def _strip_code_fences(text: str) -> str:
    t = (text or "").strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z]*\s*\n", "", t)
        t = re.sub(r"\n```$", "", t).strip()
    return t


class BugFixAgent:
    """
    Generates a fix for a bug report and updates the file on disk.
    Reliable approach:
      - Ask model for both unified diff AND full fixed code
      - Always verify file content changed
      - Write fixed_code directly (with .bak backup)
    """

    def __init__(self, client: OpenAI, model: str = "gpt-4.1"):
        self.client = client
        self.model = model

    def fix_bug(self, bug_report: Dict[str, Any], *, dry_run: bool = False) -> Dict[str, Any]:
        file_path = bug_report.get("file_path")
        if not file_path:
            return {"status": "error", "error": "bug_report missing file_path", "bug_report": bug_report}

        target = Path(file_path)
        if not target.exists():
            return {"status": "error", "error": f"file_path does not exist: {file_path}", "bug_report": bug_report}

        original_code = target.read_text(encoding="utf-8", errors="ignore")
        original_hash = _sha256(original_code)

        has_bug = bool(bug_report.get("has_bug", False))
        if not has_bug:
            return {"status": "skipped", "reason": "has_bug=false in bug_report", "file_path": str(target)}

        system_prompt = (
            "You are an automated program repair agent for Python. "
            "Given a Python file and a bug report, produce a minimal correct fix. "
            "Return STRICT JSON only (no markdown)."
        )

        user_prompt = (
            "Return JSON with this schema:\n"
            "{\n"
            '  "file_path": "<same file_path>",\n'
            '  "summary": "what you changed",\n'
            '  "confidence": 0.0-1.0,\n'
            '  "patch_unified_diff": "a unified diff string (best-effort)",\n'
            '  "fixed_code": "the FULL updated Python file content",\n'
            '  "notes": ["caveats"]\n'
            "}\n\n"
            "Rules:\n"
            "- fixed_code MUST be the full file, not a snippet.\n"
            "- Keep changes minimal.\n"
            "- Ensure the BFS handles empty queue and visited correctly.\n\n"
            "=== BUG REPORT ===\n"
            f"{json.dumps(bug_report, indent=2)}\n\n"
            "=== ORIGINAL FILE CONTENT ===\n"
            "```text\n"
            f"{original_code}\n"
            "```\n"
        )

        fallback = {
            "file_path": str(target),
            "summary": "",
            "confidence": 0.0,
            "patch_unified_diff": "",
            "fixed_code": "",
            "notes": ["fallback response used"],
        }

        try:
            resp = self.client.responses.create(
                model=self.model,
                input=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )

            try:
                text = resp.output[0].content[0].text
            except Exception:
                text = getattr(resp, "output_text", None) or str(resp)

            try:
                cleaned = _clean_json(text)
                fix_plan = json.loads(cleaned)
            except Exception as e:
                return {
                    "status": "error",
                    "error": f"Could not parse JSON from model: {str(e)}",
                    "file_path": str(target),
                    "raw_response_text": text,
                }

        except Exception as e:
            return {"status": "error", "error": f"OpenAI API call failed: {str(e)}", "file_path": str(target)}

        fixed_code = _strip_code_fences((fix_plan or {}).get("fixed_code", "") or "")
        if not fixed_code.strip():
            return {"status": "no_fixed_code", "file_path": str(target), "fix_plan": fix_plan}

        fixed_hash = _sha256(fixed_code)

        if fixed_hash == original_hash:
            return {
                "status": "no_change",
                "reason": "Model returned identical file content",
                "file_path": str(target),
                "fix_plan": fix_plan,
            }

        if dry_run:
            return {
                "status": "dry_run",
                "file_path": str(target),
                "before_hash": original_hash,
                "after_hash": fixed_hash,
                "fix_plan": fix_plan,
            }

        backup_path = target.with_suffix(target.suffix + ".bak")
        shutil.copyfile(target, backup_path)

        target.write_text(fixed_code, encoding="utf-8")

        # Verify on disk actually changed
        on_disk = target.read_text(encoding="utf-8", errors="ignore")
        on_disk_hash = _sha256(on_disk)
        if on_disk_hash == original_hash:
            # rollback
            shutil.copyfile(backup_path, target)
            return {
                "status": "write_failed",
                "error": "File did not change after write; rolled back",
                "file_path": str(target),
                "backup_path": str(backup_path),
                "fix_plan": fix_plan,
            }

        return {
            "status": "patched",
            "file_path": str(target),
            "backup_path": str(backup_path),
            "before_hash": original_hash,
            "after_hash": on_disk_hash,
            "fix_plan": fix_plan,
        }
