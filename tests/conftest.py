"""Test fixtures.

The integration's package __init__ imports Home Assistant, which is not a test
dependency here. These helpers load the Home-Assistant-free modules directly so
the parsing and API layers can be exercised on their own.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

PACKAGE = "controlmyspa_under_test"
SOURCE = Path(__file__).resolve().parent.parent / "custom_components" / "controlmyspa"

_package = types.ModuleType(PACKAGE)
_package.__path__ = [str(SOURCE)]
sys.modules[PACKAGE] = _package


def load_module(name: str):
    """Import one module of the integration without running its package init."""
    qualified = f"{PACKAGE}.{name}"
    if qualified in sys.modules:
        return sys.modules[qualified]

    spec = importlib.util.spec_from_file_location(qualified, SOURCE / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[qualified] = module
    spec.loader.exec_module(module)
    return module


const = load_module("const")
models = load_module("models")
api = load_module("api")
