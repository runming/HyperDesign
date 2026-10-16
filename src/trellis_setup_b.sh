#!/usr/bin/env bash
# Stage B: TRELLIS 依赖 + 权重下载（无 sudo/nvcc，跳过需编译的 CUDA 子模块）
set -uo pipefail
LOG=/mnt/d/hyperdesign/logs/phase3_wsl_setup.log
echo "########## STAGE B START $(date) ##########" | tee -a "$LOG"
export TORCH_CUDA_ARCH_LIST="8.9;9.0;12.0"
export HF_ENDPOINT=https://hf-mirror.com
export PIP_DISABLE_PIP_VERSION_CHECK=1

source "$HOME/hd_trellis/bin/activate"
python -V
cd "$HOME/TRELLIS"

echo ">> [B1] pip 基础依赖 (setup.sh --basic 内容)" | tee -a "$LOG"
pip install pillow imageio imageio-ffmpeg tqdm easydict opencv-python-headless scipy ninja rembg onnxruntime trimesh open3d xatlas pyvista pymeshfix igraph transformers 2>&1 | tail -3
pip install "git+https://github.com/EasternJournalist/utils3d.git@9a4eb15e4021b67b12c460c7057d642626897ec8" 2>&1 | tail -3

echo ">> [B2] 服务与稀疏卷积依赖" | tee -a "$LOG"
pip install fastapi uvicorn python-multipart huggingface_hub 2>&1 | tail -2
pip install spconv-cu120 2>&1 | tail -3

echo ">> [B3] 安装 TRELLIS 包本体 (setup.py develop, 跳过 CUDA 扩展)" | tee -a "$LOG"
pip install -e . 2>&1 | tail -5

echo ">> [B4] 下载 TRELLIS-image-large 权重 (hf-mirror)" | tee -a "$LOG"
mkdir -p /mnt/d/hyperdesign/models/trellis
export PATH="$HOME/.local/bin:$PATH"
huggingface-cli download JeffreyXiang/TRELLIS-image-large \
  --local-dir /mnt/d/hyperdesign/models/trellis/TRELLIS-image-large 2>&1 | tail -5
du -sh /mnt/d/hyperdesign/models/trellis/TRELLIS-image-large 2>/dev/null

echo ">> [B5] 关键包可用性自检" | tee -a "$LOG"
python - <<'PY' 2>&1 | tee -a "$LOG"
import importlib
for m in ("torch", "spconv", "trimesh", "rembg", "transformers", "easydict", "utils3d", "fastapi", "imageio"):
    try:
        importlib.import_module(m)
        print(f"  OK   {m}")
    except Exception as e:
        print(f"  FAIL {m}: {e!r}")
try:
    import trellis
    print("  OK   trellis", trellis.__file__)
except Exception as e:
    print("  FAIL trellis:", repr(e))
PY
echo "STAGE_B_DONE" | tee -a "$LOG"
echo "########## STAGE B END $(date) ##########" | tee -a "$LOG"
