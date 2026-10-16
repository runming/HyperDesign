#!/usr/bin/env bash
# 安装 xformers 作为 TRELLIS 稀疏注意力后端（flash_attn 需 nvcc 编译，本机不可用）
set -uo pipefail
source /home/omegahyper/hd_trellis/bin/activate
export PATH="/home/omegahyper/.local/bin:$PATH"
echo "== uv pip install xformers =="
uv pip install xformers 2>&1 | tail -8
echo "== self-check =="
python - <<'PY'
import torch
print("torch", torch.__version__, "cuda", torch.cuda.is_available())
try:
    import xformers
    import xformers.ops as xops
    print("XFORMERS_OK", xformers.__version__)
except Exception as e:
    print("XFORMERS_FAIL", repr(e))
PY
