# Project Radar

**English** | [简体中文](./README.zh-CN.md)

Scan a public GitHub repository and get the **Top 3 problems worth building** — ranked, evidenced, and explained.

Project Radar collects issues, pull requests, and discussions, groups them into recurring problems, judges each group with **typed judgments** (via [Jev / TypeSafe API](https://typesafe.ai), with a deterministic heuristic fallback), and scores everything with a transparent ranking engine. Every conclusion links back to the exact issues and PRs that support it.

## How it works

```
GitHub ──▶ collect ──▶ normalize/dedupe ──▶ cluster ──▶ judge (Jev) ──▶ rank ──▶ report
 issues     comments      bot/duplicate        TF-IDF     5 typed         weighted    Top 3 +
 pulls      timelines     removal              + overlap   questions      evidence    full
 discussions                                                        chain     candidates
```

1. **Collect** — issues (open + closed within the lookback window), pull requests, comments, issue timelines, and GraphQL discussions (if a token is provided). Budget-aware: every request is counted against the GitHub rate limit and collection degrades gracefully instead of failing.
2. **Normalize** — one artifact schema for issues/PRs/discussions, bot and duplicate filtering, comment blobs attached.
3. **Cluster** — TF-IDF similarity (titles weighted ×2) combined with a token-overlap matrix that catches reworded reports. Single-link components are then pruned of weakly-attached members and oversized components are re-split, so a pile of unrelated issues never becomes one "problem".
4. **Judge** — each candidate cluster is judged by Jev with five typed questions: `same_problem`, `recurring_independent`, `still_unresolved` (noul), `worth_building` (score), `problem_type` (choice). Without `TYPESAFE_API_KEY` a deterministic heuristic judge with the same schema runs instead — same output shape, zero network.
5. **Rank** — a deterministic scoring engine (no second LLM):

   | Signal | Weight |
   |---|---|
   | recurrence | 0.25 |
   | unresolved | 0.25 |
   | user_demand | 0.20 |
   | buildability | 0.15 |
   | cross_surface | 0.15 |

   Confirmed/rejected feedback from previous runs adjusts priority by title, so the radar learns per repository.

**Design rule:** the model only emits typed judgments. Counting, scoring, ranking, and evidence assembly are deterministic code — the same scan twice gives the same numbers.

## Quickstart

### Local

```bash
pip install -r requirements.txt
cp .env.example .env            # optional: add GITHUB_TOKEN / TYPESAFE_API_KEY
uvicorn backend.app.main:app --reload
```

Open http://127.0.0.1:8000 — the UI is served from the same process.

### Docker

```bash
docker compose up --build
```

## Configuration

Everything is environment-driven (see `.env.example`):

| Variable | Default | Purpose |
|---|---|---|
| `GITHUB_TOKEN` | — | raises rate limit 60 → 5000/h; enables Discussions (GraphQL) |
| `TYPESAFE_API_KEY` | — | Jev judge; without it the heuristic judge is used |
| `JEV_MODEL` | `jev-latest` | Jev model id |
| `EMBEDDING_BACKEND` | `tfidf` | `tfidf` (zero downloads) or `sentence-transformers` |
| `SCAN_LOOKBACK_DAYS` | `365` | closed artifacts considered |
| `MAX_ISSUES` / `MAX_PRS` / `MAX_DISCUSSIONS` | `400` / `200` / `100` | collection caps |
| `MAX_COMMENT_FETCHES` | `300` | comment enrichment cap |
| `MAX_TIMELINE_FETCHES` / `MAX_PULL_DETAILS` | `12` / `8` | fix-evidence enrichment caps |
| `GITHUB_MIN_BUDGET` | `20` | reserve below which enrichment is skipped |
| `DATA_DIR` | `./data` | SQLite DB + per-repo context files |

Keys are read only by the backend and never sent to the browser.

## API

| Method & path | Purpose |
|---|---|
| `POST /api/scans` | start a scan (`{"repo": "owner/name"}`), returns `scan_id` |
| `GET /api/scans/{id}` | progress (stage, %, label) |
| `GET /api/scans/{id}/report` | Top 3 problems + full candidates + evidence chain |
| `GET /api/candidates/{id}` | all candidates of a scan |
| `GET /api/problems/{id}` | one problem with artifacts |
| `POST /api/problems/{id}/feedback` | `confirm` / `reject` / `split` / `solved` / `minor` |
| `GET /api/repos` · `GET /api/repos/{owner}/{name}/context` | scanned repos + learned context |
| `POST /api/repos/{owner}/{name}/context/non_goals` | record a non-goal |
| `GET /api/health` | liveness |

## Report format

Each of the Top 3 problems answers four questions with evidence:

- **why it exists** — how many independent authors, over what span, on how many surfaces
- **why it is unresolved** — failed fix attempts, stale open issues, unresolved probability
- **why it is worth building** — `worth_building` score, demand signals, maintainer signals
- **minimal fix** — a concrete first step derived from the problem type

plus a chronological **evidence chain** linking every source issue/PR/discussion.

## Development

```bash
pip install -r requirements.txt
python -m pytest backend/tests -q     # 65 tests, no network required
```

Tests force `EMBEDDING_BACKEND=tfidf` and use a fake GitHub client, so CI needs no tokens.

```
backend/app/
  github/        REST + GraphQL collectors, rate-limit budgeting
  ingest/        normalization, dedupe/noise filter
  clustering/    TF-IDF + overlap graph, prune/split assembly
  judge/         Jev client, typed question specs, heuristic fallback
  ranking/       evidence extraction, deterministic scoring
  memory/        per-repo context, feedback learning
  db/            SQLite schema + helpers
  pipeline.py    orchestration
  main.py        FastAPI app
frontend/        zero-build vanilla JS UI
```

## License

MIT — see [LICENSE](LICENSE).
