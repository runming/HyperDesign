# 环境部署与运行说明（SETUP）

> 本仓库代码按桌面《工程文件.docx》实现，**依赖版本已用本机验证过的冻结清单锁定**（见 `env/`）。
> 由于模型权重体积巨大（FLUX.2 ≈ 66GB、TRELLIS ≈ 3GB、Ollama 模型 ≈ 38GB），**权重不入库**，按本文第 3 节获取。

---

## 0. 硬件与系统基线（实测环境）

| 项 | 值 |
|---|---|
| GPU | NVIDIA RTX 5080 16GB（单卡，全链路最紧资源） |
| 系统 | Windows 11 + WSL2 Ubuntu-22.04 |
| 宿主 Python | uv 托管 CPython 3.12.11（`E:\ComfyUI\resources\uv\win\uv.exe`） |
| WSL Python | 3.10.12（TRELLIS）/ 3.11.17（Unsloth） |

**显存/内存铁律**：Ollama 主控 16.9GB、ComfyUI FLUX.2 需 ~34GB（含 offload）、TRELLIS ~6GB。
每个 GPU 阶段之间必须释放：`POST /api/generate {"keep_alive":0}`（Ollama）、`POST /free {"unload_models":true}`（ComfyUI）、`POST /unload`（TRELLIS）。
Windows 提交内存（commit limit）必须 ≥ 130GB，否则 ComfyUI 会 `os error 1455 页面文件太小`。

---

## 1. Windows 侧：两个 venv

```powershell
$uv = "E:\ComfyUI\resources\uv\win\uv.exe"        # 任意 uv 均可

# hd_brain：RAG 大脑 / 流程编排 / 审阅台 / Text-to-CAD 编排
& $uv venv E:\hyperdesign\venvs\hd_brain --python 3.12
& $uv pip install --python E:\hyperdesign\venvs\hd_brain\Scripts\python.exe `
    -r D:\hyperdesign\env\requirements-hd_brain.txt
# ⚠ 若 sentence-transformers 把 torch 顶成 PyPI 的 CPU 版，需回钉 CUDA 版：
& $uv pip install --python E:\hyperdesign\venvs\hd_brain\Scripts\python.exe `
    "torch==2.9.1+cu128" --index-url https://download.pytorch.org/whl/cu128 --reinstall

# hd_cad：工程图（ezdxf + matplotlib）、网格切片（trimesh）与 DFM 校验
& $uv venv E:\hyperdesign\venvs\hd_cad --python 3.12
& $uv pip install --python E:\hyperdesign\venvs\hd_cad\Scripts\python.exe `
    -r D:\hyperdesign\env\requirements-hd_cad.txt
```

> **CadQuery/OCP 提示**：本机 OCP 原生扩展无法加载（TKOpenGL/TKIVtk/TKSTEP DllMain 失败，多版本多解释器均复现，详见 `issues.md` #6）。
> 因此 Phase 5/6 使用**工程文件同样指定的 FreeCAD 1.1.4 自带 OpenCascade**；CadQuery 版实现在 `src/phase5_cad_engine_cadquery.py` 保留备查。
> 若你的机器 OCP 正常，可直接改用该文件并在 `phase6` 里换回 CadQuery 投影。

## 2. 外部软件（一次性）

```powershell
winget install -e --id Python.Python.3.12            # 可选：标准 CPython 对照
winget install -e --id FreeCAD.FreeCAD --scope user  # Phase5/6 的 OCC 内核 + TechDraw HLR
# Blender 4.2 LTS 便携版（Phase3 白模清洗）
Invoke-WebRequest https://download.blender.org/release/Blender4.2/blender-4.2.9-windows-x64.zip `
  -OutFile D:\hyperdesign\tools\blender.zip
Expand-Archive D:\hyperdesign\tools\blender.zip D:\hyperdesign\tools
```

## 3. 模型与权重

```powershell
# 3.1 FLUX.2-dev（ComfyUI）——放 E:\bundle\models\ 下（或改 --base-directory）
#   diffusion_models\flux2_dev_fp8mixed.safetensors        33.0GB
#   text_encoders\mistral_3_small_flux2_bf16.safetensors   33.1GB
#   vae\flux2-vae.safetensors                              0.3GB
# 3.2 Ollama（主控与视觉）
ollama pull qwen38-uncensored-128k        # 主控 LLM（docx 的 qwen3.5:9b 本机不存在，见 issues #12）
ollama pull qwen3.7-flash                 # VLM 初筛（docx 的 qwen2.5-vl:7b 替身）
# 3.3 bge-m3 向量模型：首次运行 phase1 时自动从 HF 下载到 %HF_HOME%
```

## 4. WSL2：TRELLIS（Phase 3）

```bash
# 无 sudo 环境下的可行路径（免 apt/nvcc）；有 sudo 时可换 conda + 完整 setup.sh
bash /mnt/d/hyperdesign/src/trellis_setup_a.sh    # uv + venv(py3.10) + torch cu128
bash /mnt/d/hyperdesign/src/trellis_setup_b.sh    # TRELLIS 基础依赖 + spconv-cu120 + 权重
bash /mnt/d/hyperdesign/src/trellis_setup_c.sh    # kaolin 依赖打桩 + 权重校验 + 导入自检
bash /mnt/d/hyperdesign/src/wsl_install_xformers.sh   # 稀疏注意力后端 xformers
bash /mnt/d/hyperdesign/src/start_trellis_server.sh   # 启动 :8003 微服务
```
关键环境变量（已写入 `start_trellis_server.sh`，原因见 `issues.md` #15~#17）：
```bash
export PYTHONPATH=$HOME/TRELLIS      # TRELLIS 无 setup.py，走 PYTHONPATH
export ATTN_BACKEND=xformers         # flash_attn 需 nvcc，本机不可编译
export XFORMERS_DISABLED=1           # DINOv2 走 torch 原生 SDPA（xformers fp32 内核不支持 sm_120）
export SPCONV_ALGO=native            # 规避 sm_120 上 spconv auto 调优的 SIGFPE
export HF_ENDPOINT=https://hf-mirror.com
```

## 5. WSL2：Unsloth（Phase 7）

```bash
bash /mnt/d/hyperdesign/src/wsl_setup_unsloth.sh      # py3.11 + torch cu128 + unsloth + cmake
# 训练 + 导出 GGUF（HF_HOME 必须指向大容量盘，否则 14.2GB 基座权重会撑爆系统盘）
export HF_HOME=/mnt/d/hyperdesign/models/hf_cache
python /mnt/d/hyperdesign/src/phase7_unsloth_dpo_trainer.py --min-samples 50
```
训练完成后在 Windows 注册进 Ollama：
```powershell
ollama create hd-brain:vYYYYMMDD_HHMM -f D:\hyperdesign\models\checkpoints\lora_vYYYYMMDD_HHMM\gguf_gguf\Modelfile
```

## 6. 常驻服务与端口

| 服务 | 端口 | 启动命令 |
|---|---|---|
| ComfyUI（FLUX.2 出图） | 8000 | `E:\bundle\.venv\Scripts\python.exe E:\ComfyUI\resources\ComfyUI\main.py --port 8000 --base-directory E:\bundle --lowvram --bf16-text-enc --disable-pinned-memory --cache-none --database-url sqlite:///E:/bundle/user/hyperdesign.db` |
| TRELLIS 3D 重建 | 8003 | `wsl -d Ubuntu-22.04 -- bash /mnt/d/hyperdesign/src/start_trellis_server.sh` |
| 交互审阅台 | 8004 | `hd_brain\Scripts\python.exe D:\hyperdesign\src\phase4_viewer_server.py` |
| Ollama | 11434 | `ollama serve`（`OLLAMA_MODELS` 建议指向大容量盘） |

## 7. 一键跑通

```powershell
# Phase1→6（Phase4 审阅台是常驻服务；Phase7 单独在周末跑）
& "E:\hyperdesign\venvs\hd_brain\Scripts\python.exe" D:\hyperdesign\src\run_all_phases.py --phases 1,2,3,35,5,6
# Phase7 守门员回归
& "E:\hyperdesign\venvs\hd_brain\Scripts\python.exe" D:\hyperdesign\src\phase7_benchmark_eval.py `
    --models qwen38-uncensored-128k:latest hd-brain:v20261016_1326
```

## 8. 已知限制（完整清单见 `issues.md`）

1. **CadQuery/OCP 不可用** → Phase5/6 走 FreeCAD（同一 OpenCascade 内核，产出物一致）。
2. **生成式白模 DFM 不达标**（水密/壁厚/拔模）——这是 2D→3D 重建的固有特性，白模仅作造型比例锚点；制造实体由 Phase5 按 RAG 铁律重建并通过 OCC 校验。
3. **Phase 7 需样本量**：本次仅 3 条偏好样本做的机制验证，新模型未超越旧模型，守门员已正确禁止切流；正式进化建议 ≥50 条。
