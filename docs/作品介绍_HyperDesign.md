# HyperDesign —— 本地部署的自进化制造业产品设计 AI 系统

> **作品介绍文档** · 从「像素逼真」到「几何真实」的制造业生成式 AI 全链路
> 正式排版版本（推荐阅读）：[`作品介绍_HyperDesign.pdf`](./作品介绍_HyperDesign.pdf) ｜ 可编辑源：[`作品介绍_HyperDesign.html`](./作品介绍_HyperDesign.html)
> 代码仓库：<https://github.com/runming/HyperDesign> ｜ 演示视频：`docs/demo/HyperDesign_Demo_1080p.mp4`（1 分 46 秒，1080p）

`100% 本地部署` · `私有工艺 RAG` · `Text-to-CAD 自愈闭环` · `DFM 物理硬约束` · `DPO 自进化飞轮` · `国标制图直连` · `单卡消费级硬件`

---

## 一、项目背景与行业痛点

在工业制造与硬件产品研发领域，生成式 AI（AIGC）的落地长期面临一道巨大的「**车间鸿沟**」——现有图文生成与 3D 娱乐大模型虽能产出极具视觉冲击力的渲染图，却无法真正服务于生产制造。核心症结在于四大痛点：

| # | 痛点 | 具体表现 |
|---|---|---|
| 1 | **「像素幻觉」与「工程现实」脱节** | 2D 生图工具（Midjourney / Stable Diffusion）产出的工业产品充斥违反物理规律的透视与光影伪影；主流 3D 生成模型导出的仅是拓扑杂乱、无物理毫米尺寸、非水密的三角网格（Mesh），无法直接用于 CNC 加工、注塑开模或钣金折弯 |
| 2 | **缺乏可制造性设计（DFM）底层约束** | 通用大模型不具备企业私有产线经验（特定机台最小壁厚、拔模斜度、折弯扣除系数），方案常在结构评审阶段因无法脱模、壁厚不均或装配干涉而全盘推翻 |
| 3 | **跨模态试错成本高昂** | 直接在参数化 CAD 阶段探索造型修改周期极长；在 2D 阶段探索，又缺乏机制把「感性的视觉比例」无损还原为「理性的 B-Rep 参数化实体」 |
| 4 | **数据隐私红线与模型进化难题** | 核心工艺标准与历史图纸属高度机密，严禁上传公有云 API；企业需要零边际成本机制，把资深工程师的「审图判断」持续沉淀给本地模型，而非依赖昂贵算力重新预训练 |

> **核心工程理念：设计可信度来自几何真实存在，而非像素逼真。**
> HyperDesign 打造了一套 100% 本地化部署、打通「概念发散 → 白模收敛 → 参数化 CAD → 生产工程图 → DPO 偏好自进化」全闭环的制造业 AI 系统。

---

## 二、系统技术架构

采用「**多环境隔离解耦 + 统一事务状态机（`manifest.json`）+ 显存红绿灯动态调度**」的工程架构，将研发周期划分为 7 个紧密咬合的阶段，所有阶段输入输出汇聚到同一份 `manifest.json` 数据契约，任一阶段可独立重跑而不破坏上下游。

```text
┌──────────────────────────────────────────────────────────────────────────────────┐
│              HyperDesign 全链路架构（manifest.json 状态总线）                      │
├──────────────────────────────────────────────────────────────────────────────────┤
│ [Phase 1 工艺大脑]  Ollama 本地主控 LLM + Qdrant + bge-m3 私有工艺 RAG             │
│      ↓ 注入壁厚/拔模角/材料约束，并转译为「3D 重建友好型」英文 Prompt                 │
│ [Phase 2 2D 发散]   ComfyUI + FLUX.2-dev（正交透视 / 纯灰背景 / 均匀柔光母本）      │
│      ↓ 低成本视觉筛选 + VLM 初筛，用毕立即卸载显存                                  │
│ [Phase 3 3D 白模]   WSL2 TRELLIS 微服务（稀疏体素 → SLAT 重建）+ Blender 无头清洗   │
│      ↓ 赋予真实 mm 级物理包络、底面坐平 Z=0、水密化与减面，导出 GLB/STL             │
│ [Phase 4 交互审阅]  Three.js 工业检视台（360° 旋转 / 线框 / Z 轴实时截面剖析）       │
│      ↓ 人工勾选优胜方案 + 锁定包络尺寸 → 自动归档 DPO 正负样本对                    │
│ [Phase 5 精确 CAD]  白模三层切片锚点 + FreeCAD/OpenCascade + OCC 自愈循环           │
│      ↓ 拓扑合法性 / 体积 / ±1.5mm 包络三重数学校验 → 直出 .step                     │
│ [Phase 6 生产对接]  OpenCascade HLR 投影 + ezdxf 国标分层 + 尺寸与标题栏            │
│      ↓ 直出 1:1 激光切割净片 .dxf + A3 工程图 .dxf/.pdf（300dpi）                   │
│ [Phase 7 进化闭环]  DFM 射线测厚/拔模角硬校验 + VLM 初筛 + Unsloth QLoRA/DPO        │
│      ↓ 黄金基准集回归守门员：新模型未全面超越则禁止切流                             │
└──────────────────────────────────────────────────────────────────────────────────┘
```

### 2.1 四层核心技术栈

| 层级 | 阶段 | 技术组成与职责 |
|---|---|---|
| **认知与知识检索层** | Phase 1 | Qdrant 向量库 + `BAAI/bge-m3` 稠密向量（1024 维 COSINE）+ Ollama 本地大模型；企业注塑/CNC/钣金规范精准检索与**硬性参数注入**，以「规范数值必须原样引用」为铁律 |
| **视觉与三维网格层** | Phase 2–4 | ComfyUI API 驱动 FLUX.2-dev 批量生成三维重建友好型概念图；WSL2 封装的 `TRELLIS-image-large` 恢复三维结构；Blender 无头脚本完成减面/水密化/真实毫米校准；原生 ES Module Three.js 零构建审阅台 |
| **计算几何与制图交付层** | Phase 5–6 | Trimesh 提取白模多高度截面比例，驱动 FreeCAD / CadQuery（OpenCascade 内核）生成全参数化 B-Rep 实体（`.step`）；OCC HLR 隐藏线消除 + ezdxf 绘制符合 GB/T 图层标准的 2D 工程图，预留 COM 接口对接浩辰/中望/AutoCAD |
| **评判与自进化层** | Phase 7 | 法向射线测厚（Ray-Casting）+ 拔模斜度场分析 + 本地 VLM 视觉评分 + Unsloth 4-bit QLoRA/DPO；带黄金基准集回归验证的本地模型迭代流水线 |

### 2.2 本机落地技术栈（可复现的真实配置）

> 括号内标注与《工程文件》规划稿的差异，全部差异与原因记录于仓库 `issues.md`（24 条）。

| 组件 | 本机实际配置 | 说明 / 规划稿差异 |
|---|---|---|
| 推理显卡 | NVIDIA RTX 5080 16GB（单卡） | 全链路最紧资源，需显存接力调度 |
| 主控大模型 | `qwen38-uncensored-128k`（27.3B，Ollama） | 规划稿为 Qwen3.5-9B，本机不可得 |
| 视觉初筛 VLM | `qwen3.7-flash`（8.3B） | 规划稿为 Qwen2.5-VL-7B |
| 向量库 | `qdrant-client` 嵌入式持久化 | 宿主无 Docker，改用嵌入式（语义一致） |
| 出图引擎 | ComfyUI 0.9.1 + `flux2_dev_fp8mixed` + Mistral-3-Small 文本编码器 | 规划稿为 FLUX.1-dev |
| 3D 重建 | WSL2 + TRELLIS-image-large（torch 2.11.0+cu128 / spconv / xformers） | 与规划一致（`ATTN_BACKEND=xformers`、`SPCONV_ALGO=native`） |
| 网格精修 | Blender 4.2.9 便携版无头脚本 | 与规划一致（blender-mcp 未启用，全自动） |
| CAD 内核 | **FreeCAD 1.1.4 自带 OpenCascade**（`freecadcmd` 无头校验） | 本机 OCP/CadQuery 原生扩展无法加载（issues #6），改用工程文件同样指定的 FreeCAD |
| 制图与打印 | ezdxf 1.4 + matplotlib 3.11（A3 300dpi） | 与规划一致 |
| 进化训练 | WSL2 Unsloth 2026.10.6 + Qwen2.5-7B-Instruct-bnb-4bit | 与规划一致（QLoRA r16 / DPO beta 0.1） |

### 2.3 关键实测指标（一次完整跑通的真实数据）

| 阶段节点 | 实测结果 | 工程含义 |
|---|---|---|
| 私有规范引用校验 | ✅ PASS | 逐字引用 **2.4 mm / 1.44 mm / ≥1.8°**，拒绝通用 2.0 mm |
| 概念图生成 | 4/4 张，114–136 s/张 | 1024²、base_seed=88400、纯灰背景、无裁切 |
| VLM 初筛 | 几何清晰 8 / 制造可行 9 / 需求对齐 8 | 四张方案一致性良好 |
| TRELLIS 重建 | 17–32 s/次 | WSL2 微服务 `:8003`，sparse12/cfg7.5 + slat12/cfg3.0 |
| Blender 清洗 | 973,462 → **388,391** 面；X=120 mm；Z<sub>min</sub>=0 | 毫米级物理对齐，底面坐平工业基准面 |
| 参数化 CAD 自愈 | ✅ **第 1 轮一次通过** | BRep `isValid()=True`，体积 **69,042.2 mm³**，包络 **120.0×80.0×45.0 mm（偏差 0）** |
| 工程图输出 | 510 条轮廓 + 3 处检验尺寸 + 标题栏 | `CUT_PROFILE / HIDDEN_LINE / DIMENSIONS / TITLE_BLOCK` 四图层分离 |
| DFM 硬校验（白模） | ❌ 未通过 | 水密=否 / p10 壁厚 1.51 mm / 立面拔模 0.84°——生成式网格固有特性，白模仅作造型锚点 |
| 进化与守门员 | LoRA 训练成功（0.52% 参数，27.6 s）→ GGUF Q4_K_M → `hd-brain:v20261016_1326` | 黄金基准回归：旧 1/1 vs 新 0/1 → **allowed_to_switch = false，禁止切流** |

---

## 三、核心应用场景

### 场景 1｜工业外壳与结构件敏捷开发（注塑 / 压铸）
工程师仅需输入一句功能描述与安装尺寸包络，系统自动调取车间注塑机规范（强制名义壁厚 **2.4 mm**、拔模角 **≥1.8°**），在一次会话内完成从 4 组差异化造型探索到可报价 `.step` 实体模型的转化。
**本机实证：** 概念图 ≈9 min（114–136 s/张）→ TRELLIS 重建 32 s → Blender 清洗 9 s → CAD 代码生成 466 s → OCC 校验通过。

### 场景 2｜钣金与激光切割件快速排产（激光 / 数控折弯）
Phase 6 自动剥离图框与尺寸线，直出 1:1 纯净外轮廓与孔位 `laser_1to1.dxf`，可直接导入柏楚 CypCut 等激光切割 CAM 排料切割。
**本机实证：** `proj_20261014_001_laser_1to1.dxf`（TOP 投影 82 条轮廓，仅 `CUT_PROFILE` 图层，零尺寸线污染）。

### 场景 3｜非标机械零部件系列化派生
Phase 5 产出的是带顶部全局参数表的标准参数化源码（`LENGTH_X`、`BOSS_INSET`、`WALL_THICKNESS`…），改几个变量即可在 1 秒内派生出同产品家族不同规格的 `.step` 与 `.dxf`。
**本机实证：** `05_cad/parametric_model.py` 作为「可复现资产」而非一次性脚本交付。

### 场景 4｜跨部门 / 外协供应商免插件三维协同审阅
Phase 4 单文件便携打包器把精修白模与包络标尺内嵌为独立 `.html`，客户/采购/外协模具厂无需安装专业 CAD，手机浏览器即可 360° 旋转并拖动滑块剖析内腔。
**本机实证：** `04_viewer/proj_20261014_001_3D_Concept_Share.html`（68 MB，GLB+概念图+manifest 全内嵌，双击即看）。

---

## 四、项目核心创新点

### 创新点 1｜「几何真实优先（Geometry-First）」的跨模态尺寸锚定机制
通过全局事务契约 `manifest.json` 贯穿始终：Phase 3 用 Blender 把归一化网格强制对齐真实毫米包络（坐平 Z=0），Phase 5 首创「**白模三层高度（10% / 50% / 90%）激光切片采样法**」，把感性美学比例精确翻译为理性 CAD 草图尺寸约束。
**实测：** 三层截面锚点（z / span_x / span_y）注入建模提示词后，最终 CAD 包络与目标偏差为 0。

### 创新点 2｜基于 OpenCascade 硬件级反馈的 Text-to-CAD「自愈闭环」
生成代码在沙箱运行并直接调用 OpenCascade 内核做数学级检验：`isValid()` 拓扑合法性、体积 > 1 mm³、三轴 Bounding Box 误差严控 **±1.5 mm**、STEP 实体确实落盘。捕获 `BRep_API: command not done` 或尺寸超差即回灌报错堆栈自愈，最多 **5 轮**；失败/成功代码同时成为 DPO 负/正样本。
**实测：** 示范项目第 1 轮一次通过；基准题 `bench_01` 旧主控同样一次通过（70,262 mm³，120×80×45）。

### 创新点 3｜「客观 DFM 物理信号 > VLM 主观打分 > 人类终审」三级评判体系
向网格内部发射 **500 条反向法线射线（Ray-Casting）**量化真实局部壁厚（取 10% 分位 p10 为判据），结合面法向量倾角统计拔模斜度、检查水密性与包络漂移（>8% 淘汰）。只有通过物理硬指标的方案才进入 VLM 评分与人工选品台，杜绝「好看但造不出」的废案。
**实测：** Phase 3 生成式白模被判「不通过」后，系统改走「白模只作造型锚点、制造实体由 Phase 5 按工艺铁律重建」路径——评判体系真实发挥了拦截作用。

### 创新点 4｜零边际成本的「日常工作即训练（Work-as-Training）」DPO 进化飞轮
Phase 4 勾选方案时自动组装 (Brief, 选中 Prompt, 淘汰 Prompt) 视觉偏好样本对；Phase 5 自愈循环自动捕获 (建模需求, 合规代码, 报错/超差代码) CAD 代码偏好样本对。配合 Unsloth 本地 4-bit QLoRA/DPO 与黄金基准回归，无需额外标注人力与云端算力。
**实测：** 一次审阅提交即落盘 3 条 `(prompt, chosen, rejected)`；训练链路完整跑通（LoRA 40.37 M / 0.52% 参数，3 步 27.6 s），GGUF Q4_K_M 成功注册进 Ollama。

### 创新点 5｜单机消费级硬件的「显存红绿灯」接力与国标制图直连
Ollama `keep_alive=0`、ComfyUI `POST /free`、TRELLIS `POST /unload` 在阶段边界联动卸载，使单张 16GB 显卡平稳接力百亿参数级多模态流水线；末端内置 GB/T 机械制图图层规范（实线切割层/虚线隐藏层/关联标注层/图框标题栏分离），走完从 AI 到车间的「最后一公里」。
**实测：** 定位并修复 Windows 提交内存耗尽导致的 `os error 1455`（ComfyUI 默认 pinned memory 43.9 GB + 33 GB UNet + 33 GB 文本编码器触顶），关闭 pinned memory 并迁移 32 GB 模型库后全链路稳定。

---

## 五、实测验证、已知限制与工程取舍

| 阶段 | 验收项 | 结论 |
|---|---|---|
| Phase 1 | 私有规范数值原样引用 | ✅ PASS（2.4 / 1.44 / 1.8°） |
| Phase 2 | 4 张概念图 + 纯灰背景 + 无裁切 | ✅ 4/4 PASS |
| Phase 3 | 清洗白模 GLB/STL + 真实包络回填 | ✅ PASS（388,391 面） |
| Phase 3.5 | DFM 硬规则 + VLM 双层初筛 | ⚠️ 白模 DFM 未通过（设计内预期，作造型锚点） |
| Phase 4 | 审阅台交互 + 提交归档 DPO | ✅ PASS（3 条偏好样本对） |
| Phase 5 | BRep 合法 / 体积 / 包络 ±1.5 mm | ✅ PASS（69,042.2 mm³，120×80×45，Z=0） |
| Phase 6 | 1:1 激光 DXF + A3 图 + 300dpi PDF | ✅ PASS（4 图层 + 标题栏工艺铁律） |
| Phase 7 | DPO 训练 → GGUF → Ollama + 守门员回归 | ✅ 机制 PASS；守门员判定「禁止切流」（样本不足） |

**诚实声明（工程取舍与限制）**

1. **生成式白模的 DFM 不达标属行业固有现象**：单图重建网格不水密、壁厚与拔模不可控。系统应对是把白模降级为「造型比例参考」，制造实体由 Phase 5 依据企业工艺规范重新参数化生成并通过 OCC 数学校验——这正是三级评判体系存在的意义。
2. **DPO 效果需要样本量**：本次仅 3 条偏好样本做机制验证，进化版（7B-Q4）在黄金基准上未超越旧主控（27B），守门员正确阻止切流；按《工程文件》建议攒够 50–100 条后再做正式进化。
3. **本机 CadQuery/OCP 原生扩展无法加载**（多版本、多解释器均复现），Phase 5/6 改用工程文件同样指定的 FreeCAD 自带 OpenCascade；算法与交付物等价，CadQuery 版实现保留于仓库备查。
4. **未启用的规划项**：`blender-mcp` / `freecad-mcp` / CAD-COM 桥接在本机流程中未启用（全自动无头链路已覆盖需求），保留为人工精修接口。

---

## 六、参考文献

1. Xiang J., Lv B., Deng Y., et al. *Structured 3D Latents for Scalable and Versatile 3D Generation* (TRELLIS). arXiv:2412.01506, 2024. <https://arxiv.org/abs/2412.01506>
2. Chen J., Xiao S., Zhang P., Luo K., Lian D., Liu Z. *M3-Embedding: Multi-Linguality, Multi-Functionality, Multi-Granularity Text Embeddings Through Self-Knowledge Distillation* (BGE-M3). arXiv:2402.03216, 2024. <https://arxiv.org/abs/2402.03216>
3. Black Forest Labs. *FLUX.2: Frontier Visual Intelligence*. 2025. <https://bfl.ai/blog/flux-2>
4. Shen T., Munkberg J., Hasselgren J., et al. *Flexible Isosurface Extraction for Gradient-Based Mesh Optimization* (FlexiCubes). arXiv:2308.05371, SIGGRAPH 2023. <https://arxiv.org/abs/2308.05371>
5. Rafailov R., Sharma A., Mitchell E., et al. *Direct Preference Optimization: Your Language Model is Secretly a Reward Model*. arXiv:2305.18290, NeurIPS 2023. <https://arxiv.org/abs/2305.18290>
6. Dettmers T., Pagnoni A., Holtzman A., Zettlemoyer L. *QLoRA: Efficient Finetuning of Quantized LLMs*. arXiv:2305.14314, NeurIPS 2023. <https://arxiv.org/abs/2305.14314>
7. Liu X., Gong C., Liu Q. *Flow Straight and Fast: Learning to Generate and Transfer Data with Rectified Flow*. arXiv:2209.03003, ICLR 2023. <https://arxiv.org/abs/2209.03003>
8. Unsloth AI. *Unsloth: 2× faster LLM finetuning*. <https://github.com/unslothai/unsloth>
9. Qdrant. *Qdrant Vector Database Documentation*. <https://qdrant.tech/documentation/>
10. ezdxf. *ezdxf — Python DXF read/write library Documentation*. <https://ezdxf.readthedocs.io/>
11. Open CASCADE Technology. *OCCT Documentation — HLR & BRep Topology Validation*. <https://dev.opencascade.org/doc/overview/html/>
12. FreeCAD. *FreeCAD 1.1 Documentation — Part / TechDraw Workbench*. <https://wiki.freecad.org/>
13. Blender Foundation. *Blender 4.2 LTS Manual — Python API (bpy)*. <https://docs.blender.org/manual/en/4.2/>
14. three.js. *three.js Documentation — GLTFLoader / Clipping Planes / BoxHelper*. <https://threejs.org/docs/>
15. 中华人民共和国国家标准. *GB/T 14665 机械工程 CAD 制图规则*；*GB/T 1804 一般公差 未注公差的线性和角度尺寸的公差*.
16. 中华人民共和国国家标准. *GB/T 1182 产品几何技术规范(GPS) 几何公差*.

---

**全过程实时日志**：`progress.log`　|　**24 条工程问题与偏差**：`issues.md`　|　**环境复现**：`SETUP.md`　|　**演示视频分镜**：`docs/演示视频分镜.md`
