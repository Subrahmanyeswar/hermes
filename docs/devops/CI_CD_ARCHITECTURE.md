# HERMES 2.x — CI/CD Architecture & Pipeline Specification

## 1. Overview & Objectives

This document defines the automated Continuous Integration and Continuous Delivery (CI/CD) foundation for HERMES 2.x.
The architecture is designed to guarantee reproducible verification of backend Python logic, React/Vite frontend builds, Docker image construction, robust health smoke-testing, image artifact handoff, and container security compliance across branches without requiring manual host interventions or risking environment drift.

---

## 2. CI Pipeline Architecture

The primary CI pipeline is defined in [`.github/workflows/ci.yml`](../../.github/workflows/ci.yml). It employs isolated, parallelized stages using standard Ubuntu 24.04 runners with strict caching, image artifact handoff, and artifact handling.

```
+-----------------------------------------------------------------------------------+
|                                 Workflow Triggers                                 |
|            - Push to 'hermes-2.x' or 'main'                                       |
|            - Pull Request targeting 'hermes-2.x' or 'main'                        |
+-----------------------------------------------------------------------------------+
                                          |
                   +----------------------+----------------------+
                   |                                             |
                   v                                             v
+-------------------------------------+       +-------------------------------------+
|         Stage A/B: Backend          |       |         Stage C: Frontend           |
|    - Python 3.12 Setup              |       |    - Node.js 20 Setup               |
|    - Pip cache                      |       |    - npm cache                      |
|    - requirements-linux.txt install |       |    - npm ci                         |
|    - Syntax & module compilation    |       |    - tsc + vite build               |
|    - Pytest regression execution    |       |    - Upload dist artifact           |
|    - Upload JUnit XML report        |       +-------------------------------------+
+-------------------------------------+                          |
                   |                                             |
                   +----------------------+----------------------+
                                          | (Both Must Pass)
                                          v
+-----------------------------------------------------------------------------------+
|                       Stage D: Docker Build & Smoke Test                          |
|    - Multi-stage build (Node 20 builder -> Python 3.12 Debian slim)              |
|    - Docker Buildx layer caching                                                  |
|    - Active container health assertion (/api/health with bounded retries)         |
|    - Active frontend delivery verification (/ returns HTTP 200)                   |
|    - Container process liveness verification (State.Running == true)              |
|    - Safe container cleanup with log capture on error                             |
|    - Export Docker image archive (docker save -> hermes-image.tar)                |
|    - Upload image artifact to avoid rebuild in downstream jobs                    |
+-----------------------------------------------------------------------------------+
                                          |
                                          v
+-----------------------------------------------------------------------------------+
|                        Stage E: Trivy Security Scanning                           |
|    - Download & load docker image artifact (docker load -i)                       |
|    - Container image vulnerability scan (SARIF report)                            |
|    - Filesystem dependency & misconfiguration scan (Table summary)                |
|    - Enforceable vulnerability gate (exit-code: 1 for CRITICAL,HIGH)              |
|    - Validate SARIF non-empty before upload                                       |
|    - Upload SARIF to GitHub Security Center (CodeQL upload-sarif)                 |
|    - Upload scan artifact                                                         |
+-----------------------------------------------------------------------------------+
```

---

## 3. Workflow Trigger & Concurrency Policy

- **Target Branches:** `hermes-2.x` and `main`.
- **Triggers:** `push` and `pull_request`.
- **Concurrency Control:**
  ```yaml
  concurrency:
    group: ${{ github.workflow }}-${{ github.ref }}
    cancel-in-progress: true
  ```
  Prevents wasteful redundant runs when multiple commits are pushed in rapid succession.

---

## 4. Test Execution Strategy

### 4.1 Backend Test Selection
HERMES 2.x contains both platform-agnostic subsystems and legacy Windows-only launcher tests. In the Linux CI container runner, tests are partitioned to execute high-value portable core subsystems:
1. **EventBus & Memory State:** `tests/test_event_bus.py` (monotonic sequences, deduplication, state store reconstruction, pub/sub delivery).
2. **Security Gates & Docker Network Security:** `tests/test_security.py` (command boundary filters, path traversal blocks, malicious injection defense, Docker bridge CIDR validation, fail-closed loopback fallback, and middleware authorization).
3. **State Checkpointing:** `tests/test_checkpoints.py` (checkpoint creation, hash validation, payload integrity).
4. **Workspace Boundary:** `tests/test_workspace.py` (root locking, safe canonicalization, path traversal prevention, framework detection).
5. **Phase 2 Restart & Recovery:** `tests/test_phase2_restart_recovery.py` (stale worker PID clearing, orphan mission rehydration into WAITING state).

*Total Verified Tests:* 72 test cases (10 in `test_event_bus.py`, 44 in `test_security.py`, 1 in `test_checkpoints.py`, 15 in `test_workspace.py`, 2 in `test_phase2_restart_recovery.py`) running with a 100% pass rate on both Linux (20.03s) and Windows (5.42s).

### 4.2 Frontend Verification
- Evaluates `gui/package.json` and `gui/tsconfig.json`.
- Runs TypeScript compiler (`tsc`) followed by Vite production bundling (`vite build`).
- Bundles are output to `gui/dist/` and retained as GitHub Actions build artifacts.

---

## 5. Docker Build, Smoke Verification & Artifact Handoff

- **Multi-stage Build:**
  - Stage 1: `node:20-slim` builds production frontend artifacts.
  - Stage 2: `python:3.12-slim-bookworm` provides isolated, reproducible Linux runtime.
  - System packages: `curl`, `git`, `nodejs` (for runtime `node --check` syntax validation), and `ca-certificates`.
  - Non-root execution: runs under unprivileged UID `1000` (`hermes:hermes`).
- **Robust Smoke Testing:**
  - Container spins up in daemon mode with container environment overrides.
  - Polling loop checks `http://127.0.0.1:8765/api/health` with bounded retries (up to 20 seconds).
  - Asserts HTTP 200 from `/api/health`.
  - Asserts HTTP 200 from `/` (verifying frontend static mount).
  - Asserts `docker inspect` confirms `State.Running == true`.
  - On failure, full container logs are printed and container is forcefully destroyed.
  - On success, container is stopped and removed cleanly.
- **Image Artifact Handoff:**
  - The built image is saved as `hermes-image.tar` and uploaded via `actions/upload-artifact`.
  - Downstream `security-scan` downloads and loads the image directly (`docker load -i`), eliminating redundant Docker image rebuilds and guaranteeing that the exact tested binary artifact is what undergoes security scanning.

---

## 6. Trivy Security Scanning & Enforceability Policy

### 6.1 Vulnerability Scope & Remediation Audit
The pipeline audits container images and repository dependencies using official Aqua Security Trivy (`aquasecurity/trivy-action`), pinned to immutable commit SHAs.

#### Vulnerability Elimination Metrics
| Target Subsystem | Initial Status | Remediated Status | Remediations Implemented |
| :--- | :--- | :--- | :--- |
| **Python Application Packages** | 31 CVEs (6 CRIT, 25 HIGH) | **0 CVEs (0 CRIT, 0 HIGH)** | Upgraded `certifi` (2026.10.23), `pillow` (13.0.0), `gitpython` (3.2.1); uninstalled build-time `setuptools` & `pip` |
| **Debian 12 Base OS Packages** | 167 CVEs (6 CRIT, 161 HIGH) | **167 CVEs (6 CRIT, 161 HIGH)** | Evaluated all 167 OS CVEs. All are upstream Debian Bookworm unpatched (`will_not_fix` / `affected` with no available patch) |
| **Total Image Vulnerabilities** | **198 CVEs (12 CRIT, 186 HIGH)** | **167 CVEs (6 CRIT, 161 HIGH)** | **100% of fixable CVEs eliminated (31/31 eliminated)** |

#### OS Package Vulnerability Breakdown (Debian 12 Upstream)
- `node-undici`: 18 CVEs (Node.js runtime HTTP client, no upstream Debian 12 backport)
- `libgssapi-krb5-2` / `libkrb5*`: 56 CVEs (Kerberos runtime libraries, no upstream Debian 12 backport)
- `nodejs` / `libnode108`: 22 CVEs (Node.js runtime engine)
- `libsqlite3-0`: 6 CVEs (SQLite shared library)
- `curl` / `libcurl4`: 15 CVEs (System curl client)
- `libexpat1`: 4 CVEs (XML parsing library)
- `util-linux` / `libmount1` / `libuuid1`: 21 CVEs (Core Linux utilities)
- `zlib1g`: 3 CVEs (Compression library)
- `other base OS tools`: 22 CVEs (`git`, `gzip`, `perl`, `libsystemd0`)

### 6.2 Dual-Layer Trivy Enforceability Architecture
To prevent pipeline circumvention while avoiding spurious build breaks on unpatchable Debian base image CVEs, the pipeline employs a dual-layer strategy:

1. **Full Transparency Security Audit (SARIF Upload):**
   - Runs full image scan with `ignore-unfixed: false`.
   - Generates complete `trivy-image-results.sarif` report containing all findings (including upstream Debian OS vulnerabilities).
   - Validates that the SARIF file exists and is non-empty (`exit 1` if missing).
   - Uploads SARIF to GitHub Security Center (CodeQL) for full visibility.

2. **Enforceable Vulnerability Quality Gate:**
   - Runs with `exit-code: "1"`, `severity: "CRITICAL,HIGH"`, and `ignore-unfixed: true`.
   - Strictly fails the build if **ANY** application-level dependency or any Debian OS package with an available security patch has a HIGH or CRITICAL vulnerability.
   - Enforces zero regressions on newly introduced dependencies.

---

## 7. Security & Permissions Model

- **Default Root Permissions:**
  ```yaml
  permissions:
    contents: read
  ```
- **Job-level Elevation:** Only the `security-scan` job elevates permissions to `security-events: write` specifically to publish SARIF results to GitHub Code Scanning.
- **Fork Safety:** Pull requests from forks are executed with read-only tokens and cannot access repository secrets or push code scanning alerts to the base repository.
- **Zero Secret Exposure:** No hardcoded credentials or long-lived cloud keys exist in workflow files.

---

## 8. AWS OIDC Preparation (Phase 3 Roadmap)

In Phase 3 (Deployment), HERMES will eliminate long-lived AWS IAM credentials by authenticating via GitHub OpenID Connect (OIDC).

### 8.1 Technical Architecture
1. **GitHub OIDC Provider:**
   - AWS IAM Identity Provider configured with URL `https://token.actions.githubusercontent.com` and Audience `sts.amazonaws.com`.
2. **IAM Role Trust Policy:**
   ```json
   {
     "Version": "2012-10-17",
     "Statement": [
       {
         "Effect": "Allow",
         "Principal": {
           "Federated": "arn:aws:iam::<ACCOUNT_ID>:oidc-provider/token.actions.githubusercontent.com"
         },
         "Action": "sts:AssumeRoleWithWebIdentity",
         "Condition": {
           "StringEquals": {
             "token.actions.githubusercontent.com:aud": "sts.amazonaws.com"
           },
           "StringLike": {
             "token.actions.githubusercontent.com:sub": "repo:Subrahmanyeswar/hermes:ref:refs/heads/hermes-2.x"
           }
         }
       }
     ]
   }
   ```
3. **Branch & Repository Scope:**
   - Strictly restricted to `repo:Subrahmanyeswar/hermes` and branch `refs/heads/hermes-2.x` (or `main`).
4. **Required Action Permissions in Deployment Workflow:**
   ```yaml
   permissions:
     id-token: write # Required for requesting the OIDC JWT
     contents: read
   ```
5. **ECR / ECS Pipeline Integration:**
   - `aws-actions/configure-aws-credentials` will assume the temporary role.
   - Pushes built image to Amazon Elastic Container Registry (ECR).
   - Updates Amazon Elastic Container Service (ECS) task definitions without persistent API secrets.

---

## 9. Known Limitations & Operating Notes

1. **Host Ollama Connectivity:** Localhost-bound Ollama running on developer workstations is mocked or bypassed in cloud CI.
2. **Windows Launcher Separation:** Windows-specific batch scripts (`run.bat`, Windows PowerShell commands) are excluded from Linux CI runners; native Windows regressions must continue to be verified on host.
