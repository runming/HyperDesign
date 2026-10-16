# -*- coding: utf-8 -*-
"""
HyperDesign 全链路一键跑通（Phase 1 -> 7）
按《工程文件》总体流程串联各阶段脚本，并维护实时进度日志 D:\\hyperdesign\\progress.log

用法（Windows 宿主）:
  E:\\hyperdesign\\venvs\\hd_brain\\Scripts\\python.exe D:\\hyperdesign\\src\\run_all_phases.py --phases 1,2,3,4,5,6
  （Phase 7 微调建议单独周末夜间运行；Phase 4 审阅台为常驻服务）

各阶段实际执行体：
  Phase1  hd_brain\\python phase1_brain_rag.py            (RAG 私有工艺库 + 主控推理)
  Phase2  hd_brain\\python phase2_concept_gen.py          (FLUX.2-dev 4 概念图 + VLM 初筛 + DPO 归档)
  Phase3  hd_brain\\python phase3_pipeline.py             (WSL2 TRELLIS -> Blender 清洗对齐)
  Phase3.5 hd_cad\\python  phase7_dfm_and_vlm_judge.py    (DFM 硬规则 + VLM 双层初筛)
  Phase4  hd_brain\\python phase4_viewer_server.py        (Three.js 审阅台 :8004, 常驻)
  Phase5  hd_brain\\python phase5_cad_engine.py           (FreeCAD 参数化 + 5 轮自愈 -> STEP)
  Phase6  hd_cad\\python   phase6_drawing_exporter.py     (1:1 激光 DXF + A3 图 + 300dpi PDF)
  Phase7  WSL: hd_unsloth\\python phase7_unsloth_dpo_trainer.py  + phase7_benchmark_eval.py
"""
import argparse
import datetime
import subprocess
import sys
from pathlib import Path

try:  # Windows 控制台可能是 GBK，统一把 stdout/stderr 切到 UTF-8 容错，避免中文/³ 等字符抛 UnicodeEncodeError
    import sys as _sys
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    _sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

PY = {
    "brain": r"E:\hyperdesign\venvs\hd_brain\Scripts\python.exe",
    "cad": r"E:\hyperdesign\venvs\hd_cad\Scripts\python.exe",
}
SRC = Path(r"D:\hyperdesign\src")
PROGRESS_LOG = Path(r"D:\hyperdesign\progress.log")

STEPS = {
    "1": ("Phase1 RAG 工艺检索", PY["brain"], SRC / "phase1_brain_rag.py", []),
    "2": ("Phase2 FLUX.2 概念图", PY["brain"], SRC / "phase2_concept_gen.py", ["--limit", "4"]),
    "3": ("Phase3 白模重建", PY["brain"], SRC / "phase3_pipeline.py", []),
    "35": ("Phase3.5 DFM/VLM 初筛", PY["cad"], SRC / "phase7_dfm_and_vlm_judge.py", []),
    "5": ("Phase5 CAD 自愈建模", PY["brain"], SRC / "phase5_cad_engine.py", []),
    "6": ("Phase6 工程图导出", PY["cad"], SRC / "phase6_drawing_exporter.py", []),
}


def log(msg: str) -> None:
    line = f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(PROGRESS_LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--phases", default="1,2,3,35,5,6", help="逗号分隔: 1,2,3,35,5,6")
    ap.add_argument("--keep-going", action="store_true", help="某阶段失败也继续后续阶段")
    args = ap.parse_args()

    log("=" * 72)
    log("===== HyperDesign 全链路启动 phases=%s =====" % args.phases)
    failed = []
    for key in [p.strip() for p in args.phases.split(",") if p.strip()]:
        if key not in STEPS:
            log(f"[run_all][warn] 未定义阶段 {key}，跳过")
            continue
        title, py, script, extra = STEPS[key]
        log(f"----- 开始 {title} ({script.name}) -----")
        t0 = datetime.datetime.now()
        proc = subprocess.run([py, str(script), *extra], capture_output=True, text=True, cwd=str(SRC))
        dt = (datetime.datetime.now() - t0).total_seconds()
        tail = "\n".join(proc.stdout.splitlines()[-6:])
        log(f"----- 结束 {title}: rc={proc.returncode} 用时 {dt:.0f}s -----")
        if tail:
            log("尾部输出:\n" + tail)
        if proc.returncode != 0:
            failed.append(key)
            log(f"[run_all][error] {title} 失败，stderr 尾部:\n" + "\n".join(proc.stderr.splitlines()[-10:]))
            if not args.keep_going:
                break
    log("===== HyperDesign 全链路结束，失败阶段: %s =====" % (failed or "无"))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
