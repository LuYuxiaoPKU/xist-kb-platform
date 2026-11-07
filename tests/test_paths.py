import pytest

from xist_kb import __version__
from xist_kb.paths import layer_dir


def test_version_is_set():
    assert __version__


def test_unknown_layer_raises():
    with pytest.raises(ValueError, match="unknown data layer"):
        layer_dir("nope")


def test_known_layers_resolve():
    for name in ("bronze", "silver", "gold", "index"):
        assert layer_dir(name).name == name
