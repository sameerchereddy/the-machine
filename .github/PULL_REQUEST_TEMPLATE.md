## Summary

<!-- What does this PR do? 1-3 sentences. -->

## Changes

<!-- Bullet list of concrete changes. -->

-

## Test plan

<!-- How did you verify this works? -->

- [ ] Unit tests pass (`pytest tests/unit/` / `npm test`)
- [ ] Type checks pass (`mypy app/` / `tsc --noEmit`)
- [ ] Lint passes (`ruff check .` / `npm run lint`)
- [ ] Tested manually (describe below)

## Screenshots / traces

<!-- For UI or agent changes, attach a screenshot or trace snippet. -->

## Checklist

- [ ] No hardcoded secrets or API keys
- [ ] No `localStorage` for auth tokens (httpOnly cookies only)
- [ ] DB queries use asyncpg parameterised (`$1`, `$2` — no f-strings)
- [ ] New provider code uses `BaseProvider`, not raw HTTP
- [ ] New tables have RLS policies
- [ ] Related issue: #
