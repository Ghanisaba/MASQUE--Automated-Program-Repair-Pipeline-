# agents/bug_detection_agent.py

import os
from pathlib import Path
from typing import List, Dict, Any
import json
from openai import OpenAI


class BugDetectionAgent:
    """
    Minimal test version: just returns a dummy dict so we can confirm wiring.
    """

    def __init__(self, client: OpenAI, model: str = "gpt-4.1-mini"):
        self.client = client
        self.model = model

    def scan_repo(self, repo_path: str) -> List[Dict[str, Any]]:
        """
        Walk the repo, analyze .py files, and return a list of dummy bug reports.
        """
        repo = Path(repo_path)
        if not repo.exists():
            raise ValueError(f"Repo path does not exist: {repo_path}")

        bug_reports: List[Dict[str, Any]] = []
        for root, _, files in os.walk(repo):
            for fname in files:
                if fname.endswith(".py"):
                    file_path = Path(root) / fname
                    print(f"[BugDetectionAgent] Analyzing {file_path}")
                    report = self.analyze_file(file_path)
                    bug_reports.append(report)
        return bug_reports

    def analyze_file(self, file_path: Path) -> Dict[str, Any]:
        """
        Send a single file to the model and ask for a structured JSON bug description.
        Always returns a dict (never None).
        """
        print(f"[BugDetectionAgent] inside analyze_file for {file_path}")
        code = file_path.read_text(encoding="utf-8", errors="ignore")

        # Optional truncation for very large files
        MAX_CHARS = 8000
        if len(code) > MAX_CHARS:
            code_for_model = code[:MAX_CHARS] + "\n\n# [Truncated for analysis]\n"
        else:
            code_for_model = code

        system_prompt = (
            "You are a software analysis agent. "
            "Your job is to read the given source code and identify concrete bugs "
            "(logic errors, off-by-one mistakes, unhandled edge cases, etc.). "
            "Ignore formatting and style. Respond strictly in JSON."
        )

        # Build user prompt without triple-quoted strings to avoid syntax issues
        user_prompt = (
            "You are given the following source code:\n\n"
            "```text\n"
            f"{code_for_model}\n"
            "```\n\n"
            "Return JSON in the following schema:\n"
            "{\n"
            f'  "file": "{file_path.name}",\n'
            f'  "file_path": "{str(file_path)}",\n'
            '  "has_bug": true or false,\n'
            '  "bug_summary": "short description or empty string if no bugs",\n'
            '  "bug_details": [\n'
            '    {\n'
            '      "line": number or null,\n'
            '      "explanation": "what the bug is and why it is a bug"\n'
            '    }\n'
            '  ]\n'
            "}\n"
        )

        # Default fallback report
        fallback_report: Dict[str, Any] = {
            "file": file_path.name,
            "file_path": str(file_path),
            "has_bug": False,
            "bug_summary": "",
            "bug_details": [],
        }

        try:
            print("[BugDetectionAgent] Calling OpenAI...")
            response = self.client.responses.create(
                model=self.model,
                input=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )
            print("[BugDetectionAgent] OpenAI call succeeded")

            text = None
            # Try new Responses API layout
            try:
                text = response.output[0].content[0].text
                print("[BugDetectionAgent] Extracted text from response.output[0].content[0].text")
            except Exception as inner_e:
                print("[BugDetectionAgent] Failed output[0].content[0].text:", inner_e)
                text = getattr(response, "output_text", None)
                if text is not None:
                    print("[BugDetectionAgent] Using response.output_text")

            if text is None:
                print("[BugDetectionAgent] Falling back to str(response)")
                text = str(response)

            try:
                report = json.loads(text)
                print("[BugDetectionAgent] JSON parsed successfully")
            except Exception as e:
                print("[BugDetectionAgent] JSON parsing failed:", e)
                print("[BugDetectionAgent] Model text was:", text)
                report = {
                    **fallback_report,
                    "error": f"Could not parse JSON from model: {str(e)}",
                    "raw_response_text": text,
                }

        except Exception as e:
            print("[BugDetectionAgent] OpenAI call failed:", e)
            report = {
                **fallback_report,
                "error": f"OpenAI API call failed: {str(e)}",
            }

        # Always normalize the shape
        report.setdefault("code_excerpt", code[:1000])
        report.setdefault("file", file_path.name)
        report.setdefault("file_path", str(file_path))
        report.setdefault("has_bug", False)
        report.setdefault("bug_summary", "")
        report.setdefault("bug_details", [])

        print(f"[BugDetectionAgent] Done for {file_path}, has_bug={report.get('has_bug')}")
        return report

