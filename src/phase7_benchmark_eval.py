# -*- coding: utf-8 -*-
"""
HyperDesign Phase 7 - 守门员机制：黄金基准集回归对比 (Pass@1 / Pass@3)
按《工程文件》Phase 7 第四节 (docs/工程文件_extracted.txt L1543-L1613) 落地

只有当新模型（微调后的 hd-brain:xxx）的 Pass@1 / Pass@3 全面 >= 旧模型时才允许切流上线。
运行: E:\\hyperdesign\\venvs\\hd_brain\\Scripts\\python.exe D:\\hyperdesign\\src\\phase7_benchmark_eval.py --models qwen38-uncensored-128k:latest [hd-brain:v20261016]
"""
import argparse
import json
import sys
import datetime
from pathlib import Path

import trimesh

sys.path.insert(0, str(Path(__file__).parent))
import phase5_cad_engine  # noqa: E402

try:  # Windows 控制台可能是 GBK，统一把 stdout/stderr 切到 UTF-8 容错，避免中文/³ 等字符抛 UnicodeEncodeError
    import sys as _sys
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    _sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

BENCH_JSON = Path(r"D:\hyperdesign\src\benchmark_suite.json")
PROGRESS_LOG = Path(r"D:\hyperdesign\progress.log")


def log(msg: str) -> None:
    line = f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(PROGRESS_LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def load_benchmarks() -> list:
    data = json.loads(BENCH_JSON.read_text(encoding="utf-8"))
    return data["benchmarks"]


def evaluate_model_on_benchmarks(model_tag: str, benchmarks: list, max_retries: int = 3) -> dict:
    """测试指定模型在黄金基准题库上的『一次生成通过率 (Pass@1)』与『自愈通过率 (Pass@3)』"""
    phase5_cad_engine.LLM_MODEL = model_tag
    results = {"model": model_tag, "pass_at_1": 0, "pass_at_3": 0, "total": len(benchmarks),
               "dfm_wall_ok": 0, "details": [], "evaluated_at": datetime.datetime.now().isoformat(timespec="seconds")}
    for item in benchmarks:
        bench_dir = Path(r"D:\hyperdesign\workspace\_benchmarks") / f"{model_tag.replace(':', '_').replace('/', '_')}_{item['id']}"
        (bench_dir / "03_mesh").mkdir(parents=True, exist_ok=True)
        (bench_dir / "05_cad").mkdir(parents=True, exist_ok=True)
        for old in (bench_dir / "05_cad").glob("cad_gen_v*.py"):
            old.unlink()
        box = trimesh.creation.box(extents=[item["target_bbox_mm"]["x"],
                                            item["target_bbox_mm"]["y"],
                                            item["target_bbox_mm"]["z"]])
        box.export(str(bench_dir / "03_mesh" / "white_model_clean.stl"))
        manifest = {
            "project_id": item["id"],
            "product": item["title"],
            "target_bbox_mm": item["target_bbox_mm"],
            "mfg_constraints": item["constraints"],
            "manufacturing_constraints": item["constraints"],
            "mesh_metrics": {"clean_stl": "03_mesh/white_model_clean.stl"},
            "human_feedback": {"notes": item["notes"]},
        }
        (bench_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        engine = phase5_cad_engine.Phase5ParametricCAD(bench_dir)
        try:
            ok, report = engine.generate_and_verify(max_retries=max_retries, allow_fallback=False)
            passed_in_1 = ok and not (bench_dir / "05_cad" / "cad_gen_v2.py").exists()
            if ok:
                results["pass_at_3"] += 1
                if passed_in_1:
                    results["pass_at_1"] += 1
                wall_ok = report.get("volume_mm3", 0) > 0
                if wall_ok:
                    results["dfm_wall_ok"] += 1
            results["details"].append({"bench_id": item["id"], "status": "PASS" if ok else "FAIL",
                                       "pass_at_1": passed_in_1, "report": report})
        except Exception as e:
            results["details"].append({"bench_id": item["id"], "status": "FAIL", "error": str(e)})
        log(f"[Bench] {model_tag} :: {item['id']} -> {results['details'][-1]['status']} "
            f"(Pass@1={results['details'][-1].get('pass_at_1')})")
    total = len(benchmarks)
    log(f"================ 回归测试成绩单 [{model_tag}] ================")
    log(f"一次生成通过率 (Pass@1): {results['pass_at_1']}/{total} ({results['pass_at_1']/total*100:.1f}%)")
    log(f"三轮自愈通过率 (Pass@3): {results['pass_at_3']}/{total} ({results['pass_at_3']/total*100:.1f}%)")
    out = Path(r"D:\hyperdesign\models\checkpoints") / f"benchmark_{model_tag.replace(':', '_').replace('/', '_')}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"[Bench] 成绩单已存盘: {out}")
    return results


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", nargs="+", default=["qwen38-uncensored-128k:latest"],
                    help="待对比模型标签列表: 旧模型在前, 新模型在后")
    ap.add_argument("--max-retries", type=int, default=3)
    ap.add_argument("--only", type=str, default=None, help="只跑某个 bench id（调试）")
    args = ap.parse_args()

    benches = load_benchmarks()
    if args.only:
        benches = [b for b in benches if b["id"] == args.only]
        if not benches:
            log(f"[Bench][fatal] 未找到基准题 {args.only}")
            sys.exit(1)

    scores = {}
    for m in args.models:
        scores[m] = evaluate_model_on_benchmarks(m, benches, max_retries=args.max_retries)

    verdict = None
    if len(args.models) >= 2:
        old, new = args.models[0], args.models[-1]
        o, n = scores[old], scores[new]
        better = (n["pass_at_1"] >= o["pass_at_1"]) and (n["pass_at_3"] >= o["pass_at_3"])
        verdict = {"old": old, "new": new, "old_scores": [o["pass_at_1"], o["pass_at_3"]],
                   "new_scores": [n["pass_at_1"], n["pass_at_3"]],
                   "allowed_to_switch": bool(better),
                   "note": "全面 >= 旧模型才允许切流上线（守门员机制）" if better else "新模型未全面超越，禁止切流"}
        log(f"[Bench 守门员] {json.dumps(verdict, ensure_ascii=False)}")
    print(json.dumps({"PHASE7_BENCH": "OK", "scores": scores, "verdict": verdict}, ensure_ascii=False))
    sys.exit(0)
