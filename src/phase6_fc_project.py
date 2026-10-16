# -*- coding: utf-8 -*-
"""
HyperDesign Phase 6 (Step 1) - FreeCAD 无头 HLR 三视图投影
由 phase6_drawing_exporter.py 通过 freecadcmd.exe 调用：
    freecadcmd.exe phase6_fc_project.py -- <step_path> <out_dxf> [template_svg]

产出: 带 FRONT/TOP/LEFT/ISO 四视图（含隐藏虚线）的中间 DXF（TechDraw 页），
      供 ezdxf 后处理成国标图层工程总图 + 1:1 激光切割图 + 300dpi PDF。
"""
import os
import sys

import FreeCAD
import Part
import TechDraw

DEFAULT_TPL = r"C:\Users\omegahyper\AppData\Local\Programs\FreeCAD 1.1\data\Mod\TechDraw\Templates\ISO\A3_Landscape_ISO5457_advanced.svg"

argv = sys.argv
args = argv[argv.index("--") + 1:] if "--" in argv else argv[1:]
step_path = args[0]
out_dxf = args[1]
tpl_path = args[2] if len(args) > 2 and os.path.exists(args[2]) else DEFAULT_TPL

print("[FC-Proj] STEP:", step_path)
shape = Part.Shape()
shape.read(step_path)
bb = shape.BoundBox
L, W, H = bb.XLength, bb.YLength, bb.ZLength
print("[FC-Proj] BBOX mm: %.2f x %.2f x %.2f (zmin=%.2f)" % (L, W, H, bb.ZMin))

doc = FreeCAD.newDocument("hd_drawing")
body = doc.addObject("Part::Feature", "HDBody")
body.Shape = shape

page = doc.addObject("TechDraw::DrawPage", "Page")
tpl = doc.addObject("TechDraw::DrawSVGTemplate", "Template")
tpl.Template = tpl_path
page.Template = tpl

# A3 (420x297) 下的四视图排布（与工程文件 L1214-L1220 一致；按实际包络略微自适应）
views = [
    ("FRONT", (0, -1, 0), 110.0, 190.0, 1.0),
    ("TOP", (0, 0, 1), 110.0, 85.0, 1.0),
    ("LEFT", (-1, 0, 0), 265.0, 190.0, 1.0),
    ("ISO", (1, -1, 1), 300.0, 120.0, 0.6),
]
made = []
for name, direction, x, y, scale in views:
    v = doc.addObject("TechDraw::DrawViewPart", name + "View")
    v.Source = [body]
    v.Direction = FreeCAD.Vector(*direction)
    v.Scale = scale
    v.Label = name
    for prop, val in (("HardHidden", True), ("SmoothHidden", True), ("ShowAllEdges", False)):
        if hasattr(v, prop):
            try:
                setattr(v, prop, val)
            except Exception as e:
                print("[FC-Proj][warn] set %s.%s failed: %r" % (name, prop, e))
    page.addView(v)          # 注意：必须先 addView 再设置 X/Y，否则位置会被重置到图幅中心
    v.X = x
    v.Y = y
    made.append(v)

doc.recompute()
# 二次校正视图位置（TechDraw 首次 recompute 可能重排）
for v, (name, direction, x, y, _sc) in zip(made, views):
    v.X = x
    v.Y = y
doc.recompute()
print("[FC-Proj] views:", len(made))
actual = [{"name": v.Label, "x": round(float(v.X), 2), "y": round(float(v.Y), 2),
           "w": round(float(v.getSize()[0]) if hasattr(v, "getSize") else 0.0, 2)} for v in made]
for a in actual:
    print("[FC-Proj] view", a["name"], "@", a["x"], a["y"])

os.makedirs(os.path.dirname(out_dxf), exist_ok=True)
TechDraw.writeDXFPage(page, out_dxf)
print("[FC-Proj] DXF_BYTES", os.path.getsize(out_dxf) if os.path.exists(out_dxf) else 0)

# 视图几何信息（供后续标题栏/尺寸标注使用）
import json
meta = {
    "bbox_mm": {"x": round(L, 2), "y": round(W, 2), "z": round(H, 2)},
    "z_min": round(bb.ZMin, 3),
    "views": actual,
    "dxf": out_dxf,
}
with open(out_dxf + ".meta.json", "w", encoding="utf-8") as f:
    json.dump(meta, f, ensure_ascii=False, indent=2)
print("[FC-Proj] META", json.dumps(meta["bbox_mm"], ensure_ascii=False))
print("FC_PROJECT_DONE")
