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
            "OpenVINO was requested, but this ONNX Runtime install has no OpenVINO provider."
        )
    return [("OpenVINOExecutionProvider", {"device_type": device}), "CPUExecutionProvider"]


def open_session(path: Path, execution: str, device: str):
    import onnxruntime as ort

    return ort.InferenceSession(
        str(path),
        providers=execution_providers(execution, device),
    )
