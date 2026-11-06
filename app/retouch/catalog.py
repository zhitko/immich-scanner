from dataclasses import dataclass


@dataclass(frozen=True)
class ExtraFile:
    filename: str
    sha256: str
    archive_name: str


@dataclass(frozen=True)
class ModelSpec:
    id: str
    filename: str
    version: str
    purpose: str
    license_id: str
    license_summary: str
    source_url: str
    download_url: str | None = None
    sha256: str | None = None
    archive_name: str | None = None
    extra: tuple[ExtraFile, ...] = ()

    def filenames(self) -> tuple[str, ...]:
        return (self.filename, *(item.filename for item in self.extra))


# CodeFormer is not listed. S-Lab License 1.0 limits it to non-commercial research.
# The ONNX files below are conversions of the official weights. Each checksum is pinned.
CATALOG: dict[str, ModelSpec] = {
    "upscale": ModelSpec(
        id="upscale",
        filename="realesr-general-x4v3.onnx",
        version="general-x4v3",
        purpose="Denoise",
        license_id="BSD-3-Clause",
        license_summary=(
            "Real-ESRGAN, Xintao Wang, BSD-3-Clause. "
            "This ONNX is a conversion of the official realesr-general-x4v3 weights "
            "from the v0.2.5.0 release, published by CoderViking. "
            "Those weights are the strong-denoise end of the official pair "
            "(denoise strength 1). It takes an RGB image in 0..1 and returns one at 4×. "
            "This export has one input. Denoise alone resizes that result back to the crop. "
            "With upscale on, the 4× image is kept and the other network is not run. "
            "A second input, if a graph has one, is a denoise strength, and this step passes 1."
        ),
        source_url="https://huggingface.co/CoderViking/realesr-general-x4v3-onnx",
        download_url=(
            "https://huggingface.co/CoderViking/realesr-general-x4v3-onnx/"
            "resolve/main/realesr-general-x4v3.onnx"
        ),
        sha256="1940a93ee08283a0a7286183186357b1688fe9fa8ede74604b424586aaddf112",
    ),
    "scale": ModelSpec(
        id="scale",
        filename="realesr-general-wdn-x4v3.onnx",
        version="general-wdn-x4v3",
        purpose="Upscale 4×",
        license_id="BSD-3-Clause",
        license_summary=(
            "Real-ESRGAN, Xintao Wang, BSD-3-Clause. "
            "Official realesr-general-wdn-x4v3 weights from the v0.2.5.0 release: "
            "the denoise-strength 0 end of that pair, which keeps texture. "
            "This ONNX is the conversion published by ricardo-manuel-22. "
            "Its weights match that official file, and the graph clips the 4× image to 0..1. "
            "One RGB input in 0..1. Used only when upscale is on and denoise is off, "
            "so the denoising network is not applied. "
            "A second input, if a graph has one, is a denoise strength, and this step passes 0."
        ),
        source_url="https://huggingface.co/ricardo-manuel-22/editoria-models",
        download_url=(
            "https://huggingface.co/ricardo-manuel-22/editoria-models/"
            "resolve/main/realesr-general-wdn-x4v3.onnx"
        ),
        sha256="5073c57599850fe59320473ab5e07a91ac7de3af916ef44d5eef2218c7d0b33a",
    ),
    "faces": ModelSpec(
        id="faces",
        filename="gfpgan-v1.4.onnx",
        version="v1.4",
        purpose="Face restoration",
        license_id="Apache-2.0",
        license_summary=(
            "GFPGAN v1.4, Tencent ARC, Apache-2.0, with the third-party notices in that "
            "repository (StyleGAN2's NVIDIA license and DFDNet's CC-BY-NC-SA cover parts of "
            "the GFPGAN source). This ONNX is a conversion of the official GFPGANv1.4.pth, "
            "published by HowToSD. The graph takes a 512×512 RGB face in -1..1 and returns one. "
            "CodeFormer is not used: S-Lab License 1.0 is non-commercial research."
        ),
        source_url="https://huggingface.co/HowToSD/GFPGAN-ONNX",
        download_url="https://huggingface.co/HowToSD/GFPGAN-ONNX/resolve/main/GFPGANv1.4.onnx",
        sha256="15c36ba1a8304e077a9d99954427eac3fb604bb790636dd5e34e72cdeb0830d8",
    ),
    "face-detection": ModelSpec(
        id="face-detection",
        filename="face_detection_yunet_2023mar.onnx",
        version="2023mar",
        purpose="Find faces before restoration",
        license_id="Apache-2.0",
        license_summary=(
            "YuNet face detector from the OpenCV Zoo, Apache-2.0. "
            "The five landmarks are the person's right eye, left eye, nose, "
            "right mouth corner, and left mouth corner."
        ),
        source_url="https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet",
        download_url=(
            "https://github.com/opencv/opencv_zoo/raw/main/models/"
            "face_detection_yunet/face_detection_yunet_2023mar.onnx"
        ),
        sha256="8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4",
    ),
    "colorize": ModelSpec(
        id="colorize",
        filename="ddcolor.onnx",
        version="paper-tiny",
        purpose="Colorize",
        license_id="Apache-2.0",
        license_summary=(
            "DDColor, Xiaoyang Kang and others, Apache-2.0. "
            "This ONNX is Qualcomm AI Hub's export of ddcolor_paper_tiny. "
            "It takes a 256×256 gray RGB image in 0..1 and returns Lab a,b. "
            "Lightness stays from the scan. The weights sit in ddcolor.data beside the ONNX file."
        ),
        source_url="https://huggingface.co/qualcomm/DDColor",
        download_url=(
            "https://qaihub-public-assets.s3.us-west-2.amazonaws.com/qai-hub-models/"
            "models/ddcolor/releases/v0.65.0/ddcolor-onnx-float.zip"
        ),
        sha256="310d0c66a38cd8cfd7d9d93fdb5500fef79d584fe59e25a417aea5915a6b3733",
        archive_name="ddcolor-onnx-float/ddcolor.onnx",
        extra=(
            ExtraFile(
                filename="ddcolor.data",
                sha256="5b65cb3eab9fa4ae9ecacd539b148fa51157655732022913b1cf47346f93940c",
                archive_name="ddcolor-onnx-float/ddcolor.data",
            ),
        ),
    ),
    "scratch-detection": ModelSpec(
        id="scratch-detection",
        filename="scratch-detection.onnx",
        version="bopbtl-fp16w",
        purpose="Detect scratches conservatively",
        license_id="MIT",
        license_summary=(
            "Microsoft Bringing Old Photos Back to Life, MIT. "
            "Saimon8420's ONNX conversion of FT_Epoch_latest.pt, with fp16 weights "
            "cast to fp32 and sigmoid included. Whole-photo grayscale input in -1..1 "
            "at short side 256; probability threshold 0.7 protects intact detail."
        ),
        source_url="https://huggingface.co/Saimon8420/old-photo-scratch-detection-web",
        download_url=(
            "https://huggingface.co/Saimon8420/old-photo-scratch-detection-web/"
            "resolve/fdaf4799eaeb7f0ad50ea9e88ac86505486ce3be/scratch_detection_fp16w.onnx"
        ),
        sha256="842a7bb191664c3746a635f5a0b9734098d2558712d047e902ef8d39abb96541",
    ),
    "inpaint": ModelSpec(
        id="inpaint",
        filename="lama.onnx",
        version="big-lama",
        purpose="Fill scratches and creases",
        license_id="Apache-2.0",
        license_summary=(
            "LaMa, Roman Suvorov and others, Apache-2.0. "
            "This ONNX is Carve's conversion of big-lama. "
            "It takes a 512×512 RGB image and a mask in 0..1, with 1 marking the hole. "
            "Larger crops are scaled to that size."
        ),
        source_url="https://huggingface.co/Carve/LaMa-ONNX",
        download_url="https://huggingface.co/Carve/LaMa-ONNX/resolve/main/lama_fp32.onnx",
        sha256="1faef5301d78db7dda502fe59966957ec4b79dd64e16f03ed96913c7a4eb68d6",
    ),
}


@dataclass(frozen=True)
class Restoration:
    """One Real-ESRGAN pass. Both networks emit 4×, so the steps share that pass."""

    model_id: str
    keep_scale: bool
    stage: str


def restoration_for(*, upscale: bool, denoise: bool) -> Restoration | None:
    """Pick the single network for this combination.

    Official Real-ESRGAN interpolates two 4× weight files and then resizes to the
    requested output scale. Strength 0 is ``realesr-general-wdn-x4v3`` (keep
    texture). Strength 1 is ``realesr-general-x4v3`` (strong denoise). There is
    no 1× denoiser. Denoise alone therefore runs the strong-denoise network and
    the caller resizes back to the crop. Both steps use that same network once
    and keep the 4× image, which is strength 1 with no second enlargement.
    """

    if denoise:
        return Restoration(
            model_id="upscale",
            keep_scale=upscale,
            stage="Upscaling and denoising" if upscale else "Denoising",
        )
    if upscale:
        return Restoration(model_id="scale", keep_scale=True, stage="Upscaling")
    return None


def specs_for(
    *,
    upscale: bool,
    denoise: bool,
    faces: bool,
    colorize: bool,
    scratches: bool,
) -> list[ModelSpec]:
    needed: list[ModelSpec] = []
    if scratches:
        needed.extend((CATALOG["scratch-detection"], CATALOG["inpaint"]))
    if colorize:
        needed.append(CATALOG["colorize"])
    plan = restoration_for(upscale=upscale, denoise=denoise)
    if plan is not None:
        needed.append(CATALOG[plan.model_id])
    if faces:
        needed.extend((CATALOG["face-detection"], CATALOG["faces"]))
    return needed
