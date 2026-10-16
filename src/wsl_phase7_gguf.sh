#!/usr/bin/env bash
# Phase 7 续跑：安装 cmake（GGUF 导出需要）+ 重跑 DPO 训练并导出 GGUF q4_k_m
set -uo pipefail
LOG=/mnt/d/hyperdesign/logs/phase7_gguf.log
mkdir -p /mnt/d/hyperdesign/logs
exec > >(tee -a "$LOG") 2>&1
export PATH="/home/omegahyper/.local/bin:$PATH"
export HF_ENDPOINT=https://hf-mirror.com
export HF_HOME=/mnt/d/hyperdesign/models/hf_cache        # 14.2GB 基座权重下载到 D 盘，避免撑爆 C 盘/WSL 系统盘
export PYTHONIOENCODING=utf-8
source /home/omegahyper/hd_unsloth/bin/activate

echo ">> 安装 cmake/make 供 llama.cpp 转换使用"
uv pip install cmake 2>&1 | tail -2
command -v cmake && cmake --version | head -1
command -v make && make --version | head -1

echo ">> 重新执行 QLoRA+DPO 并导出 GGUF"
python /mnt/d/hyperdesign/src/phase7_unsloth_dpo_trainer.py --min-samples 1 2>&1 | tail -40

echo ">> GGUF 产物"
ls -la /mnt/d/hyperdesign/models/checkpoints/lora_v*/gguf 2>/dev/null | tail -10
echo "PHASE7_GGUF_DONE"
