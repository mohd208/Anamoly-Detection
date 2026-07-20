# Connecting the EC2 agent to EKS

The agent never stores kubeconfig credentials. It authenticates as the EC2
instance's IAM role, via IMDSv2 -> STS -> the `aws eks get-token` exec
credential plugin that `aws eks update-kubeconfig` wires up automatically.
Read access only - the agent diagnoses via `kubectl describe/logs/get events`,
it never applies changes to the cluster. Fixes go through a PR and your
existing GitHub Actions deploy pipeline.

## 1. Create the IAM role and instance profile

```bash
aws iam create-role \
  --role-name anomaly-agent-eks-readonly \
  --assume-role-policy-document '{
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Principal": {"Service": "ec2.amazonaws.com"},
      "Action": "sts:AssumeRole"
    }]
  }'

aws iam put-role-policy \
  --role-name anomaly-agent-eks-readonly \
  --policy-name eks-readonly \
  --policy-document file://deploy/iam-policy.json

aws iam create-instance-profile --instance-profile-name anomaly-agent-eks-readonly
aws iam add-role-to-instance-profile \
  --instance-profile-name anomaly-agent-eks-readonly \
  --role-name anomaly-agent-eks-readonly

# Attach to the existing EC2 instance:
aws ec2 associate-iam-instance-profile \
  --instance-id <YOUR_EC2_INSTANCE_ID> \
  --iam-instance-profile Name=anomaly-agent-eks-readonly
```

## 2. Per-cluster EKS access - now automatic, nothing to do here

AWS IAM permissions (even `AdministratorAccess`) only cover the *AWS API*
side (`eks:DescribeCluster` etc). EKS keeps a separate, per-cluster
Kubernetes-RBAC layer (access entries) that IAM admin does **not**
automatically grant - that's a deliberate AWS security boundary, not a bug.

`src/k8s/eks.py`'s `ensure_kubeconfig()` now calls `ensure_cluster_access()`
first, which self-grants this instance's IAM role a read-only access entry
(`AmazonEKSViewPolicy`) on whatever cluster the incident names, the first
time it's needed. It's idempotent (safe to call every time - a benign
`ResourceInUseException` on repeat calls is treated as success), so there is
**no manual step and no script to run per cluster** - any new cluster the
agent is ever pointed at gets access automatically on first use.

This requires the instance role to have `eks:CreateAccessEntry` and
`eks:AssociateAccessPolicy` (included in `deploy/iam-policy.json`) - already
covered if the role has `AdministratorAccess`.

If your clusters still use the legacy `aws-auth` ConfigMap instead of access
entries, self-granting isn't possible via the AWS API (it requires a
`kubectl edit` on the ConfigMap itself, which needs pre-existing cluster
access - a chicken-and-egg problem). Add a `mapRoles` entry once, manually:
```yaml
# kubectl edit configmap aws-auth -n kube-system
mapRoles: |
  - rolearn: arn:aws:iam::<ACCOUNT_ID>:role/anomaly-agent-eks-readonly
    username: anomaly-agent
    groups:
      - anomaly-agent-viewers
---
# apply once (ClusterRoleBinding to the built-in "view" ClusterRole):
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: anomaly-agent-view
subjects:
  - kind: Group
    name: anomaly-agent-viewers
    apiGroup: rbac.authorization.k8s.io
roleRef:
  kind: ClusterRole
  name: view
  apiGroup: rbac.authorization.k8s.io
```

## 3. Verify from the EC2 box

```bash
aws sts get-caller-identity   # should show the anomaly-agent-eks-readonly role
aws eks update-kubeconfig --name <CLUSTER_NAME> --region <REGION> --kubeconfig /tmp/test-kubeconfig
kubectl --kubeconfig /tmp/test-kubeconfig get pods -n <SOME_NAMESPACE>
```

If this returns pods without error, the agent's `ensure_kubeconfig`/`kubectl`
helpers (`src/k8s/eks.py`) will work identically at runtime - including
against any cluster you haven't tested yet, since access is granted
on-demand.
