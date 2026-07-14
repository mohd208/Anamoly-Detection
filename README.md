# anomaly-agent

Listens for Datadog-originated Kubernetes incident alerts in a Slack channel
(CrashLoopBackOff, OOMKilled, ImagePullBackOff, probe failures, ...), pulls
live diagnostics from the affected EKS cluster, and uses the `claude` CLI to
find the root cause:

- If the fix belongs in DevOps-owned files (Dockerfile, K8s manifests, Helm,
  Terraform, CI workflows) it makes the fix and opens a GitHub PR for review.
- If the fix requires application source code changes, it does **not** touch
  code - it posts a suggested fix back to the same Slack thread instead.

Runs as a single long-lived Python process on an EC2 host that already has an
authenticated `claude` CLI session (no Anthropic API key needed - it rides
the existing CLI login).

## How it fits together

```
Datadog ──alert──▶ Slack channel ◀──Socket Mode── this agent (on EC2)
                                                     │
                                                     ├─ aws eks update-kubeconfig (EC2 instance role)
                                                     ├─ kubectl describe/logs/get events   (read-only)
                                                     ├─ git clone + branch (repo from config/repo-map.yaml)
                                                     ├─ claude -p  (root cause + fix-or-suggest)
                                                     ├─ PyGithub PR creation (DevOps files only)
                                                     └─ Slack thread reply (status / PR link / suggestion)
```

See `deploy/eks-access-entry.md` for exactly how the EC2 instance authenticates
to EKS (IAM role -> IMDSv2 -> STS -> `aws eks get-token`, read-only RBAC).

## What you need to configure before running this

1. **Slack app** - Socket Mode enabled, bot token + app-level token, invited
   into the incident channel. Scopes: `channels:history`, `chat:write` (add
   `groups:history` too if the channel is private).
2. **GitHub token** - a fine-grained PAT scoped to just the repos in
   `config/repo-map.yaml`, with Contents and Pull requests read/write.
3. **`config/repo-map.yaml`** - map each cluster/namespace to the GitHub repo
   that owns its deployment config, and the file globs the agent may
   auto-fix (`fix_paths`). Anything outside `fix_paths` is never touched -
   enforced in code (`src/github/path_guard.py`), not just by prompting.
4. **AWS/EKS** - IAM instance role + EKS access entry per `deploy/eks-access-entry.md`.
5. **`.env`** - copy `.env.example` to `.env` and fill in the above.

## Local dev

```bash
python3 -m venv .venv
source .venv/bin/activate        # .venv\Scripts\activate on Windows
pip install -r requirements.txt
cp .env.example .env             # fill in values
python -m src.main
```

## Run on EC2

```bash
bash scripts/setup-ec2.sh        # installs/verifies aws-cli, kubectl, gh, checks claude login
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
sudo cp deploy/anomaly-agent.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now anomaly-agent
journalctl -u anomaly-agent -f   # or tail /var/log/anomaly-agent/agent.log
```

## Safety notes

- The agent only ever *reads* from the EKS cluster. It never runs `kubectl
  apply`/`edit`. Fixes flow through a PR and your existing GitHub Actions
  deploy pipeline.
- PRs are never auto-merged.
- File changes outside a repo's `fix_paths` allow-list are hard-reverted
  before commit (`src/github/path_guard.py`), even if the model attempted them.
- A per-incident cooldown (`INCIDENT_COOLDOWN_MINUTES`, default 30) prevents
  duplicate PRs from flapping alerts.

## Tests

```bash
pip install pytest
pytest
```
