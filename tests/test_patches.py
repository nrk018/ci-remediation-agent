import pytest

from app.patches import PatchError, apply_unified_diff, make_unified_diff, validate_patch


def test_diff_roundtrip_and_yaml_rejection():
    before = "name: ci\non: [push]\njobs:\n  build:\n    runs-on: ubuntu-latest\n"
    after = "name: ci\non: [push]\njobs:\n  build:\n    runs-on: ubuntu-22.04\n"
    diff = make_unified_diff(".github/workflows/ci.yml", before, after)
    assert apply_unified_diff(before, diff) == after
    ok, error, patched = validate_patch(".github/workflows/ci.yml", before, diff)
    assert ok and error is None and patched == after

    broken = make_unified_diff(".github/workflows/ci.yml", before, "runs-on: [\n")
    ok, error, patched = validate_patch(".github/workflows/ci.yml", before, broken)
    assert not ok
    assert patched is None
    assert error


def test_secret_and_unrelated_path_are_rejected():
    before = "name: ci\n"
    diff = "--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n-name: ci\n+TOKEN=ghp_abcdefghijklmnopqrstuvwxyz012345\n"
    ok, error, _patched = validate_patch("app.py", before, diff)
    assert not ok
    assert "workflow" in error.lower() or "manifest" in error.lower() or "refusing" in error.lower()

    secret_diff = make_unified_diff(
        "requirements.txt",
        "numpy==1.0\n",
        "numpy==1.0\nTOKEN=ghp_abcdefghijklmnopqrstuvwxyz012345\n",
    )
    ok, error, _patched = validate_patch("requirements.txt", "numpy==1.0\n", secret_diff)
    assert not ok
    assert "secret" in error.lower()
    with pytest.raises(PatchError):
        apply_unified_diff("numpy==1.0\n", "not a diff")
