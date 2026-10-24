# AGENTS.md — Agent Operating Guidelines

This file provides the core operational instructions for AI coding agents operating within the `AI Employee Platform` repository.

## Primary Instructions

All agent workflows, architecture standards, security rules, and verified development commands are authoritatively documented in [GEMINI.md](./GEMINI.md).

### Mandatory Protocol:
1. **Always read [GEMINI.md](./GEMINI.md)** before executing any task.
2. **Inspect existing code and Git status** before writing or modifying files.
3. **Execute autonomous verification**:
   - Backend: Pytest via `.venv\Scripts\pytest.exe`.
   - Frontend Dashboards: Vitest + TypeScript build via `npm run build` and `npm test`.
   - Autonomous UI testing: invoke skill in `.agents/skills/autonomous-page-testing/SKILL.md`.
4. **Preserve uncommitted changes**: never perform hard resets or delete user files.
5. **Enforce Tenant Isolation**: all queries and actions must be scoped to `tenant_id`.
