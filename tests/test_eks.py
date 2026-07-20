from unittest.mock import MagicMock, patch

import pytest

from src.k8s.eks import _self_role_arn, ensure_cluster_access


def _completed(returncode=0, stdout="", stderr=""):
    result = MagicMock()
    result.returncode = returncode
    result.stdout = stdout
    result.stderr = stderr
    return result


def test_self_role_arn_converts_assumed_role_sts_arn_to_iam_role_arn():
    sts_arn = "arn:aws:sts::478546323821:assumed-role/instanceRoleecai-agentrtctek/i-0e3d388d341a6a769"
    with patch("subprocess.run", return_value=_completed(stdout=sts_arn + "\n")):
        assert _self_role_arn() == "arn:aws:iam::478546323821:role/instanceRoleecai-agentrtctek"


def test_self_role_arn_passes_through_non_assumed_role_arns():
    plain_arn = "arn:aws:iam::478546323821:user/someone"
    with patch("subprocess.run", return_value=_completed(stdout=plain_arn + "\n")):
        assert _self_role_arn() == plain_arn


def test_ensure_cluster_access_succeeds_when_grant_is_new():
    with patch("src.k8s.eks._self_role_arn", return_value="arn:aws:iam::123:role/agent"), \
         patch("subprocess.run", side_effect=[_completed(returncode=0), _completed(returncode=0)]):
        ensure_cluster_access("my-cluster", "us-west-2")  # should not raise


def test_ensure_cluster_access_treats_already_exists_as_success():
    with patch("src.k8s.eks._self_role_arn", return_value="arn:aws:iam::123:role/agent"), \
         patch(
             "subprocess.run",
             side_effect=[
                 _completed(returncode=254, stderr="An error occurred (ResourceInUseException): ..."),
                 _completed(returncode=0),
             ],
         ):
        ensure_cluster_access("my-cluster", "us-west-2")  # should not raise


def test_ensure_cluster_access_raises_on_genuine_create_failure():
    with patch("src.k8s.eks._self_role_arn", return_value="arn:aws:iam::123:role/agent"), \
         patch("subprocess.run", return_value=_completed(returncode=254, stderr="AccessDeniedException: nope")):
        with pytest.raises(RuntimeError, match="Failed to create EKS access entry"):
            ensure_cluster_access("my-cluster", "us-west-2")


def test_ensure_cluster_access_raises_on_associate_failure():
    with patch("src.k8s.eks._self_role_arn", return_value="arn:aws:iam::123:role/agent"), \
         patch(
             "subprocess.run",
             side_effect=[_completed(returncode=0), _completed(returncode=254, stderr="nope")],
         ):
        with pytest.raises(RuntimeError, match="Failed to associate EKS view policy"):
            ensure_cluster_access("my-cluster", "us-west-2")
