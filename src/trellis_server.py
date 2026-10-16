# -*- coding: utf-8 -*-
"""
HyperDesign Phase 3 - TRELLIS 3D 白模微服务 (在 WSL2 hd_trellis 环境中运行)
按《工程文件》Phase 3 Step 1 (docs/工程文件_extracted.txt L378-L425) 落地

启动: source ~/hd_trellis/bin/activate && python /mnt/d/hyperdesign/src/trellis_server.py
接口: POST http://127.0.0.1:8003/image_to_3d  {win_image_path, win_output_glb, seed}
"""
import gc
import os
from pathlib import Path

import torch
from PIL import Image
from fastapi import FastAPI
from pydantic import BaseModel

MODEL_DIR = "/mnt/d/hyperdesign/models/trellis/TRELLIS-image-large"

app = FastAPI(title="HyperDesign TRELLIS Service")

_pipeline = None


def get_pipeline():
    """惰性加载并复用管道；首次调用后常驻，由 /unload 或 keep_alive 策略释放"""
    global _pipeline
    if _pipeline is None:
        from trellis.pipelines import TrellisImageTo3DPipeline
        print("[TRELLIS] 加载权重至 GPU...", flush=True)
        _pipeline = TrellisImageTo3DPipeline.from_pretrained(MODEL_DIR)
        _pipeline.cuda()
    return _pipeline


def _export_mesh_only(mesh_result, out_path: Path):
    """不依赖 nvdiffrast 的纯几何 GLB 导出（本机无 sudo/nvcc，无法编译 nvdiffrast）"""
    import numpy as np
    import trimesh

    verts = getattr(mesh_result, "vertices", None)
    faces = getattr(mesh_result, "faces", None)
    if verts is None or faces is None:
        verts, faces = mesh_result[0], mesh_result[1]
    v = verts.detach().cpu().numpy() if hasattr(verts, "detach") else np.asarray(verts)
    f = faces.detach().cpu().numpy() if hasattr(faces, "detach") else np.asarray(faces)
    tm = trimesh.Trimesh(vertices=v, faces=f, process=False)
    attrs = getattr(mesh_result, "vertex_attrs", None)
    if attrs is not None:
        a = attrs.detach().cpu().numpy() if hasattr(attrs, "detach") else np.asarray(attrs)
        if a.ndim == 2 and a.shape[1] >= 3 and a.shape[0] == len(v):
            rgb = a[:, :3]
            if rgb.max() <= 1.0 + 1e-3:
                rgb = rgb * 255.0
            tm.visual.vertex_colors = np.clip(rgb, 0, 255).astype(np.uint8)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tm.export(str(out_path))
    print(f"[TRELLIS] 纯几何 GLB 导出完成: {out_path} ({len(tm.faces)} faces)", flush=True)
    return out_path


class ReconstructRequest(BaseModel):
    win_image_path: str   # 例如: "D:/hyperdesign/workspace/proj_001/02_concepts/concept_01.png"
    win_output_glb: str   # 例如: "D:/hyperdesign/workspace/proj_001/03_mesh/raw_trellis.glb"
    seed: int = 42
    texture: bool = False  # 纹理烘焙需要 gaussian 光栅化算子；Phase 3 用素模即可


def win_to_wsl_path(win_path: str) -> Path:
    p = win_path.replace("\\", "/")
    if len(p) > 2 and p[1:3] == ":/":
        drive = p[0].lower()
        return Path(f"/mnt/{drive}/{p[3:]}")
    return Path(p)


@app.get("/health")
def health():
    return {"status": "ok", "model_dir": MODEL_DIR, "exists": os.path.isdir(MODEL_DIR),
            "cuda": torch.cuda.is_available(),
            "loaded": _pipeline is not None}


@app.post("/unload")
def unload():
    global _pipeline
    _pipeline = None
    gc.collect()
    torch.cuda.empty_cache()
    return {"status": "unloaded", "vram_free_gb": round(torch.cuda.mem_get_info()[0] / 1e9, 2)}


@app.post("/image_to_3d")
def reconstruct_3d(req: ReconstructRequest):
    try:
        from trellis.utils import postprocessing_utils  # 依赖 nvdiffrast(需 nvcc 编译)
    except Exception as e:
        print(f"[TRELLIS][warn] postprocessing_utils 不可用({e!r})，使用纯几何导出", flush=True)
        postprocessing_utils = None

    img_path = win_to_wsl_path(req.win_image_path)
    out_path = win_to_wsl_path(req.win_output_glb)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    pipeline = get_pipeline()
    image = Image.open(img_path).convert("RGBA")
    print(f"[TRELLIS] 正在对 {img_path.name} 执行稀疏结构采样与 SLAT 网格重建...", flush=True)
    outputs = pipeline.run(
        image,
        seed=req.seed,
        sparse_structure_sampler_params={"steps": 12, "cfg_strength": 7.5},
        slat_sampler_params={"steps": 12, "cfg_strength": 3.0},
    )

    # 导出 GLB：优先带纹理(需 gaussian 光栅化/nvdiffrast)；失败则退化为纯几何素模
    exported = False
    if req.texture and postprocessing_utils is not None:
        try:
            glb = postprocessing_utils.to_glb(
                outputs['gaussian'][0],
                outputs['mesh'][0],
                simplify=0.90,
                texture_size=1024,
            )
            glb.export(str(out_path))
            exported = True
            print("[TRELLIS] 带纹理 GLB 导出成功", flush=True)
        except Exception as e:
            print(f"[TRELLIS][warn] 纹理烘焙失败({e!r})，回退纯几何导出", flush=True)
    if not exported:
        _export_mesh_only(outputs['mesh'][0], out_path)

    vram = torch.cuda.mem_get_info()
    print(f"[TRELLIS] 白模已导出至 {out_path} | VRAM free={vram[0]/1e9:.2f}GB", flush=True)
    return {"status": "success", "wsl_path": str(out_path), "win_path": req.win_output_glb}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8003)
