# Issues 记录（遇到问题先记这里，最后统一回来解决）

> 铁律：能绕过的先绕过并把偏差写清楚，保证全流程跑通；跑完全部阶段后回头统一处理 open 项。

| # | 时间 | 阶段 | 问题 | 状态 | 处置 |
|---|------|------|------|------|------|
| 1 | 2026-10-15 | Phase0 | Windows 宿主无系统 python (MS Store stub)、无 conda、无 docker | resolved | 全部改用 `E:\ComfyUI\resources\uv\win\uv.exe` 建 venv：`E:\hyperdesign\venvs\{hd_brain,hd_cad}`；另装官方 CPython 3.12.10 (winget, 用户级) 作为对照 |
| 2 | 2026-10-15 | Phase0 | RTX5080 16GB 被 Ollama qwen38 常驻占 15.4GB VRAM | resolved | GPU 阶段前 `POST /api/generate {keep_alive:0}` 卸载；ComfyUI 阶段后 `POST /free` |
| 3 | 2026-10-15 | Phase2 | FLUX.2-dev fp8mixed 33GB 权重在 16GB 显存上必须 offload | resolved | 启动加 `--lowvram`（或 NORMAL_VRAM 流式），见 #8 |
| 4 | 2026-10-15 | Phase2 | 本机无现成 FLUX workflow JSON | resolved | 依据官方模板 `image_flux2_text_to_image.json`（FluxGuidance=4 / euler / Flux2Scheduler steps=20）+ 实测 `/object_info` 手工编写 API JSON：`D:\hyperdesign\src\workflows\flux2_concept_api.json` |
| 5 | 2026-10-15 | Phase1 | docx 要求 docker Qdrant `http://localhost:6333` | resolved(偏差) | 改用 qdrant-client 嵌入式持久化 `D:\hyperdesign\qdrant_storage`，1024d COSINE，接口与检索语义一致 |
| 6 | 2026-10-16 | Phase5 | **CadQuery/OCP 原生扩展在本机无法加载**（`DLL load failed while importing OCP`；逐 DLL 定位为 TKOpenGL / TKIVtk / TKXDESTEP 的 DllMain 失败）。已排除：wheel 哈希全对(417/417)、VTK 版本冲突、MSVC 运行时(14.51 已装)、uv CPython 与官方 CPython 双解释器、OCP 7.7.2 / 7.8 / 7.9.3.1.1 / 8.0.1.1.0 四个版本 | **workaround** | Phase 5/6 改用工程文件同样指定的 **FreeCAD 1.1.4 自带 OpenCascade 内核**（`freecadcmd.exe` 无头执行 + TechDraw HLR 投影），DPO/自愈/校验逻辑不变；CadQuery 版实现保留在 `phase5_cad_engine_cadquery.py` 备查 |
| 7 | 2026-10-16 | Phase2 | ComfyUI 加载 33GB Mistral-3-Small 文本编码器时进程崩溃（WER: `python.exe` 在 `torch_cpu.dll` 访问违例 0xc0000005） | resolved | 真因 = **Windows 提交内存(commit)耗尽**：pagefile 仅 28.7GB、commit limit 124GB，而 ComfyUI 默认 pinned memory 就占 43.9GB + UNet 33GB + TE 33GB。改为 `--lowvram --bf16-text-enc --disable-pinned-memory --disable-smart-memory --cache-none` 后正常（`os error 1455 页面文件太小` 亦可复现同一根因） |
| 8 | 2026-10-16 | Phase2 | 两次服务端崩溃后重建 | resolved | 重启命令见 `progress.log`；生成前后 gpu_report 记录显存水位 |
| 9 | 2026-10-16 | Phase0 | `OLLAMA_MODELS` 被设为 `D:\hyperdesign\models\ollama`（空目录），导致模型不可见 | resolved | 真实模型库在 `C:\Users\omegahyper\.ollama\models` (32GB)，已改回该路径；不再为省 C 盘空间迁移 32GB 权重 |
| 10 | 2026-10-16 | Phase3 | WSL2 无免密 sudo（`SUDO_NEEDS_PASS`）→ 无法 apt 安装 cmake/ninja/CUDA toolkit；`python3-venv`(ensurepip) 也不可用 | **workaround** | 用 curl 装用户级 `uv`，`uv venv` 建 `~/hd_trellis`（py3.10 + torch 2.11.0+cu128 已验证 CUDA 可用）；跳过需 nvcc 编译的 `--diffoctreerast --mipgaussian --nvdiffrast`，TRELLIS 以 **纯几何素模**（不烘纹理）导出 GLB —— Phase 3 后续本就用 Blender 赋工业灰哑光材质，纹理非必需 |
| 11 | 2026-10-16 | Phase3 | TRELLIS 源码克隆到 `/mnt/d`(9p) 编译/IO 极慢 | resolved(偏差) | 克隆到 ext4 `~/TRELLIS`，再 `ln -s` 到 `/mnt/d/hyperdesign/src/TRELLIS`，docx 中的路径依然可用 |
| 12 | 2026-10-16 | Phase1/2/5 | docx 指定 `qwen3.5:9b` / `qwen2.5-vl:7b` 本机不存在 | resolved(偏差) | 主控 LLM → `qwen38-uncensored-128k:latest` (27.3B)；VLM 初筛 → `qwen3.7-flash:latest` |
| 13 | 2026-10-16 | Phase3+ | 16GB 显存需在 ComfyUI / Ollama / TRELLIS(WSL) / FreeCAD 之间轮转 | monitoring | 各阶段结束调用 `POST /free` 或 `keep_alive=0`；WSL 侧 TRELLIS 服务提供 `POST /unload` |
| 14 | 2026-10-16 | Phase3.5 | TRELLIS 生成式白模无法通过 DFM 硬指标：不水密、p10 壁厚 1.51mm(<2.4)、立面拔模 0.84°(<1.8°)、包络漂移 Y+63.7%/Z+329% | **known** | 这是 2D→3D 生成式重建的固有特性，也正是《工程文件》设计第一层漏斗要淘汰的对象。本流水线按 docx 继续推进：白模仅作为**造型比例参考**（Phase5 切片锚点），真正的制造实体由 Phase5 按 target_bbox + RAG 工艺铁律重新参数化生成并 100% 通过 OCC 校验。若需白模本身合规，可在 Phase4 点“比例失真→重跑”换概念图重试 |
| 15 | 2026-10-16 | Phase3 | TRELLIS 依赖链缺 `nvcc` 导致 `nvdiffrast`/`kaolin`/`flash_attn` 均不可用 | resolved(偏差) | ①`flexicubes.py` 的 kaolin 唯一依赖用纯 torch 等价 `check_tensor` 替代（补丁已写入源码）；②`postprocessing_utils` 不可用时改用 trimesh 直接导出**纯几何 GLB**（无纹理烘焙，Blender 后续本就赋工业灰哑光材质）；③注意力后端改 `ATTN_BACKEND=xformers`（flash_attn 需编译） |
| 16 | 2026-10-16 | Phase3 | spconv `auto` 算法在 RTX5080(sm_120) 触发 SIGFPE（`core_cc` 除零，dmesg: trap divide error） | resolved | 环境变量 `SPCONV_ALGO=native` 绕开自动调优内核，重建稳定通过（32s/17s） |
| 17 | 2026-10-16 | Phase3 | DINOv2 图像编码器 fp32 走 xformers 报 `NotImplementedError`（fa3F/cutlassF 要求 capability ≤ 9.0，本卡 12.0） | resolved | `XFORMERS_DISABLED=1` 让 DINOv2 走 torch 原生 SDPA，TRELLIS 自身稀疏注意力仍用 xformers |
| 18 | 2026-10-16 | Phase2 | ComfyUI `os error 1455 页面文件太小`：pinned memory 43.9GB + 33GB UNet + 33GB TE 超过 commit limit(124GB) | resolved | `--disable-pinned-memory --cache-none --disable-smart-memory --lowvram --bf16-text-enc` 组合；出图 114~136s/张 |
| 19 | 2026-10-16 | Phase6 | FreeCAD TechDraw `view.X/Y` 在 `page.addView()` 前设置会被重置到图幅中心（四视图重叠）；且 ACI 7 在白底 PDF 中渲染为白色不可见 | resolved | ①`addView()` 之后再设 X/Y 并二次 recompute；②渲染 PDF 前把 color=7 的图层改真彩色黑（CAD 内仍为自适应白/黑）；③ISO 视图 0.6 缩放避让标题栏 |
| 20 | 2026-10-16 | Phase5 | hd_brain 缺 trimesh/rtree，hd_cad 缺 trimesh/rtree/rtree 依赖 | resolved | 两个 venv 分别补齐；hd_cad 保持 ezdxf/matplotlib/numpy/scipy 工业出图栈 |
| 21 | 2026-10-16 | 全局 | Windows 控制台 GBK 编码导致脚本 `print()` 抛 UnicodeEncodeError（³ ℃ 等字符） | resolved | 全部脚本头部加 `sys.stdout.reconfigure(encoding="utf-8", errors="replace")` 兜底；subprocess 统一 `encoding="utf-8", errors="replace"` |
| 22 | 2026-10-16 | Phase3/7 | **C 盘只剩 8.1GB** → WSL ext4.vhdx 无法增长，出现 `[Errno 30] Read-only file system`、`[Errno 5] I/O error`、`getpwnam(omegahyper) failed`（WSL 一度不可用） | resolved | ①把 Ollama 模型库 32GB 从 `C:\Users\omegahyper\.ollama\models` 迁移到 `D:\hyperdesign\models\ollama` 并把 `OLLAMA_MODELS` 指向新路径（正是 docx Step1 的规划）；②`wsl --shutdown` 后恢复。C 盘可用空间 8.1GB → 40.1GB，WSL 恢复正常 |
| 23 | 2026-10-16 | Phase7 | Unsloth 训练成功（LoRA 40.37M 参数 0.52%，3 步 27.6s），但 GGUF 导出需 14.2GB 未量化基座权重，首次因磁盘 EIO 失败 | resolved | 续跑脚本 `wsl_phase7_gguf.sh`：`HF_HOME` 指向 D 盘 + 补装 cmake 后导出成功 → `Qwen2.5-7B-Instruct.Q4_K_M.gguf` + Modelfile，已 `ollama create hd-brain:v20261016_1326`（4.7GB）并冒烟推理通过 |
| 24 | 2026-10-16 | Phase7 | 仅 3 条 DPO 样本即训练，新模型（7B-Q4）在黄金基准 bench_01 上 Pass@1=0/1，而旧主控（27B）Pass@1=1/1；**守门员判定 allowed_to_switch=false，禁止切流** | **deferred(符合预期)** | 这正是《工程文件》守门员机制要拦住的场景：样本不足时进化版不得上线。正式进化需先攒 50~100 条偏好样本，再跑 `src\weekend_evolve.ps1`（训练→GGUF→ollama create→同台回归对比）。机制链路已 100% 跑通并有实测成绩单 |


