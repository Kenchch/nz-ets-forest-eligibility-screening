"""Exercise wrapper parameter forwarding without an ArcGIS installation."""

import importlib.machinery
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest


@pytest.mark.parametrize("value, expected", [(0.0, 0.0), (None, 0.80), (0.4, 0.4)])
def test_arcgis_preserves_zero_reject_threshold(monkeypatch, value, expected):
    import ets_screening.load as load
    import ets_screening.screen as screen

    monkeypatch.setitem(sys.modules, "arcpy", SimpleNamespace(AddMessage=lambda message: None))
    path = Path(__file__).resolve().parents[1] / "arcgis" / "ets_screening.pyt"
    loader = importlib.machinery.SourceFileLoader("test_ets_toolbox", str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    monkeypatch.setattr(load, "read_layer", lambda *args, **kwargs: object())
    seen = []
    def run(*args):
        seen.append(args[4])
        return {}
    monkeypatch.setattr(screen, "run_screening", run)
    parameters = [SimpleNamespace(valueAsText=name) for name in ("c", "p", "d", "out")]
    parameters.append(SimpleNamespace(value=value))
    module.ScreenPost1989Candidates().execute(parameters, None)
    assert seen == [expected]


def test_arcgis_reports_validation_failures_as_tool_errors(monkeypatch):
    import ets_screening.load as load

    class ExecuteError(Exception):
        pass

    errors = []
    monkeypatch.setitem(
        sys.modules,
        "arcpy",
        SimpleNamespace(AddMessage=lambda message: None, AddError=errors.append, ExecuteError=ExecuteError),
    )
    path = Path(__file__).resolve().parents[1] / "arcgis" / "ets_screening.pyt"
    loader = importlib.machinery.SourceFileLoader("test_ets_toolbox_errors", str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)

    def invalid(*args, **kwargs):
        raise load.InputValidationError("candidates uses EPSG:4326; expected EPSG:2193")

    monkeypatch.setattr(load, "read_layer", invalid)
    parameters = [SimpleNamespace(valueAsText=name) for name in ("c", "p", "d", "out")]
    parameters.append(SimpleNamespace(value=None))
    with pytest.raises(ExecuteError):
        module.ScreenPost1989Candidates().execute(parameters, None)
    assert errors == ["candidates uses EPSG:4326; expected EPSG:2193"]
