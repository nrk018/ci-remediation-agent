# CI Failure Remediation Agent

A prototype that diagnoses failed GitHub Actions runs, drafts a fix for a human to review, and exposes the same steps as MCP tools. It does not merge pull requests, and it does not try to fix application-logic bugs. The first version covers build, dependency, configuration, and test-infrastructure failures.

## How it fits together

GitHub sends a `workflow_run` event to `POST /webhook`. FastAPI checks the HMAC signature, ignores runs that did not fail, and starts the agent in the background. The agent and the MCP server call one tools module.

LangGraph runs `ingest → retrieve → diagnose → route`. Below the confidence threshold it reports the finding and stops. Otherwise it drafts a patch, checks that the patch applies and still parses, and opens a pull request only when `approved` is true. A retry cap limits fix attempts.

```
GitHub workflow_run (failed)
        |
        v
   FastAPI /webhook
        |
        v
   LangGraph agent ---- shared tools ---- GitHub REST
        ^                      |
        |                      +---- Postgres + pgvector
   MCP server                  |
        ^                      +---- OpenAI (or the offline retriever)
        |
   IDE / other agent
```

## Layout

- `app/main.py` — webhook
- `app/github_client.py` — Actions logs, file contents, pull requests. No merge API.
- `app/logs.py` — failed-step window, signature, secret redaction
- `app/memory.py` — pgvector search, with an in-memory store for tests
- `app/embedding.py` — `text-embedding-3-small` when `OPENAI_API_KEY` is set, otherwise a deterministic hash embedding
- `app/graph.py` — diagnosis graph
- `app/tools.py` — `get_failed_runs`, `fetch_logs`, `search_similar_failures`, `diagnose_failure`, `propose_fix`, `open_fix_pr`
- `mcp_server/server.py` — MCP wrapper. `open_fix_pr` refuses unless `approved` is true
- `eval/cases/` — 25 seeded failures, five per category, including one ambiguous case that should be declined
- `sql/001_init.sql` — `failures` table and HNSW cosine index

## Run it

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
docker compose up --build
```

Docker is optional. With no `DATABASE_URL`, the service keeps failure memory in process. With no `OPENAI_API_KEY`, diagnosis copies the category from the nearest past failure and uses that failure's patch when it applies. Set `CI_REMEDIATION_OFFLINE=1` to force that path even if a key is present.

The GitHub token should be limited to the test repositories, with contents and pull request permissions only.

## Harness token and AWS Postgres

Create a free Harness account, then Profile, My API Keys, an API key, and a token. Copy the token once. Copy the account ID from the signed-in URL. Put both in `.env` as `HARNESS_API_TOKEN` and `HARNESS_ACCOUNT_ID`.

That token authenticates this app to the Harness API. It is not a model key. The free plan's $5 of hosted LLM usage is spent only by Worker Agents inside Harness.

For the database, create one Single-AZ RDS for PostgreSQL 16 instance on `db.t4g.micro` or `db.t3.micro`, 20 GB, in `ap-south-1`. Allow inbound port 5432 only from your current IP. Set `DATABASE_URL` to the endpoint with `sslmode=require`. Hosts other than localhost get `sslmode=require` added automatically.

```bash
python -m app.init_db
```

That applies `sql/001_init.sql` and checks that a similarity search returns the row it just inserted. `GET /health` reports `database` and `harness` as `ok`, `down`, or `unconfigured`. It does not return the token or the database password.

MCP stdio server:

```bash
python -m mcp_server.server
```

## Guardrails

- Nothing merges. The GitHub client has no merge method.
- `open_fix_pr` returns an error when `approved` is false.
- The webhook diagnoses and can draft a patch, but it does not open a pull request.
- Patches must apply, must still parse, and may only touch a workflow or a manifest.
- Logs are redacted before they are embedded or sent to a model.
- Every webhook request is HMAC-verified.

## Evaluation

The 25 cases are seeded. They are not organic production failures. Twenty are clear variants (four per category: dependency, flaky test, config, timeout, other). Five are ambiguous and should be declined.

```bash
python -m eval.catalog   # refresh eval/cases/*.json
python -m eval.run_eval
pytest
```

`run_eval` prints top-1 root-cause accuracy, retrieval hit rate at 3, first-run fix success, and the decline rate. It also scores the same cases with an empty memory so the contribution of retrieval is visible. Misses stay in the output.

On the offline hash embedder, the seeded set currently scores:

- 25 cases (20 clear, 5 ambiguous)
- Top-1 root-cause accuracy on clear cases: 100%
- Retrieval hit rate at 3: 100%
- First-run fix success on clear cases: 100%
- Ambiguous cases declined: 100%
- With an empty memory, clear-case accuracy drops to 0% and every case is declined

Those figures are for seeded failures, not production incidents. A run with `OPENAI_API_KEY` set will differ.

## Not in this version

Harness pipeline remediation, automatic merges, policy-as-code gates, and Slack or Jira notifications. The Harness personal access token is wired for API checks only.
