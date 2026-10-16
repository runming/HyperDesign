# -*- coding: utf-8 -*-
"""
HyperDesign Phase 5 - 白模几何截面锚点提取
按《工程文件》Phase 5 第二节 (docs/工程文件_extracted.txt L872-L901) 落地
对 Phase 3 清洗后的白模做 Z 轴三层高度切片(10%/50%/90%)，量出真实截面长宽喂给大模型
"""
import trimesh
import numpy as np


def extract_white_model_anchors(stl_path: str) -> dict:
    """对 Phase 3 清洗后的白模做 Z 轴三层高度切片，提取真实截面长宽作为 CAD 参数锚点"""
    mesh = trimesh.load_mesh(stl_path)
    min_bound, max_bound = mesh.bounds
    total_dims = max_bound - min_bound  # [X, Y, Z]
    anchors = {
        "overall_bbox_mm": {
            "x": round(float(total_dims[0]), 2),
            "y": round(float(total_dims[1]), 2),
            "z": round(float(total_dims[2]), 2),
        },
        "z_sections": {},
    }
    for label, ratio in [("bottom_10pct", 0.1), ("mid_50pct", 0.5), ("top_90pct", 0.9)]:
        z_height = min_bound[2] + total_dims[2] * ratio
        slice_2d = mesh.section(plane_origin=[0, 0, z_height], plane_normal=[0, 0, 1])
        if slice_2d is not None:
            slice_pts = slice_2d.vertices
            if len(slice_pts) == 0:
                continue
            sec_span = slice_pts.max(axis=0) - slice_pts.min(axis=0)
            anchors["z_sections"][label] = {
                "z_mm": round(float(z_height), 2),
                "span_x_mm": round(float(sec_span[0]), 2),
                "span_y_mm": round(float(sec_span[1]), 2),
            }
    return anchors


if __name__ == "__main__":
    import json
    import sys
    p = sys.argv[1] if len(sys.argv) > 1 else r"D:\hyperdesign\workspace\proj_20261014_001\03_mesh\white_model_clean.stl"
    print(json.dumps(extract_white_model_anchors(p), ensure_ascii=False, indent=2))
