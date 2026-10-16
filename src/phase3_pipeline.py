# -*- coding: utf-8 -*-
"""
HyperDesign Phase 3 - 总控串联：概念图 -> WSL2 TRELLIS 3D 重建 -> Blender 无头清洗
按《工程文件》Phase 3 Step 3 (docs/工程文件_extracted.txt L522-L556) 落地

偏差（issues.md #10/#11）：TRELLIS 部署在 WSL2 (http://127.0.0.1:8003)，
源码在 ext4 (~/TRELLIS) 并软链到 /mnt/d/hyperdesign/src/TRELLIS；
Blender 使用便携版 D:\\hyperdesign\\tools\\blender-4.2.9-windows-x64\\blender.exe。

运行: E:\\hyperdesign\\venvs\\hd_brain\\Scripts\\python.exe D:\\hyperdesign\\src\\phase3_pipeline.py
"""
import json
import subprocess
import sys
import time
import datetime
import urllib.request
from pathlib import Path

try:  # Windows 控制台可能是 GBK，统一把 stdout/stderr 切到 UTF-8 容错，避免中文/³ 等字符抛 UnicodeEncodeError
    import sys as _sys
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    _sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

TRELLIS_API = "http://127.0.0.1:8003/image_to_3d"
TRELLIS_HEALTH = "http://127.0.0.1:8003/health"
BLENDER_EXE = r"D:\hyperdesign\tools\blender-4.2.9-windows-x64\blender.exe"
BLENDER_CLEAN_SCRIPT = r"D:\hyperdesign\src\blender_clean_mesh.py"
PROGRESS_LOG = Path(r"D:\hyperdesign\progress.log")


def log(msg: str) -> None:
    line = f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(PROGRESS_LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def http_json(url: str, payload=None, timeout=1800):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def run_phase3(project_dir: Path, texture: bool = False):
    manifest_path = project_dir / "manifest.json"
    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    # 1. 查找 Phase 2 中被设计师勾选的概念图（若未勾选，默认取第 1 张）
    candidates = manifest.get("phase2_candidates", [])
    if not candidates:
        raise RuntimeError("manifest.phase2_candidates 为空，请先跑 Phase 2")
    selected = next((c for c in candidates if c.get("selected_for_3d")), candidates[0])
    win_img = selected.get("image_path") or selected.get("file")
    img_path = Path(win_img)
    if not img_path.is_absolute():
        img_path = project_dir / win_img
    if not img_path.exists():
        raise RuntimeError(f"概念图不存在: {img_path}")
    win_raw_glb = str(project_dir / "03_mesh" / "raw_trellis.glb")
    (project_dir / "03_mesh").mkdir(parents=True, exist_ok=True)

    log(f"[Phase3] 选中概念图: {img_path.name} (concept_id={selected.get('concept_id')})，请求 WSL2 TRELLIS 重建 3D...")
    try:
        health = http_json(TRELLIS_HEALTH, timeout=30)
        log(f"[Phase3] TRELLIS 服务在线: {json.dumps(health, ensure_ascii=False)}")
    except Exception as e:
        log(f"[Phase3][fatal] TRELLIS 服务不可达: {e!r}")
        raise

    t0 = time.time()
    resp = http_json(TRELLIS_API, {
        "win_image_path": str(img_path).replace("\\", "/"),
        "win_output_glb": win_raw_glb.replace("\\", "/"),
        "seed": int(selected.get("seed", 42)),
        "texture": texture,
    }, timeout=3600)
    log(f"[Phase3] TRELLIS 重建完成，耗时 {time.time()-t0:.0f}s -> {resp.get('wsl_path')}")

    # 2. Blender 无头拓扑清洗 + 物理尺寸对齐
    log("[Phase3] 启动 Blender 无头引擎执行拓扑清洗与物理尺寸校准...")
    cmd = [BLENDER_EXE, "--background", "--python", BLENDER_CLEAN_SCRIPT, "--", str(manifest_path)]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=1800,
                          encoding="utf-8", errors="replace")
    for line in proc.stdout.splitlines():
        if line.startswith("[Blender Clean]") or "Error" in line:
            log("  " + line)
    if proc.returncode != 0:
        log(f"[Phase3][error] Blender 失败 rc={proc.returncode}\n{proc.stderr[-1200:]}")
        raise RuntimeError("Blender 清洗失败")

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)
    mm = manifest.get("mesh_metrics", {})
    log(f"[Phase3 验收] 真实包络(mm): {mm.get('actual_bbox_mm')} | 面数 {mm.get('face_count')} | "
        f"比例 {mm.get('proportion_ratio')}")
    clean_glb = project_dir / "03_mesh" / "white_model_clean.glb"
    clean_stl = project_dir / "03_mesh" / "white_model_clean.stl"
    for p in (clean_glb, clean_stl):
        log(f"  产出: {p.name} {'OK' if p.exists() else 'MISSING'} ({p.stat().st_size if p.exists() else 0} 字节)")
    return manifest


if __name__ == "__main__":
    log("=" * 72)
    log("===== PHASE 3 启动：TRELLIS 白模重建 + Blender 清洗对齐 =====")
    proj = Path(r"D:\hyperdesign\workspace\proj_20261014_001")
    try:
        run_phase3(proj)
        log("[Phase3] ===== PHASE 3 完成 =====")
        sys.exit(0)
    except Exception as e:
        log(f"[Phase3] ===== PHASE 3 失败: {e!r} =====")
        sys.exit(1)
