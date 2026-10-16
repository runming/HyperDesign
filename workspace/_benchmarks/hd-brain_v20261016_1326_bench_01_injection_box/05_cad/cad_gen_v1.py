import FreeCAD
import Part

# 全局变量参数表
LENGTH_X = 120.0
WIDTH_Y = 80.0
HEIGHT_Z = 45.0
WALL_THICKNESS = 2.4
DRAFT_ANGLE = 1.8
FILLET_R = 3.0
TOP_HOLE_DIAMETER = 8.0
M4_CENTRAL_X = LENGTH_X * 0.25
M4_CENTRAL_Y = WIDTH_Y / 2
M4_CENTRE_X = M4_CENTRAL_X + 8.0
M4_CENTRE_Y = M4_CENTRAL_Y
STEP_OUTPUT_PATH = "D:/hyperdesign/workspace/_benchmarks/hd-brain_v20261016_1326_bench_01_injection_box/05_cad/parametric_model.step"

# 基础体
base = Part.makeBox(LENGTH_X, WIDTH_Y, HEIGHT_Z, FreeCAD.Vector(-LENGTH_X/2, -WIDTH_Y/2, 0))

# 竖向棱边圆角
vert = [e for e in base.Edges if abs(e.Vertexes[0].Point.z - e.Vertexes[1].Point.z) > 1e-6]
base = base.makeFillet(FILLET_R, vert)

# 顶面倒角
top = [e for e in base.Edges if abs(e.Vertexes[0].Point.z - HEIGHT_Z) < 1e-6 and abs(e.Vertexes[1].Point.z - HEIGHT_Z) < 1e-6]
base = base.makeChamfer(DRAFT_ANGLE * 1000, top)

# 底面抽壳
bottom = [f for f in base.Faces if abs(f.normalAt(0,0).z + 1.0) < 1e-6]
shell = base.makeThickness(bottom, -WALL_THICKNESS, 1e-3)

# 内部螺钉柱
m4_cylinder = Part.makeCylinder(4.0, 45.0, FreeCAD.Vector(M4_CENTRE_X, M4_CENTRE_Y, 0))
m4_hole = Part.makeCylinder(3.4, 45.0, FreeCAD.Vector(M4_CENTRE_X, M4_CENTRE_Y, 0))
shell = shell.fuse(m4_cylinder.cut(m4_hole))

# 顶面开孔
top_hole = Part.makeCylinder(TOP_HOLE_DIAMETER / 2, 45.0, FreeCAD.Vector(M4_CENTRAL_X, M4_CENTRAL_Y, 45.0))
shell = shell.cut(top_hole)

# 最终实体
result_solid = shell

# 导出 STEP 文件
result_solid.exportStep(STEP_OUTPUT_PATH)