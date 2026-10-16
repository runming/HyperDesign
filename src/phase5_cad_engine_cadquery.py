# -*- coding: utf-8 -*-
"""
HyperDesign Phase 5 - 带自验证与自愈闭环的 Text-to-CAD 生成器
按《工程文件》Phase 5 第三节 (docs/工程文件_extracted.txt L911-L1061) 落地

闭环: LLM 生成 CadQuery -> 子进程执行 -> OpenCascade 校验(零报错 / STEP非空 / BRep合法 / 包络±1.5mm)
      -> 失败则把报错堆栈回灌给大模型自愈(最多5轮) -> 成功则把失败代码 vs 成功代码写入 Phase 7 DPO

运行: E:\\hyperdesign\\venvs\\hd_cad\\Scripts\\python.exe D:\\hyperdesign\\src\\phase5_cad_engine.py
"""
import json
import os
import subprocess
import sys
import tempfile
import time
import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from utils_mesh_slicer import extract_white_model_anchors  # noqa: E402

sys.path.insert(0, str(Path(__file__).parent))
from hd_llm import chat as llm_chat, unload as llm_unload  # noqa: E402

LLM_MODEL = "qwen38-uncensored-128k:latest"   # 偏差: docx 为 qwen3.5:9b
DATASET_DIR = Path(r"D:\hyperdesign\models\checkpoints\dpo_dataset")
DATASET_DIR.mkdir(parents=True, exist_ok=True)
PROGRESS_LOG = Path(r"D:\hyperdesign\progress.log")
PY_EXE = sys.executable

SYSTEM_PROMPT = """你是 HyperDesign 首席参数化 CAD 工程师，精通 Python CadQuery (OpenCascade 内核)。
你的任务是根据【目标包络尺寸】、【白模多层截面比例】、【制造工艺约束】和【设计师批注】，编写可直接运行的 CadQuery 脚本。
必须遵守的工程与编码铁律：
1. 脚本顶部必须定义清晰的全局变量参数表（如 LENGTH_X, WIDTH_Y, HEIGHT_Z, WALL_THICKNESS, DRAFT_ANGLE, FILLET_R 等），方便人工二次修改。
2. 建模坐标系：XY 平面居中，底部基准面位于 Z=0（即首个基础拉伸体使用 centered=(True, True, False) 或在 Z>=0 空间构建）。
3. 严禁使用危险的大半径 fillet() 导致 BRep_API: command not done 拓扑崩溃；建议外圆角 R <= 3.0mm，内圆角 R <= 1.0mm，且在 shell() 抽壳之前先做外部主倒角。
4. 脚本末尾必须将最终主实体赋值给变量 `result_solid`（类型为 cq.Workplane），并使用 cq.exporters.export(result_solid, STEP_OUTPUT_PATH) 导出 STEP 文件。
5. 只输出纯 Python 代码（包裹在 ```python ... ``` 中），不要解释。
6. 禁止任何网络访问、禁止读取外部文件、禁止 print 调试以外的副作用。"""


def log(msg: str) -> None:
    line = f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(PROGRESS_LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


class Phase5ParametricCAD:
    def __init__(self, project_dir: Path):
        self.project_dir = project_dir
        self.manifest_path = project_dir / "manifest.json"
        self.cad_dir = project_dir / "05_cad"
        self.cad_dir.mkdir(parents=True, exist_ok=True)

    # ---------------- 主闭环 ----------------
    def generate_and_verify(self, max_retries: int = 5):
        with open(self.manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)

        # 1. 提取白模多层截面尺寸锚点
        stl_rel = manifest.get("mesh_metrics", {}).get("clean_stl", "03_mesh/white_model_clean.stl")
        stl_path = self.project_dir / stl_rel
        try:
            mesh_anchors = extract_white_model_anchors(str(stl_path))
            log(f"[Phase5] 白模截面锚点: {json.dumps(mesh_anchors['z_sections'], ensure_ascii=False)}")
        except Exception as e:
            mesh_anchors = {"overall_bbox_mm": manifest.get("target_bbox_mm", {}), "z_sections": {},
                            "error": repr(e)}
            log(f"[Phase5][warn] 白模切片失败({e!r})，仅用目标包络建模")

        target_bbox = manifest["target_bbox_mm"]
        mfg = manifest.get("mfg_constraints", manifest.get("manufacturing_constraints", {}))
        notes = manifest.get("human_feedback", {}).get("notes") or \
            "常规工业壳体，四角带M4安装柱，抽壳壁厚均匀，顶部居中预留导光柱窗口，两侧M6安装耳"
        step_out_path = (self.cad_dir / "parametric_model.step").as_posix()

        base_task_prompt = f"""请编写 CadQuery 参数化建模脚本，并将 STEP 导出至路径："{step_out_path}"
【1. 强制目标物理包络 (mm)】(生成的模型外包围盒长宽高误差不得超过 ±1.5mm)：
- 总长 (X): {target_bbox['x']} mm
- 总宽 (Y): {target_bbox['y']} mm
- 总高 (Z): {target_bbox['z']} mm
【2. Phase 3 白模实测截面比例参考】：{json.dumps(mesh_anchors['z_sections'], ensure_ascii=False, indent=2)}
【3. 制造工艺与 DFM 约束】：
- 加工工艺: {mfg.get('process', '注塑/CNC')}
- 标准壁厚: {mfg.get('min_wall_thickness_mm', 2.4)} mm
- 加强筋厚度上限: {mfg.get('rib_max_thickness_mm', 1.44)} mm
- 拔模斜度: >= {mfg.get('min_draft_angle_deg', 1.8)} 度
- 顶部状态指示灯导光孔径: 8.0 mm (居中偏 X 正向 25% 处)
- 四角 M4 内六角螺钉柱: 外径 8.0mm / 底孔 3.4mm / 距外壁中心距 8.0mm
- 设计师结构指令: {notes}
【4. 建议特征顺序】：基础包络体(centered=(True,True,False), 底部 Z=0) -> 四周 |Z 棱边倒圆角 R<=3.0
-> 顶面 >Z 棱边倒 C 角 -> 底面 <Z 抽壳 -WALL_THICKNESS -> 内顶面 pushPoints 生成四角螺钉柱 -> 顶面导光孔。
"""
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": base_task_prompt},
        ]
        failed_attempts = []
        for attempt in range(1, max_retries + 1):
            log(f"[Phase5] 第 {attempt}/{max_retries} 轮生成参数化 CadQuery 脚本...")
            t0 = time.time()
            try:
                content = llm_chat(model=LLM_MODEL, messages=messages, keep_alive="2m",
                                   options={"temperature": 0.2})
            except Exception as e:
                log(f"[Phase5][error] LLM 调用失败: {e!r}")
                raise
            log(f"[Phase5] 代码生成耗时 {time.time()-t0:.1f}s")
            code_str = self._extract_python_code(content)
            script_path = self.cad_dir / f"cad_gen_v{attempt}.py"
            script_path.write_text(code_str, encoding="utf-8")
            log(f"[Phase5] 第 {attempt} 轮脚本已落盘: {script_path.name} ({len(code_str)} 字符)")

            is_valid, verify_report = self._run_occ_verification(script_path, target_bbox)
            if is_valid:
                log(f"[Phase5 验证通过!] 实体体积: {verify_report['volume_mm3']} mm³ | "
                    f"实测包络: {verify_report['bbox_mm']}")
                llm_unload(LLM_MODEL)
                final_script = self.cad_dir / "parametric_model.py"
                final_script.write_text(code_str, encoding="utf-8")
                if failed_attempts:
                    self._record_cad_dpo(base_task_prompt, chosen_code=code_str, rejected_list=failed_attempts)
                self._update_manifest(verify_report, final_script)
                return True, verify_report
            log(f"[Phase5 校验未通过] 原因: {verify_report['error_msg'][:400]}")
            failed_attempts.append(code_str)
            messages.append({"role": "assistant", "content": f"```python\n{code_str}\n```"})
            messages.append({
                "role": "user",
                "content": (
                    f"上一段代码执行或几何验证失败！具体诊断信息如下：\n{verify_report['error_msg']}\n"
                    "请修复上述拓扑报错或尺寸偏差（若因 fillet/shell 失败，请减小倒角半径或调整特征顺序），"
                    "重新输出完整 Python 代码。"
                ),
            })

        llm_unload(LLM_MODEL)
        log(f"[Phase5] 经过 {max_retries} 轮自愈仍未通过，启用工程样板兜底代码 (reference fallback)")
        return self._reference_fallback(target_bbox, mfg, notes)

    # ---------------- OCC 硬件级校验 ----------------
    def _run_occ_verification(self, script_path: Path, target_bbox: dict):
        verifier_suffix = """
# === HyperDesign Automated OCC Geometry Verifier ===
import json as _json
_solid = result_solid.val()
_bbox = _solid.BoundingBox()
_report = {
    "is_valid_brep": bool(_solid.isValid()),
    "volume_mm3": round(float(_solid.Volume()), 2),
    "bbox_mm": {
        "x": round(float(_bbox.xlen), 2),
        "y": round(float(_bbox.ylen), 2),
        "z": round(float(_bbox.zlen), 2)
    }
}
print("__VERIFY_JSON__" + _json.dumps(_report))
"""
        full_test_code = script_path.read_text(encoding="utf-8") + "\n" + verifier_suffix
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as tmp:
            tmp.write(full_test_code)
            tmp_path = tmp.name
        try:
            env = dict(os.environ)
            proc = subprocess.run([PY_EXE, tmp_path], capture_output=True, text=True,
                                  timeout=300, env=env, cwd=str(self.cad_dir))
        except subprocess.TimeoutExpired:
            Path(tmp_path).unlink(missing_ok=True)
            return False, {"error_msg": "CadQuery 脚本执行超时(>300s)，可能存在死循环或超复杂布尔运算。"}
        Path(tmp_path).unlink(missing_ok=True)

        if proc.returncode != 0:
            return False, {"error_msg": f"Python 运行时/OCC 内核报错:\n{proc.stderr[-1500:]}"}
        for line in proc.stdout.splitlines():
            if line.startswith("__VERIFY_JSON__"):
                report = json.loads(line.replace("__VERIFY_JSON__", ""))
                if not report["is_valid_brep"] or report["volume_mm3"] <= 1.0:
                    return False, {"error_msg": f"BRep 实体拓扑非法或体积为零: {report}"}
                bx, by, bz = report["bbox_mm"]["x"], report["bbox_mm"]["y"], report["bbox_mm"]["z"]
                tx, ty, tz = target_bbox["x"], target_bbox["y"], target_bbox["z"]
                if abs(bx - tx) > 1.5 or abs(by - ty) > 1.5 or abs(bz - tz) > 1.5:
                    return False, {
                        "error_msg": f"生成的 CAD 实体外尺寸 ({bx}x{by}x{bz} mm) 与目标包络 "
                                     f"({tx}x{ty}x{tz} mm) 偏差超过 1.5mm！"
                    }
                step_file = self.cad_dir / "parametric_model.step"
                if not step_file.exists() or step_file.stat().st_size < 1000:
                    return False, {"error_msg": "STEP 文件未产出或内容为空，请检查 STEP_OUTPUT_PATH 与导出调用。"}
                report["step_bytes"] = step_file.stat().st_size
                return True, report
        return False, {"error_msg": "脚本未能输出 __VERIFY_JSON__，请确认最终实体变量名严格为 `result_solid`。"}

    # ---------------- 兜底样板 (来自工程文件 L1064-L1109 的官方样板) ----------------
    def _reference_fallback(self, target_bbox: dict, mfg: dict, notes: str):
        step_out_path = (self.cad_dir / "parametric_model.step").as_posix()
        code = f'''# -*- coding: utf-8 -*-
# HyperDesign Phase 5 兜底样板（LLM 自愈 5 轮未通过时启用，源自工程文件官方样板）
import cadquery as cq

LENGTH_X = {float(target_bbox['x'])}          # 外壳总长 (mm)
WIDTH_Y = {float(target_bbox['y'])}           # 外壳总宽 (mm)
HEIGHT_Z = {float(target_bbox['z'])}          # 外壳总高 (mm)
WALL_THICKNESS = {float(mfg.get('min_wall_thickness_mm', 2.4))}      # 二号车间 PC+ABS 规范壁厚 (mm)
OUTER_FILLET_R = 4.0      # 四周主棱边圆角 (mm)
TOP_CHAMFER = 1.5         # 顶部抗冲击C角 (mm)
BOSS_OD = 8.0             # 四角 M4 螺钉柱外径 (mm)
BOSS_ID = 3.4             # M4 自攻底孔内径 (mm)
BOSS_INSET = 8.0          # 螺钉柱距外壁中心距 (mm)
WINDOW_DIA = 8.0          # 顶部状态指示灯导光孔径 (mm)
STEP_OUTPUT_PATH = r"{step_out_path}"

# Step A: 基础包络体构建（底部坐平 Z=0）
base_body = (
    cq.Workplane("XY")
    .box(LENGTH_X, WIDTH_Y, HEIGHT_Z, centered=(True, True, False))
    .edges("|Z")
    .fillet(OUTER_FILLET_R)
    .edges(">Z")
    .chamfer(TOP_CHAMFER)
)

# Step B: 底部抽壳形成均匀壁厚腔体
hollow_shell = base_body.faces("<Z").shell(-WALL_THICKNESS)

# Step C: 内部四角生成 M4 安装螺钉柱
boss_x = LENGTH_X / 2.0 - BOSS_INSET
boss_y = WIDTH_Y / 2.0 - BOSS_INSET
boss_pts = [(-boss_x, -boss_y), (boss_x, -boss_y), (boss_x, boss_y), (-boss_x, boss_y)]
shell_with_bosses = (
    hollow_shell.faces(">Z").workplane(offset=-WALL_THICKNESS)
    .pushPoints(boss_pts)
    .circle(BOSS_OD / 2.0)
    .extrude(-(HEIGHT_Z - WALL_THICKNESS), combine=True)
    .faces("<Z").workplane()
    .pushPoints(boss_pts)
    .hole(BOSS_ID, depth=HEIGHT_Z - WALL_THICKNESS - 2.0)
)

# Step D: 顶面加工导光柱安装通孔
result_solid = (
    shell_with_bosses.faces(">Z").workplane()
    .center(LENGTH_X * 0.25, 0)
    .hole(WINDOW_DIA)
)

cq.exporters.export(result_solid, STEP_OUTPUT_PATH)
'''
        script_path = self.cad_dir / "cad_gen_fallback.py"
        script_path.write_text(code, encoding="utf-8")
        is_valid, report = self._run_occ_verification(script_path, target_bbox)
        if is_valid:
            log(f"[Phase5 兜底样板验证通过] 体积 {report['volume_mm3']} mm³ | 包络 {report['bbox_mm']}")
            (self.cad_dir / "parametric_model.py").write_text(code, encoding="utf-8")
            self._update_manifest(report, self.cad_dir / "parametric_model.py")
            self._record_cad_dpo("兜底: LLM 5 轮自愈失败", chosen_code=code,
                                 rejected_list=[p.read_text(encoding="utf-8")
                                                for p in sorted(self.cad_dir.glob("cad_gen_v*.py"))])
            return True, report
        log(f"[Phase5][fatal] 兜底样板也失败: {report['error_msg'][:400]}")
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
    log("===== PHASE 5 启动：CadQuery 参数化建模 + 自愈闭环 =====")
    engine = Phase5ParametricCAD(Path(r"D:\hyperdesign\workspace\proj_20261014_001"))
    ok, report = engine.generate_and_verify()
    log(f"[Phase5] ===== PHASE 5 {'完成' if ok else '失败'} =====")
    print(json.dumps({"PHASE5_RESULT": "OK" if ok else "FAIL", "report": report}, ensure_ascii=False))
    sys.exit(0 if ok else 1)
