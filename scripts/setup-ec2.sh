#!/usr/bin/env bash
# One-time bootstrap for the EC2 host running the anomaly-agent.
# Installs/verifies: python3, aws-cli v2, kubectl, gh CLI. Verifies `claude`
# is already logged in (this script does not install or authenticate Claude -
# per the setup, that's already done on this box).
set -euo pipefail

echo "== Checking Python 3 =="
if ! command -v python3 >/dev/null; then
  echo "python3 not found. Install Python 3.10+ before continuing." >&2
  exit 1
fi
python3 --version

echo "== Checking/installing AWS CLI v2 =="
if ! command -v aws >/dev/null; then
  curl -sSL "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o /tmp/awscliv2.zip
  unzip -q /tmp/awscliv2.zip -d /tmp
  sudo /tmp/aws/install
fi
aws --version

echo "== Checking/installing kubectl =="
if ! command -v kubectl >/dev/null; then
  KUBECTL_VERSION=$(curl -sL https://dl.k8s.io/release/stable.txt)
  curl -sLO "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/amd64/kubectl"
  chmod +x kubectl
  sudo mv kubectl /usr/local/bin/kubectl
fi
kubectl version --client

echo "== Checking/installing GitHub CLI (gh) =="
if ! command -v gh >/dev/null; then
  type -p curl >/dev/null || sudo apt-get install -y curl
  curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg | sudo dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg
  sudo chmod go+r /usr/share/keyrings/githubcli-archive-keyring.gpg
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" | sudo tee /etc/apt/sources.list.d/github-cli.list > /dev/null
  sudo apt-get update && sudo apt-get install -y gh
fi
gh --version

echo "== Verifying claude CLI is installed and logged in =="
if ! command -v claude >/dev/null; then
  echo "claude CLI not found on PATH. Install/login it before running the agent." >&2
  exit 1
fi
claude --version
if ! claude -p "reply with OK" --output-format json >/tmp/claude-check.json 2>/dev/null; then
  echo "claude CLI does not appear to be logged in / working. Run 'claude login' as the service user." >&2
  exit 1
fi
echo "claude CLI OK."

echo "== Verifying IAM role / EKS access (informational) =="
aws sts get-caller-identity || echo "No instance role credentials found yet - attach the IAM instance profile (see deploy/eks-access-entry.md)."

echo "== Done. Next steps =="
cat <<'EOF'
1. Copy this project to /opt/anomaly-agent on this host (git clone or scp).
2. cp .env.example .env and fill in Slack/GitHub values.
3. python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
4. sudo cp deploy/anomaly-agent.service /etc/systemd/system/
5. sudo mkdir -p /var/log/anomaly-agent && sudo useradd -r anomaly-agent || true
6. sudo systemctl daemon-reload && sudo systemctl enable --now anomaly-agent
EOF
