# -*- coding: utf-8 -*-
"""
HyperDesign Phase 7 (第一层) - 双层自动评判引擎：客观几何/DFM 硬规则 > VLM 主观审美
按《工程文件》Phase 7 第一节 (docs/工程文件_extracted.txt L1357-L1448) 落地

偏差（issues.md #12）：VLM 由 docx 的 qwen2.5-vl:7b 换为本机 qwen3.7-flash:latest。
运行: E:\\hyperdesign\\venvs\\hd_cad\\Scripts\\python.exe D:\\hyperdesign\\src\\phase7_dfm_and_vlm_judge.py [--geometry-only]
"""
import argparse
import base64
import json
import sys
import datetime
from pathlib import Path

import numpy as np
import trimesh

sys.path.insert(0, str(Path(__file__).parent))
from hd_llm import chat as llm_chat, unload as llm_unload  # noqa: E402

try:  # Windows 控制台可能是 GBK，统一把 stdout/stderr 切到 UTF-8 容错，避免中文/³ 等字符抛 UnicodeEncodeError
    import sys as _sys
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    _sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

VLM_MODEL = "qwen3.7-flash:latest"      # 偏差: docx 为 qwen2.5-vl:7b
PROGRESS_LOG = Path(r"D:\hyperdesign\progress.log")


def log(msg: str) -> None:
    line = f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(PROGRESS_LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


class HyperDesignJudge:
    def __init__(self, project_dir: Path):
        self.project_dir = project_dir
        self.manifest_path = project_dir / "manifest.json"

    # ---------- 第一优先级：客观几何与 DFM 规则硬校验 ----------
    def evaluate_geometry_dfm(self) -> dict:
        with open(self.manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
        stl_rel = manifest.get("mesh_metrics", {}).get("clean_stl", "03_mesh/white_model_clean.stl")
        stl_path = self.project_dir / stl_rel
        mesh = trimesh.load_mesh(str(stl_path))
        mfg = manifest.get("mfg_constraints", manifest.get("manufacturing_constraints", {}))
        min_wall_req = float(mfg.get("min_wall_thickness_mm", 2.4))
        min_draft_req = float(mfg.get("min_draft_angle_deg", 1.8))

        # 1. 随机采样 500 个表面点向内发射反向法线射线，计算真实局部壁厚分布
        pts, face_idx = trimesh.sample.sample_surface(mesh, 500)
        inward_normals = -mesh.face_normals[face_idx]
        locations, index_ray, _ = mesh.ray.intersects_location(
            ray_origins=pts + inward_normals * 0.05,
            ray_directions=inward_normals,
            multiple_hits=False,
        )
        if len(locations) > 0:
            hit_origins = pts[index_ray]
            thicknesses = np.linalg.norm(locations - hit_origins, axis=1)
            p10_thickness = float(np.percentile(thicknesses, 10))
            thick_max = float(np.percentile(thicknesses, 90))
        else:
            p10_thickness = min_wall_req
            thick_max = min_wall_req

        # 2. 拔模角检查：查找接近垂直立面（法线 Z 分量接近 0）的实际倾角
        z_dots = np.abs(mesh.face_normals[:, 2])
        vertical_wall_mask = z_dots < np.sin(np.radians(10.0))
        if np.any(vertical_wall_mask):
            draft_angles_deg = np.degrees(np.arcsin(z_dots[vertical_wall_mask]))
            median_draft = float(np.median(draft_angles_deg))
        else:
            median_draft = 90.0

        # 3. 包络长宽比偏差（Proportion Drift, >8% 淘汰）
        target = manifest.get("target_bbox_mm", {})
        actual = manifest.get("mesh_metrics", {}).get("actual_bbox_mm", {})
        drift = {}
        for ax in ("x", "y", "z"):
            t = float(target.get(ax, 0) or 0)
            a = float(actual.get(ax, 0) or 0)
            drift[ax] = round(abs(a - t) / t * 100.0, 2) if t else 0.0
        drift_ok = all(v <= 8.0 for v in drift.values())

        # 4. 汇总硬性判定
        wall_ok = p10_thickness >= (min_wall_req * 0.85)
        draft_ok = median_draft >= (min_draft_req * 0.8)
        over_thick = thick_max > 4.5
        dfm_passed = bool(mesh.is_watertight and wall_ok and draft_ok and drift_ok and not over_thick)
        report = {
            "is_watertight": bool(mesh.is_watertight),
            "measured_p10_wall_mm": round(p10_thickness, 2),
            "measured_p90_wall_mm": round(thick_max, 2),
            "required_min_wall_mm": min_wall_req,
            "measured_median_draft_deg": round(median_draft, 2),
            "required_min_draft_deg": min_draft_req,
            "proportion_drift_pct": drift,
            "over_thick_risk": bool(over_thick),
            "face_count": int(len(mesh.faces)),
            "dfm_hard_passed": dfm_passed,
            "evaluated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        }
        log(f"[DFM 硬规则检验] 通过={dfm_passed} | 实测P10壁厚={report['measured_p10_wall_mm']}mm | "
            f"P90={report['measured_p90_wall_mm']}mm | 立面拔模角={report['measured_median_draft_deg']}° | "
            f"水密={report['is_watertight']} | 包络漂移={drift}")
        with open(self.manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
        manifest["phase7_dfm_report"] = report
        with open(self.manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)
        return report

    # ---------- 第二优先级：VLM 视觉初筛 ----------
    def evaluate_vlm_concepts(self, brief_text: str) -> list:
        with open(self.manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
        scored = []
        for cand in manifest.get("phase2_candidates", []):
            p = cand.get("image_path") or cand.get("file")
            img_path = Path(p)
            if not img_path.is_absolute():
                img_path = self.project_dir / p
            if not img_path.exists():
                log(f"[VLM][warn] 概念图缺失: {img_path}")
                cand["vlm_score"] = {"error": "image_missing"}
                scored.append(cand)
                continue
            img_b64 = base64.b64encode(img_path.read_bytes()).decode("utf-8")
            prompt = (
                f"请作为工业设计总监审阅这张产品概念图。原始设计需求为：{brief_text}\n"
                "请从以下3个维度按 1~10 分打分，并只输出严格 JSON 格式 "
                '{"geometry_clarity": 8, "manufacturing_feasibility": 9, "brief_alignment": 8, "reason": "..."}：\n'
                "1. geometry_clarity：轮廓是否清晰、背景是否干净无遮挡（适合3D重建）；\n"
                "2. manufacturing_feasibility：分型线、倒角、装配螺钉位是否符合真实注塑/机加工逻辑；\n"
                "3. brief_alignment：是否完整体现了需求中的结构特征（顶部导光柱窗口、两侧M6安装耳、4颗M4螺钉、PC+ABS上盖+铝合金底座）。"
            )
            try:
                text = llm_chat(model=VLM_MODEL, messages=[{"role": "user", "content": prompt}],
                                images=[str(img_path)], keep_alive=0,
                                options={"temperature": 0.1})
                s = text.strip()
                if "```" in s:
                    s = s.split("```")[1]
                    if s.lstrip().lower().startswith("json"):
                        s = s.lstrip()[4:]
                a, b = s.find("{"), s.rfind("}")
                score_data = json.loads(s[a:b + 1]) if a >= 0 and b > a else {"raw": text[:300]}
                cand["vlm_score"] = score_data
                log(f"[VLM 初筛] {cand.get('concept_id')}: {json.dumps(score_data, ensure_ascii=False)[:220]}")
            except Exception as e:
                cand["vlm_score"] = {"error": repr(e)}
                log(f"[VLM][warn] {cand.get('concept_id')} 打分失败: {e!r}")
            scored.append(cand)
        llm_unload(VLM_MODEL)
        manifest["phase2_candidates"] = scored
        with open(self.manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)
        return scored


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--geometry-only", action="store_true")
    ap.add_argument("--vlm-only", action="store_true")
    args = ap.parse_args()
    log("=" * 72)
    log("===== PHASE 7 第一层：DFM 几何硬校验 + VLM 视觉初筛 =====")
    proj = Path(r"D:\hyperdesign\workspace\proj_20261014_001")
    judge = HyperDesignJudge(proj)
    rep = None
    if not args.vlm_only:
        rep = judge.evaluate_geometry_dfm()
    if not args.geometry_only:
        brief = Path(r"D:\hyperdesign\01_brief\01_brief.md")
        brief_text = brief.read_text(encoding="utf-8")[:900] if brief.exists() else \
            "工业级无线振动温湿度三合一传感器外壳 120x80x45mm, PC+ABS上盖壁厚2.4mm拔模1.8度, 铝合金CNC底座带M6安装耳, 4颗M4螺钉"
        judge.evaluate_vlm_concepts(brief_text)
    print(json.dumps({"PHASE7_JUDGE": "OK", "dfm": rep}, ensure_ascii=False))
    sys.exit(0 if (rep is None or rep["dfm_hard_passed"]) else 2)
