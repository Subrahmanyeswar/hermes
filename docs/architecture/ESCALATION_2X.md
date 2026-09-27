# HERMES 2.x Selective Escalation Engine (Prompt 11)

## Executive Summary
The HERMES 2.x Selective Escalation Engine routes verification and quality decisions across three tiers (T1 Act, T2 Critic, T3 Judge). It ensures high-risk, ambiguous, or contested actions receive independent skeptical review, while routine low-risk actions pass instantly without latency or token waste.

---

## 1. Core Invariants
1. **Low-Risk Fast-Path Bypass:** Routine operations (CSS, documentation, simple formatting, variable renames, localized edits with passing checks) strictly bypass T2 and T3.
2. **Fact Invariant:** Neither T2 Critic nor T3 Judge can override failed objective facts (failing tests, broken syntax, missing files).
3. **Workspace Confinement:** Neither T2 Critic nor T3 Judge may directly mutate workspace files. They evaluate, arbitrate, and critique only.
4. **Bounded Evaluation Packets:** Packets dispatched to T2 and T3 are minimized to avoid context explosion.
5. **Bounded Escalation Budget:** Capped invocations per mission to prevent runaway arbitration costs.

---

## 2. Risk Assessment Criteria
| Risk Level | Trigger Conditions | Routing |
|------------|--------------------|---------|
| **LOW** | Documentation, CSS, small edit (<30 lines), passing tests | Bypass T2/T3 entirely |
| **MEDIUM** | Standard code edits, non-core features | Optional T2 review |
| **HIGH** | Core runtime, state reducer, security/auth, recurring failures | Mandatory T2 review |
| **CRITICAL** | Persistent disagreements, destructive commands, stalled repairs | Escalated to T3 Judge |

---

## 3. Escalation Decision Types
- `NO_ESCALATION`: Handled directly by T1.
- `T1_REPAIR`: Directed back to T1 for self-repair.
- `T2_REQUIRED`: Dispatched to T2 Critic.
- `T3_REQUIRED`: Dispatched to T3 Judge for arbitration.
- `USER_REQUIRED`: Requires human-in-the-loop intervention.
