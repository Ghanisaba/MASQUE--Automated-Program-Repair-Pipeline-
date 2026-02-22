
from pathlib import Path
from openai import OpenAI
from bug_detection_agent import BugDetectionAgent

API_KEY = "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"
client = OpenAI(api_key=API_KEY)

if __name__ == "__main__":
    root = Path(__file__).resolve().parent.parent
    test_file = root / "python_programs" / "bitcount.py"

    print(f"Testing analyze_file on: {test_file}")

    agent = BugDetectionAgent(client=client)
    report = agent.analyze_file(test_file)

    print("=== Raw report type ===")
    print(type(report))

    print("=== Report keys ===")
    if isinstance(report, dict):
        print(report.keys())
    else:
        print(report)

    print("=== Full report ===")
    print(report)