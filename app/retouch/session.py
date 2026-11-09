import json
from pathlib import Path


def execution_providers(execution: str, device: str) -> list[str | tuple[str, dict[str, str]]]:
    """CPU is the default. OpenVINO is used only when asked for, and only if it is installed."""

    if execution == "cpu":
        return ["CPUExecutionProvider"]
    if execution != "openvino":
        raise ValueError(f"unknown retouch execution {execution!r}")
    import onnxruntime as ort

    if "OpenVINOExecutionProvider" not in ort.get_available_providers():
        raise RuntimeError(
            "OpenVINO was requested, but this ONNX Runtime install has no OpenVINO provider. "
            "Use the Intel GPU Docker override or install onnxruntime-openvino (see README)."
        )
    # Accept older .env values, but send the current OpenVINO option format.
    device, separator, precision = device.partition("_FP")
    options = {"device_type": device}
    if separator:
        if precision not in {"16", "32"}:
            raise ValueError(f"unsupported OpenVINO precision FP{precision}")
        options["load_config"] = json.dumps(
            {device: {"INFERENCE_PRECISION_HINT": f"f{precision}"}}
        )
    return [("OpenVINOExecutionProvider", options), "CPUExecutionProvider"]


def open_session(path: Path, execution: str, device: str):
    import onnxruntime as ort

    providers = execution_providers(execution, device)
    options = ort.SessionOptions()
    if execution == "openvino":
        options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_DISABLE_ALL
    session = ort.InferenceSession(
        str(path),
        sess_options=options,
        providers=providers,
    )
    if execution == "openvino":
        # ORT may catch provider initialization errors and silently recreate on CPU.
        if "OpenVINOExecutionProvider" not in session.get_providers():
            raise RuntimeError(
                f"OpenVINO could not load on {device}. Check the Intel compute driver, "
                "/dev/dri access, and the runtime logs. CPU-only fallback was rejected."
            )
        session.disable_fallback()
    return session
