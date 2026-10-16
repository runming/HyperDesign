#!/usr/bin/env bash
# HyperDesign Phase 3 - 启动 WSL2 内的 TRELLIS 3D 重建微服务 (:8003)
source /home/omegahyper/hd_trellis/bin/activate
export PYTHONPATH=/home/omegahyper/TRELLIS
export HF_ENDPOINT=https://hf-mirror.com
export ATTN_BACKEND=xformers   # flash_attn 需 nvcc 编译，本机改用 xformers 后端
export XFORMERS_DISABLED=1     # DINOv2 图像编码器改走 torch 原生 SDPA（xformers fp32 内核不支持 sm_120）
export SPCONV_ALGO=native      # spconv auto 调优在本机 SIGFPE(core_cc 除零)，改用 native 算法
cd /mnt/d/hyperdesign/src
exec python trellis_server.py
