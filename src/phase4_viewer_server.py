# -*- coding: utf-8 -*-
"""
HyperDesign Phase 4 - 交互式 3D 审阅工作台 + DPO 标注网关
按《工程文件》Phase 4 (docs/工程文件_extracted.txt L576-L632) 落地

启动: E:\\hyperdesign\\venvs\\hd_brain\\Scripts\\python.exe D:\\hyperdesign\\src\\phase4_viewer_server.py
访问: http://127.0.0.1:8004/review/proj_20261014_001
"""
import json
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, FileResponse
from pydantic import BaseModel

try:  # Windows 控制台可能是 GBK，统一把 stdout/stderr 切到 UTF-8 容错，避免中文/³ 等字符抛 UnicodeEncodeError
    import sys as _sys
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    _sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

app = FastAPI(title="HyperDesign Phase 4 - Interactive 3D Review & DPO Gate")

WORKSPACE_DIR = Path(r"D:\hyperdesign\workspace")
DATASET_DIR = Path(r"D:\hyperdesign\models\checkpoints\dpo_dataset")
DATASET_DIR.mkdir(parents=True, exist_ok=True)


class FeedbackPayload(BaseModel):
    project_id: str
    selected_concept_id: str
    decision: str          # "approve_for_cad" 或 "reject_regenerate"
    adjusted_bbox_mm: dict # 设计师在网页上微调确认后的精确物理包络 {"x": 120.0, "y": 80.0, "z": 45.0}
    designer_notes: str    # 审美或工艺批注


def _cid(c: dict) -> str:
    return c.get("concept_id") or c.get("id") or ""


def _cfile(c: dict) -> str:
    """返回相对项目目录的图片路径，兼容 docx(file) 与本流水线(image_path)两种字段"""
    f = c.get("file") or c.get("image_path") or ""
    f = str(f).replace("\\", "/")
    low = f.lower()
    for marker in ("/02_concepts/", "/03_mesh/"):
        if marker in low:
            return f[low.index(marker) + 1:]
    if "/proj_20261014_001/" in low:
        return f[low.index("/proj_20261014_001/") + len("/proj_20261014_001/"):]
    return f


def _cprompt(c: dict) -> str:
    return c.get("flux_prompt") or c.get("prompt") or c.get("variant_name", "")


@app.get("/api/project/{project_id}")
def get_project_manifest(project_id: str):
    manifest_path = WORKSPACE_DIR / project_id / "manifest.json"
    with open(manifest_path, "r", encoding="utf-8") as f:
        m = json.load(f)
    # 归一化候选字段，前端只认 id / file / prompt
    for c in m.get("phase2_candidates", []):
        c["id"] = _cid(c)
        c["file"] = _cfile(c)
        c["prompt"] = _cprompt(c)
    return m


@app.get("/files/{project_id}/{file_path:path}")
def serve_project_file(project_id: str, file_path: str):
    full_path = WORKSPACE_DIR / project_id / file_path
    return FileResponse(full_path)


@app.post("/api/submit_review")
def submit_review(payload: FeedbackPayload):
    proj_dir = WORKSPACE_DIR / payload.project_id
    manifest_path = proj_dir / "manifest.json"
    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    # 1. 锁定最终确认尺寸（直接作为 Phase 5 建模铁律输入）
    manifest["target_bbox_mm"] = payload.adjusted_bbox_mm
    manifest["human_feedback"] = {
        "decision": payload.decision,
        "selected_concept_id": payload.selected_concept_id,
        "notes": payload.designer_notes,
        "timestamp": datetime.now().isoformat(),
        "adjusted_bbox_mm": payload.adjusted_bbox_mm,
    }

    # 2. 自动构建 Phase 7 (DPO) 偏好样本对：(Brief -> Chosen Prompt vs Rejected Prompts)
    candidates = manifest.get("phase2_candidates", [])
    chosen_item = next((c for c in candidates if _cid(c) == payload.selected_concept_id), None)
    rejected_items = [c for c in candidates if _cid(c) != payload.selected_concept_id]
    n_dpo = 0
    if chosen_item and payload.decision == "approve_for_cad":
        dpo_file = DATASET_DIR / "phase2_prompt_dpo.jsonl"
        with open(dpo_file, "a", encoding="utf-8") as df:
            for rej in rejected_items:
                dpo_record = {
                    "project_id": payload.project_id,
                    "prompt": json.dumps(manifest.get("mfg_constraints", manifest.get("manufacturing_constraints", {})),
                                         ensure_ascii=False),
                    "chosen": _cprompt(chosen_item),
                    "rejected": _cprompt(rej),
                    "designer_notes": payload.designer_notes,
                    "timestamp": datetime.now().isoformat(),
                }
                df.write(json.dumps(dpo_record, ensure_ascii=False) + "\n")
                n_dpo += 1

    if payload.decision == "reject_regenerate":
        manifest["human_feedback"]["rejected_concept_id"] = payload.selected_concept_id

    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    # 同步 selected_for_3d 勾选状态
    for c in candidates:
        c["selected_for_3d"] = (_cid(c) == payload.selected_concept_id)
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    return {"status": "ok", "dpo_records": n_dpo,
            "message": f"审阅结果已写入 manifest.json，DPO 偏好样本对已归档 {n_dpo} 条！"}


@app.get("/review/{project_id}", response_class=HTMLResponse)
def render_workbench(project_id: str):
    html_path = Path(r"D:\hyperdesign\src\templates\viewer.html")
    return html_path.read_text(encoding="utf-8").replace("__PROJECT_ID__", project_id)


if __name__ == "__main__":
    import uvicorn
    print("启动交互式审阅台: http://127.0.0.1:8004/review/proj_20261014_001")
    uvicorn.run(app, host="127.0.0.1", port=8004)
