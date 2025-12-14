# MASQUE--Automated-Program-Repair-Pipeline
# quixbugs-agentic-apr

An agentic Automated Program Repair (APR) pipeline for Python programs (tested on QuixBugs).
It detects bugs, optionally supervises/validates them, and can apply fixes back to the original files.

## What it does

Pipeline stages:

1. **BugDetectionAgent**  
   Scans Python files and produces a structured bug report (JSON).

2. **SupervisorAgent** (optional but supported)  
   Reviews the bug report and confirms whether the bug is real.

3. **BugFixAgent**  
   Generates a fix and updates the same file on disk (creates a `.bak` backup).

4. **Runner**  
   Orchestrates the pipeline, writes a report, and prompts you before applying fixes.

Output:
- `bug_detection_with_supervision.json` (detection + review + fix results)
- `.bak` backup files for any patched source file

---

# How to run

cd QuixBugs

# Install dependencies (once)
pip install openai

# Set API key (PowerShell example)
$env:OPENAI_API_KEY="sk-...."

# Run on default: python_programs/
python agents/run_bug_supervision.py

# Or run on Java buggy programs:
python run_bug_supervision.py java_programs

Run the pipeline: py agents/run_bug_supervision.py

