# -*- coding: utf-8 -*-
"""
HyperDesign Phase 6 - 工程图纸导出引擎（1:1 激光切割 DXF + A3 国标工程总图 DXF + 300dpi PDF）
按《工程文件》Phase 6 (docs/工程文件_extracted.txt L1125-L1323) 落地

落地偏差（issues.md #6）：HLR 投影由 FreeCAD 1.1.4 TechDraw 无头完成（OCP/CadQuery 本机不可用），
图层/尺寸/标题栏/PDF 仍按 docx 用 ezdxf + matplotlib 生成。
运行: E:\\hyperdesign\\venvs\\hd_cad\\Scripts\\python.exe D:\\hyperdesign\\src\\phase6_drawing_exporter.py
"""
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import ezdxf
from ezdxf import units
from ezdxf.addons import Importer
from ezdxf.addons.drawing import RenderContext, Frontend
from ezdxf.addons.drawing.matplotlib import MatplotlibBackend
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

try:  # Windows 控制台可能是 GBK，统一把 stdout/stderr 切到 UTF-8 容错，避免中文/³ 等字符抛 UnicodeEncodeError
    import sys as _sys
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    _sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

FREECAD_CMD = r"C:\Users\omegahyper\AppData\Local\Programs\FreeCAD 1.1\bin\freecadcmd.exe"
FC_PROJECT = r"D:\hyperdesign\src\phase6_fc_project.py"
PROGRESS_LOG = Path(r"D:\hyperdesign\progress.log")


def log(msg: str) -> None:
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(PROGRESS_LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


class Phase6DrawingExporter:
    def __init__(self, project_dir: Path):
        self.project_dir = project_dir
        self.manifest_path = project_dir / "manifest.json"
        self.step_path = project_dir / "05_cad" / "parametric_model.step"
        self.out_dir = project_dir / "06_drawings"
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.raw_dxf = self.out_dir / "_fc_raw_views.dxf"

    # ---------- 0. 调用 FreeCAD 做 HLR 投影 ----------
    def project_views(self):
        cmd = [FREECAD_CMD, FC_PROJECT, "--", str(self.step_path), str(self.raw_dxf)]
        log("[Phase6] 调用 FreeCAD 无头 HLR 投影: %s" % self.raw_dxf.name)
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=900)
        for line in proc.stdout.splitlines():
            if line.startswith(("[FC-Proj]", "FC_PROJECT_DONE")):
                log("  " + line)
        if proc.returncode != 0 or not self.raw_dxf.exists():
            log("[Phase6][error] FreeCAD 投影失败 rc=%s\n%s" % (proc.returncode, proc.stderr[-1500:]))
            raise RuntimeError("FreeCAD HLR 投影失败")
        meta_path = Path(str(self.raw_dxf) + ".meta.json")
        meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
        log("[Phase6] 视图投影完成，DXF %d 字节" % self.raw_dxf.stat().st_size)
        return meta

    # ---------- 1. 组装国标图层 + 尺寸 + 标题栏 ----------
    def build_engineering_dxf(self, meta: dict) -> Path:
        with open(self.manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
        src = ezdxf.readfile(str(self.raw_dxf))
        doc = ezdxf.new("R2010", setup=True)
        doc.units = units.MM
        msp = doc.modelspace()

        doc.layers.add("CUT_PROFILE", color=7, lineweight=50)
        doc.layers.add("HIDDEN_LINE", color=8, linetype="DASHED", lineweight=25)
        doc.layers.add("DIMENSIONS", color=3, lineweight=18)
        doc.layers.add("TITLE_BLOCK", color=5, lineweight=35)

        importer = Importer(src, doc)
        importer.import_modelspace()
        importer.finalize()
        n_vis = n_hid = 0
        src_layers = sorted({e.dxf.layer for e in src.modelspace()})
        for e in msp:
            lay = e.dxf.layer
            if lay in ("0", "Defpoints"):
                e.dxf.layer = "CUT_PROFILE"
                n_vis += 1
                continue
            if "hidden" in lay.lower() or "hid" in lay.lower():
                e.dxf.layer = "HIDDEN_LINE"
                n_hid += 1
            else:
                e.dxf.layer = "CUT_PROFILE"
                n_vis += 1
        log("[Phase6] 视图几何导入: 可见/轮廓 %d 条 -> CUT_PROFILE, 隐藏 %d 条 -> HIDDEN_LINE (源图层 %s)"
            % (n_vis, n_hid, src_layers))

        bbox = manifest.get("cad_verification", {}).get("verified_bbox_mm") or manifest["target_bbox_mm"]
        lx, ly, lz = float(bbox["x"]), float(bbox["y"]), float(bbox["z"])
        # 用 FreeCAD 投影元数据中的真实视图中心定位尺寸标注（避免与视图重叠/错位）
        centers = {v.get("name", "").upper(): (float(v.get("x", 0)), float(v.get("y", 0)))
                   for v in (meta.get("views") or [])}
        front = centers.get("FRONT", (110.0, 190.0))
        top = centers.get("TOP", (110.0, 85.0))
        self._add_dimensions(msp, lx, ly, lz, front, top)
        self._draw_a3_title_block(msp, manifest, lx, ly, lz)

        out = self.out_dir / f"{self.project_dir.name}_engineering_A3.dxf"
        doc.saveas(str(out))
        log("[Phase6] [工程总图] A3 DXF 已导出: %s (%d 字节)" % (out.name, out.stat().st_size))
        return out

    def _add_dimensions(self, msp, lx, ly, lz, front, top):
        fx, fy = front
        tx, ty = top
        dims = [
            dict(base=(fx, fy - lz / 2 - 14), p1=(fx - lx / 2, fy - lz / 2), p2=(fx + lx / 2, fy - lz / 2)),
            dict(base=(fx - lx / 2 - 14, fy), p1=(fx - lx / 2, fy - lz / 2), p2=(fx - lx / 2, fy + lz / 2), angle=90),
            dict(base=(tx - lx / 2 - 14, ty), p1=(tx - lx / 2, ty - ly / 2), p2=(tx - lx / 2, ty + ly / 2), angle=90),
        ]
        for d in dims:
            dim = msp.add_linear_dim(dimstyle="EZDXF", override={"dimtxt": 3.0, "dimasz": 2.5},
                                     dxfattribs={"layer": "DIMENSIONS"}, **d)
            dim.render()
        log("[Phase6] 三轴检验尺寸标注已添加 (总长 %.1f / 总高 %.1f / 总宽 %.1f mm)" % (lx, lz, ly))

    @staticmethod
    def _draw_a3_title_block(msp, manifest: dict, lx: float, ly: float, lz: float):
        msp.add_lwpolyline([(0, 0), (420, 0), (420, 297), (0, 297), (0, 0)], dxfattribs={"layer": "TITLE_BLOCK"})
        msp.add_lwpolyline([(10, 10), (410, 10), (410, 287), (10, 287), (10, 10)], dxfattribs={"layer": "TITLE_BLOCK"})
        msp.add_lwpolyline([(250, 10), (410, 10), (410, 62), (250, 62), (250, 10)], dxfattribs={"layer": "TITLE_BLOCK"})
        mfg = manifest.get("mfg_constraints", manifest.get("manufacturing_constraints", {}))
        vol = manifest.get("cad_verification", {}).get("volume_mm3", 0.0)
        tech_notes = [
            f"PROJECT ID : {manifest.get('project_id', 'HD-001')}",
            f"PRODUCT    : {manifest.get('product', 'Industrial Sensor Enclosure')}",
            f"MATERIAL   : {mfg.get('material', 'PC+ABS / AL6061')}",
            f"PROCESS    : {mfg.get('process', 'Injection Molding / CNC')}",
            f"WALL / DRAFT: {mfg.get('min_wall_thickness_mm', 2.4)}mm / >= {mfg.get('min_draft_angle_deg', 1.8)} deg",
            f"BBOX / VOL : {lx} x {ly} x {lz} mm | {round(vol / 1000.0, 2)} cm3",
            "TOLERANCE  : GB/T 1804-m (Unmarked Fillet R0.5)",
        ]
        for idx, line in enumerate(tech_notes):
            msp.add_text(line, dxfattribs={"layer": "TITLE_BLOCK", "height": 2.8}).set_placement((255, 55 - idx * 6.2))
        msp.add_text("HyperDesign 自动出图 / GB-T 14665", dxfattribs={"layer": "TITLE_BLOCK", "height": 3.2}) \
            .set_placement((255, 8.5))
        log("[Phase6] A3 图框与标题栏已绘制 (WALL/DRAFT 来自 Phase1 RAG)")

    # ---------- 2. 1:1 激光切割净轮廓 DXF ----------
    def export_laser_profile(self) -> Path:
        src = ezdxf.readfile(str(self.raw_dxf))
        doc = ezdxf.new("R2010", setup=True)
        doc.units = units.MM
        doc.layers.add("CUT_PROFILE", color=7, lineweight=50)
        msp = doc.modelspace()
        top_layers = [l for l in {e.dxf.layer for e in src.modelspace()} if l.upper().startswith("TOP")]
        importer = Importer(src, doc)
        for lay in top_layers:
            ents = list(src.modelspace().query(f'*[layer=="{lay}"]'))
            importer.import_entities(ents)
        importer.finalize()
        n = 0
        for e in msp:
            e.dxf.layer = "CUT_PROFILE"
            n += 1
        out = self.out_dir / f"{self.project_dir.name}_laser_1to1.dxf"
        doc.saveas(str(out))
        log("[Phase6] [机床直连] 1:1 净轮廓 DXF: %s (%d 条轮廓实体, 源图层 %s)" % (out.name, n, top_layers))
        return out

    # ---------- 3. 矢量 PDF (A3 300dpi) ----------
    def render_dxf_to_pdf(self, dxf_path: Path) -> Path:
        doc = ezdxf.readfile(str(dxf_path))
        msp = doc.modelspace()
        # ACI 7 在白底上渲染为白色 -> 不可见；统一改成真彩色黑（CAD 里仍是"白/黑"自适应色）
        for lay in doc.layers:
            if lay.dxf.color == 7:
                lay.dxf.true_color = 0x000000
        fig = plt.figure(figsize=(16.53, 11.69), dpi=300)
        ax = fig.add_axes([0, 0, 1, 1])
        ax.set_axis_off()
        ctx = RenderContext(doc)
        out = MatplotlibBackend(ax)
        Frontend(ctx, out).draw_layout(msp, finalize=True)
        pdf_path = self.out_dir / f"{self.project_dir.name}_engineering_A3.pdf"
        fig.savefig(str(pdf_path), format="pdf", dpi=300)
        plt.close(fig)
        log("[Phase6] [移动审阅] 矢量工程图 PDF 已导出: %s (%.2f MB)" % (pdf_path.name, pdf_path.stat().st_size / 1e6))
        return pdf_path

    def run_all(self):
        meta = self.project_views()
        eng = self.build_engineering_dxf(meta)
        laser = self.export_laser_profile()
        pdf = self.render_dxf_to_pdf(eng)
        with open(self.manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
        manifest["drawing_deliverables"] = {
            "laser_1to1_dxf": f"06_drawings/{laser.name}",
            "engineering_a3_dxf": f"06_drawings/{eng.name}",
            "engineering_a3_pdf": f"06_drawings/{pdf.name}",
            "layers": ["CUT_PROFILE", "HIDDEN_LINE", "DIMENSIONS", "TITLE_BLOCK"],
            "exported_at": datetime.now().isoformat(timespec="seconds"),
        }
        with open(self.manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)
        log("[Phase6 完成] 生产交付包已生成至: %s" % self.out_dir)
        return eng, laser, pdf


if __name__ == "__main__":
    log("=" * 72)
    log("===== PHASE 6 启动：1:1 激光 DXF + A3 工程总图 + 300dpi PDF =====")
    exporter = Phase6DrawingExporter(Path(r"D:\hyperdesign\workspace\proj_20261014_001"))
    eng, laser, pdf = exporter.run_all()
    print(json.dumps({"PHASE6_RESULT": "OK", "engineering_dxf": str(eng), "laser_dxf": str(laser),
                      "pdf": str(pdf)}, ensure_ascii=False))
    sys.exit(0)
