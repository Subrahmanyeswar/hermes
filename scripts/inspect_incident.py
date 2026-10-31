import sys, os, sqlite3
sys.path.insert(0, os.path.abspath("."))
from pathlib import Path
from core.persistence.database import get_canonical_database_path
from core.verification_profiles import classify_verification_profile, VerificationProfileEvaluator
from core.agent_loop.completion import CompletionPolicy
from core.workspace import WorkspaceManager

conn = sqlite3.connect(str(get_canonical_database_path()))
cur = conn.cursor()
cur.execute("SELECT prompt FROM missions WHERE mission_id = 'm_30ebfbeb'")
prompt = cur.fetchone()[0]

prof = classify_verification_profile(prompt)
print(f"Classified Profile: {prof}")

ws_path = Path(r"C:\Users\SUBBU\Downloads\rocket4 hermes test")
res = VerificationProfileEvaluator.evaluate(prof, ws_path, prompt)
print(f"VerificationProfileEvaluator result:")
print(f"  Passed: {res.passed}")
print(f"  Issues: {res.issues}")
print(f"  Summary: {res.summary}")

wm = WorkspaceManager()
wm.lock(str(ws_path))
policy = CompletionPolicy()
accepted, reason, issues = policy.evaluate_completion(
    mission_prompt=prompt,
    workspace=wm,
    written_files=["index.html"],
)
print(f"\nCompletionPolicy result:")
print(f"  Accepted: {accepted}")
print(f"  Reason: {reason}")
print(f"  Issues: {issues}")
