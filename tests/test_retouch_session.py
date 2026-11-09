import json
from pathlib import Path
from unittest.mock import Mock

import onnxruntime as ort
import pytest

from app.retouch.catalog import CATALOG
from app.retouch.engine import OnnxRetoucher
from app.retouch.session import execution_providers, open_session


def test_legacy_gpu_precision_is_translated(monkeypatch):
    monkeypatch.setattr(ort, "get_available_providers", lambda: ["OpenVINOExecutionProvider"])
    provider, options = execution_providers("openvino", "GPU_FP16")[0]
    assert provider == "OpenVINOExecutionProvider"
    assert options["device_type"] == "GPU"
    assert json.loads(options["load_config"]) == {
        "GPU": {"INFERENCE_PRECISION_HINT": "f16"}
    }


@pytest.mark.parametrize("model_id", list(CATALOG))
def test_only_realesrgan_uses_openvino(monkeypatch, tmp_path, model_id):
    spec = CATALOG[model_id]
    (tmp_path / spec.filename).touch()
    factory = Mock()
    monkeypatch.setattr("app.retouch.engine.open_session", factory)
    retoucher = OnnxRetoucher(tmp_path, execution="openvino", openvino_device="GPU")
    assert retoucher._session(spec) is factory.return_value
    expected = "openvino" if model_id in {"upscale", "scale"} else "cpu"
    factory.assert_called_once_with(tmp_path / spec.filename, expected, "GPU")
    assert retoucher._session(spec) is factory.return_value
    assert factory.call_count == 1


@pytest.mark.parametrize("active", [True, False])
def test_openvino_does_not_silently_fall_back(monkeypatch, active):
    monkeypatch.setattr(ort, "get_available_providers", lambda: ["OpenVINOExecutionProvider"])
    session = Mock()
    session.get_providers.return_value = (
        ["OpenVINOExecutionProvider", "CPUExecutionProvider"] if active
        else ["CPUExecutionProvider"]
    )
    factory = Mock(return_value=session)
    monkeypatch.setattr(ort, "InferenceSession", factory)
    if active:
        assert open_session(Path("model.onnx"), "openvino", "GPU") is session
        session.disable_fallback.assert_called_once()
    else:
        with pytest.raises(RuntimeError, match="CPU-only fallback was rejected"):
            open_session(Path("model.onnx"), "openvino", "GPU")
    assert factory.call_args.kwargs["providers"][0] == (
        "OpenVINOExecutionProvider", {"device_type": "GPU"}
    )
    assert factory.call_args.kwargs["sess_options"].graph_optimization_level == (
        ort.GraphOptimizationLevel.ORT_DISABLE_ALL
    )
