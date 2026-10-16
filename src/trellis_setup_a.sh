#!/usr/bin/env bash
# HyperDesign Phase 3 - WSL2 TRELLIS 环境搭建 Stage A: venv + torch(CUDA)
# 无 sudo 权限 -> 全部走 venv + 预编译轮子；CUDA 子模块编译放到 Stage C 再决定
set -uo pipefail
LOG=/mnt/d/hyperdesign/logs/phase3_wsl_setup.log
mkdir -p /mnt/d/hyperdesign/logs
exec > >(tee -a "$LOG") 2>&1
echo "########## STAGE A START $(date) ##########"
export TORCH_CUDA_ARCH_LIST="8.9;9.0;12.0"
export HF_ENDPOINT=https://hf-mirror.com
export PIP_DISABLE_PIP_VERSION_CHECK=1

if [ ! -d "$HOME/hd_trellis" ]; then
  echo ">> 创建 venv ~/hd_trellis"
  python3 -m venv "$HOME/hd_trellis"
fi
source "$HOME/hd_trellis/bin/activate"
python -V
pip install -q -U pip setuptools wheel

echo ">> 安装 torch (cu128)"
if pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu128 ; then
  echo "TORCH_FROM_PYTORCH_OK"
else
  echo ">> pytorch 官方源不可用，回退清华 PyPI (Linux 默认轮子自带 CUDA)"
  pip install -i https://pypi.tuna.tsinghua.edu.cn/simple torch torchvision torchaudio
fi
python - <<'PY'
import torch
print("TORCH", torch.__version__, "cuda", torch.version.cuda, "avail", torch.cuda.is_available())
if torch.cuda.is_available():
    print("DEV", torch.cuda.get_device_name(0))
    x = torch.randn(512, 512, device="cuda"); print("MATMUL_SUM", float((x @ x).sum()))
PY
echo "STAGE_A_DONE"

echo ">> 克隆 TRELLIS 源码 (ext4 以加速编译, 再软链到 /mnt/d/hyperdesign/src)"
if [ ! -d "$HOME/TRELLIS/.git" ]; then
  git clone --recurse-submodules https://github.com/microsoft/TRELLIS.git "$HOME/TRELLIS" || \
  git clone --recursive https://github.com/microsoft/TRELLIS.git "$HOME/TRELLIS"
fi
mkdir -p /mnt/d/hyperdesign/src
ln -sfn "$HOME/TRELLIS" /mnt/d/hyperdesign/src/TRELLIS
ls /mnt/d/hyperdesign/src/TRELLIS | head -20
echo "TRELLIS_CLONE_DONE"
echo "########## STAGE A END $(date) ##########"
