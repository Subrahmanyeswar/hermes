# HERMES Demo Script — 10-Minute Viva Demo

Rehearse this script minimum 5 times. Time each section with a stopwatch.
Total target: 10 minutes. Hard stop at 10:30.

---

## Pre-Demo Checklist (do this 30 minutes before)

- [ ] Ollama running: `ollama serve` (if not already running as service)
- [ ] Models pulled: `ollama list` → must show qwen2.5-coder:7b AND mistral:7b-instruct
- [ ] Both models warm: run `python main.py info` — check "running" shows True
- [ ] Terminal: font size 14+, window at least 120×45
- [ ] .env file present with ANTHROPIC_API_KEY set (for T3 escalation demo)
- [ ] Battery: 80%+ or charger plugged in
- [ ] Close all other applications to avoid VRAM pressure
- [ ] generated_projects/ directory exists and is empty (clean start)

---

## Section 1 — System Overview (1 minute)

**Say:** "HERMES is a local-first agentic coding framework. It takes natural language requests
and executes them through a 12-stage pipeline using two free local models — Qwen2.5-Coder
and Mistral 7B — with selective escalation to Claude Sonnet only when they disagree.
Let me show you."

**Show:** `python main.py info`

Point out:
- Both models show as available (T1: Qwen, T2: Mistral)
- 12 skills loaded
- Current API cost: $0.000 (nothing spent yet)
- KAIROS: idle

**Target: 60 seconds**

---

## Section 2 — Launch TUI (30 seconds)

```bash
python main.py ui
```

**Say:** "This is the terminal interface. Chat panel on the left where you type requests.
On the right: Tool Trace, Memory View, and Task Queue — all update in real time.
Status bar at the top shows the current mode, active skill, and API cost."

**Point out:** Status bar shows [AUTO] in green, "Ready", $0.000

**Target: 30 seconds**

---

## Section 3 — Basic Task: File Operation (1 minute)

**Type in TUI:**
List all files and folders in the current directory

**While it runs, say:** "Tier 1 is generating a structured JSON tool call.
Tier 2 is now verifying it. They agree — local resolution, no API cost."

**After response:**
- Point to Tool Trace tab: shows list_directory, ✓, latency, trace_id
- Point to Status bar: cost still $0.000

**Say:** "Zero API cost. Both local models agreed. This is what local resolution looks like."

**Target: 60 seconds**

---

## Section 4 — Skill Injection Demo (2 minutes)

**Type in TUI:**
Create a Flask REST API at generated_projects/flask_demo.py with a /users endpoint
that returns a list of users from a SQLite database

**While it runs, say:** "The intent classifier detected 'Flask' and 'REST API' — 
it loaded the flask-rest-api SKILL.md. Watch the status bar — it should show 
Skill: flask-rest-api."

**After response:**
- Point to status bar: shows `[Skill: flask-rest-api]`
- Point to Tool Trace: shows write_file with the generated code
- Point to Memory tab: may show a new fact if memory was written

**Say:** "The skill file injects 15 Flask-specific workflow rules into the context.
Our ablation study showed this gives an 18 percentage point accuracy lift on
domain-specific tasks. Without the skill, the model often misses things like 
proper error handling and response format."

**Target: 2 minutes**

---

## Section 5 — Disagreement Routing Demo (2 minutes)

**Explanation while waiting:** "Now let me show you what happens when the models disagree.
The disagreement router is the core of the Speculative Disagreement Routing algorithm."

**Type in TUI:**
Push the current changes to GitHub on branch main

**Say:** "git_push is in the always-escalate list — high-risk, irreversible action.
Regardless of T1/T2 confidence, this escalates to Tier 3. Watch the [T3] marker
appear in the Tool Trace, and the cost update."

**After response:**
- Point to Tool Trace: shows [T3 called] marker
- Point to Status bar: cost has increased

**Say:** "This is the only time money gets spent — when the action is genuinely risky
or when the two local models disagree. In our benchmark, 78% of tasks resolved
locally at zero cost."

*If T3 does not escalate (git repo not configured), explain:*
**Say:** "In a real project with a configured remote, this would escalate. The system
correctly identifies high-risk operations."

**Target: 2 minutes**

---

## Section 6 — Screenshot-to-Code WOW Feature (2 minutes)

**Type in TUI:**
/screenshot tests/screenshots/test_login_form.png html

**Say:** "This is the vision feature — screenshot to code. It sends the image to
Qwen2.5-Coder's multimodal endpoint. This will take 30-60 seconds — vision inference
is slow on a 6GB GPU."

**While waiting (30-60 seconds), say:**
"The model analyses the layout, extracts colours, identifies UI components —
buttons, inputs, labels — and generates matching HTML with Tailwind CSS.
This runs entirely locally on the RTX 3050. No cloud vision API."

**After response:**
- Show the generated HTML file: `cat generated_projects/screenshot_*.html | head -30`

**Say:** "Complete HTML with Tailwind CSS. The model matched the login form layout,
extracted the dark colour scheme, and reproduced the button styling.
This runs at zero API cost."

**Target: 2 minutes (including wait)**

---

## Section 7 — Export and Close (30 seconds)

**Type in TUI:**
/export generated_projects

**Say:** "One command to package the entire project as a ZIP archive for sharing."

**After response:** Show the ZIP was created in generated_projects/.

**Press Ctrl+Q to exit.**

**Say:** "The TUI exits cleanly, KAIROS daemon shuts down, all session logs preserved."

**Target: 30 seconds**

---

## Section 8 — Benchmark Results (1 minute)

**Switch to terminal (outside TUI):**

```bash
python benchmarks/compute_metrics.py --results-file benchmarks/results.json 2>/dev/null | head -40
```

Or if results not yet available:
```bash
cat benchmarks/metrics.json | python -c "
import json,sys
m = json.load(sys.stdin)
h = m['m1_task_completion_rate']['hermes']['overall']
l = m['m2_tier3_escalation']['local_resolution_rate']
lift = m['m3_skill_accuracy_lift']['skill_accuracy_lift']
cost = m['m5_api_cost']['hermes_actual_cost_usd']
print(f'Completion: {h*100:.1f}%  Local: {l*100:.1f}%  Skill lift: +{lift*100:.1f}pp  Cost: \${cost:.3f}')
"
```

**Say:** "78% completion rate. 78% of tasks ran locally at zero cost. 18 percentage
point skill accuracy lift. Total API spend across 50 tasks: $0.33.
Estimated all-Claude equivalent: $4.50. 92.7% cost reduction."

**Target: 60 seconds**

---

## TOTAL TARGET: 10 minutes

| Section | Target |
|---------|--------|
| 1. System overview | 1:00 |
| 2. Launch TUI | 0:30 |
| 3. Basic file task | 1:00 |
| 4. Skill injection | 2:00 |
| 5. Disagreement routing | 2:00 |
| 6. Screenshot-to-code | 2:00 |
| 7. Export and close | 0:30 |
| 8. Benchmark results | 1:00 |
| **TOTAL** | **10:00** |

---

## Timing Log (fill in during each rehearsal)

| Run | Date | Sec 1 | Sec 2 | Sec 3 | Sec 4 | Sec 5 | Sec 6 | Sec 7 | Sec 8 | Total |
|-----|------|-------|-------|-------|-------|-------|-------|-------|-------|-------|
| 1 | | | | | | | | | | |
| 2 | | | | | | | | | | |
| 3 | | | | | | | | | | |
| 4 | | | | | | | | | | |
| 5 | | | | | | | | | | |

---

# VIVA Q&A Preparation — 8 Questions

Rehearse each answer out loud. Aim for 60-90 seconds per answer.
Do not memorise — understand.

---

## Q1: Why did you use two different model families for verification?

**Key points to cover:**
- Models from the same training family (e.g., two Qwen models) share failure modes — they make the same mistakes because they learned from similar data
- Cross-family verification (Qwen/Alibaba + Mistral/Mistral AI) exploits different training distributions and architectures
- When both agree despite different biases, the probability of a correlated error is lower
- This is analogous to ensemble methods in ML but applied to agentic tool verification
- The alternative (single-model self-consistency) has been shown to be less reliable for factual claims

**One-sentence summary:** Two models from different companies, different architectures, and different training data — when they agree, their agreement is more meaningful than a single model's confidence.

---

## Q2: How does the confidence threshold calibration work?

**Key points to cover:**
- We tested 5 threshold values (0.60, 0.70, 0.72, 0.80, 0.90) on 50 synthetic verification scenarios
- Each scenario has a known ground truth (correct/incorrect)
- For each threshold, we measure: false escalation rate (correct answers unnecessarily escalated) and missed error rate (wrong answers accepted)
- F1 score = harmonic mean of (1 - FER) and (1 - MER) — balances cost efficiency vs safety
- The threshold maximising F1 was selected
- Limitation: calibration used synthetic scenarios, not real Tier 2 outputs — future work should use a held-out validation set

**One-sentence summary:** We framed threshold selection as a binary classification problem and optimised the F1 score across 5 candidate values.

---

## Q3: What are the limitations of your approach?

**Key points to cover (be honest — examiners respect intellectual honesty):**
- The 50-task benchmark is small by NLP evaluation standards — results may not generalise
- Calibration used synthetic scenarios — real-world calibration would be more rigorous
- Sequential model execution (6GB VRAM constraint) adds T2 latency to every request
- Skill accuracy lift is confounded — domain tasks are harder so the baseline is lower
- The three-layer memory system doesn't scale to very large codebases
- Local model quality ceiling — for L4/L5 tasks, 7B models sometimes produce incorrect code even with skills

**One-sentence summary:** The system is designed for the 6GB VRAM constraint and that constraint limits both throughput and quality ceiling.

---

## Q4: How does the memory system work?

**Key points to cover:**
- Three layers: Layer 1 (MEMORY.md — always in context), Layer 2 (topic files — loaded on demand via [DETAIL] pointers), Layer 3 (JSONL session logs — searchable but never re-read into context)
- Facts follow a state machine: PROPOSED → CONFIRMED (requires tool exit_code=0) → PERSISTED
- Only confirmed facts (from successful tool executions) get written to MEMORY.md
- Memory extraction uses Tier 1 to identify fact-worthy content from conversation history
- KAIROS consolidation runs when the Triple-Gate passes: 60+ minutes, 3+ completed tasks, no lock file held
- Consolidation deduplicates facts and marks stale entries with [STALE] prefix

**One-sentence summary:** Three layers of increasing detail, with a state machine that only writes facts after tool execution success.

---

## Q5: How does the skill system prevent false activations?

**Key points to cover:**
- Word-boundary regex matching (not substring matching) — prevents "flash" from triggering "flask"
- Minimum 2 distinct trigger matches required — single-keyword activation is blocked
- Negation detection: 5-word window before each trigger checks for "not", "no", "without", "avoid", "don't use"
- If user says "I'm not using Flask, I'm using Django" — Flask skill does not activate
- Maximum 2 skills simultaneously — prevents context window saturation
- Skills are sorted by priority — if both flask and database activate, higher-priority skill gets primary position

**One-sentence summary:** Word boundaries, a 2-match minimum, and negation detection make false activation rate low in practice.

---

## Q6: Why didn't you use RAG or vector search for skills and memory?

**Key points to cover:**
- RAG requires embedding inference — adds latency, another model, and VRAM pressure
- On 6GB VRAM, running an embedding model alongside Qwen and Mistral is not feasible without significant complexity
- The intent classifier achieves sub-millisecond classification with zero VRAM
- For the 12-skill domain we're targeting, keyword matching has high precision — the skills are designed around distinct vocabularies
- For memory retrieval, the three-layer architecture keeps the frequently-accessed facts (Layer 1) always in context without retrieval overhead
- Future work: Layer 2 could use ChromaDB with a smaller embedding model for large codebases

**One-sentence summary:** Given the 6GB VRAM constraint, a zero-cost keyword classifier was the right trade-off — RAG's accuracy advantage doesn't justify the hardware cost at this scale.

---

## Q7: How do you ensure the system never produces harmful actions?

**Key points to cover:**
- 15 security gates run on every shell command before execution
- Gates check for: rm -rf wildcards, path traversal (../), protected paths (~/.ssh, /etc), sudo, curl | bash pipe patterns, fork bombs, base64 execution, crontab modification, force git push, etc.
- The PermissionGate blocks entire tool categories per mode: Safe mode blocks all writes; Plan mode shows the tool call before execution
- git_push and delete_file are always-escalate tools — they go to Tier 3 regardless of T1/T2 agreement
- The hard block threshold (risk_score ≥ 0.9) requires explicit user confirmation regardless of routing
- Token masking: GITHUB_TOKEN value is never logged anywhere in the system

**One-sentence summary:** Defence in depth — mode-based permission gates, content-based security gates, risk-score-based routing gates, and explicit confirmation for destructive operations.

---

## Q8: What would you build next if you had more time?

**Key points to cover (show vision, not wishful thinking):**
- **Semantic memory**: Replace the keyword MEMORY.md with ChromaDB vector storage — would scale to large codebases where keyword search degrades
- **Larger Tier 1**: Qwen2.5-Coder 14B on 12GB VRAM would dramatically improve L4/L5 task completion — the quality ceiling is the current bottleneck
- **Online threshold calibration**: Continuously update the confidence threshold based on observed tool success rates, instead of the static calibrated value
- **Multi-file awareness**: Currently generates one file per request — a file graph model would enable cross-file refactoring
- **Actual benchmark expansion**: 50 tasks is small — 500 tasks across 10 domains would give publication-quality statistical significance

**One-sentence summary:** The most impactful next step is semantic memory retrieval, which would remove the practical ceiling on project size.

---

## Final Submission Checklist

Run these commands on the day of submission in order:

```bash
# 1. Run the submission readiness check
python tests/test_submission_ready.py

# 2. Run all unit tests one final time
pytest tests/ --ignore=tests/integration/ -q --timeout=120

# 3. Verify no secrets in git
git log -p --all | grep -E "sk-ant-|ghp_" | head -5
# Must return nothing

# 4. Verify data/ and .env are ignored
git status  # Must NOT show data/ or .env as staged/tracked

# 5. Pin requirements
pip freeze > requirements.txt

# 6. Final commit
git add README.md requirements.txt DEMO_SCRIPT.md
git status  # Review everything one more time
git commit -m "Week 20 complete: README, requirements pinned, demo script, submission ready"

# 7. Push to GitHub
git push origin main

# 8. Verify on GitHub that:
#    - .env is NOT in the repository
#    - data/ contents are NOT in the repository (except safe benchmark files)
#    - The README renders correctly
#    - No API keys visible anywhere

# 9. Submit the repository URL
```

---

## Demo Day Mental Checklist

**30 minutes before:**
- [ ] `ollama serve` running
- [ ] `ollama list` shows both models
- [ ] `python main.py info` shows both models available
- [ ] Terminal at correct size (120×45 minimum)
- [ ] Font size 14+
- [ ] Browser tab open to GitHub repo (in case they ask for the URL)
- [ ] Benchmark metrics printed and in hand

**During the demo:**
- Speak while the models run — never stand in silence
- If something fails: say "Let me show you the error handling" and explain how the system handles it
- If Ollama is slow: explain that T1+T2 sequential execution is a 6GB VRAM constraint
- If a test times out: say "The 120-second timeout protects the session from hanging"

**If the examiner asks something you don't know:**
Say: "That's a good question I haven't specifically tested. Based on the architecture, I would expect X because Y, but I'd want to measure it to be certain."

Never bluff. Intellectual honesty scores higher than confident wrong answers.

Final verification — run all 5 demo rehearsals:
```bash
bash# Rehearsal 1
python tests/test_submission_ready.py
python main.py ui
# (run the demo script, time each section, fill in timing log)
```

# After all 5 rehearsals, run the submission check one final time:
python tests/test_submission_ready.py

# If it prints READY FOR SUBMISSION:
pip freeze > requirements.txt
git add README.md requirements.txt DEMO_SCRIPT.md tests/test_submission_ready.py
git commit -m "Week 20 complete: submission ready, all checks pass"
git push origin main

Week 20 is done when python tests/test_submission_ready.py prints "READY FOR SUBMISSION" and you have run the 10-minute demo script at least 5 times with the timing log filled in. The submission readiness script has 19 automated checks across 4 sections — security, completeness, code quality, and demo readiness. Every single check must pass. The most important is the security section. A single API key in the git history can have consequences far beyond the mark — it is a credential leak. Do not submit until all 4 security checks are green. Good luck bro.
