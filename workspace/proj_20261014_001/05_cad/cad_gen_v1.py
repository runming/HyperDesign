import FreeCAD
import Part

# ============================================================
#  GLOBAL PARAMETER TABLE  (edit here for secondary revision)
# ============================================================
LENGTH_X        = 120.0          # total length  (mm)
WIDTH_Y         = 80.0           # total width   (mm)
HEIGHT_Z        = 45.0           # total height  (mm)
WALL_THICKNESS  = 2.4            # uniform wall  (mm)
DRAFT_ANGLE_DEG = 1.8            # min draft     (deg) – manufacturing note
FILLET_R        = 3.0            # outer vertical-edge fillet (mm), ≤ 3.0
CHAMFER_TOP     = 1.5            # top-edge chamfer (mm)

# LED light-guide window
LED_HOLE_D      = 8.0            # diameter (mm)
LED_HOLE_X      = LENGTH_X * 0.25   # 30 mm from centre, +X
LED_HOLE_Y      = 0.0            # Y-centre

# M4 socket-head screw posts (×4 corners)
SCREW_POST_OD   = 8.0            # outer diameter (mm)
SCREW_POST_R    = SCREW_POST_OD / 2.0   # 4.0
SCREW_PILOT_D   = 3.4            # pilot-hole diameter (mm)
SCREW_PILOT_R   = SCREW_PILOT_D / 2.0   # 1.7
SCREW_FROM_WALL = 8.0            # post centre → outer wall (mm)

STEP_OUTPUT_PATH = "D:/hyperdesign/workspace/proj_20261014_001/05_cad/parametric_model.step"

# ============================================================
#  1. BASE SOLID  (XY-centred, Z=0 bottom)
# ============================================================
base = Part.makeBox(
    LENGTH_X, WIDTH_Y, HEIGHT_Z,
    FreeCAD.Vector(-LENGTH_X / 2.0, -WIDTH_Y / 2.0, 0.0)
)

# ============================================================
#  2. FILLET – vertical edges only (both vertices Z-differ)
# ============================================================
vert_edges = [
    e for e in base.Edges
    if abs(e.Vertexes[0].Point.z - e.Vertexes[1].Point.z) > 1e-6
]
base = base.makeFillet(FILLET_R, vert_edges)

# ============================================================
#  3. CHAMFER – top-face perimeter edges only
# ============================================================
top_edges = [
    e for e in base.Edges
    if abs(e.Vertexes[0].Point.z - HEIGHT_Z) < 1e-6
    and abs(e.Vertexes[1].Point.z - HEIGHT_Z) < 1e-6
]
base = base.makeChamfer(CHAMFER_TOP, top_edges)

# ============================================================
#  4. SHELL – remove bottom face, uniform wall
# ============================================================
bottom_faces = [
    f for f in base.Faces
    if abs(f.normalAt(0, 0).z + 1.0) < 1e-6
]
shell = base.makeThickness(bottom_faces, -WALL_THICKNESS, 1e-3)

# ============================================================
#  5. SCREW POSTS  (fuse AFTER shell to avoid self-intersection)
# ============================================================
sx = LENGTH_X / 2.0 - SCREW_FROM_WALL   # 52.0
sy = WIDTH_Y / 2.0 - SCREW_FROM_WALL    # 32.0
post_h = HEIGHT_Z - WALL_THICKNESS      # 42.6  (stop at inner top)

screw_positions = [(sx, sy), (sx, -sy), (-sx, sy), (-sx, -sy)]

for (px, py) in screw_positions:
    post = Part.makeCylinder(
        SCREW_POST_R, post_h,
        FreeCAD.Vector(px, py, 0.0)
    )
    shell = shell.fuse(post)

# ============================================================
#  6. PILOT HOLES  (cut through each post)
# ============================================================
for (px, py) in screw_positions:
    pilot = Part.makeCylinder(
        SCREW_PILOT_R, post_h + 2.0,
        FreeCAD.Vector(px, py, -1.0)
    )
    shell = shell.cut(pilot)

# ============================================================
#  7. LED LIGHT-GUIDE HOLE  (through top wall)
# ============================================================
led_cyl = Part.makeCylinder(
    LED_HOLE_D / 2.0,
    WALL_THICKNESS + 2.0,
    FreeCAD.Vector(LED_HOLE_X, LED_HOLE_Y, HEIGHT_Z - WALL_THICKNESS - 1.0)
)
shell = shell.cut(led_cyl)

# ============================================================
#  8. FINALISE & EXPORT
# ============================================================
result_solid = shell
result_solid.exportStep(STEP_OUTPUT_PATH)