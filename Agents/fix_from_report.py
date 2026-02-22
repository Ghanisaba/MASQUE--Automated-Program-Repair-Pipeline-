import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from openai import OpenAI
from bug_fix_agent import BugFixAgent


def extract_json_from_text(text: str) -> Optional[Dict[str, Any]]:
    """
    Handles model responses like ```json { ... } ``` and also extracts
    the first {...} object if there's extra text.
    """
    if not text:
        return None

    t = text.strip()

    # Remove ```json fences
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z]*\s*\n", "", t)
        t = re.sub(r"\n```$", "", t).strip()

    # Extract first JSON object
    start = t.find("{")
    end = t.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None

    candidate = t[start : end + 1]
    try:
        return json.loads(candidate)
    except Exception:
        return None


def normalize_bug_report(entry: Dict[str, Any]) -> Dict[str, Any]:
    """
    Prefer entry["bug_report"]. If it has an error (parse failed),
    try to recover JSON from raw_response_text.
    """
    bug_report = entry.get("bug_report") or {}
    if not isinstance(bug_report, dict):
        return {}

    # If parsing failed earlier, recover from raw_response_text
    if bug_report.get("error") and bug_report.get("raw_response_text"):
        recovered = extract_json_from_text(bug_report["raw_response_text"])
        if isinstance(recovered, dict):
            # carry over code excerpt (helpful) if present
            if bug_report.get("code_excerpt") and not recovered.get("code_excerpt"):
                recovered["code_excerpt"] = bug_report["code_excerpt"]
            return recovered

    return bug_report


def main():
    # ✅ CHANGE THESE PATHS IF NEEDED
    report_path = Path("bug_detection_with_supervision.json")  # same file your runner writes :contentReference[oaicite:2]{index=2}

    # ⚠️ IMPORTANT: use env var in real usage; this mirrors your current runner style :contentReference[oaicite:3]{index=3}
    API_KEY = "PUT_YOUR_KEY_HERE"
    client = OpenAI(api_key=API_KEY)

    FIX_MODEL = "gpt-4.1"
    fix_agent = BugFixAgent(client=client, model=FIX_MODEL)

    if not report_path.exists():
        raise FileNotFoundError(f"Report not found: {report_path.resolve()}")

    entries: List[Dict[str, Any]] = json.loads(report_path.read_text(encoding="utf-8"))
    if not isinstance(entries, list):
        raise ValueError("Report JSON is not a list")

    updated = 0

    for i, entry in enumerate(entries):
        bug_report = normalize_bug_report(entry)
        if not bug_report:
            entry["fix_result"] = {"status": "skipped", "reason": "Invalid bug_report structure"}
            continue

        # Only fix if has_bug true
        if bug_report.get("has_bug") is not True:
            entry["fix_result"] = {"status": "skipped", "reason": "has_bug is not true"}
            continue

        print(f"[FixFromReport] Fixing: {bug_report.get('file')}")

        fix_result = fix_agent.fix_bug(bug_report, dry_run=False)
        entry["fix_result"] = fix_result
        updated += 1

    # Write back updated report
    report_path.write_text(json.dumps(entries, indent=2), encoding="utf-8")
    print(f"✅ Done. Attempted fixes for {updated} bugs.")
    print(f"✅ Updated report saved to: {report_path.resolve()}")


if __name__ == "__main__":
    main()
