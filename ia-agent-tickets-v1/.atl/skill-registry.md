# Project Skill Registry: ia-agent-tickets-v1

## User Skills
| Skill | Trigger | Summary |
|-------|---------|---------|
| branch-pr | PR creation, opening a PR, preparing changes for review | PR creation workflow for Agent Teams Lite following the issue-first enforcement system. |
| issue-creation | Creating a GitHub issue, reporting a bug, or requesting a feature | Issue creation workflow for Agent Teams Lite following the issue-first enforcement system. |
| judgment-day | "judgment day", "judgment-day", "review adversarial", "dual review", "doble review", "juzgar", "que lo juzguen" | Parallel adversarial review protocol that launches two independent blind judge sub-agents. |

## Project Standards
- **Backend**: Express.js + better-sqlite3 + CORS. Routes in `src/routes/`. Middleware in `src/middleware/`.
- **Frontend**: React + Vite. Views in `src/pages/`. Components in `src/components/`.
- **Testing**: NOT AVAILABLE.
- **Strict TDD**: disabled.
