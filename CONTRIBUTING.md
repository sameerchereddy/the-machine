# Contributing to The Machine

## Development setup

See the [Quick Start](README.md#quick-start) in the README.

## Branches

- `main` — stable, CI must pass before merging
- Feature branches — `feat/<name>`, `fix/<name>`, `chore/<name>`

## Commit style

Follow conventional commits:

```
feat(auth): add Google SSO callback handler
fix(llm): correct Usage field names for Anthropic provider
chore: disable dependabot until app is stable
docs: update Quick Start with correct env paths
test(auth): add unit tests for login and me endpoints
```

## Running checks locally

```bash
# Backend
cd backend
ruff check .
mypy app/
pytest tests/unit/

# Frontend
cd frontend
npm run lint
npx tsc --noEmit
npm test
```

## Pull requests

- All PRs target `main`
- CI (lint + types + tests) must be green
- An AI review comment is posted automatically — it is not a substitute for human review
