#!/usr/bin/env bash
# Stage C: 去掉 TRELLIS 对 kaolin(需编译) 的唯一依赖 + 下载权重 + 导入自检
set -uo pipefail
LOG=/mnt/d/hyperdesign/logs/phase3_wsl_setup.log
echo "########## STAGE C START $(date) ##########" | tee -a "$LOG"
export HF_ENDPOINT=https://hf-mirror.com
source "$HOME/hd_trellis/bin/activate"
cd "$HOME/TRELLIS"

python - <<'PY' 2>&1 | tee -a /mnt/d/hyperdesign/logs/phase3_wsl_setup.log
import io, os
p = 'trellis/representations/mesh/flexicubes/flexicubes.py'
shim = '''try:
    from kaolin.utils.testing import check_tensor as _kt

    def check_tensor(tensor, shape, throw=False):
        return _kt(tensor, shape, throw=throw)
except Exception:  # HyperDesign: kaolin(需 nvcc 编译) 缺失时的纯 torch 等价实现
    def check_tensor(tensor, shape, throw=False):
        if tensor is None:
            return False
        try:
            if len(tensor.shape) != len(shape):
                return False
            for t, s in zip(tensor.shape, shape):
                if s is not None and int(t) != int(s):
                    return False
            return True
        except Exception:
            return False
'''
s = open(p, encoding='utf-8').read()
old = 'from kaolin.utils.testing import check_tensor'
if old in s:
    s = s.replace(old, shim)
    open(p, 'w', encoding='utf-8').write(s)
    print('PATCHED flexicubes.py (kaolin -> pure torch shim)')
else:
    print('ALREADY_PATCHED_OR_CHANGED')
PY

echo ">> [C1] 下载 TRELLIS-image-large 权重 (hf-mirror, 约数 GB)" | tee -a "$LOG"
mkdir -p /mnt/d/hyperdesign/models/trellis
hf download JeffreyXiang/TRELLIS-image-large \
  --local-dir /mnt/d/hyperdesign/models/trellis/TRELLIS-image-large 2>&1 | tail -4
du -sh /mnt/d/hyperdesign/models/trellis/TRELLIS-image-large 2>/dev/null | tee -a "$LOG"

echo ">> [C2] 导入自检 (PYTHONPATH=repo)" | tee -a "$LOG"
export PYTHONPATH="$HOME/TRELLIS"
python - <<'PY' 2>&1 | tee -a /mnt/d/hyperdesign/logs/phase3_wsl_setup.log
import traceback
for m in ("trellis", "trellis.pipelines", "trellis.utils.postprocessing_utils"):
    try:
        __import__(m)
        print("  OK  ", m)
    except Exception as e:
        print("  FAIL", m, repr(e))
        traceback.print_exc()
import torch
print("  cuda:", torch.cuda.is_available(), torch.cuda.get_device_name(0) if torch.cuda.is_available() else "")
PY
echo "STAGE_C_DONE" | tee -a "$LOG"
echo "########## STAGE C END $(date) ##########" | tee -a "$LOG"
