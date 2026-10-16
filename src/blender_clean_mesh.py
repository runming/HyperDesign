# -*- coding: utf-8 -*-
"""
HyperDesign Phase 3 - Blender 无头拓扑清洗 + 物理尺寸对齐
按《工程文件》Phase 3 Step 2 (docs/工程文件_extracted.txt L436-L521) 落地

调用: blender.exe --background --python blender_clean_mesh.py -- <manifest.json 绝对路径>
产出: 03_mesh/white_model_clean.glb (Phase 4 用) + 03_mesh/white_model_clean.stl (Phase 5 用)
并回填 manifest.json -> mesh_metrics
"""
import sys
import json

import bpy
from mathutils import Vector

argv = sys.argv
manifest_path = argv[argv.index("--") + 1]
with open(manifest_path, "r", encoding="utf-8") as f:
    manifest = json.load(f)
proj_dir = manifest_path.replace("manifest.json", "").replace("\\", "/")
raw_glb = proj_dir + "03_mesh/raw_trellis.glb"
clean_glb = proj_dir + "03_mesh/white_model_clean.glb"
clean_stl = proj_dir + "03_mesh/white_model_clean.stl"

print(f"[Blender Clean] 载入粗模: {raw_glb}")

# 1. 清空默认场景并导入 TRELLIS 粗模
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=raw_glb)
mesh_objs = [obj for obj in bpy.context.scene.objects if obj.type == 'MESH']
if not mesh_objs:
    raise RuntimeError("未在 GLB 中检测到有效网格！")

# 合并所有网格为单一实体
bpy.ops.object.select_all(action='DESELECT')
bpy.context.view_layer.objects.active = mesh_objs[0]
for obj in mesh_objs:
    obj.select_set(True)
if len(mesh_objs) > 1:
    bpy.ops.object.join()
obj = bpy.context.active_object
obj.name = "HyperDesign_WhiteModel"
print(f"[Blender Clean] 合并后网格: faces={len(obj.data.polygons)} verts={len(obj.data.vertices)}")

# 2. 拓扑清理：合并重叠顶点、删除游离碎片、统一法线朝外
bpy.ops.object.mode_set(mode='EDIT')
bpy.ops.mesh.select_all(action='SELECT')
bpy.ops.mesh.remove_doubles(threshold=0.0005)
bpy.ops.mesh.delete_loose()
bpy.ops.mesh.normals_make_consistent(inside=False)
bpy.ops.object.mode_set(mode='OBJECT')

# 3. 塌陷减面 (Decimate)：保留硬边特征，面数控制在 3 万面以内
faces_before = len(obj.data.polygons)
decimate = obj.modifiers.new(name="CleanDecimate", type='DECIMATE')
decimate.ratio = 0.4
bpy.ops.object.modifier_apply(modifier="CleanDecimate")
print(f"[Blender Clean] 减面: {faces_before} -> {len(obj.data.polygons)}")

# 4. 按 manifest 目标最大跨度 (X=120mm) 等比例缩放真实物理尺寸，保留 TRELLIS 推演的美学比例
bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
target_x = manifest.get("target_bbox_mm", {}).get("x", 120.0)
current_dims = obj.dimensions
scale_factor = target_x / max(current_dims.x, 1e-5)
obj.scale = (scale_factor, scale_factor, scale_factor)
bpy.ops.object.transform_apply(scale=True)
print(f"[Blender Clean] 缩放系数 {scale_factor:.4f} (原始 dims={tuple(round(v,3) for v in current_dims)})")

# 5. 坐标基准归零：XY 居中，底部贴紧 Z=0 工业基准面
bbox_corners = [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
min_z = min(c.z for c in bbox_corners)
center_x = sum(c.x for c in bbox_corners) / 8.0
center_y = sum(c.y for c in bbox_corners) / 8.0
obj.location.x -= center_x
obj.location.y -= center_y
obj.location.z -= min_z
bpy.ops.object.transform_apply(location=True)

# 6. 赋予纯净工业灰哑光白模材质
mat = bpy.data.materials.new(name="Industrial_Clay_Matte")
mat.use_nodes = True
bsdf = mat.node_tree.nodes.get("Principled BSDF")
if bsdf:
    bsdf.inputs["Base Color"].default_value = (0.72, 0.74, 0.76, 1.0)
    bsdf.inputs["Roughness"].default_value = 0.65
    bsdf.inputs["Metallic"].default_value = 0.15
obj.data.materials.clear()
obj.data.materials.append(mat)

# 7. 导出干净的 GLB (给 Phase 4 Three.js) 与 STL (给 Phase 5 FreeCAD/CadQuery)
bpy.ops.object.select_all(action='DESELECT')
obj.select_set(True)
bpy.context.view_layer.objects.active = obj
bpy.ops.export_scene.gltf(filepath=clean_glb, export_format='GLB', use_selection=True)
try:
    bpy.ops.wm.stl_export(filepath=clean_stl, export_selected_objects=True)
except Exception as e:
    print(f"[Blender Clean][warn] wm.stl_export 失败({e!r})，改用 exporter 后备")
    bpy.ops.export_mesh.stl(filepath=clean_stl, use_selection=True)

# 8. 真实物理包围盒与面数写回 manifest.json
final_dims = obj.dimensions
manifest["mesh_metrics"] = {
    "raw_file": "03_mesh/raw_trellis.glb",
    "clean_glb": "03_mesh/white_model_clean.glb",
    "clean_stl": "03_mesh/white_model_clean.stl",
    "actual_bbox_mm": {
        "x": round(final_dims.x, 2),
        "y": round(final_dims.y, 2),
        "z": round(final_dims.z, 2),
    },
    "proportion_ratio": [
        round(final_dims.x / max(final_dims.z, 1e-5), 2),
        round(final_dims.y / max(final_dims.z, 1e-5), 2),
        1.0,
    ],
    "face_count": len(obj.data.polygons),
    "vertex_count": len(obj.data.vertices),
    "unit": "mm",
    "z_base": 0.0,
}
with open(manifest_path, "w", encoding="utf-8") as f:
    json.dump(manifest, f, ensure_ascii=False, indent=2)
print(f"[Blender Clean] 精修完成！真实包络尺寸(mm): {manifest['mesh_metrics']['actual_bbox_mm']}")
