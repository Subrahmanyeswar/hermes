#!/usr/bin/env python3
"""
HERMES Skill Engine — Classifier Evaluation Script
Tests the IntentClassifier on 100 diverse prompts.
Measures: true positive rate, false positive rate, and no-match rate.

Run: python tests/evaluate_classifier.py

Pass criteria:
  - True positive rate >= 85% (correct skill identified for relevant prompts)
  - False positive rate <= 10% (wrong skill loaded for unrelated prompts)
  - No crashes on any of the 100 prompts
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.intent_classifier import IntentClassifier

classifier = IntentClassifier("skills/")

# ── Test data ─────────────────────────────────────────────────────────
# Format: (prompt, expected_skill_id_or_None)
# None means "no skill should load" — classifier should return empty list

TEST_CASES = [
    # ── Should trigger flask-rest-api ──────────────────────────────────
    ("build a flask rest api with user authentication", "flask-rest-api"),
    ("create a flask app with crud endpoints for todos", "flask-rest-api"),
    ("I need a flask backend with sqlalchemy and jwt", "flask-rest-api"),
    ("build me a rest api server using flask", "flask-rest-api"),
    ("create flask api endpoints for user management", "flask-rest-api"),
    ("I want to build a web api with flask", "flask-rest-api"),
    ("make a flask backend with login and registration endpoints", "flask-rest-api"),
    ("create a rest api for my todo app using flask", "flask-rest-api"),
    ("build a flask crud api with sqlalchemy database", "flask-rest-api"),
    ("I need a flask api server with user authentication", "flask-rest-api"),

    # ── Should trigger debugging ────────────────────────────────────────
    ("I have an error in my python code please debug it", "debugging"),
    ("my app is broken and throwing a traceback", "debugging"),
    ("help me fix this exception in my code", "debugging"),
    ("this function is not working correctly", "debugging"),
    ("I am getting an AttributeError on line 42", "debugging"),
    ("my tests are failing with a TypeError", "debugging"),
    ("fix this bug in my login function", "debugging"),
    ("I have a crash in my application please help", "debugging"),
    ("my program is broken I need to debug it", "debugging"),
    ("there is an error in my flask route please fix it", "debugging"),

    # ── Should trigger pytest-generation ───────────────────────────────
    ("write pytest tests for my calculator module", "pytest-generation"),
    ("generate a unit test suite for this class", "pytest-generation"),
    ("create test cases for the user authentication module", "pytest-generation"),
    ("I need a test file for my flask routes", "pytest-generation"),
    ("write comprehensive tests with edge cases for my api", "pytest-generation"),
    ("generate pytest test coverage for this module", "pytest-generation"),
    ("create unit tests for the database models", "pytest-generation"),
    ("write a test suite for my helper functions", "pytest-generation"),
    ("I need test cases for my login endpoint", "pytest-generation"),
    ("generate pytest tests for the data processing module", "pytest-generation"),

    # ── Should return empty (no skill) ────────────────────────────────
    ("create a folder called myproject", None),
    ("list all files in the current directory", None),
    ("read the contents of config.yaml", None),
    ("what is the current directory structure", None),
    ("show me the contents of requirements.txt", None),
    ("create a new python file called main.py", None),
    ("move the file from src to dest", None),
    ("open the file hello.py", None),
    ("print the directory listing", None),
    ("search the web for python documentation", None),
    ("fetch the content of the python docs page", None),
    ("git commit the changes with message initial setup", None),
    ("initialise a git repository in the myproject folder", None),
    ("what files are in the tests directory", None),
    ("write hello world to a file", None),
    ("append a line to the log file", None),
    ("delete the temp folder", None),
    ("show me the project structure", None),
    ("create a requirements file with flask listed", None),
    ("make a folder structure for my project", None),

    # ── Negation — should return empty despite containing trigger words ─
    ("build a rest api but not using flask, use fastapi", None),
    ("I want tests but not pytest, use unittest instead", None),
    ("avoid using flask for this project", None),
    ("no flask please, I prefer django", None),
    ("skip the debugging step for now", None),
    ("I dont want to write tests right now", None),
    ("without flask, build a simple http server", None),
    ("instead of flask, use aiohttp", None),
    ("not a flask app, a django app please", None),
    ("never mind the tests, just write the code", None),

    # ── Ambiguous / edge cases ─────────────────────────────────────────
    ("flask", None),              # single word — below MIN_MATCHES
    ("error", None),              # single word — below MIN_MATCHES
    ("test", None),               # single word — below MIN_MATCHES
    ("", None),                   # empty string
    ("hello world", None),        # completely unrelated
    ("python script", None),      # generic, no skill match
    ("help me with my project", None),  # too vague
    ("I need assistance", None),        # too vague
    ("what should I do next", None),    # too vague
    ("please help me code something", None),  # too vague
]

def run_evaluation():
    total = len(TEST_CASES)
    true_positives = 0
    false_positives = 0
    true_negatives = 0
    false_negatives = 0
    errors = []

    print(f"Running {total} classifier evaluation tests...\n")

    for prompt, expected in TEST_CASES:
        try:
            result = classifier.classify(prompt)

            if expected is None:
                # We expect no skill to load
                if len(result) == 0:
                    true_negatives += 1
                else:
                    false_positives += 1
                    errors.append({
                        "type": "FALSE POSITIVE",
                        "prompt": prompt,
                        "expected": "[]",
                        "got": str(result)
                    })
            else:
                # We expect a specific skill to be in the result
                if expected in result:
                    true_positives += 1
                else:
                    false_negatives += 1
                    errors.append({
                        "type": "FALSE NEGATIVE",
                        "prompt": prompt,
                        "expected": expected,
                        "got": str(result)
                    })
        except Exception as e:
            errors.append({
                "type": "CRASH",
                "prompt": prompt,
                "expected": str(expected),
                "got": f"Exception: {e}"
            })

    # ── Compute metrics ───────────────────────────────────────────────
    relevant_prompts = sum(1 for _, e in TEST_CASES if e is not None)
    irrelevant_prompts = sum(1 for _, e in TEST_CASES if e is None)

    tp_rate = true_positives / relevant_prompts if relevant_prompts > 0 else 0
    fp_rate = false_positives / irrelevant_prompts if irrelevant_prompts > 0 else 0

    # ── Print report ──────────────────────────────────────────────────
    print("=" * 60)
    print("HERMES Classifier Evaluation Report")
    print("=" * 60)
    print(f"Total test cases:          {total}")
    print(f"Relevant prompts (expect skill):  {relevant_prompts}")
    print(f"Irrelevant prompts (expect []):   {irrelevant_prompts}")
    print()
    print(f"True Positives  (correct skill):  {true_positives}")
    print(f"True Negatives  (correct empty):  {true_negatives}")
    print(f"False Positives (wrong skill loaded): {false_positives}")
    print(f"False Negatives (skill missed):  {false_negatives}")
    print()
    print(f"True Positive Rate  (recall):  {tp_rate*100:.1f}%  (must be >= 85%)")
    print(f"False Positive Rate (precision): {fp_rate*100:.1f}%  (must be <= 10%)")
    print()

    if errors:
        print(f"FAILURES ({len(errors)} total):")
        for err in errors:
            print(f"  [{err['type']}]")
            print(f"    Prompt:   {err['prompt'][:70]!r}")
            print(f"    Expected: {err['expected']}")
            print(f"    Got:      {err['got']}")
        print()

    # ── Pass/Fail determination ───────────────────────────────────────
    passed = True
    fail_reasons = []

    if tp_rate < 0.85:
        passed = False
        fail_reasons.append(f"True positive rate {tp_rate*100:.1f}% is below 85% threshold")
    if fp_rate > 0.10:
        passed = False
        fail_reasons.append(f"False positive rate {fp_rate*100:.1f}% exceeds 10% threshold")
    crash_count = sum(1 for e in errors if e["type"] == "CRASH")
    if crash_count > 0:
        passed = False
        fail_reasons.append(f"Classifier crashed on {crash_count} prompts")

    print("=" * 60)
    if passed:
        print("RESULT: PASS — Classifier is ready for pipeline integration")
        print("Week 3 classifier gate: CLEARED")
    else:
        print("RESULT: FAIL — Fix the following before proceeding:")
        for reason in fail_reasons:
            print(f"  x {reason}")
        print()
        print("How to fix false negatives: Add more trigger keywords to the relevant SKILL.md")
        print("How to fix false positives: Increase MIN_MATCHES or add more specific triggers")
    print("=" * 60)

    return passed


if __name__ == "__main__":
    success = run_evaluation()
    sys.exit(0 if success else 1)
