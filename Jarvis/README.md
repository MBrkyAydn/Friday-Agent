# JARVIS Worker

Autonomous Specialist Worker Agent for Multi-Agent Architecture.

## Roles & Responsibilities
- Worker/Specialist agent executing coding, testing, and verification tasks dispatched by FRIDAY.
- Communicates out-of-process strictly via `Shared/mailboxes` (`friday_inbox` & `jarvis_inbox`).
- Employs strict verification before marking tasks `task_completed`.

## CLI Usage
```bash
# Start background polling worker
jarvis worker --interval 1.0

# Process single pending task and exit
jarvis run-once

# Send ping heartbeat to Friday
jarvis ping
```
