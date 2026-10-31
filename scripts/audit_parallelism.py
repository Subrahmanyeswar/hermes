"""
HERMES Phase 4G - Independent Parallelism and Safety Audit
Validates conflict-key serialization vs disjoint parallel execution.
Outputs:
- artifacts/phase4g/parallel_execution_trace.json
"""

import json
import sys
from pathlib import Path

root = Path(__file__).resolve().parent.parent
if str(root) not in sys.path:
    sys.path.insert(0, str(root))

from core.mission_planner import Mission, MissionTask, TaskState

def run_parallelism_audit():
    root = Path(__file__).resolve().parent.parent
    trace_output = root / "artifacts" / "phase4g" / "parallel_execution_trace.json"
    
    events = []
    
    # ── Test 1: Conflict Key Serialization ───────────────────────────────────
    # Two tasks attempting to modify the same file (index.html)
    t1 = MissionTask(
        title="Implement main header in index.html",
        description="Write header layout",
        target_paths=["index.html"],
        write_dependencies=["index.html"],
        depends_on=[]
    )
    t2 = MissionTask(
        title="Add footer section in index.html",
        description="Write footer layout",
        target_paths=["index.html"],
        write_dependencies=["index.html"],
        depends_on=[]
    )
    
    m_conflict = Mission(
        mission_id="audit_conflict_test",
        user_prompt="Build layout in index.html",
        tasks=[t1, t2]
    )
    
    batch_conflict = m_conflict.get_executable_batch(max_concurrent=3)
    conflict_batch_ids = [t.task_id for t in batch_conflict]
    conflict_serialized = (len(batch_conflict) == 1 and t1.task_id in conflict_batch_ids and t2.task_id not in conflict_batch_ids)
    
    events.append({
        "scenario": "conflicting_writes_same_target",
        "description": "Two tasks both write to 'index.html'",
        "batch_size_returned": len(batch_conflict),
        "tasks_in_batch": [t.title for t in batch_conflict],
        "serialized_safely": conflict_serialized,
        "verdict": "PASS" if conflict_serialized else "FAIL"
    })
    
    # ── Test 2: Disjoint Parallel Execution ──────────────────────────────────
    # Two independent tasks targeting disjoint files
    t_css = MissionTask(
        title="Write styles.css",
        description="Create responsive CSS stylesheet",
        target_paths=["css/styles.css"],
        write_dependencies=["css/styles.css"],
        depends_on=[]
    )
    t_js = MissionTask(
        title="Write app.js",
        description="Create interactive JavaScript",
        target_paths=["js/app.js"],
        write_dependencies=["js/app.js"],
        depends_on=[]
    )
    
    m_parallel = Mission(
        mission_id="audit_parallel_test",
        user_prompt="Build styles and script",
        tasks=[t_css, t_js]
    )
    
    batch_parallel = m_parallel.get_executable_batch(max_concurrent=3)
    parallel_batch_ids = [t.task_id for t in batch_parallel]
    both_dispatched = (len(batch_parallel) == 2 and t_css.task_id in parallel_batch_ids and t_js.task_id in parallel_batch_ids)
    
    events.append({
        "scenario": "disjoint_independent_writes",
        "description": "Tasks targeting disjoint files 'css/styles.css' and 'js/app.js'",
        "batch_size_returned": len(batch_parallel),
        "tasks_in_batch": [t.title for t in batch_parallel],
        "parallel_dispatched": both_dispatched,
        "verdict": "PASS" if both_dispatched else "FAIL"
    })
    
    # ── Test 3: Hard Verification Barrier ────────────────────────────────────
    t_impl = MissionTask(
        title="Write data model",
        description="Create models.py",
        target_paths=["models.py"],
        write_dependencies=["models.py"],
        depends_on=[]
    )
    t_verify = MissionTask(
        title="Verify and validate system integrity",
        description="Run test suite and verify",
        depends_on=[]
    )
    
    m_barrier = Mission(
        mission_id="audit_barrier_test",
        user_prompt="Create model and verify",
        tasks=[t_impl, t_verify]
    )
    
    batch_barrier_initial = m_barrier.get_executable_batch(max_concurrent=3)
    barrier_held = (len(batch_barrier_initial) == 1 and batch_barrier_initial[0].task_id == t_impl.task_id)
    
    # Complete implementation task
    m_barrier.mark_task_complete(t_impl.task_id)
    batch_barrier_post = m_barrier.get_executable_batch(max_concurrent=3)
    barrier_released = (len(batch_barrier_post) == 1 and batch_barrier_post[0].task_id == t_verify.task_id)
    
    events.append({
        "scenario": "verification_barrier_preservation",
        "description": "Verification task held back until all implementation tasks complete",
        "barrier_held_initially": barrier_held,
        "barrier_released_after_completion": barrier_released,
        "verdict": "PASS" if (barrier_held and barrier_released) else "FAIL"
    })
    
    # Write report
    report = {
        "title": "HERMES Phase 4G Parallelism & Safety Audit",
        "all_passed": all(e["verdict"] == "PASS" for e in events),
        "scenarios_tested": len(events),
        "events": events
    }
    
    with open(trace_output, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
        
    print(f"Parallelism Audit Complete: {'ALL PASS' if report['all_passed'] else 'FAILURES DETECTED'}")
    for ev in events:
        print(f"  {ev['scenario']}: {ev['verdict']}")

if __name__ == "__main__":
    run_parallelism_audit()
