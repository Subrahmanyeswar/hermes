# HERMES Event-Driven TUI & Unified Event Bus Architecture
==========================================================

**Module:** `core.event_bus`, `ui.event_tui`  
**Date:** September 1, 2026  
**Status:** PRODUCTION READY  

---

## 1. Unified Event Bus Flow

```
                         HERMES BACKEND
                   (Execution / KAIROS / Models)
                              │
                              ▼
                         EVENT BUS
             (Sequence-ordered, Deduplicated, Bounded)
                              │
              ┌───────────────┼────────────────┐
              ▼               ▼                ▼
         State Store       Logger          Telemetry
              │
              ▼
       Event-Driven TUI
         (Live View)
```

---

## 2. Invariant Rules

1. **The TUI is a consumer, not a controller.**
2. **Never emit or display fake progress or fake completion.**
3. **Subscriber failures must never crash backend execution.**
4. **Out-of-order events must not corrupt state.**
5. **Sensitive tokens and passwords are automatically redacted.**
6. **Zero chain-of-thought exposure in UI feeds.**
