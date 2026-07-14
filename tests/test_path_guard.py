from pathlib import Path
from unittest.mock import patch

from src.github.path_guard import enforce_path_allow_list

FIX_PATHS = ["**/Dockerfile*", "**/*.tf", "**/k8s/**", ".github/workflows/**"]


def test_allows_files_matching_fix_paths_and_does_not_revert_them():
    with patch("src.github.path_guard.changed_files", return_value=["Dockerfile", "k8s/deployment.yaml"]), \
         patch("src.github.path_guard.discard_file") as mock_discard:
        result = enforce_path_allow_list(Path("/tmp/repo"), FIX_PATHS)

        assert result.allowed == ["Dockerfile", "k8s/deployment.yaml"]
        assert result.reverted == []
        mock_discard.assert_not_called()


def test_allows_nested_devops_files_via_recursive_glob():
    files = ["services/api/Dockerfile", "infra/main.tf", "charts/api/k8s/deployment.yaml"]
    with patch("src.github.path_guard.changed_files", return_value=files), \
         patch("src.github.path_guard.discard_file") as mock_discard:
        result = enforce_path_allow_list(Path("/tmp/repo"), FIX_PATHS)

        assert result.allowed == files
        mock_discard.assert_not_called()


def test_reverts_files_outside_fix_paths_eg_application_source_code():
    with patch("src.github.path_guard.changed_files", return_value=["Dockerfile", "src/index.py"]), \
         patch("src.github.path_guard.discard_file") as mock_discard:
        result = enforce_path_allow_list(Path("/tmp/repo"), FIX_PATHS)

        assert result.allowed == ["Dockerfile"]
        assert result.reverted == ["src/index.py"]
        mock_discard.assert_called_once_with(Path("/tmp/repo"), "src/index.py")


def test_reverts_everything_when_no_files_match_allow_list():
    with patch("src.github.path_guard.changed_files", return_value=["README.md"]), \
         patch("src.github.path_guard.discard_file"):
        result = enforce_path_allow_list(Path("/tmp/repo"), FIX_PATHS)

        assert result.allowed == []
        assert result.reverted == ["README.md"]
