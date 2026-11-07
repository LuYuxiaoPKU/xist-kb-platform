import os
import subprocess
import sys
from pathlib import Path

from xist_kb import __version__
from xist_kb.paths import PROJECT_ROOT

PY = sys.executable


def test_version_is_set():
    assert __version__


def test_data_dir_honours_env(tmp_path):
    """paths.py must re-read XIST_KB_DATA at import, not cache it at first use."""
    env = os.environ | {"XIST_KB_DATA": str(tmp_path), "PYTHONPATH": str(PROJECT_ROOT / "src")}
    out = subprocess.run(
        [PY, "-c", "from xist_kb.paths import DATA_DIR; print(DATA_DIR)"],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert Path(out) == tmp_path


def test_unknown_layer_raises():
    import pytest

    from xist_kb.paths import layer_dir

    with pytest.raises(ValueError, match="unknown data layer"):
        layer_dir("nope")


def test_known_layers_resolve():
    from xist_kb.paths import layer_dir

    for name in ("bronze", "silver", "gold", "index"):
        assert layer_dir(name).name == name
