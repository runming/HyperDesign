import FreeCAD
import Part

# ============================================================
# GLOBAL PARAMETERS (mm)
# ============================================================
LENGTH_X       = 120.0
WIDTH_Y        = 80.0
HEIGHT_Z       = 45.0
WALL_THICKNESS = 2.4
FILLET_R       = 3.0
CHAMFER_SIZE   = 1.5
DRAFT_ANGLE    = 1.8          # deg (mold reference)

# LED light-guide hole
LED_HOLE_D     = 8.0
LED_HOLE_X     = 0.25 * LENGTH_X   # 30 mm, +X direction
LED_HOLE_Y     = 0.0              # Y centre

# M4 socket-head screw posts
POST_OD        = 8.0
POST_R         = POST_OD / 2.0    # 4.0
PILOT_HOLE_D   = 3.4
PILOT_HOLE_R   = PILOT_HOLE_D / 2.0  # 1.7
POST_OFFSET    = 8.0              # centre-to-outer-wall
PILOT_DEPTH    = 10.0            # drilled from top

# Derived post-centre coordinates
POST_CX = LENGTH_X / 2.0 - POST_OFFSET   # 52.0
POST_CY = WIDTH_Y  / 2.0 - POST_OFFSET   # 32.0

# Output
STEP_OUTPUT_PATH = "D:/hyperdesign/workspace/_benchmarks/qwen38-uncensored-128k_latest_bench_01_injection_box/05_cad/parametric_model.step"

# ============================================================
# MODELING  (order: base → fillet → chamfer → shell → posts → cuts)
# ============================================================

# 1) Base solid – XY centred, Z 0 → HEIGHT_Z
base = Part.makeBox(LENGTH_X, WIDTH_Y, HEIGHT_Z,
                    FreeCAD.Vector(-LENGTH_X / 2.0, -WIDTH_Y / 2.0, 0.0))

# 2) Vertical-edge fillet  R = 3.0
vert_edges = [e for e in base.Edges
              if abs(e.Vertexes[0].Point.z - e.Vertexes[1].Point.z) > 1e-6]
base = base.makeFillet(FILLET_R, vert_edges)

# 3) Top-face chamfer  1.5 mm
top_edges = [e for e in base.Edges
             if abs(e.Vertexes[0].Point.z - HEIGHT_Z) < 1e-6
             and abs(e.Vertexes[1].Point.z - HEIGHT_Z) < 1e-6]
base = base.makeChamfer(CHAMFER_SIZE, top_edges)

# 4) Shell – remove bottom face, wall = 2.4 mm
bottom_faces = [f for f in base.Faces
                if abs(f.normalAt(0, 0).z + 1.0) < 1e-6]
shell = base.makeThickness(bottom_faces, -WALL_THICKNESS, 1e-3)

# 5) Fuse four M4 screw posts (full height)
post_xy = [
    ( POST_CX,  POST_CY),
    (-POST_CX,  POST_CY),
    ( POST_CX, -POST_CY),
    (-POST_CX, -POST_CY),
]
for (px, py) in post_xy:
    post = Part.makeCylinder(POST_R, HEIGHT_Z,
                             FreeCAD.Vector(px, py, 0.0))
    shell = shell.fuse(post)

# 6) Cut pilot holes (Ø3.4 × 10 mm from top of each post)
for (px, py) in post_xy:
    pilot = Part.makeCylinder(PILOT_HOLE_R, PILOT_DEPTH,
                              FreeCAD.Vector(px, py, HEIGHT_Z - PILOT_DEPTH))
    shell = shell.cut(pilot)

# 7) Cut LED light-guide hole (Ø8 through top wall)
led_cyl = Part.makeCylinder(LED_HOLE_D / 2.0,
                            WALL_THICKNESS + 2.0,
                            FreeCAD.Vector(LED_HOLE_X, LED_HOLE_Y,
                                           HEIGHT_Z - WALL_THICKNESS - 1.0))
shell = shell.cut(led_cyl)

# ============================================================
# EXPORT
# ============================================================
result_solid = shell
result_solid.exportStep(STEP_OUTPUT_PATH)