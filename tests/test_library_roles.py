import json
import importlib.util
from pathlib import Path

module_path = Path(__file__).parents[1] / "extensions" / "no3d_asset_developer" / "library_roles.py"
spec = importlib.util.spec_from_file_location("no3d_library_roles_test", module_path)
library_roles = importlib.util.module_from_spec(spec)
spec.loader.exec_module(library_roles)


def test_roles_are_bound_to_machine_ids(tmp_path):
    marker = tmp_path / library_roles.MARKER_FILENAME
    marker.write_text(json.dumps({
        "schema_version": library_roles.SCHEMA,
        "library_id": library_roles.WIP_ID,
        "role": "wip",
        "verified_at": "2026-08-26T04:00:00Z",
    }))
    assert library_roles.require_wip(str(tmp_path))["role"] == "wip"
    try:
        library_roles.require_staged(str(tmp_path))
    except ValueError as error:
        assert "role mismatch" in str(error)
    else:
        raise AssertionError("WIP root was accepted as staged")


def test_missing_or_unverified_marker_fails_closed(tmp_path):
    try:
        library_roles.require_wip(str(tmp_path))
    except ValueError as error:
        assert "missing or invalid" in str(error)
    else:
        raise AssertionError("markerless root was accepted")
