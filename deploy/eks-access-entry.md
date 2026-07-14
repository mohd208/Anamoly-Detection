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

## 2. Grant that role RBAC view access on each target EKS cluster

Get the role ARN first:
```bash
ROLE_ARN=$(aws iam get-role --role-name anomaly-agent-eks-readonly --query 'Role.Arn' --output text)
```

### If the cluster uses EKS access entries (current default, clusters created/updated recently)
```bash
aws eks create-access-entry \
  --cluster-name <CLUSTER_NAME> \
  --principal-arn "$ROLE_ARN" \
  --type STANDARD

aws eks associate-access-policy \
  --cluster-name <CLUSTER_NAME> \
  --principal-arn "$ROLE_ARN" \
  --policy-arn arn:aws:eks::aws:cluster-access-policy/AmazonEKSViewPolicy \
  --access-scope type=cluster
```

### If the cluster still uses the legacy `aws-auth` ConfigMap
Add a `mapRoles` entry bound to the built-in `view` ClusterRole:
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
helpers (`src/k8s/eks.py`) will work identically at runtime.

Repeat step 2 for every EKS cluster the agent needs to reach.
