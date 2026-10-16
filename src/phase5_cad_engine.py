# -*- coding: utf-8 -*-
"""
HyperDesign Phase 5 - 带自验证与自愈闭环的 Text-to-CAD 生成器 (FreeCAD/OpenCascade 内核)
按《工程文件》Phase 5 第三节 (docs/工程文件_extracted.txt L911-L1061) 落地

落地偏差（issues.md #6）：
  本机 OCP(CadQuery) 原生扩展无法加载（TKOpenGL/TKIVtk/TKSTEP DllMain 失败，多版本/多解释器均复现），
  故改用工程文件同样指定的 FreeCAD 1.1.4 自带 OpenCascade 内核（freecadcmd.exe 无头执行），
  CadQuery 版实现保留于 phase5_cad_engine_cadquery.py。

闭环: LLM 生成 FreeCAD Part 脚本 -> freecadcmd 无头执行 -> 校验(零报错/STEP非空/BRep合法/包络±1.5mm)
      -> 失败把诊断回灌自愈(最多5轮) -> 成功把 失败代码 vs 成功代码 写入 Phase 7 DPO
运行: E:\\hyperdesign\\venvs\\hd_brain\\Scripts\\python.exe D:\\hyperdesign\\src\\phase5_cad_engine.py
"""
import json
import subprocess
import sys
import tempfile
import time
import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from utils_mesh_slicer import extract_white_model_anchors  # noqa: E402
from hd_llm import chat as llm_chat, unload as llm_unload  # noqa: E402

try:  # Windows 控制台可能是 GBK，统一把 stdout/stderr 切到 UTF-8 容错，避免中文/³ 等字符抛 UnicodeEncodeError
    import sys as _sys
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    _sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

LLM_MODEL = "qwen38-uncensored-128k:latest"       # 偏差: docx 为 qwen3.5:9b
FREECAD_CMD = r"C:\Users\omegahyper\AppData\Local\Programs\FreeCAD 1.1\bin\freecadcmd.exe"
DATASET_DIR = Path(r"D:\hyperdesign\models\checkpoints\dpo_dataset")
DATASET_DIR.mkdir(parents=True, exist_ok=True)
PROGRESS_LOG = Path(r"D:\hyperdesign\progress.log")

SYSTEM_PROMPT = """你是 HyperDesign 首席参数化 CAD 工程师，精通 FreeCAD 的 Python Part (OpenCascade) 脚本编程。
你的任务是根据【目标包络尺寸】、【白模多层截面比例】、【制造工艺约束】和【设计师批注】，编写可直接运行的 FreeCAD Part 脚本。
必须遵守的工程与编码铁律：
1. 脚本顶部必须定义清晰的全局变量参数表（如 LENGTH_X, WIDTH_Y, HEIGHT_Z, WALL_THICKNESS, DRAFT_ANGLE, FILLET_R 等），方便人工二次修改。
2. 只允许 `import FreeCAD` 和 `import Part`（严禁 Gui、严禁 TechDraw、严禁网络、严禁写文件，导出由最后一行完成）。
3. 建模坐标系：XY 平面居中，底部基准面位于 Z=0（例如 Part.makeBox(L, W, H, FreeCAD.Vector(-L/2, -W/2, 0))）。
4. 严禁危险的大半径圆角导致拓扑崩溃：外圆角 R <= 3.0mm；makeFillet(radius, edge_list) 只能传“竖向棱边”（两端点 Z 相同的边）；
   抽壳用 shape.makeThickness(face_list, -WALL_THICKNESS, 1e-3)，face_list 必须是待移除的面（底面）；
   建议顺序：基础体 -> 竖向棱边圆角 -> 顶面倒角(makeChamfer 只传顶面边) -> 底面抽壳 -> 内部螺钉柱 -> 顶面开孔。
5. 布尔运算用 shape.cut(...) / shape.fuse(...)；必须先做抽壳再做内部螺钉柱与开孔，避免拓扑自交。
6. 脚本末尾必须把最终实体赋值给变量 `result_solid`（类型为 Part.Shape），
   并调用 `result_solid.exportStep(STEP_OUTPUT_PATH)` 导出 STEP 文件。
7. 只输出纯 Python 代码（包裹在 ```python ... ``` 中），不要解释。"""


def log(msg: str) -> None:
    line = f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    try:
        print(line, flush=True)
    except UnicodeEncodeError:
        print(line.encode("utf-8", "replace").decode("utf-8", "replace"), flush=True)
    with open(PROGRESS_LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


class Phase5ParametricCAD:
    def __init__(self, project_dir: Path):
        self.project_dir = project_dir
        self.manifest_path = project_dir / "manifest.json"
        self.cad_dir = project_dir / "05_cad"
        self.cad_dir.mkdir(parents=True, exist_ok=True)

    # ---------------- 主闭环 ----------------
    def generate_and_verify(self, max_retries: int = 5, allow_fallback: bool = True):
        with open(self.manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)

        stl_rel = manifest.get("mesh_metrics", {}).get("clean_stl", "03_mesh/white_model_clean.stl")
        stl_path = self.project_dir / stl_rel
        try:
            mesh_anchors = extract_white_model_anchors(str(stl_path))
            log("[Phase5] 白模截面锚点: %s" % json.dumps(mesh_anchors["z_sections"], ensure_ascii=False))
        except Exception as e:
            mesh_anchors = {"overall_bbox_mm": manifest.get("target_bbox_mm", {}), "z_sections": [], "error": repr(e)}
            log("[Phase5][warn] 白模切片失败(%r)，仅按目标包络建模" % (e,))

        target_bbox = manifest["target_bbox_mm"]
        mfg = manifest.get("mfg_constraints", manifest.get("manufacturing_constraints", {}))
        notes = manifest.get("human_feedback", {}).get("notes") or \
            "常规工业壳体，四角带M4安装柱，抽壳壁厚均匀，顶部居中预留导光柱窗口"
        step_out_path = (self.cad_dir / "parametric_model.step").as_posix()

        base_task_prompt = f"""请编写 FreeCAD Part 参数化建模脚本，并将 STEP 导出至路径："{step_out_path}"
【1. 强制目标物理包络 (mm)】(生成实体外包围盒长宽高误差不得超过 ±1.5mm)：
- 总长 (X): {target_bbox['x']} mm
- 总宽 (Y): {target_bbox['y']} mm
- 总高 (Z): {target_bbox['z']} mm
【2. Phase 3 白模实测截面比例参考】：{json.dumps(mesh_anchors['z_sections'], ensure_ascii=False)}
【3. 制造工艺与 DFM 约束】：
- 加工工艺: {mfg.get('process', '注塑/CNC')}
- 标准壁厚: {mfg.get('min_wall_thickness_mm', 2.4)} mm
- 加强筋厚度上限: {mfg.get('rib_max_thickness_mm', 1.44)} mm
- 拔模斜度: >= {mfg.get('min_draft_angle_deg', 1.8)} 度
- 顶部状态指示灯导光孔径: 8.0 mm（位于顶面 X 正方向 25% 长度处，Y 居中）
- 四角 M4 内六角螺钉柱: 外径 8.0mm / 底孔 3.4mm / 柱中心距外壁 8.0mm
- 设计师结构指令: {notes}
【4. 参考实现骨架】
base = Part.makeBox(LENGTH_X, WIDTH_Y, HEIGHT_Z, FreeCAD.Vector(-LENGTH_X/2, -WIDTH_Y/2, 0))
vert = [e for e in base.Edges if abs(e.Vertexes[0].Point.z - e.Vertexes[1].Point.z) > 1e-6]
base = base.makeFillet(3.0, vert)
top = [e for e in base.Edges if abs(e.Vertexes[0].Point.z - HEIGHT_Z) < 1e-6 and abs(e.Vertexes[1].Point.z - HEIGHT_Z) < 1e-6]
base = base.makeChamfer(1.5, top)
bottom = [f for f in base.Faces if abs(f.normalAt(0,0).z + 1.0) < 1e-6]
shell = base.makeThickness(bottom, -WALL_THICKNESS, 1e-3)
# 螺钉柱：Part.makeCylinder(r, h, Vector(x,y,z)) 与 shell.fuse(...) 融合；底孔用 makeCylinder 做 cut
result_solid = ...
result_solid.exportStep(STEP_OUTPUT_PATH)
"""
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": base_task_prompt},
        ]
        failed_attempts = []
        for attempt in range(1, max_retries + 1):
            log(f"[Phase5] 第 {attempt}/{max_retries} 轮生成 FreeCAD 参数化脚本...")
            t0 = time.time()
            content = llm_chat(model=LLM_MODEL, messages=messages, keep_alive="2m",
                               options={"temperature": 0.2})
            log(f"[Phase5] 代码生成耗时 {time.time()-t0:.1f}s")
            code_str = self._extract_python_code(content)
            script_path = self.cad_dir / f"cad_gen_v{attempt}.py"
            script_path.write_text(code_str, encoding="utf-8")
            log(f"[Phase5] 第 {attempt} 轮脚本已落盘: {script_path.name} ({len(code_str)} 字符)")

            is_valid, report = self._run_occ_verification(script_path, target_bbox)
            if is_valid:
                log(f"[Phase5 验证通过!] 实体体积: {report['volume_mm3']} mm³ | 实测包络: {report['bbox_mm']}")
                llm_unload(LLM_MODEL)
                (self.cad_dir / "parametric_model.py").write_text(code_str, encoding="utf-8")
                if failed_attempts:
                    self._record_cad_dpo(base_task_prompt, code_str, failed_attempts)
                self._update_manifest(report, self.cad_dir / "parametric_model.py")
                return True, report
            log(f"[Phase5 校验未通过] 原因: {report['error_msg'][:500]}")
            failed_attempts.append(code_str)
            messages.append({"role": "assistant", "content": f"```python\n{code_str}\n```"})
            messages.append({"role": "user", "content": (
                f"上一段代码执行或几何验证失败！具体诊断信息如下：\n{report['error_msg']}\n"
                "请修复上述拓扑报错或尺寸偏差（若因 makeFillet/makeThickness 失败，请减小半径、"
                "只对竖向棱边倒角、或调整特征顺序为先倒角后抽壳），重新输出完整 FreeCAD Part 代码。")})

        llm_unload(LLM_MODEL)
        if not allow_fallback:
            log(f"[Phase5] {max_retries} 轮自愈未通过，且已禁用兜底（基准回归模式）-> FAIL")
            return False, {"error_msg": f"{max_retries} 轮自愈未通过", "bbox_mm": {}, "volume_mm3": 0.0,
                           "is_valid_brep": False}
        log(f"[Phase5] {max_retries} 轮自愈未通过，启用工程样板兜底代码 (reference fallback)")
        return self._reference_fallback(target_bbox, mfg)

    # ---------------- OCC 硬件级校验（freecadcmd 无头执行） ----------------
    def _run_occ_verification(self, script_path: Path, target_bbox: dict):
        verifier_suffix = """
# === HyperDesign Automated OCC Geometry Verifier (FreeCAD) ===
import json as _json
_s = result_solid
_bb = _s.BoundBox
_report = {
    "is_valid_brep": bool(_s.isValid()),
    "volume_mm3": round(float(_s.Volume), 2),
    "bbox_mm": {
        "x": round(float(_bb.XLength), 2),
        "y": round(float(_bb.YLength), 2),
        "z": round(float(_bb.ZLength), 2)
    },
    "z_min": round(float(_bb.ZMin), 3)
}
print("__VERIFY_JSON__" + _json.dumps(_report))
"""
        full_test_code = script_path.read_text(encoding="utf-8") + "\n" + verifier_suffix
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as tmp:
            tmp.write(full_test_code)
            tmp_path = tmp.name
        step_file = self.cad_dir / "parametric_model.step"
        if step_file.exists():
            step_file.unlink()
        try:
            proc = subprocess.run([FREECAD_CMD, tmp_path], capture_output=True, text=True,
                                  encoding="utf-8", errors="replace", timeout=600, cwd=str(self.cad_dir))
        except subprocess.TimeoutExpired:
            Path(tmp_path).unlink(missing_ok=True)
            return False, {"error_msg": "FreeCAD 脚本执行超时(>600s)，可能存在死循环或超复杂布尔运算。"}
        Path(tmp_path).unlink(missing_ok=True)

        if proc.returncode != 0:
            return False, {"error_msg": f"FreeCAD/OCC 内核报错(rc={proc.returncode}):\n"
                                        f"{proc.stderr[-1500:]}\n{proc.stdout[-800:]}"}
        for line in proc.stdout.splitlines():
            if line.startswith("__VERIFY_JSON__"):
                report = json.loads(line.replace("__VERIFY_JSON__", ""))
                if not report["is_valid_brep"] or report["volume_mm3"] <= 1.0:
                    return False, {"error_msg": f"BRep 实体拓扑非法或体积为零: {report}"}
                bx, by, bz = report["bbox_mm"]["x"], report["bbox_mm"]["y"], report["bbox_mm"]["z"]
                tx, ty, tz = target_bbox["x"], target_bbox["y"], target_bbox["z"]
                if abs(bx - tx) > 1.5 or abs(by - ty) > 1.5 or abs(bz - tz) > 1.5:
                    return False, {"error_msg": f"生成的 CAD 实体外尺寸 ({bx}x{by}x{bz} mm) 与目标包络 "
                                                f"({tx}x{ty}x{tz} mm) 偏差超过 1.5mm！"}
                if not step_file.exists() or step_file.stat().st_size < 1000:
                    return False, {"error_msg": "STEP 文件未产出或内容为空，请检查 exportStep(STEP_OUTPUT_PATH)。"}
                report["step_bytes"] = step_file.stat().st_size
                return True, report
        tail = "\n".join(proc.stdout.splitlines()[-12:])
        return False, {"error_msg": "脚本未能输出 __VERIFY_JSON__，请确认最终实体变量名严格为 `result_solid`。\n"
                                    f"最后输出:\n{tail}"}

    # ---------------- 兜底样板（工程文件 L1064-L1109 官方样板的 FreeCAD 等价实现） ----------------
    def _reference_fallback(self, target_bbox: dict, mfg: dict):
        step_out = (self.cad_dir / "parametric_model.step").as_posix()
        code = f'''# -*- coding: utf-8 -*-
# HyperDesign Phase 5 兜底样板 (FreeCAD Part) —— LLM 自愈 5 轮未通过时启用
import FreeCAD
import Part

LENGTH_X = {float(target_bbox['x'])}
WIDTH_Y = {float(target_bbox['y'])}
HEIGHT_Z = {float(target_bbox['z'])}
WALL_THICKNESS = {float(mfg.get('min_wall_thickness_mm', 2.4))}
OUTER_FILLET_R = 3.0
TOP_CHAMFER = 1.5
BOSS_OD = 8.0
BOSS_ID = 3.4
BOSS_INSET = 8.0
WINDOW_DIA = 8.0
STEP_OUTPUT_PATH = r"{step_out}"

# Step A: 基础包络体（底部坐平 Z=0）+ 竖向棱边圆角 + 顶面倒角
base = Part.makeBox(LENGTH_X, WIDTH_Y, HEIGHT_Z, FreeCAD.Vector(-LENGTH_X / 2.0, -WIDTH_Y / 2.0, 0.0))
vertical = [e for e in base.Edges if abs(e.Vertexes[0].Point.z - e.Vertexes[1].Point.z) > 1e-6]
base = base.makeFillet(OUTER_FILLET_R, vertical)
top_edges = [e for e in base.Edges
             if abs(e.Vertexes[0].Point.z - HEIGHT_Z) < 1e-6 and abs(e.Vertexes[1].Point.z - HEIGHT_Z) < 1e-6]
base = base.makeChamfer(TOP_CHAMFER, top_edges)

# Step B: 底面抽壳形成均匀壁厚腔体
bottom_faces = [f for f in base.Faces if abs(f.normalAt(0, 0).z + 1.0) < 1e-6]
shell = base.makeThickness(bottom_faces, -WALL_THICKNESS, 1e-3)

# Step C: 内部四角 M4 螺钉柱
boss_x = LENGTH_X / 2.0 - BOSS_INSET
boss_y = WIDTH_Y / 2.0 - BOSS_INSET
for sx in (-1.0, 1.0):
    for sy in (-1.0, 1.0):
        cx, cy = sx * boss_x, sy * boss_y
        pillar = Part.makeCylinder(BOSS_OD / 2.0, HEIGHT_Z - WALL_THICKNESS,
                                   FreeCAD.Vector(cx, cy, WALL_THICKNESS))
        shell = shell.fuse(pillar)
        hole = Part.makeCylinder(BOSS_ID / 2.0, HEIGHT_Z,
                                 FreeCAD.Vector(cx, cy, -0.5))
        shell = shell.cut(hole)

# Step D: 顶面导光柱安装通孔（X 正向 25% 长度处，Y 居中）
window = Part.makeCylinder(WINDOW_DIA / 2.0, HEIGHT_Z * 2.0,
                           FreeCAD.Vector(LENGTH_X * 0.25, 0.0, -HEIGHT_Z * 0.5))
result_solid = shell.cut(window)

result_solid.exportStep(STEP_OUTPUT_PATH)
'''
        script_path = self.cad_dir / "cad_gen_fallback.py"
        script_path.write_text(code, encoding="utf-8")
        is_valid, report = self._run_occ_verification(script_path, target_bbox)
        if is_valid:
            log(f"[Phase5 兜底样板验证通过] 体积 {report['volume_mm3']} mm³ | 包络 {report['bbox_mm']}")
            (self.cad_dir / "parametric_model.py").write_text(code, encoding="utf-8")
            self._update_manifest(report, self.cad_dir / "parametric_model.py")
            rejected = [p.read_text(encoding="utf-8") for p in sorted(self.cad_dir.glob("cad_gen_v*.py"))]
            if rejected:
                self._record_cad_dpo("兜底: LLM 5 轮自愈失败", code, rejected)
            return True, report
        log(f"[Phase5][fatal] 兜底样板也失败: {report['error_msg'][:500]}")
        return False, report

    @staticmethod
    def _extract_python_code(text: str) -> str:
        if "```python" in text:
            return text.split("```python")[1].split("```")[0].strip()
        elif "```" in text:
            return text.split("```")[1].split("```")[0].strip()
        return text.strip()

    def _record_cad_dpo(self, prompt: str, chosen_code: str, rejected_list):
        dpo_file = DATASET_DIR / "phase5_cad_code_dpo.jsonl"
        n = 0
        with open(dpo_file, "a", encoding="utf-8") as f:
            for rej in rejected_list:
                f.write(json.dumps({"prompt": prompt, "chosen": chosen_code, "rejected": rej},
                                   ensure_ascii=False) + "\n")
                n += 1
        log(f"[DPO 收集器] 已自动捕获 {n} 组 CAD 代码正负偏好样本对 -> {dpo_file}")

    def _update_manifest(self, report: dict, script_path: Path):
        with open(self.manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
        manifest["cad_verification"] = {
            "engine": "FreeCAD 1.1.4 Part (OpenCascade) — CadQuery/OCP 本机不可用",
            "script_file": f"05_cad/{script_path.name}",
            "step_file": "05_cad/parametric_model.step",
            "is_valid_brep": report["is_valid_brep"],
            "volume_mm3": report["volume_mm3"],
            "verified_bbox_mm": report["bbox_mm"],
            "verified_at": datetime.datetime.now().isoformat(timespec="seconds"),
        }
        with open(self.manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)
        log("[Phase5] manifest.json cad_verification 已更新")


if __name__ == "__main__":
    log("=" * 72)
    log("===== PHASE 5 启动：FreeCAD 参数化建模 + 自愈闭环 =====")
    engine = Phase5ParametricCAD(Path(r"D:\hyperdesign\workspace\proj_20261014_001"))
    ok, report = engine.generate_and_verify()
    log(f"[Phase5] ===== PHASE 5 {'完成' if ok else '失败'} =====")
    print(json.dumps({"PHASE5_RESULT": "OK" if ok else "FAIL", "report": report}, ensure_ascii=False))
    sys.exit(0 if ok else 1)
