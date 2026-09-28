**What this changes, and why**


**How I checked it**

- [ ] `cd backend && python -m pytest tests/ -q`
- [ ] `cd frontend && npm run typecheck`
- [ ] Mutation check, if a guard changed (`python -m evaluation.mutation_check`)
- [ ] Tried it in the browser, if the UI changed

**Anything a subscriber can now reach?**

If yes: the route is on the allowlist in `backend/app/core/cockpit_scope.py`
with a test in `backend/tests/test_cockpit.py`.
