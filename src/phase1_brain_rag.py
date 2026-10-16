# -*- coding: utf-8 -*-
"""
HyperDesign Phase 1 — 主控大脑 / 私有工艺知识库 RAG
按《工程文件》Phase 1 验收脚本落地（见 docs/工程文件_extracted.txt L82-L158）

落地偏差（已记录于 D:\\hyperdesign\\issues.md）：
  1. Qdrant: 宿主无 Docker -> 使用 qdrant-client 嵌入式持久化 (D:\\hyperdesign\\qdrant_storage)
  2. LLM: "qwen3.5:9b" 本地不存在 -> 替换为本机已有 "qwen38-uncensored-128k:latest" (27.3B)
  3. 语料: 除 docx sample_kb 两条外，追加《工程文件》中带明确数值的工艺条款（原样引用）

运行: E:\\hyperdesign\\venvs\\hd_brain\\Scripts\\python.exe D:\\hyperdesign\\src\\phase1_brain_rag.py
"""
import os
import sys
import json
import time
import datetime
from pathlib import Path

# ---- 固化环境变量（工程文件 L71-L72）：HF 缓存与 Ollama 模型都落到 D 盘 ----
os.environ["HF_HOME"] = r"D:\hyperdesign\models\hf_cache"
os.environ["OLLAMA_MODELS"] = r"D:\hyperdesign\models\ollama"
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

import ollama
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct
from FlagEmbedding import BGEM3FlagModel

try:  # Windows 控制台可能是 GBK，统一把 stdout/stderr 切到 UTF-8 容错，避免中文/³ 等字符抛 UnicodeEncodeError
    import sys as _sys
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    _sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# ================= 配置区 (工程文件 L86-L90) =================
QDRANT_PATH = r"D:\hyperdesign\qdrant_storage"          # 偏差: 嵌入式替代 http://localhost:6333
COLLECTION_NAME = "mfg_knowledge_base"
EMBED_MODEL_PATH = "BAAI/bge-m3"                         # 自动缓存至 D:\hyperdesign\models\hf_cache
LLM_MODEL = "qwen38-uncensored-128k:latest"              # 偏差: 原 qwen3.5:9b
PROJECT_ID = "proj_20261014_001"
PROJECT_DIR = Path(r"D:\hyperdesign\workspace") / PROJECT_ID
PROGRESS_LOG = Path(r"D:\hyperdesign\progress.log")
STATUS_JSON = Path(r"D:\hyperdesign\status.json")


def ts() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log(msg: str) -> None:
    line = f"[{ts()}] {msg}"
    print(line, flush=True)
    PROGRESS_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(PROGRESS_LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


class HyperDesignBrain:
    def __init__(self, use_gpu: bool = True):
        self.use_gpu = use_gpu
        log("[Phase1] [1/3] 连接 Qdrant 向量库 (embedded @ %s)..." % QDRANT_PATH)
        Path(QDRANT_PATH).mkdir(parents=True, exist_ok=True)
        self.qdrant = QdrantClient(path=QDRANT_PATH)
        self._init_collection()
        log("[Phase1] [2/3] 加载 bge-m3 向量模型 (1024d, fp16=%s)..." % use_gpu)
        t0 = time.time()
        self.embedder = BGEM3FlagModel(EMBED_MODEL_PATH, use_fp16=use_gpu)
        log("[Phase1] bge-m3 就绪，耗时 %.1fs" % (time.time() - t0))

    def _init_collection(self):
        collections = [c.name for c in self.qdrant.get_collections().collections]
        if COLLECTION_NAME not in collections:
            self.qdrant.create_collection(
                collection_name=COLLECTION_NAME,
                vectors_config=VectorParams(size=1024, distance=Distance.COSINE),
            )
            log("[Phase1] 新建集合 %s (size=1024, COSINE)" % COLLECTION_NAME)
        else:
            log("[Phase1] 集合 %s 已存在，复用" % COLLECTION_NAME)

    def reset_collection(self):
        """幂等: 清空旧向量后重灌"""
        try:
            self.qdrant.delete_collection(COLLECTION_NAME)
        except Exception:
            pass
        self.qdrant.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=VectorParams(size=1024, distance=Distance.COSINE),
        )

    def ingest_documents(self, docs: list):
        """灌入行业工艺标准与历史设计规范 (工程文件 L105-L114)"""
        texts = [d["content"] for d in docs]
        embeddings = self.embedder.encode(texts, batch_size=12, max_length=1024)["dense_vecs"]
        points = [
            PointStruct(id=idx, vector=emb.tolist(), payload=doc)
            for idx, (emb, doc) in enumerate(zip(embeddings, docs))
        ]
        self.qdrant.upsert(collection_name=COLLECTION_NAME, points=points)
        log("[Phase1] 成功入库 %d 条制造业知识条目 (dim=%d)" % (len(points), len(embeddings[0])))

    def search(self, query: str, limit: int = 3):
        query_vec = self.embedder.encode([query], batch_size=1, max_length=1024)["dense_vecs"][0].tolist()
        try:
            res = self.qdrant.query_points(
                collection_name=COLLECTION_NAME, query=query_vec, limit=limit
            ).points
        except Exception:
            res = self.qdrant.search(
                collection_name=COLLECTION_NAME, query_vector=query_vec, limit=limit
            )
        return res

    def query_and_plan(self, user_brief: str, unload_vram_after: bool = True) -> str:
        """检索私有工艺库并生成结构化设计约束 (工程文件 L115-L139)"""
        hits = self.search(user_brief, limit=3)
        context_str = "\n".join(
            ["- [%s]: %s" % (h.payload["source"], h.payload["content"]) for h in hits]
        )
        log("[Phase1] 检索命中 %d 条: %s" % (len(hits), " | ".join(h.payload["source"] for h in hits)))
        system_prompt = (
            "你是 HyperDesign 工业设计主控引擎。请严格依据【企业内部工艺规范】回答问题或拆解设计任务。\n"
            "如果规范中有明确数值（如壁厚、拔模角、公差、材料牌号），必须原样引用，严禁捏造。"
        )
        prompt = "【企业内部工艺规范】\n%s\n\n【输入需求】\n%s" % (context_str, user_brief)
        # keep_alive=0 确保流水线进入下一阶段(FLUX/TRELLIS)前立即释放显存
        keep_alive = 0 if unload_vram_after else "5m"
        t0 = time.time()
        response = ollama.chat(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            keep_alive=keep_alive,
            options={"temperature": 0.2},
        )
        answer = response["message"]["content"] if isinstance(response, dict) else response.message.content
        log("[Phase1] 主控推理完成，耗时 %.1fs (keep_alive=%s)" % (time.time() - t0, keep_alive))
        return answer

    def release_embedder(self):
        """释放 bge-m3 占用的显存"""
        try:
            self.embedder = None
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            log("[Phase1] bge-m3 已卸载，torch 显存缓存已清空")
        except Exception as e:
            log("[Phase1][warn] 释放 embedder 异常: %r" % (e,))


# ================= 语料库 =================
# 前两条为 docx sample_kb 原文；其后为《工程文件》中带明确数值的条款（原样引用）
CORPUS = [
    {
        "source": "内部注塑工艺规范_v2.4.pdf",
        "content": "我司二号车间海天注塑机加工 PC+ABS 材质工业外壳时，凡外壳最大跨度超过 150mm 的产品，标准名义壁厚必须设定为 2.4mm（严禁采用通用 2.0mm），内侧加强筋厚度不得超过名义壁厚的 60%（即 1.44mm），否则极易产生表面缩水纹；拔模斜度统一要求 ≥ 1.8°。",
    },
    {
        "source": "钣金折弯展开标准_2025.docx",
        "content": "我司激光切割+数控折弯产线加工 2.0mm 冷轧钢板（SPCC）时，90度折弯统一使用 V12 下模，内R角按 R1.6 计算，折弯扣除系数（K因子校准值）固定取 3.35mm。",
    },
    {
        "source": "工程文件_Phase2_产品设计任务书.docx",
        "content": (
            "产品：工业级无线振动温湿度三合一传感器外壳（安装在电机表面）。"
            "尺寸包络：120mm x 80mm x 45mm。"
            "工艺要求：顶部为 PC+ABS 抗冲击注塑上盖（壁厚2.4mm，拔模角1.8度，带状态指示灯导光柱窗口），"
            "底部为铝合金 CNC 底座（带两侧M6安装耳和磁吸沉孔），上下壳通过4颗内六角螺钉锁紧并夹持硅胶防水圈。"
        ),
    },
    {
        "source": "工程文件_Phase5_CAD铁律.docx",
        "content": (
            "HyperDesign Phase 5 参数化 CAD 建模铁律："
            "1) 必须通过 OpenCascade 底层拓扑检验 solid.isValid() 是否为 True（无自交面、无破洞）；"
            "2) 严禁使用危险的大半径 fillet() 导致 BRep_API: command not done 拓扑崩溃；"
            "建议外圆角 R <= 3.0mm，内圆角 R <= 1.0mm，且在 shell() 抽壳之前先做外部主倒角；"
            "3) 脚本末尾必须将最终主实体赋值给变量 result_solid（类型为 cq.Workplane），"
            "并使用 cq.exporters.export(result_solid, STEP_OUTPUT_PATH) 导出 STEP 文件。"
            "项目基准参数：标准壁厚 2.4mm，顶部状态指示灯导光孔径 8.0mm，"
            "STEP 输出路径 D:/hyperdesign/workspace/proj_20261014_001/05_cad/parametric_model.step。"
            "自愈机制：报错或超差自动重试，最多 5 次，失败样本自动捕获为 Phase 7 的 DPO 负样本。"
        ),
    },
    {
        "source": "工程文件_Phase6_制图规范.docx",
        "content": (
            "HyperDesign Phase 6 工程图纸规范（GB/T 14665 机械工程 CAD 制图标准图层体系）："
            "CUT_PROFILE = 1:1 激光切割/CNC 实线外轮廓层（直接导入机床 CAM）；"
            "HIDDEN_LINE = 内部暗孔/抽壳内壁虚线层（供审图看内部壁厚与螺钉柱深度）；"
            "DIMENSIONS = 长宽高检验尺寸标注层（质检员拿卡尺验收的依据）；"
            "TITLE_BLOCK = A3 标准图框、标题栏与来自 Phase 1 RAG 的技术要求文本。"
            "文件格式：激光切割 1:1 净轮廓 DXF（MM, R2010），尺寸线严禁混入切割层；"
            "A3 图幅 420mm x 297mm，标题栏自动打印 WALL / DRAFT: 2.4mm / >= 1.8 deg；"
            "PDF 渲染 figsize=(16.53, 11.69), dpi=300。"
        ),
    },
    {
        "source": "工程文件_Phase7_DFM双层评判.docx",
        "content": (
            "HyperDesign 双层自动评判引擎：客观几何铁律 > VLM 主观审美。"
            "壁厚红线扫描（Min Wall Thickness）：从零件表面向内发射法向射线测量真实局部壁厚，"
            "若二号车间要求 >= 2.4mm，而实测存在 < 1.8mm 的薄壁区（注塑欠注风险）"
            "或 > 4.5mm 的肥厚积料区（缩水纹风险），直接判定为 rejected；"
            "拔模角扫描（Draft Angle Check）：统计所有近似平行于脱模方向（Z 轴）的立面法向量夹角，识别零度直壁（卡模拉伤风险）。"
            "只有通过第一关几何硬指标的方案，才送 VLM 检查视觉特征是否漏项"
            "（如：需求要求的顶部状态指示灯导光窗口、两侧 M6 安装耳是否在图中清晰可见）。"
            "随机采样 500 个表面点向内发射反向法线射线，取 10% 分位最薄处壁厚作为 p10_thickness 判据。"
        ),
    },
]


def write_manifest_and_outputs(brain, hits, answer, test_question, brief_path):
    PROJECT_DIR.mkdir(parents=True, exist_ok=True)
    for sub in ("02_concepts", "03_mesh", "04_threejs", "05_cad", "06_drawings"):
        (PROJECT_DIR / sub).mkdir(parents=True, exist_ok=True)

    manifest_path = PROJECT_DIR / "manifest.json"
    manifest = {
        "project_id": PROJECT_ID,
        "created_at": ts(),
        "product": "工业无线振动/温湿度三合一传感器外壳 (电机表面安装)",
        "target_bbox_mm": {"x": 120.0, "y": 80.0, "z": 45.0},
        "mfg_constraints": {
            "process": "注塑成型(上盖 PC+ABS) + CNC(铝合金底座)",
            "workshop": "二号车间",
            "min_wall_thickness_mm": 2.4,
            "rib_max_thickness_mm": 1.44,
            "min_draft_angle_deg": 1.8,
            "source": "内部注塑工艺规范_v2.4.pdf",
        },
        "phase1_brain_rag": {
            "collection": COLLECTION_NAME,
            "embed_model": EMBED_MODEL_PATH,
            "llm_model": LLM_MODEL,
            "docs_ingested": len(CORPUS),
            "retrieved_sources": [h.payload["source"] for h in hits],
            "retrieved_contents": [h.payload["content"] for h in hits],
            "acceptance_question": test_question,
            "acceptance_answer": answer,
            "acceptance_citations_ok": all(k in answer for k in ("2.4", "1.44", "1.8")),
        },
        "phase2_candidates": [],
        "mesh_metrics": {},
        "cad_verification": {},
        "drawing_deliverables": {},
        "human_feedback": {},
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    log("[Phase1] manifest.json 已写入: %s" % manifest_path)
    return manifest


def main():
    log("=" * 72)
    log("===== PHASE 1 启动：主控大脑 + 私有工艺知识库 RAG =====")

    # 0) 先让 Ollama 卸载常驻模型，给 bge-m3 腾出显存（RTX5080 16GB 是全程最紧资源）
    try:
        before = ollama.ps()
        log("[Phase1] Ollama 常驻模型(before): %s" % [
            m.get("name") if isinstance(m, dict) else getattr(m, "name", "?")
            for m in (before.get("models", []) if isinstance(before, dict) else getattr(before, "models", []))
        ])
    except Exception as e:
        log("[Phase1][warn] ollama.ps 查询失败: %r" % (e,))
    try:
        ollama.generate(model=LLM_MODEL, prompt="ok", keep_alive=0, options={"num_predict": 1})
        log("[Phase1] 已请求 Ollama 卸载 %s (keep_alive=0)，VRAM 让给 bge-m3" % LLM_MODEL)
    except Exception as e:
        log("[Phase1][warn] Ollama 预卸载失败(不影响流程): %r" % (e,))

    brain = HyperDesignBrain(use_gpu=True)

    log("[Phase1] [3/3] 灌入私有工艺知识库 (%d 条)..." % len(CORPUS))
    brain.reset_collection()
    brain.ingest_documents(CORPUS)

    # 验收提问（工程文件 L155 原文）
    test_question = "现在要设计一款跨度 180mm 的 PC+ABS 材质手持终端外壳，交由二号车间生产，请问名义壁厚、加强筋厚度和拔模斜度应该定多少？"
    log("--- 验收提问 --- %s" % test_question)
    answer = brain.query_and_plan(test_question, unload_vram_after=True)

    print("\n--- 主控模型回答 ---\n%s\n" % answer, flush=True)

    # 检索证据（供 top3 引用留档）
    hits = brain.search(test_question, limit=3)
    brain.release_embedder()

    # 硬性校验：2.4 / 1.44 / 1.8 必须原样出现
    citations = {k: (k in answer) for k in ("2.4", "1.44", "1.8")}
    ok = all(citations.values())
    log("[Phase1] 铁律校验(规范数值原样引用) 2.4=%s 1.44=%s 1.8=%s -> %s"
        % (citations["2.4"], citations["1.44"], citations["1.8"], "PASS" if ok else "FAIL"))

    manifest = write_manifest_and_outputs(brain, hits, answer, test_question, None)

    # 01_brief.md —— 下游 Phase 2/5 的直接输入
    brief_dir = Path(r"D:\hyperdesign\01_brief")
    brief_dir.mkdir(parents=True, exist_ok=True)
    brief_path = brief_dir / "01_brief.md"
    brief_md = f"""# Phase 1 设计任务书 / 工艺约束（RAG 检索产出）

- 项目ID: {PROJECT_ID}
- 生成时间: {ts()}
- 向量库: {COLLECTION_NAME} (bge-m3 1024d COSINE, 嵌入式 @ {QDRANT_PATH})
- 主控模型: {LLM_MODEL}

## 一、产品需求（原始 Brief）
```text
{CORPUS[2]['content']}
```

## 二、RAG 命中的企业工艺规范（原样引用，严禁改写）
{chr(10).join(['- [%s]: %s' % (h.payload['source'], h.payload['content']) for h in hits])}

## 三、主控模型回答（验收提问）
提问: {test_question}

```text
{answer}
```

## 四、硬性工艺约束（写入 manifest.json -> 全链路强制）
| 参数 | 数值 | 来源 |
|---|---|---|
| 名义壁厚 | 2.4 mm | 内部注塑工艺规范_v2.4.pdf |
| 加强筋厚度上限 | 1.44 mm (名义壁厚60%) | 内部注塑工艺规范_v2.4.pdf |
| 拔模斜度 | >= 1.8 deg | 内部注塑工艺规范_v2.4.pdf |
| 包络尺寸 | 120 x 80 x 45 mm | 产品设计任务书 |
| 外圆角 / 内圆角 | <= 3.0 mm / <= 1.0 mm | Phase 5 CAD 铁律 |
| DFM 红线 | p10壁厚 >= 2.4mm 且无 <1.8mm / >4.5mm 区域 | Phase 7 DFM 双层评判 |

## 五、Phase 1 验收结论
- 规范数值原样引用校验: {'PASS' if ok else 'FAIL'} (2.4={citations['2.4']}, 1.44={citations['1.44']}, 1.8={citations['1.8']})
- 下一步: Phase 2 —— 由本任务书驱动 FLUX.2-dev 生成 4 个概念变体（base_seed=88400）
"""
    brief_path.write_text(brief_md, encoding="utf-8")
    log("[Phase1] 设计任务书已写入: %s" % brief_path)

    # 更新 status.json
    status = {
        "project_id": PROJECT_ID,
        "product": "工业无线振动/温湿度三合一传感器外壳",
        "spec": {"bbox_mm": [120, 80, 45], "wall_mm": 2.4, "draft_deg": 1.8, "screws": "4xM4", "gasket": "硅胶防水圈"},
        "phase": "1_brain_rag",
        "phase_status": "completed" if ok else "completed_with_warning",
        "updated_at": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        "artifacts": {
            "brief": str(brief_path),
            "manifest": str(PROJECT_DIR / "manifest.json"),
            "qdrant": QDRANT_PATH,
        },
        "blockers": [] if ok else ["RAG答案未完整引用规范数值"],
        "next": "Phase 2: FLUX.2-dev 生成4张概念图 (base_seed=88400) + VLM初筛 + 人工勾选",
    }
    STATUS_JSON.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")

    log("[Phase1] ===== PHASE 1 完成 (%s) =====" % ("PASS" if ok else "WARN"))
    print(json.dumps({"PHASE1_RESULT": "PASS" if ok else "FAIL", "citations": citations}, ensure_ascii=False))
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
