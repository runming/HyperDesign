#!/usr/bin/env bash
# Stage A2: 用 uv 在 WSL 内建 venv 并装 torch cu128（无 sudo、无 ensurepip 问题的解法）
set -uo pipefail
LOG=/mnt/d/hyperdesign/logs/phase3_wsl_setup.log
mkdir -p /mnt/d/hyperdesign/logs
echo "########## STAGE A2 START $(date) ##########" | tee -a "$LOG"
export TORCH_CUDA_ARCH_LIST="8.9;9.0;12.0"
export HF_ENDPOINT=https://hf-mirror.com

if ! command -v uv >/dev/null 2>&1 && [ ! -x "$HOME/.local/bin/uv" ]; then
  echo ">> 安装 uv (用户级, 无需 sudo)" | tee -a "$LOG"
  curl -LsSf https://astral.sh/uv/install.sh | sh 2>&1 | tail -5
fi
export PATH="$HOME/.local/bin:$PATH"
command -v uv && uv --version

echo ">> uv venv ~/hd_trellis (python3.10)" | tee -a "$LOG"
rm -rf "$HOME/hd_trellis"
uv venv "$HOME/hd_trellis" --python 3.10 --seed 2>&1 | tail -3
source "$HOME/hd_trellis/bin/activate"
python -V
python -c "import pip; print('pip', pip.__version__)" 2>/dev/null || echo "no-pip(uv 自带即可)"

echo ">> 安装 torch cu128" | tee -a "$LOG"
uv pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu128 2>&1 | tail -6 || {
  echo ">> 官方源失败，回退清华 PyPI (Linux 轮子自带 CUDA)" | tee -a "$LOG"
  uv pip install torch torchvision torchaudio --index-url https://pypi.tuna.tsinghua.edu.cn/simple 2>&1 | tail -6
}
python - <<'PY' 2>&1 | tee -a /mnt/d/hyperdesign/logs/phase3_wsl_setup.log
import torch
print("TORCH", torch.__version__, "cuda", torch.version.cuda, "avail", torch.cuda.is_available())
if torch.cuda.is_available():
    print("DEV", torch.cuda.get_device_name(0))
    x = torch.randn(1024, 1024, device="cuda")
    print("MATMUL_SUM", round(float((x @ x).sum()), 2))
PY
echo "STAGE_A2_DONE" | tee -a "$LOG"
echo "########## STAGE A2 END $(date) ##########" | tee -a "$LOG"
