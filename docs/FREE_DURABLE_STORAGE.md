# Keeping the data, without paying for storage

Written 2026-08-21. Solves this warning, which is the one the founder saw:

> History is stored at /tmp/titan_state.json, which is not a persistent mount.
> Signups survive restarts and sleep-wake, but a fresh Space rebuild wipes
> them.

## What was actually at risk

Not just "history". A free Space wipes `/tmp` on every rebuild, and that store
holds every account, organisation, audit row, subscription event — and
`site_fix`'s snapshot of the **previous content of pages Titan has changed on
somebody else's live website**. Losing it does not merely lose the record; it
loses the ability to undo a change Titan made to another business.

## The free answer

Hugging Face's first answer is persistent storage mounted at `/data`. It is
continuous, it is correct, and it is a **paid** add-on.

Their second answer costs nothing, and their own docs state it plainly: *use a
dataset as a data store* for anything that must outlive the Space. A **private
Dataset repo is free**, and a Space can push to one.

So Titan snapshots itself into one. `core/remote_state.py`.

## Turn it on — two variables, both free

On the Space: **Settings → Variables and secrets**.

| Name | Kind | Value |
|---|---|---|
| `HF_TOKEN` | **Secret** | A Hugging Face token with **write** access |
| `TITAN_STATE_REPO` | Variable | *Optional.* Defaults to `<your-username>/titan-state` |

Get the token at <https://huggingface.co/settings/tokens> — "Create new token",
type **Write**. Free.

`TITAN_STATE_REPO` is optional because the repo name is derived from `SPACE_ID`,
which Hugging Face sets on every Space automatically. One variable to get right
is better than two.

**The repo is created for you, private, on the first push.** You do not need to
make it beforehand.

### Checking it worked

`GET /api/founder/integrations` — the **Durable storage** row. Or the Executive
screen's *Needs attention* panel: the "Storage does not survive a rebuild"
notification disappears once snapshots are running.

`remote_state.status(check_remote=True)` asks the Hub whether a snapshot
actually exists, rather than assuming one does because a token is set.

## What this is honestly worth

**It is not continuous durability.** It is *snapshot* durability, with a
recovery point equal to the backup interval (`TITAN_BACKUP_INTERVAL`, default
6h). A rebuild loses at most the work since the last successful push.

The product says exactly that rather than claiming the data is safe:

> History is stored at …, which is ephemeral, and is snapshotted to the private
> Dataset repo …/titan-state after every verified backup. A rebuild restores
> from the last snapshot, so at most ~6h of activity is lost. This is free;
> persistent storage at /data is continuous but paid.

Lower the interval if 6h is too much. Every push is a git commit, so pushing
every 15 minutes is possible and will grow the repo's history faster.

## Design decisions worth defending

**Only a VERIFIED backup is ever uploaded.** `core/backup.py` takes the
snapshot through SQLite's own backup API — a `shutil.copy` of a live database
can capture a torn write that opens cleanly and fails later — and proves it by
restoring it into a scratch database and counting the rows. If that check
fails, nothing is uploaded. Replacing a good snapshot with a broken one is
worse than having an old one.

**`CommitScheduler` was the obvious tool and is the wrong one.**
`huggingface_hub` ships it for exactly this use case, and its contract is
**append-only**: the docs warn that "deleting or overwriting a file might
corrupt your repository". A SQLite database is rewritten in place, constantly,
including while an uploader is reading it. Pointing the scheduler at a live
database ships torn files. A plain `upload_file` of a finished snapshot is a
git commit replacing one blob, which is safe to overwrite in a way the
scheduler's incremental diffing is not.

**Restoring only ever happens towards an EMPTY database.** `pull()` refuses if
a state file already exists. Overwriting a live database with an older snapshot
is the one direction that destroys data, so it is not a code path that exists.
On a rebuild there is no local file, which is exactly when a restore is wanted.
Mutation-guarded.

**The repo is created private.** It holds accounts. Mutation-guarded.

**`configured()` is intent; `last_push` is proof.** A token being set says
somebody meant to configure this. It says nothing about whether a byte ever
reached the Hub, and believing a snapshot exists when it does not is the
failure you discover on the day you need it.

## What was considered and rejected

| Option | Why not |
|---|---|
| HF persistent storage (`/data`) | Correct and continuous — **paid**. Still the right upgrade later. |
| Turso / libSQL free tier | SQLite-compatible, but a network database means a driver change through every call site, and a second provider to keep alive. |
| Cloudflare D1 | Free tier is generous; requires rewriting the storage layer away from local SQLite. |
| Supabase / Neon free Postgres | Same rewrite, plus a dialect change. |
| `CommitScheduler` on the live DB | Append-only contract; ships torn databases. See above. |

The Dataset-repo route needs **no new provider, no new account, no driver
change and no rewrite** — the storage layer stays local SQLite and gains a
sink. That is why it wins, not because it is the most sophisticated.

## Limits

- Private Dataset repos are free with a storage quota that a database measured
  in megabytes will not trouble.
- Every push is a commit. The repo's history grows; `huggingface_hub` exposes
  `super_squash_history` if it ever needs flattening.
- The snapshot is only as recent as the last successful push. Watch the
  **Durable storage** row rather than assuming.
