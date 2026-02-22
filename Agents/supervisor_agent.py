# supervisor_agent.py
import json
import re
from typing import Dict, Any
from openai import OpenAI


def _extract_json(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z]*\s*\n", "", t)
        t = re.sub(r"\n```$", "", t).strip()

    start = t.find("{")
    end = t.rfind("}")
    if start != -1 and end != -1 and end > start:
        return t[start:end+1]
    return t


class SupervisorAgent:
    def __init__(self, client: OpenAI, model: str = "gpt-4.1"):
        self.client = client
        self.model = model

    def review_report(self, bug_report: Dict[str, Any]) -> Dict[str, Any]:
        file_name = bug_report.get("file")
        file_path = bug_report.get("file_path")
        code_excerpt = bug_report.get("code_excerpt", "")
        has_bug = bug_report.get("has_bug")
        bug_summary = bug_report.get("bug_summary", "")
        bug_details = bug_report.get("bug_details", [])

        system_prompt = (
            "You are a senior code review supervisor. "
            "Verify whether the AI bug report is correct. "
            "Respond STRICTLY as JSON (no markdown)."
        )

        user_prompt = (
            "Review the bug report for correctness.\n\n"
            f"File: {file_name}\n"
            f"Path: {file_path}\n\n"
            "=== CODE EXCERPT ===\n"
            f"{code_excerpt}\n\n"
            "=== BUG REPORT ===\n"
            f"{json.dumps({'has_bug': has_bug, 'bug_summary': bug_summary, 'bug_details': bug_details}, indent=2)}\n\n"
            "Return JSON schema:\n"
            "{\n"
            '  "confirmed_bug": true/false,\n'
            '  "corrected_has_bug": true/false,\n'
            '  "corrected_bug_summary": "string",\n'
            '  "corrected_bug_details": [{"line": number|null, "explanation": "string"}],\n'
            '  "notes": ["string"]\n'
            "}\n"
        )

        fallback = {
            "confirmed_bug": False,
            "corrected_has_bug": bool(has_bug),
            "corrected_bug_summary": bug_summary or "",
            "corrected_bug_details": bug_details or [],
            "notes": ["fallback supervisor response (parse failure or API failure)"],
        }

        try:
            resp = self.client.responses.create(
                model=self.model,
                input=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )

            text = None
            try:
                text = resp.output[0].content[0].text
            except Exception:
                text = getattr(resp, "output_text", None) or str(resp)

            cleaned = _extract_json(text)
            return json.loads(cleaned)

        except Exception as e:
            fallback["notes"].append(f"Supervisor error: {str(e)}")
            return fallback
