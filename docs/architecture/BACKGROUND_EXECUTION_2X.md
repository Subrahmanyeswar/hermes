# HERMES 2.x — Background Execution Architecture (BACKGROUND_EXECUTION_2X.md)

## 1. Architectural Purpose
Long-running subagent tasks, build pipelines, test suites, and dev servers must not block the agent loop turn cycle. HERMES 2.x provides a unified background execution engine supporting both asynchronous subagent loops and operating system processes.

---

## 2. Core Execution Kinds & Models
- `JobKind.SUBAGENT`: Asynchronous subagent task coroutines running concurrently with the main loop.
- `JobKind.SHELL`: Background shell scripts and processes.
- `JobKind.SERVER`: Persistent background dev servers or mock endpoints.
- `JobKind.TEST`: Background test runner suites (e.g. pytest, npm test).
- `JobKind.BUILD`: Background compilation or bundling jobs.

---

## 3. Streamed File-Backed Outputs
To prevent memory leaks and buffer exhaustion:
- Background process stdout is continuously redirected to `.hermes/jobs/{job_id}.out`.
- Background process stderr is continuously redirected to `.hermes/jobs/{job_id}.err`.
- Outputs can be queried incrementally via `get_job_output(job_id, offset, limit)`.
- If outputs exceed size limits, they are indexed in the `OutputStore` or artifact directory.

---

## 4. Lifecycle Bindings
- `JobLifecycle.CHILD_BOUND`: The job belongs to a specific subagent. When the owning subagent terminates or is cancelled, all child-bound processes and tasks are automatically terminated.
- `JobLifecycle.DETACHED`: The job continues running independently of the subagent's lifecycle (e.g. background servers).

---

## 5. Windows Process Tree Termination
On Windows systems, killing a parent process via standard `proc.kill()` often leaves child processes orphaned in the background.

HERMES 2.x eliminates this via `CancellationController`:
1. Enumerates the full process tree using `psutil.Process(pid).children(recursive=True)`.
2. Sends graceful `terminate()` signals to all child and parent processes.
3. Bounded wait period (e.g. 1.0–2.0s).
4. Issues forceful `kill()` on any surviving processes.
5. Employs OS-native fallback (`taskkill /F /T /PID <pid>`) when `psutil` is unavailable.

---

## 6. Concurrency & Rate Governance
- Controlled via `ResourceGovernor` semaphore (default max 3 active parallel subagents).
- Stall watchdog detects hung jobs (no activity for > 60s) and triggers timeout recovery.
