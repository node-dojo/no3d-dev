import importlib.util
from pathlib import Path
from types import SimpleNamespace

module_path = Path(__file__).parents[1] / "extensions" / "no3d_asset_developer" / "solvet_bridge.py"
spec = importlib.util.spec_from_file_location("no3d_solvet_bridge_test", module_path)
solvet_bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(solvet_bridge)


def test_shared_solvet_validation_invokes_the_canonical_cli(monkeypatch, tmp_path):
    cli = tmp_path / "solvet" / "cli.js"
    cli.parent.mkdir()
    cli.write_text("// fixture")
    source = tmp_path / "product"
    source.mkdir()
    node = tmp_path / "node"
    node.write_text("")
    captured = {}

    monkeypatch.setattr(solvet_bridge.shutil, "which", lambda name: str(node) if name == "node" else None)
    monkeypatch.setattr(solvet_bridge.subprocess, "run", lambda command, **kwargs: (
        captured.update(command=command, kwargs=kwargs) or SimpleNamespace(returncode=0, stdout='{"ok":true}', stderr="")
    ))

    ok, _output = solvet_bridge.validate_entry(str(tmp_path), str(source))

    assert ok
    assert captured["command"] == [
        str(node), str(cli), "validate", str(source), "--profile", "workbench", "--json",
    ]
    assert captured["kwargs"]["cwd"] == str(tmp_path)
