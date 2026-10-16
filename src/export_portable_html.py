# -*- coding: utf-8 -*-
"""
HyperDesign Phase 4 - 便携式单文件 3D 审阅网页打包器
按《工程文件》Phase 4 第四节 (docs/工程文件_extracted.txt L819-L837) 落地
GLB -> Base64 内嵌，双击即可离线 360° 查看（发给客户/模具厂）
"""
import base64
import re
import json
from pathlib import Path

try:  # Windows 控制台可能是 GBK，统一把 stdout/stderr 切到 UTF-8 容错，避免中文/³ 等字符抛 UnicodeEncodeError
    import sys as _sys
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    _sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

PROJECT_DIR = Path(r"D:\hyperdesign\workspace\proj_20261014_001")


def pack_portable_3d_viewer(project_dir: Path):
    glb_path = project_dir / "03_mesh" / "white_model_clean.glb"
    b64_glb = base64.b64encode(glb_path.read_bytes()).decode("ascii")
    html_template = Path(r"D:\hyperdesign\src\templates\viewer.html").read_text(encoding="utf-8")

    # 1) 白模走内嵌 Data URI，彻底免服务器
    portable = html_template.replace(
        "`/files/${PROJECT_ID}/${metrics.clean_glb || '03_mesh/white_model_clean.glb'}`",
        f"'data:model/gltf-binary;base64,{b64_glb}'"
    )
    # 2) 概念图与 manifest 也内嵌（否则离线打开会 fetch 失败）
    manifest_path = project_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    imgs = {}
    for c in manifest.get("phase2_candidates", []):
        for key in ("file", "image_path"):
            f = c.get(key)
            if not f:
                continue
            p = Path(str(f))
            if not p.is_absolute():
                p = project_dir / str(f)
            if p.exists():
                mime = "image/png" if p.suffix.lower() == ".png" else "image/jpeg"
                imgs[str(f).replace("\\", "/")] = f"data:{mime};base64," + base64.b64encode(p.read_bytes()).decode("ascii")
                break
    for rel, uri in imgs.items():
        portable = portable.replace(f"/files/${{PROJECT_ID}}/{rel}", uri)
    portable = portable.replace(
        "const res = await fetch(`/api/project/${PROJECT_ID}`);\n  const manifest = await res.json();",
        "const manifest = " + json.dumps(manifest, ensure_ascii=False) + ";"
    )
    # 提交按钮在离线包里失效，给出提示
    portable = portable.replace(
        "const data = await res.json();\n  document.getElementById('status-msg').innerText = data.message;",
        "const data = await res.json().catch(() => ({message: '离线便携包：请将上述参数填入工程系统后提交'}));\n"
        "  document.getElementById('status-msg').innerText = data.message;"
    )

    out_file = project_dir / "04_viewer" / f"{project_dir.name}_3D_Concept_Share.html"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(portable, encoding="utf-8")
    print(f"[Phase 4 便携包] 已生成免服务独立 3D 演示网页: {out_file}  ({out_file.stat().st_size/1e6:.2f} MB)")
    return out_file


if __name__ == "__main__":
    pack_portable_3d_viewer(PROJECT_DIR)
