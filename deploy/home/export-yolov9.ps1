# deploy/home/export-yolov9.ps1 -- OPTIONAL: a lighter people-detector for the laptop's CPU (R3 D7).
#
# Only run this if Frigate -> System shows detection using more than about half a CPU core. It
# builds a small YOLOv9 model (320 px) as a file Frigate's OpenVINO detector can use. OpenVINO runs
# on Intel and AMD processors; Frigate ships no model for it, so this script makes one.
#
# What it does, in plain words:
#   1. Checks that Docker answers inside your Ubuntu (WSL).
#   2. Builds the model inside a throw-away Docker build (it downloads the YOLOv9 code and the
#      pre-trained file from GitHub, so it needs internet once).
#   3. Copies  yolov9-t-320.onnx  into frigate\config\model_cache  next to Frigate's settings.
#   4. Tells you the lines to put in frigate\config\config.yml (it never edits that file).
#
# Not verified here: the exact build steps follow Frigate's documentation from memory; the YOLOv9
# code's licence has not been checked (read it before relying on this beyond your own home).
# Frigate's docs are the authority:  https://docs.frigate.video/configuration/object_detectors
#
# Run:  right-click -> Run with PowerShell (administrator not needed).

$ErrorActionPreference = "Stop"
$Distro = "Ubuntu-24.04"
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$Out = Join-Path $Here "frigate\config\model_cache"
$Work = Join-Path $env:TEMP "jarvis-yolov9"

function Say($text) { Write-Host $text }

Say "Checking Docker inside $Distro ..."
wsl -d $Distro -- docker version --format "{{.Server.Version}}" | Out-Null
if ($LASTEXITCODE -ne 0) {
    Say "Docker does not answer inside $Distro. Start JARVIS Home first (start-home.ps1), then run this again."
    exit 1
}

New-Item -ItemType Directory -Force -Path $Work | Out-Null
New-Item -ItemType Directory -Force -Path $Out | Out-Null

$Dockerfile = @'
FROM python:3.11 AS build
RUN apt-get update && apt-get install --no-install-recommends -y libgl1 && rm -rf /var/lib/apt/lists/*
WORKDIR /yolov9
RUN git clone https://github.com/WongKinYiu/yolov9.git .
RUN pip install -r requirements.txt && pip install onnx onnxruntime onnx-simplifier onnxscript
ARG MODEL_SIZE
ARG IMG_SIZE
ADD https://github.com/WongKinYiu/yolov9/releases/download/v0.1/yolov9-${MODEL_SIZE}-converted.pt yolov9-${MODEL_SIZE}.pt
RUN python3 export.py --weights ./yolov9-${MODEL_SIZE}.pt --imgsz ${IMG_SIZE} --simplify --include onnx
FROM scratch
ARG MODEL_SIZE
ARG IMG_SIZE
COPY --from=build /yolov9/yolov9-${MODEL_SIZE}.onnx /yolov9-${MODEL_SIZE}-${IMG_SIZE}.onnx
'@
Set-Content -Path (Join-Path $Work "Dockerfile.yolov9") -Value $Dockerfile -Encoding ASCII

Say "Building the model (this can take 10-20 minutes the first time) ..."
$WorkWsl = (wsl -d $Distro -- wslpath -a $Work).Trim()
wsl -d $Distro -- bash -c "cd '$WorkWsl' && docker build . -f Dockerfile.yolov9 --build-arg MODEL_SIZE=t --build-arg IMG_SIZE=320 --output ."
if ($LASTEXITCODE -ne 0) {
    Say "The build failed. Nothing was changed. Tell Claude what the last lines said."
    exit 1
}

$Model = Join-Path $Work "yolov9-t-320.onnx"
if (-not (Test-Path $Model)) {
    Say "The model file was not made. Nothing was changed."
    exit 1
}
Copy-Item $Model (Join-Path $Out "yolov9-t-320.onnx") -Force
Say ""
Say "Done. The model is in: $Out"
Say ""
Say "Now open frigate\config\config.yml and replace the 'detectors:' block with:"
Say ""
Say "detectors:"
Say "  ov:"
Say "    type: openvino"
Say "    device: CPU"
Say "model:"
Say "  model_type: yolo-generic"
Say "  width: 320"
Say "  height: 320"
Say "  input_tensor: nchw"
Say "  input_dtype: float"
Say "  path: /config/model_cache/yolov9-t-320.onnx"
Say "  labelmap_path: /labelmap/coco-80.txt"
Say ""
Say "Then restart Frigate (stop-home.ps1, start-home.ps1) and look at Frigate -> System again."
