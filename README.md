# anomaly-agent

Listens for Datadog-originated Kubernetes incident alerts in a Slack channel
(CrashLoopBackOff, OOMKilled, ImagePullBackOff, probe failures, ...), pulls
live diagnostics from the affected EKS cluster, and uses the `claude` CLI to
find the root cause:

- If the fix belongs in DevOps-owned files (Dockerfile, K8s manifests, Helm,
  Terraform, CI workflows) it makes the fix and opens a GitHub PR for review.
- If the fix requires application source code changes, it does **not** touch
  code - it posts a suggested fix back to the same Slack thread instead.

Runs on an EC2 host that already has an authenticated `claude` CLI session
(no Anthropic API key needed - it rides the existing CLI login), served via
FastAPI/uvicorn for the same operational shape as your other agents.

## How it fits together

```
Datadog ──alert──▶ Slack channel ◀──Socket Mode── this agent (on EC2)
                                                     │
                                                     ├─ aws eks update-kubeconfig (EC2 instance role)
                                                     ├─ kubectl describe/logs/get events   (read-only)
                                                     ├─ git clone + branch (repo = f"{GITHUB_ORG}/{namespace}")
                                                     ├─ claude -p  (root cause + fix-or-suggest)
                                                     ├─ PyGithub PR creation (DevOps files only)
                                                     └─ Slack thread reply (status / PR link / suggestion)
```

Slack Socket Mode makes an *outbound* connection to Slack - it doesn't accept
inbound HTTP itself. `app/main.py` wraps it in a tiny FastAPI app: on startup
it launches the Socket Mode listener on a background thread, and exposes
`GET /health` so it can be run/monitored via uvicorn like your other
FastAPI-based agents.

See `deploy/eks-access-entry.md` for exactly how the EC2 instance authenticates
to EKS (IAM role -> IMDSv2 -> STS -> `aws eks get-token`, read-only RBAC).

## Layout

```
app/
  main.py      # FastAPI app + entrypoint (uvicorn app.main:app)
  config.py    # env var loading
  listener.py  # Slack Socket Mode listener
  agent.py     # incident pipeline + Slack message templates
  parser.py    # Incident type + Datadog tag extraction
  k8s.py       # EKS kubeconfig (self-granting access) + kubectl diagnostics
  github.py    # repo resolution, git ops, path allow-list guard, PR creation
  claude.py    # claude CLI runner + prompt templates
  state.py     # JSON store + incident cooldown/dedupe
config/fix-paths.yaml   # allow-listed DevOps file globs
deploy/                 # systemd unit, IAM policy, EKS access doc
scripts/setup-ec2.sh    # EC2 bootstrap
tests/                  # one test file per app/ module
```

## What you need to configure before running this

1. **Slack app** - Socket Mode enabled, bot token + app-level token, invited
   into the incident channel. Scopes: `channels:history`, `chat:write` (add
   `groups:history` too if the channel is private).
2. **GitHub token + org** - a fine-grained PAT with Contents and Pull requests
   read/write, plus `GITHUB_ORG` in `.env`. The repo for an incident is
   computed as `f"{GITHUB_ORG}/{namespace}"` - cluster/namespace come
   dynamically from the Slack message itself (`app/github.py`), so
   there's no static mapping table to maintain. This assumes your k8s
   namespace names match your GitHub repo names exactly - if that's not
   true for you, this is the one function to change. Set the optional
   `GITHUB_REPO` env var to pin every incident to one fixed repo instead
   (useful for testing, or if you only have a single repo today).
3. **`config/fix-paths.yaml`** - a single, repo-agnostic list of glob patterns
   the agent may auto-fix (Dockerfile, k8s manifests/Helm, Terraform, CI
   workflows, wherever they live in a repo). Anything outside it is never
   touched, enforced in code (`app/github.py`), not just by
   prompting.
4. **AWS/EKS** - IAM instance role + EKS access entry per `deploy/eks-access-entry.md`.
5. **`.env`** - copy `.env.example` to `.env` and fill in the above.

## Local dev

```bash
python3 -m venv .venv
source .venv/bin/activate        # .venv\Scripts\activate on Windows
pip install -r requirements.txt
cp .env.example .env             # fill in values
uvicorn app.main:app --reload --port 8000
```

`curl localhost:8000/health` should return `{"status": "ok", "slack_listener_alive": true}`.

## Run on EC2

```bash
bash scripts/setup-ec2.sh        # installs/verifies aws-cli, kubectl, gh, checks claude login
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
sudo cp deploy/anomaly-agent.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now anomaly-agent
journalctl -u anomaly-agent -f   # or tail /var/log/anomaly-agent/agent.log
curl localhost:8000/health
```

The systemd unit runs `uvicorn app.main:app --host 0.0.0.0 --port 8000` - same
entry point as local dev, just without `--reload`.

## Safety notes

- The agent only ever *reads* from the EKS cluster. It never runs `kubectl
  apply`/`edit`. Fixes flow through a PR and your existing GitHub Actions
  deploy pipeline.
- PRs are never auto-merged.
- File changes outside `config/fix-paths.yaml`'s allow-list are hard-reverted
  before commit (`app/github.py`), even if the model attempted them.
- A per-incident cooldown (`INCIDENT_COOLDOWN_MINUTES`, default 30) prevents
  duplicate PRs from flapping alerts.

## Tests

```bash
pip install pytest
pytest
```
