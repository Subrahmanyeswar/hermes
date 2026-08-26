# HERMES v4.0 — Demo Script

## Pre-flight (30 minutes before)

- [ ] `ollama serve` running
- [ ] `ollama list` shows qwen2.5-coder:7b AND mistral:7b-instruct
- [ ] `python main.py info` prints both models ✓
- [ ] `ANTHROPIC_API_KEY` set in environment
- [ ] Demo project directory ready (a Flask project or blank directory)
- [ ] Terminal: 160×50 minimum, font 13+
- [ ] Battery 80%+ or charger connected

---

## Section 1 — System Overview (45 seconds)

```bash
python main.py info
```

Say: "HERMES v4.0 is a goal-driven local coding runtime. Unlike a chatbot that answers
one question at a time, HERMES takes a complete objective, decomposes it into a DAG
of atomic tasks, and executes them to completion — just like Claude Code but running
entirely on a 6GB GPU."

Point out: both models ✓, 12 skills loaded, cost $0.000

---

## Section 2 — Launch + Workspace Selection (30 seconds)

```bash
python main.py ui
```

**On startup screen:** type the demo project path or press Enter for CWD.

Say: "The workspace manager indexes the project — folder skeleton, file signatures,
framework detection. This is how HERMES knows which files to read without dumping
the entire codebase into the context window."

Point out status bar: [framework/project-name] appears.

---

## Section 3 — The Mission: Multi-Task Prompt (3 minutes)

Type in chat (use the large TextArea — it supports multi-line):
```text
Create a Flask REST API at generated_projects/edupath/app.py with student career questionnaire endpoints using SQLite
Build SQLAlchemy models for Student, Question, and CareerPath
Write a comprehensive pytest test suite in generated_projects/edupath/tests/
Generate a README.md with API documentation
Commit all changes with message feat: add EduPath career questionnaire API
```

Press Ctrl+Enter to submit.

Say while plan appears: "HERMES parsed the prompt into 5 tasks using the DAG planner.
Dependencies are detected — tests can't run before the API exists, commit comes last.
Watch the execution plan on the left — it updates in real-time."

Point out: execution plan checklist appears, task states update as work completes.

---

## Section 4 — Watch the Loop Execute (4 minutes)

As tasks execute, narrate:

"Task 1 running — Tier 1 Qwen generating the Flask factory pattern. The context
builder selected the workspace skeleton and Flask skill rules. No unnecessary
file content injected — stays within 6000 token budget."

"Task 2 — SQLAlchemy models. Notice Tier 2 Mistral verifying the ORM relationships.
Different model family, different training data — cross-family disagreement detection."

"Task 3 — pytest suite. The skill system loaded pytest-generation rules automatically
from the intent classifier. The commit task is blocked until this completes."

"Tasks 4 and 5 completing — git commit runs last because the DAG scheduler detected
the dependency chain."

Point out:
- Status bar: Skill: pytest-generation → flask-rest-api → git-workflow
- Right panel Tool Trace updating with each tool call
- Cost stays near $0 (all local, no T3 escalation needed)

---

## Section 5 — Mission Complete Walkthrough (30 seconds)

When walkthrough appears:

Say: "Mission complete. HERMES generated all 5 outputs without stopping once.
No chatbot. No manual re-prompting. One goal, continuous execution."

Point out:
- Files created list
- Time taken (should be 3-8 minutes for real Ollama)
- Cost (should be < $0.05 — mostly free local inference)
- Git commit section with auto-generated message

---

## Section 6 — WOW Feature: Screenshot to Code (1 minute)

```text
/screenshot tests/screenshots/test_dashboard.png html
```

Say: "One more feature — vision. Drop a UI design and HERMES converts it to
production HTML with Tailwind CSS using the multimodal endpoint. Runs locally,
zero API cost."

---

## Section 7 — Benchmark Numbers (30 seconds)

```bash
python benchmarks/compute_metrics.py --results-file benchmarks/results.json 2>/dev/null | head -30
```

"78% task completion rate. 78% local resolution — free. 18pp skill lift from
the ablation study. $0.33 total API cost for 50 tasks vs $4.50 all-Claude.
92.7% cost reduction."

---

## Total: 10 minutes

| Section | Target |
|---------|--------|
| 1. System overview | 0:45 |
| 2. Launch + workspace | 0:30 |
| 3. Multi-task prompt | 0:30 |
| 4. Watch loop execute | 4:00 |
| 5. Walkthrough | 0:30 |
| 6. Screenshot-to-code | 1:00 |
| 7. Benchmark results | 0:30 |
| Buffer | 2:15 |
| **Total** | **10:00** |

---

## Rehearsal Log

| Run | Date | P1 | P2 | P3 | P4 | P5 | P6 | P7 | Total |
|-----|------|----|----|----|----|----|----|----|-------|
| 1 | | | | | | | | | |
| 2 | | | | | | | | | |
| 3 | | | | | | | | | |
| 4 | | | | | | | | | |
| 5 | | | | | | | | | |

**The difference from v3.0:** The demo no longer shows a chatbot responding once.
It shows a system that takes a specification and delivers a working project.
That is the gap between a tool and an agent.
