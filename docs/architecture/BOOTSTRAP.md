# HERMES 2.x Environment Lifecycle Bootstrap

## 1. Overview

Agent execution frequently halts or fails because the agent does not know how to install dependencies, run the test suite, lint code, or start the development server.

The HERMES 2.x **Bootstrap Subsystem** standardizes environment lifecycle awareness across platforms (Windows, Linux, macOS) without granting arbitrary unattended execution permissions.

---

## 2. Canonical Lifecycle Actions

| Action | Primary Purpose | Risk Tier |
|---|---|---|
| `install` | Package dependency resolution (`pip install`, `npm install`) | HIGH |
| `test` | Test execution (`pytest`, `jest`, `cargo test`) | LOW |
| `lint` | Static analysis and type checking (`flake8`, `eslint`, `mypy`) | LOW |
| `build` | Compilation and asset bundling (`vite build`, `tsc`, `go build`) | MEDIUM |
| `dev` | Local development server / watch mode | MEDIUM |
| `start` | Production service startup | MEDIUM |

---

## 3. Explicit Manifest vs Workspace Heuristic Fallback

The Bootstrap Engine follows an explicit-first, heuristic-fallback discovery path:

1. **Declared Manifests**:
   - `.hermes/bootstrap/bootstrap.json`
   - `.hermes/bootstrap/bootstrap.yaml`
   - `.hermes/bootstrap/<action>.md`
   Commands found here have `source="project"` and take absolute precedence.
2. **Workspace Heuristic Fallback**:
   When no explicit manifest exists, the engine queries Prompt 6's `WorkspaceDiscoveryService` to detect project manifests (`package.json`, `pyproject.toml`, `requirements.txt`, `Cargo.toml`, `go.mod`) and synthesizes normalized commands with `source="auto_detected"`.

---

## 4. Safety Invariants & Execution Control

1. **No Auto-Execution of Install**:
   The agent is strictly prohibited from auto-executing `install` without explicit user permission or safe policy clearance.
2. **Risk Classification**:
   Every lifecycle command carries a `risk` attribute (`low`, `medium`, `high`) allowing the harness `PermissionPolicy` to enforce confirmation gates.
3. **Cross-Platform Binary Normalization**:
   On Windows, commands like `npm` and `npx` are normalized to `npm.cmd` and `npx.cmd` to prevent Windows shell invocation errors.
