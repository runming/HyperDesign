# -*- coding: utf-8 -*-
"""
HyperDesign Phase 2 — Brief -> 主控转译 -> ComfyUI(FLUX.2-dev) 批量出图 -> VLM初筛 -> 显存释放
按《工程文件》Phase 2 落地（docs/工程文件_extracted.txt L216-L349）

落地偏差（记录于 D:\\hyperdesign\\issues.md）：
  1. 权重: 本机为 FLUX.2-dev (flux2_dev_fp8mixed + mistral_3_small_flux2 + flux2-vae)，
     而非 docx 所写 FLUX.1-dev (t5xxl+clip_l+ae) —— 提示词协议与验收指标完全一致。
  2. 服务端口: 8000（docx 写 8188），启动参数带 --lowvram（16GB 显存跑 33GB fp8 权重）。

运行: E:\\hyperdesign\\venvs\\hd_brain\\Scripts\\python.exe D:\\hyperdesign\\src\\phase2_concept_gen.py [--pick N]
"""
import os
import io
import sys
import json
import time
import shutil
import argparse
import datetime
import urllib.parse
import urllib.request
from pathlib import Path

os.environ["HF_HOME"] = r"D:\hyperdesign\models\hf_cache"
os.environ["OLLAMA_MODELS"] = r"D:\hyperdesign\models\ollama"

import ollama

try:  # Windows 控制台可能是 GBK，统一把 stdout/stderr 切到 UTF-8 容错，避免中文/³ 等字符抛 UnicodeEncodeError
    import sys as _sys
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    _sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# ================= 配置区 (工程文件 L229-L232) =================
COMFY_HOST = "127.0.0.1:8000"                                   # 偏差: docx 为 8188
WORKFLOW_JSON_PATH = Path(r"D:\hyperdesign\src\workflows\flux2_concept_api.json")
LLM_MODEL = "qwen38-uncensored-128k:latest"                     # 偏差: docx 为 qwen3.5:9b
VLM_MODEL = "qwen3.7-flash:latest"                              # 偏差: docx 为 qwen2.5-vl:7b / glm-4v
BASE_SEED = 88400
PROJECT_ID = "proj_20261014_001"
PROJECT_DIR = Path(r"D:\hyperdesign\workspace") / PROJECT_ID
CONCEPTS_DIR = Path(r"D:\hyperdesign\02_concepts") / PROJECT_ID
PROGRESS_LOG = Path(r"D:\hyperdesign\progress.log")


def ts() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log(msg: str) -> None:
    line = f"[{ts()}] {msg}"
    print(line, flush=True)
    with open(PROGRESS_LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def http_json(url: str, payload=None, timeout=60):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = r.read()
    return json.loads(body) if body else {}


# ---- 工程文件 L216-L222：面向 TRELLIS 的三维重建友好型后缀（铁律） ----
GEO_SUFFIX = (
    "Single whole product only, isometric three-quarter view, centered in frame, "
    "orthographic-like lens (no wide-angle distortion). "
    "Isolated on solid flat neutral light grey background (#E5E5E5), no props, no text, no watermark. "
    "Even studio softbox diffuse lighting, ambient occlusion, no harsh cast shadows, no specular mirror highlights. "
    "Industrial product design prototype, clean CAD-like chamfered edges and visible parting lines, "
    "matte plastic and brushed aluminum texture, realistic industrial manufacturing proportions, "
    "flat matte surface finish suitable for photogrammetry-grade 3D reconstruction."
)


class Phase2ConceptExplorer:
    def __init__(self, project_dir: Path):
        self.project_dir = project_dir
        self.concepts_dir = project_dir / "02_concepts"
        self.concepts_dir.mkdir(parents=True, exist_ok=True)
        self.manifest_path = project_dir / "manifest.json"

    # ---------- Step 1: Brief -> 4 组差异化英文提示词 (工程文件 L239-L260) ----------
    def brief_to_flux_prompts(self, design_brief: str, num_variants: int = 4, reuse: bool = True):
        cache = self.concepts_dir / "prompts.json"
        if reuse and cache.exists():
            try:
                cached = json.loads(cache.read_text(encoding="utf-8"))
                if cached:
                    log("[Phase2] 复用已缓存的 %d 组提示词: %s" % (
                        len(cached), " | ".join(p["variant_name"] for p in cached)))
                    return cached[:num_variants]
            except Exception as e:
                log("[Phase2][warn] 提示词缓存读取失败: %r" % (e,))
        system_prompt = """你是 HyperDesign 的工业视觉导演。你的任务是将用户的【产品设计需求与工艺约束】转化为用于 FLUX 的英文提示词。
为了确保后续 TRELLIS 能够完美重建 3D 网格，每条提示词必须遵循以下铁律：
1. 视角固定：Single whole product, isometric three-quarter view, centered in frame, orthographic-like lens (no wide-angle distortion).
2. 背景与光照：Solid flat neutral grey background, studio softbox diffuse lighting, no harsh shadows, no reflections, matte surface finish.
3. 工程细节：Clearly visible parting lines, functional chamfers, screw bosses or snap-fit seams if applicable, realistic industrial manufacturing proportions.
4. 请输出严格的 JSON 数组格式，包含 4 个不同造型演化方向的变体（例如：硬朗切面风、圆润流线风、模块化装甲风、极简包豪斯风），字段为 [{"variant_name": "...", "flux_prompt": "..."}]。
只输出 JSON 数组本身，不要输出任何解释、Markdown 代码块或多余文字。"""
        user_prompt = (
            f"【产品设计需求与工艺约束】\n{design_brief}\n\n"
            f"请输出 {num_variants} 个变体。每条 flux_prompt 必须以如下三维重建友好型后缀结尾（可原样拼接）：\n{GEO_SUFFIX}"
        )
        log("[Phase2] 调用主控模型 %s 生成 %d 组 FLUX 提示词..." % (LLM_MODEL, num_variants))
        t0 = time.time()
        resp = ollama.chat(
            model=LLM_MODEL,
            messages=[{"role": "system", "content": system_prompt},
                      {"role": "user", "content": user_prompt}],
            keep_alive=0,
            options={"temperature": 0.8},
        )
        text = resp["message"]["content"] if isinstance(resp, dict) else resp.message.content
        log("[Phase2] 提示词生成完成，耗时 %.1fs" % (time.time() - t0))
        prompts = self._parse_json_array(text)
        if prompts is None:
            log("[Phase2][warn] 主控模型未返回合法 JSON，启用兜底变体集")
            prompts = self._fallback_prompts()
        prompts = prompts[:num_variants]
        for i, p in enumerate(prompts):
            if GEO_SUFFIX[:60] not in p.get("flux_prompt", ""):
                p["flux_prompt"] = p.get("flux_prompt", "").strip() + " " + GEO_SUFFIX
            p["seed"] = BASE_SEED + i
        log("[Phase2] 变体清单: %s" % " | ".join("%s(seed=%d)" % (p["variant_name"], p["seed"]) for p in prompts))
        cache.write_text(json.dumps(prompts, ensure_ascii=False, indent=2), encoding="utf-8")
        return prompts

    @staticmethod
    def _parse_json_array(text: str):
        s = text.strip()
        if "```" in s:
            s = s.split("```")[1]
            if s.lstrip().lower().startswith("json"):
                s = s.lstrip()[4:]
        start, end = s.find("["), s.rfind("]")
        if start < 0 or end < 0:
            return None
        try:
            arr = json.loads(s[start:end + 1])
        except Exception:
            return None
        out = []
        for a in arr:
            if isinstance(a, dict) and a.get("flux_prompt"):
                out.append({"variant_name": str(a.get("variant_name") or f"variant_{len(out)+1}"),
                            "flux_prompt": str(a["flux_prompt"])})
        return out or None

    @staticmethod
    def _fallback_prompts():
        base = ("Industrial wireless vibration + temperature/humidity 3-in-1 sensor enclosure, "
                "120 x 80 x 45 mm envelope, PC+ABS injection molded top cover with 2.4mm nominal wall, "
                "1.8 degree draft, status LED light-pipe window on top, aluminum CNC base with two M6 mounting ears, "
                "4 x M4 hex socket screws clamping a silicone gasket, ")
        styles = [
            ("硬朗切面风", "hard-edged faceted architecture, crisp planar chamfered surfaces, angular bold silhouette, "),
            ("圆润流线风", "soft rounded streamlined surfaces, generous continuous fillets, smooth organic flow, "),
            ("模块化装甲风", "modular armored construction, visible bolted sub-panels, rugged machined armor plates, "),
            ("极简包豪斯风", "minimalist Bauhaus design, pure geometric volumes, restrained detailing, functional purity, "),
        ]
        return [{"variant_name": n, "flux_prompt": s + base + GEO_SUFFIX} for n, s in styles]

    # ---------- Step 2: ComfyUI 批量出图 (工程文件 L261-L320) ----------
    def run_comfy_batch(self, prompts, base_seed: int = 88400):
        self._unload_ollama_vram()
        results = []
        for i, p in enumerate(prompts):
            seed = p.get("seed", base_seed + i)
            wf = json.loads(WORKFLOW_JSON_PATH.read_text(encoding="utf-8"))
            wf["103"]["inputs"]["text"] = p["flux_prompt"]
            wf["109"]["inputs"]["noise_seed"] = seed
            wf["112"]["inputs"]["filename_prefix"] = "hd_p2_%s_seed%d" % (self._slug(p["variant_name"]), seed)
            log("[Phase2] (%d/%d) 提交 ComfyUI 出图: %s seed=%d" % (i + 1, len(prompts), p["variant_name"], seed))
            t0 = time.time()
            try:
                resp = http_json("http://%s/prompt" % COMFY_HOST, {"prompt": wf}, timeout=120)
                pid = resp["prompt_id"]
            except Exception as e:
                log("[Phase2][error] 提交失败 %s: %r" % (p["variant_name"], e))
                results.append({"variant_name": p["variant_name"], "seed": seed,
                                "flux_prompt": p["flux_prompt"], "status": "submit_failed", "error": repr(e)})
                continue
            imgs = self._wait_for_images(pid, timeout=1800)
            png_local = self.concepts_dir / ("concept_%d_%s_seed%d.png" % (i + 1, self._slug(p["variant_name"]), seed))
            if imgs:
                self._download_image(imgs[0], png_local)
                dt = time.time() - t0
                log("[Phase2] (%d/%d) 出图完成 %.0fs -> %s" % (i + 1, len(prompts), dt, png_local.name))
                results.append({"concept_id": "concept_%d" % (i + 1),
                                "variant_name": p["variant_name"], "seed": seed,
                                "flux_prompt": p["flux_prompt"], "image_path": str(png_local),
                                "comfy_filename": imgs[0]["filename"], "gen_seconds": round(dt, 1),
                                "status": "generated"})
            else:
                log("[Phase2][error] 出图超时/失败: %s (prompt_id=%s)" % (p["variant_name"], pid))
                results.append({"variant_name": p["variant_name"], "seed": seed,
                                "flux_prompt": p["flux_prompt"], "status": "timeout", "prompt_id": pid})
        self._free_comfy_vram()
        return results

    @staticmethod
    def _slug(s: str) -> str:
        keep = [c for c in s if c.isalnum()]
        return "".join(keep)[:16] or "variant"

    def _wait_for_images(self, prompt_id, timeout=1800):
        t0 = time.time()
        while time.time() - t0 < timeout:
            try:
                hist = http_json("http://%s/history/%s" % (COMFY_HOST, prompt_id), timeout=30)
            except Exception:
                time.sleep(3)
                continue
            if prompt_id in hist:
                entry = hist[prompt_id]
                status = entry.get("status", {})
                if status.get("status_str") == "error":
                    log("[Phase2][error] ComfyUI 执行报错: %s" % json.dumps(status, ensure_ascii=False)[:800])
                    return []
                out = entry.get("outputs", {})
                for node_id, node_out in out.items():
                    if node_out.get("images"):
                        return node_out["images"]
                if status.get("completed"):
                    return []
            time.sleep(3)
        return []

    def _download_image(self, img_meta, dest: Path):
        q = urllib.parse.urlencode({"filename": img_meta["filename"],
                                    "subfolder": img_meta.get("subfolder", ""),
                                    "type": img_meta.get("type", "output")})
        with urllib.request.urlopen("http://%s/view?%s" % (COMFY_HOST, q), timeout=120) as r:
            data = r.read()
        dest.write_bytes(data)

    # ---------- VLM 初筛（几何可重建性自检，工程文件 L342-L343） ----------
    def vlm_prescreen(self, results):
        for r in results:
            if r.get("status") != "generated":
                r["vlm_score"] = 0.0
                r["vlm_verdict"] = "n/a(%s)" % r.get("status")
                continue
            path = Path(r["image_path"])
            geo = self._grey_background_check(path)
            r["bg_check"] = geo
            question = (
                "你在为 3D 重建(TRELLIS)做入库质检。请只回答一个 JSON 对象，字段："
                "{\"score\": 0-10 的整数, \"background_clean\": true/false, \"fully_visible\": true/false, "
                "\"no_mirror_highlight\": true/false, \"led_window_visible\": true/false, "
                "\"mounting_ears_visible\": true/false, \"reason\": \"一句话中文\"}。"
                "评分标准：纯灰无杂物背景、产品完整无裁切、无镜面高光死黑、顶部导光柱窗口与两侧安装耳清晰可见者得高分。"
            )
            try:
                resp = ollama.chat(
                    model=VLM_MODEL,
                    messages=[{"role": "user", "content": question, "images": [str(path)]}],
                    keep_alive=0,
                    options={"temperature": 0.1},
                )
                text = resp["message"]["content"] if isinstance(resp, dict) else resp.message.content
                obj = self._parse_json_obj(text)
                if obj:
                    r["vlm_score"] = float(obj.get("score", 0))
                    r["vlm_verdict"] = json.dumps(obj, ensure_ascii=False)
                else:
                    r["vlm_score"] = 0.0
                    r["vlm_verdict"] = "unparsed: " + text[:200]
                log("[Phase2] VLM初筛 %s: score=%s bg_clean=%s" % (
                    r["concept_id"], r.get("vlm_score"), (obj or {}).get("background_clean")))
            except Exception as e:
                r["vlm_score"] = 0.0
                r["vlm_verdict"] = "vlm_error: %r" % (e,)
                log("[Phase2][warn] VLM 初筛失败(%s): %r" % (r.get("concept_id"), e))
        return results

    @staticmethod
    def _parse_json_obj(text: str):
        s = text.strip()
        if "```" in s:
            s = s.split("```")[1]
            if s.lstrip().lower().startswith("json"):
                s = s.lstrip()[4:]
        a, b = s.find("{"), s.rfind("}")
        if a < 0 or b < 0:
            return None
        try:
            return json.loads(s[a:b + 1])
        except Exception:
            return None

    @staticmethod
    def _grey_background_check(path: Path):
        """客观兜底校验：四角像素是否接近 #E5E5E5 中性灰，且非纯黑/纯白"""
        try:
            from PIL import Image
            im = Image.open(path).convert("RGB")
            w, h = im.size
            pts = [(2, 2), (w - 3, 2), (2, h - 3), (w - 3, h - 3)]
            px = [im.getpixel(p) for p in pts]
            means = [sum(p) / 3 for p in px]
            neutral = all(max(p) - min(p) <= 25 for p in px)
            grey_ok = all(150 <= m <= 250 for m in means)
            return {"size": [w, h], "corner_rgb": px, "neutral": neutral, "grey_ok": grey_ok,
                    "pass": bool(neutral and grey_ok)}
        except Exception as e:
            return {"error": repr(e), "pass": False}

    # ---------- 显存归零验证 (工程文件 L344-L345) ----------
    @staticmethod
    def _unload_ollama_vram():
        try:
            ollama.generate(model=LLM_MODEL, prompt="ok", keep_alive=0, options={"num_predict": 1})
        except Exception as e:
            log("[Phase2][warn] Ollama 卸载失败: %r" % (e,))
        time.sleep(2)
        log("[Phase2] 已请求 Ollama keep_alive=0 卸载，显存让给 ComfyUI FLUX.2")

    @staticmethod
    def _free_comfy_vram():
        try:
            http_json("http://%s/free" % COMFY_HOST, {"unload_models": True, "free_memory": True}, timeout=60)
            log("[Phase2] 已调用 ComfyUI POST /free {unload_models:true, free_memory:true}")
        except Exception as e:
            log("[Phase2][warn] ComfyUI /free 失败: %r" % (e,))

    @staticmethod
    def gpu_report():
        try:
            out = os.popen("nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader").read().strip()
            log("[Phase2] 显存水位: %s" % out)
            return out
        except Exception as e:
            return "n/a %r" % (e,)

    # ---------- manifest 归档 ----------
    def archive(self, results, picked_ids):
        mf = json.loads(self.manifest_path.read_text(encoding="utf-8")) if self.manifest_path.exists() else {}
        cands = []
        for r in results:
            c = dict(r)
            c["selected_for_3d"] = r.get("concept_id") in picked_ids
            cands.append(c)
        mf.setdefault("project_id", PROJECT_ID)
        mf["phase2_candidates"] = cands
        mf["phase2"] = {"base_seed": BASE_SEED, "llm_model": LLM_MODEL, "vlm_model": VLM_MODEL,
                        "comfy_host": COMFY_HOST, "workflow": str(WORKFLOW_JSON_PATH),
                        "generated_at": ts(), "num_candidates": len(cands)}
        if picked_ids:
            pick = next((c for c in cands if c["concept_id"] in picked_ids), None)
            if pick:
                mf["human_feedback"] = {
                    "project_id": PROJECT_ID,
                    "selected_concept_id": pick["concept_id"],
                    "image_path": pick.get("image_path"),
                    "auto_locked_bbox_mm": mf.get("target_bbox_mm", {"x": 120.0, "y": 80.0, "z": 45.0}),
                    "decision": "approve_for_cad",
                    "notes": "Phase2 概念图人工勾选（Phase4 审阅台可再调整）",
                    "at": ts(),
                }
        self.manifest_path.write_text(json.dumps(mf, ensure_ascii=False, indent=2), encoding="utf-8")
        log("[Phase2] manifest.json 已更新: %d 个候选, 勾选=%s" % (len(cands), picked_ids or "无(待人工)"))
        return mf

    # ---------- DPO 样本归档（为 Phase 7 埋线，工程文件 L159-L177 / L346） ----------
    def dpo_archive(self, results, chosen_ids, rejected_ids, notes=""):
        dpo_dir = Path(r"D:\hyperdesign\models\checkpoints\dpo_dataset")
        dpo_dir.mkdir(parents=True, exist_ok=True)
        f = dpo_dir / "phase2_prompt_dpo.jsonl"
        n = 0
        chosen = [r for r in results if r.get("concept_id") in chosen_ids]
        rejected = [r for r in results if r.get("concept_id") in rejected_ids]
        with open(f, "a", encoding="utf-8") as fh:
            for c in chosen:
                for rj in rejected:
                    row = {"prompt": c.get("flux_prompt", ""),
                           "chosen": c.get("flux_prompt", ""),
                           "rejected": rj.get("flux_prompt", ""),
                           "designer_notes": notes or "人工勾选: %s 优于 %s (VLM %s vs %s)" % (
                               c.get("concept_id"), rj.get("concept_id"), c.get("vlm_score"), rj.get("vlm_score"))}
                    fh.write(json.dumps(row, ensure_ascii=False) + "\n")
                    n += 1
        log("[Phase2] DPO 正负样本已归档 %d 条 -> %s" % (n, f))
        return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pick", type=int, default=0, help="人工勾选的 concept 序号(1-4)，0=待人工")
    ap.add_argument("--notes", type=str, default="")
    ap.add_argument("--limit", type=int, default=4, help="本次只生成前 N 张(调试用)")
    ap.add_argument("--reuse-prompts", action="store_true", default=True)
    args = ap.parse_args()

    log("=" * 72)
    log("===== PHASE 2 启动：FLUX.2-dev 概念图生成 (base_seed=%d) =====" % BASE_SEED)

    PROJECT_DIR.mkdir(parents=True, exist_ok=True)
    for sub in ("02_concepts", "03_mesh", "04_threejs", "05_cad", "06_drawings"):
        (PROJECT_DIR / sub).mkdir(parents=True, exist_ok=True)
    CONCEPTS_DIR.mkdir(parents=True, exist_ok=True)

    explorer = Phase2ConceptExplorer(PROJECT_DIR)

    brief_path = Path(r"D:\hyperdesign\01_brief\01_brief.md")
    if brief_path.exists():
        brief = brief_path.read_text(encoding="utf-8")
        log("[Phase2] 已载入 Phase 1 设计任务书: %s (%d 字符)" % (brief_path, len(brief)))
    else:
        brief = ("产品：工业级无线振动温湿度三合一传感器外壳（安装在电机表面）。"
                 "尺寸包络：120mm x 80mm x 45mm。"
                 "工艺要求：顶部为 PC+ABS 抗冲击注塑上盖（壁厚2.4mm，拔模角1.8度，带状态指示灯导光柱窗口），"
                 "底部为铝合金 CNC 底座（带两侧M6安装耳和磁吸沉孔），上下壳通过4颗内六角螺钉锁紧并夹持硅胶防水圈。")
        log("[Phase2][warn] 未找到 01_brief.md，使用工程文件内联 Brief")

    Phase2ConceptExplorer.gpu_report()
    prompts = explorer.brief_to_flux_prompts(brief, num_variants=4)
    if args.limit and args.limit < len(prompts):
        prompts = prompts[:args.limit]
        log("[Phase2] --limit=%d，本次仅生成前 %d 张概念图" % (args.limit, args.limit))
    Phase2ConceptExplorer.gpu_report()

    results = explorer.run_comfy_batch(prompts, base_seed=BASE_SEED)
    Phase2ConceptExplorer.gpu_report()

    results = explorer.vlm_prescreen(results)

    picked = set()
    if args.pick:
        cid = "concept_%d" % args.pick
        picked = {cid}
        rejected = {r["concept_id"] for r in results if r.get("concept_id") and r["concept_id"] != cid}
        explorer.dpo_archive(results, picked, rejected, args.notes)
    explorer.archive(results, picked)

    gen_ok = [r for r in results if r.get("status") == "generated"]
    log("[Phase2] ===== PHASE 2 出图完成: %d/%d 张 =====" % (len(gen_ok), len(results)))
    print(json.dumps({"PHASE2_RESULT": "OK" if len(gen_ok) == len(results) else "PARTIAL",
                      "generated": len(gen_ok),
                      "images": [r.get("image_path") for r in gen_ok],
                      "vlm_scores": {r.get("concept_id"): r.get("vlm_score") for r in gen_ok}},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
