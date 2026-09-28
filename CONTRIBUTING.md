# Contributing

Titan Omega is a solo project, but issues and pull requests are welcome.

## Running it

```bash
# backend (Python 3.11+)
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# frontend
cd frontend
npm install
npm run dev
```

It runs with no API keys at all; every engine that needs one says so instead
of failing.

## Before you open a pull request

```bash
cd backend && python -m pytest tests/ -q
cd frontend && npm run typecheck
```

If you touched a guard - an ownership check, a limit, anything that refuses
something - run the mutation check too. It removes each guard in turn and
fails if the tests still pass:

```bash
cd backend && python -m evaluation.mutation_check
```

A new guard gets an entry in `backend/evaluation/mutation_check.py` and a test
that fails without it.

## Two rules the code follows

- **No number is shown unless it was measured.** Unknown is `null`, not `0`.
- **A subscriber only ever sees their own data.** A route is reachable from a
  subscriber's cockpit (`/api/me`) only once it is on the allowlist in
  `backend/app/core/cockpit_scope.py`, with a test in
  `backend/tests/test_cockpit.py` showing it reads only their workspace.

## Commits

Short, plain subject lines that say what changed and why. One logical change
per commit.
