# NBA correlations — deploy checklist

NBA correlations data is uploaded at runtime (drag-drop xlsx in the NBA tab) and
persisted to a Railway Volume. Nothing about the data lives in git.

## Railway Volume

Create a Volume on the Railway service and mount it at `/data`.

- Dashboard flow: **Service → Variables → Volumes → New Volume**
- Mount path: `/data`
- Size: 1 GB (smallest tier — the parsed JSON is under 2 MB even for a
  full-season 1,700-entry dataset)

Cost (verified against Railway's live pricing docs, April 2026): Volumes
bill at USD 0.00000006 per GB-second, which is roughly USD 0.16 per GB per
month of continuous usage. A 1 GB volume therefore costs about USD 0.16 per
month — well under the USD 5 monthly credit included with the Hobby plan.
Verify against Railway's current pricing page before finalizing in case
the rate has shifted.

## Environment variables

Optional: `NBA_DATA_DIR`. Defaults to `/data/nba`. Set only if you want the
app to read/write somewhere else (e.g. for local dev without a mounted
volume, set `NBA_DATA_DIR=./nba_data_local` and the dir will be created on
first upload).

No other NBA-specific env vars are required. The upload endpoint runs
`scripts/nba_parse_correlations.py` as a subprocess using the repo's
existing `python3` + venv layout from the Dockerfile / nixpacks.toml.

## First-deploy verification

1. Boot the service — it must NOT crash on an empty `/data/nba/`.
2. `GET /api/nba/correlations/meta` returns
   `{"status":"empty", ...}` — that's the cold-start placeholder.
3. Drop a valid xlsx into the NBA tab's upload card. Within 5 s the
   meta line should populate with row count + season.
4. Refresh the page. Meta line still populated → persistence working.
5. Redeploy the app. Meta line still populated → Volume is surviving
   deploys (if it's not, the Volume isn't mounted at `/data` correctly).

## Uploaded file layout

Under `/data/nba/`:

```
correlations_current.json.gz   # live dataset the app reads
correlations_meta.json         # "last updated" sidecar
correlations_history/          # last 7 uploads for rollback
  correlations_2026-04-21_091433.json.gz
  ...
```

## Rollback

`POST /api/nba/correlations/rollback` restores the newest file from
`correlations_history/`. The UI wraps this in a confirmation prompt. If
`correlations_history/` is empty, the endpoint returns 400 rather than
clearing current data.

## Non-goals

- The repo must never hold an xlsx snapshot (enforced in `.gitignore`).
- There is no bundled default dataset — staleness ambiguity is worse than
  an empty state. Cold start shows an explicit "upload your xlsx" card.
