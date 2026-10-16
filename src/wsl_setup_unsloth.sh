#!/usr/bin/env bash
# HyperDesign Phase 7 - WSL2 内 Unsloth 微调环境部署（周末夜间一键进化前置）
# 用法: wsl -d Ubuntu-22.04 -- bash /mnt/d/hyperdesign/src/wsl_setup_unsloth.sh
set -uo pipefail
LOG=/mnt/d/hyperdesign/logs/phase7_unsloth_setup.log
mkdir -p /mnt/d/hyperdesign/logs
exec > >(tee -a "$LOG") 2>&1
echo "########## PHASE7 UNSLOTH ENV $(date) ##########"
export PATH="/home/omegahyper/.local/bin:$PATH"
export HF_ENDPOINT=https://hf-mirror.com

if [ ! -d "$HOME/hd_unsloth" ]; then
  uv venv "$HOME/hd_unsloth" --python 3.11 --seed
fi
source "$HOME/hd_unsloth/bin/activate"
python -V

echo ">> 安装 torch (cu128)"
uv pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu128 2>&1 | tail -3

echo ">> 安装 unsloth (docx 指定 colab-new 分支，失败则回退纯 unsloth)"
uv pip install "unsloth[colab-new] @ git+https://github.com/unslothai/unsloth.git" 2>&1 | tail -4 || \
  uv pip install unsloth 2>&1 | tail -4
uv pip install --no-deps trl peft accelerate bitsandbytes datasets 2>&1 | tail -3

echo ">> 自检"
python - <<'PY'
import torch
print("torch", torch.__version__, "cuda", torch.cuda.is_available())
try:
    import unsloth
    print("UNSLOTH_OK", getattr(unsloth, "__version__", "?"))
except Exception as e:
    print("UNSLOTH_FAIL", repr(e))
PY
echo "PHASE7_UNSLOTH_SETUP_DONE"
