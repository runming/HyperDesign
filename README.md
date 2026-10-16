# HyperDesign — 工业设计全链路 AI 流水线（proj_20261014_001）

> 依据桌面《工程文件.docx》逐步落地的 7 阶段闭环：**RAG 工艺大脑 → FLUX 概念图 → TRELLIS 白模 → Three.js 审阅台 → CadQuery/FreeCAD 参数化 STEP → 激光 DXF + A3 图纸 → Unsloth DPO 进化**。
> 产品：**工业级无线振动/温湿度三合一传感器外壳**（120×80×45mm，PC+ABS 上盖 + 铝合金 CNC 底座）。

---

## 1. 一键跑通

```powershell
# 全链路（Phase1→6；Phase4 审阅台为常驻服务，Phase7 微调单独跑）
& "E:\hyperdesign\venvs\hd_brain\Scripts\python.exe" D:\hyperdesign\src\run_all_phases.py --phases 1,2,3,35,5,6

# 分阶段
& "E:\hyperdesign\venvs\hd_brain\Scripts\python.exe" D:\hyperdesign\src\phase1_brain_rag.py        # RAG 私有工艺库 + 主控推理
& "E:\hyperdesign\venvs\hd_brain\Scripts\python.exe" D:\hyperdesign\src\phase2_concept_gen.py      # FLUX.2-dev 4 概念图 + VLM 初筛 + DPO 归档
& "E:\hyperdesign\venvs\hd_brain\Scripts\python.exe" D:\hyperdesign\src\phase3_pipeline.py         # WSL2 TRELLIS → Blender 清洗对齐
& "E:\hyperdesign\venvs\hd_cad\Scripts\python.exe"   D:\hyperdesign\src\phase7_dfm_and_vlm_judge.py # DFM 硬规则 + VLM 双层初筛
& "E:\hyperdesign\venvs\hd_brain\Scripts\python.exe" D:\hyperdesign\src\phase4_viewer_server.py     # 交互审阅台 :8004（常驻）
& "E:\hyperdesign\venvs\hd_brain\Scripts\python.exe" D:\hyperdesign\src\phase5_cad_engine.py        # FreeCAD 参数化 + 5 轮自愈 → STEP
& "E:\hyperdesign\venvs\hd_cad\Scripts\python.exe"   D:\hyperdesign\src\phase6_drawing_exporter.py  # 1:1 激光 DXF + A3 图 + 300dpi PDF
```

**常驻服务**

| 服务 | 地址 | 启动 |
|---|---|---|
| ComfyUI（FLUX.2-dev 出图） | http://127.0.0.1:8000 | `E:\bundle\.venv\Scripts\python.exe E:\ComfyUI\resources\ComfyUI\main.py --port 8000 --base-directory E:\bundle --lowvram --bf16-text-enc --disable-pinned-memory --cache-none --database-url sqlite:///E:/bundle/user/hyperdesign.db` |
| TRELLIS 3D 重建（WSL2） | http://127.0.0.1:8003 | `wsl -d Ubuntu-22.04 -- bash /mnt/d/hyperdesign/src/start_trellis_server.sh` |
| 交互审阅台（Three.js） | http://127.0.0.1:8004/review/proj_20261014_001 | `hd_brain\python D:\hyperdesign\src\phase4_viewer_server.py` |

---

## 2. 目录与交付物

```
D:\hyperdesign\
├── 01_brief\01_brief.md                     # Phase1 设计任务书（RAG 命中的工艺铁律）
├── workspace\proj_20261014_001\
│   ├── manifest.json                        # 全链路数据契约（唯一事实源）
│   ├── 02_concepts\ *.png + prompts.json    # Phase2 四张概念图
│   ├── 03_mesh\  raw_trellis.glb            # Phase3 TRELLIS 原始白模
│   │             white_model_clean.glb/.stl #       Blender 清洗+mm对齐+Z=0
│   ├── 04_viewer\*_3D_Concept_Share.html    # Phase4 免服务器便携 3D 审阅包
│   ├── 05_cad\   parametric_model.py/.step  # Phase5 参数化实体 + 自愈代码
│   └── 06_drawings\                         # Phase6 生产图纸
│        ├── proj_20261014_001_laser_1to1.dxf      # 1:1 净轮廓（机床直连）
│        ├── proj_20261014_001_engineering_A3.dxf  # A3 国标图层工程总图
│        └── proj_20261014_001_engineering_A3.pdf  # 矢量 PDF（300dpi，车间/微信审阅）
├── models\checkpoints\dpo_dataset\          # Phase7 DPO 偏好样本（jsonl 持续累积）
├── models\trellis\TRELLIS-image-large\      # TRELLIS 权重
├── qdrant_storage\                          # bge-m3 私有工艺向量库
├── src\                                     # 全部流程脚本（见下）
├── progress.log                             # ★ 实时进度日志（每阶段每步都记）
├── issues.md                                # ★ 问题清单与处置（含所有工程偏差）
└── status.json                              # 当前阶段状态摘要
```

**脚本清单（`D:\hyperdesign\src\`）**

| 脚本 | 作用 |
|---|---|
| `phase1_brain_rag.py` | bge-m3(1024d) + Qdrant + 主控 LLM 的私有工艺 RAG，铁律“规范数值必须原样引用” |
| `phase2_concept_gen.py` | Brief→FLUX 提示词→ComfyUI 批量出图→VLM 初筛→DPO 归档 |
| `workflows\flux2_concept_api.json` | 手写 FLUX.2-dev API 工作流（UNETLoader+CLIPLoader(flux2)+FluxGuidance4+euler+Flux2Scheduler20） |
| `phase3_pipeline.py` / `trellis_server.py` / `blender_clean_mesh.py` | TRELLIS 重建微服务 + Blender 无头清洗（mm 归一、Z=0、减面、工业灰材质） |
| `phase4_viewer_server.py` / `templates\viewer.html` / `export_portable_html.py` | Three.js 360° 审阅台（线框/剖切/包络标尺 + DPO 打勾网关）+ 便携单文件导出 |
| `phase5_cad_engine.py` / `utils_mesh_slicer.py` | 白模 Z 轴三层切片锚点 + LLM 生成 FreeCAD 参数化脚本 + OCC 硬件级自检 + ≤5 轮自愈 + DPO 负样本捕获 |
| `phase6_fc_project.py` / `phase6_drawing_exporter.py` | FreeCAD HLR 四视图投影 → ezdxf 国标图层/尺寸/标题栏 → 1:1 激光 DXF + 300dpi PDF |
| `phase7_dfm_and_vlm_judge.py` | 第一层漏斗：射线测厚(p10)/拔模角/水密/包络漂移 + VLM 视觉初筛 |
| `phase7_unsloth_dpo_trainer.py` / `phase7_benchmark_eval.py` / `benchmark_suite.json` | QLoRA+DPO 微调、GGUF 注入 Ollama、10 道黄金基准回归守门员 |
| `run_all_phases.py` | 全链路编排 |
| `hd_llm.py` | 统一 LLM 客户端（ollama-python → REST 自动回落，支持多模态图片） |

---

## 3. 验收结论（本机实测）

| 阶段 | 验收项 | 结果 |
|---|---|---|
| Phase1 | 私有规范数值原样引用（2.4mm / 1.44mm / 1.8°） | ✅ PASS（LLM 回答逐字引用，未用通用 2.0mm） |
| Phase2 | 4 张概念图 + 纯灰背景 + 无裁切 | ✅ 4/4（VLM: clarity 8 / feasibility 9 / alignment 8） |
| Phase3 | `white_model_clean.glb/.stl` + `mesh_metrics.actual_bbox_mm` 回填 | ✅ 388,391 面，X=120mm，Z=0 基准 |
| Phase3.5 | DFM 硬规则 + VLM 双层初筛 | ⚠ 生成式白模 DFM 硬指标不通过（水密/p10壁厚1.51mm/拔模0.84°）→ 已在 issues.md #14 记录；CAD 实体由 Phase5 按规范重建 |
| Phase4 | 审阅台 :8004 交互 + `/api/submit_review` → manifest + DPO 落盘 | ✅ 一次提交归档 3 条偏好样本对 |
| Phase5 | BRep 合法 / 体积 / 包络 ±1.5mm / STEP 落盘 | ✅ 一次通过（volume 69,042 mm³，bbox 120.0×80.0×45.0，z_min=0） |
| Phase6 | 1:1 激光 DXF + A3 四视图 DXF + 300dpi PDF（图层/尺寸/标题栏含 RAG 铁律） | ✅ 510 条轮廓 → CUT_PROFILE；标题栏自动印 `WALL/DRAFT: 2.4mm / >= 1.8 deg` |
| Phase7 | DPO 样本累积 + 基准回归守门员 | ✅ 机制跑通：Unsloth QLoRA+DPO 实跑（LoRA 40.37M 参数/0.52%，27.6s）→ GGUF q4_k_m → `ollama create hd-brain:v20261016_1326`（4.7GB）冒烟通过；10 题黄金基准集 harness 就绪。⚠ 仅 3 条样本，正式进化需按 docx 攒 50~100 条（`src\weekend_evolve.ps1` 一键跑） |

## 4. 环境（本机实际）

- GPU：RTX 5080 16GB（**全链路最紧资源**，各阶段间用 `keep_alive=0` / `POST /free` 轮转显存）
- 宿主：Windows + `E:\hyperdesign\venvs\{hd_brain,hd_cad}`（uv 建 venv，py3.12）
- WSL2 Ubuntu-22.04：`~/hd_trellis`（py3.10 + torch 2.11.0+cu128 + xformers 0.0.35 + spconv-cu120）
- FreeCAD 1.1.4（用户级安装）：Phase5/6 的 OpenCascade 内核与 HLR 投影引擎
- ComfyUI 0.9.1 + FLUX.2-dev(fp8mixed) + Mistral-3-Small 文本编码器
- Ollama：主控 `qwen38-uncensored-128k:latest`、视觉 `qwen3.7-flash:latest`、进化产出 `hd-brain:v20261016_1326`
  - 模型库已按 docx 规划迁到 **`D:\hyperdesign\models\ollama`**（`OLLAMA_MODELS`），避免 C 盘被 32GB 权重占满（见 issues.md #22）

> ⚠ 所有与《工程文件》不一致的落地选择（CadQuery→FreeCAD、Qdrant docker→嵌入式、模型替换、spconv/xformers 后端等）**全部记录在 `issues.md`**，并标注了原因与影响。
