# -*- coding: utf-8 -*-
"""
HyperDesign Phase 7 - Unsloth QLoRA + DPO 周末夜间一键进化
按《工程文件》Phase 7 第三节 (docs/工程文件_extracted.txt L1461-L1542) 落地

在 WSL2 的 hd_unsloth 环境中运行（映射路径 /mnt/d/hyperdesign/src/phase7_unsloth_dpo_trainer.py）：
    source ~/hd_unsloth/bin/activate
    export PYTHONPATH=$HOME/TRELLIS  # 不需要，仅提示
    python /mnt/d/hyperdesign/src/phase7_unsloth_dpo_trainer.py [--min-samples 50] [--dry-run]

产物:
    D:\\hyperdesign\\models\\checkpoints\\lora_vYYYYMMDD_HHMM\\lora_adapter\\  (LoRA 适配器, 可回滚)
    D:\\hyperdesign\\models\\checkpoints\\lora_vYYYYMMDD_HHMM\\gguf\\           (q4_k_m GGUF + Modelfile)
Windows 侧注册: ollama create hd-brain:vYYYYMMDD_HHMM -f <...>\\gguf\\Modelfile
"""
import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

DATASET_FILES = [
    "/mnt/d/hyperdesign/models/checkpoints/dpo_dataset/phase2_prompt_dpo.jsonl",
    "/mnt/d/hyperdesign/models/checkpoints/dpo_dataset/phase5_cad_code_dpo.jsonl",
]
CHECKPOINT_ROOT = Path("/mnt/d/hyperdesign/models/checkpoints")
BASE_MODEL = "unsloth/Qwen2.5-7B-Instruct-bnb-4bit"   # docx 指定基座
LOG = Path("/mnt/d/hyperdesign/progress.log")


def log(msg: str) -> None:
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def count_samples() -> int:
    n = 0
    for f in DATASET_FILES:
        p = Path(f)
        if p.exists():
            with open(p, encoding="utf-8") as fh:
                n += sum(1 for line in fh if line.strip())
    return n


def run_dpo_evolution(min_samples: int = 1, dry_run: bool = False):
    VERSION_TAG = datetime.now().strftime("v%Y%m%d_%H%M")
    OUTPUT_DIR = CHECKPOINT_ROOT / f"lora_{VERSION_TAG}"
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    valid_files = [f for f in DATASET_FILES if os.path.exists(f)]
    n_samples = count_samples()
    log(f"[Phase7 Evolution] 检测到 DPO 偏好样本 {n_samples} 条 (需 >= {min_samples})，文件: {valid_files}")
    if not valid_files:
        raise FileNotFoundError("尚未检测到 DPO 数据集文件，请先运行 Phase 2~5 积累偏好样本。")
    if n_samples < min_samples and not dry_run:
        raise RuntimeError(f"样本量 {n_samples} < 最低要求 {min_samples}（工程文件建议攒够 50~100 条再训）")

    import torch
    from datasets import load_dataset
    from unsloth import FastLanguageModel, PatchDPOTrainer
    from trl import DPOTrainer, DPOConfig

    PatchDPOTrainer()
    log(f"[Phase7 Evolution] 加载 4-bit 基座模型: {BASE_MODEL}")
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=BASE_MODEL,
        max_seq_length=4096,
        dtype=None,
        load_in_4bit=True,
    )
    model = FastLanguageModel.get_peft_model(
        model,
        r=16,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
        lora_alpha=16,
        lora_dropout=0,
        bias="none",
        use_gradient_checkpointing="unsloth",
        random_state=3407,
    )
    dataset = load_dataset("json", data_files=valid_files, split="train")
    log(f"[Phase7 Evolution] 共加载 {len(dataset)} 组设计师优选/DFM校验 DPO 样本对。")

    if dry_run:
        log("[Phase7 Evolution] --dry-run: 已完成环境与数据自检，跳过训练。")
        return {"status": "dry_run", "samples": len(dataset), "version": VERSION_TAG,
                "output_dir": str(OUTPUT_DIR)}

    dpo_trainer = DPOTrainer(
        model=model,
        ref_model=None,
        args=DPOConfig(
            per_device_train_batch_size=2,
            gradient_accumulation_steps=4,
            warmup_ratio=0.1,
            num_train_epochs=3,
            learning_rate=5e-6,
            fp16=not torch.cuda.is_bf16_supported(),
            bf16=torch.cuda.is_bf16_supported(),
            logging_steps=1,
            optim="adamw_8bit",
            weight_decay=0.0,
            lr_scheduler_type="linear",
            seed=42,
            output_dir=str(OUTPUT_DIR),
            beta=0.1,
            max_length=2048,
            max_prompt_length=1024,
        ),
        train_dataset=dataset,
        tokenizer=tokenizer,
    )
    log("[Phase7 Evolution] 开始执行 QLoRA + DPO 偏好微调...")
    dpo_trainer.train()

    model.save_pretrained(str(OUTPUT_DIR / "lora_adapter"))
    tokenizer.save_pretrained(str(OUTPUT_DIR / "lora_adapter"))
    log(f"[Phase7 Evolution] LoRA 适配器已存盘: {OUTPUT_DIR / 'lora_adapter'}")

    gguf_dir = OUTPUT_DIR / "gguf"
    log(f"[Phase7 Evolution] 正在导出 GGUF (q4_k_m) 至 {gguf_dir} ...")
    try:
        model.save_pretrained_gguf(str(gguf_dir), tokenizer, quantization_method="q4_k_m")
        log(f"[微调完成!] 演进版权重已存盘: {OUTPUT_DIR}")
    except Exception as e:
        log(f"[Phase7][warn] GGUF 导出失败({e!r})，LoRA 适配器仍可用于回滚/续训")

    print("\n请在 Windows 终端运行以下命令将其注册为新主控大脑：\n"
          f"ollama create hd-brain:{VERSION_TAG} -f "
          f"D:\\hyperdesign\\models\\checkpoints\\lora_{VERSION_TAG}\\gguf\\Modelfile")
    return {"status": "trained", "samples": len(dataset), "version": VERSION_TAG, "output_dir": str(OUTPUT_DIR)}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-samples", type=int, default=1, help="最低样本数（docx 建议 50~100）")
    ap.add_argument("--dry-run", action="store_true", help="只做环境与数据自检，不训练")
    args = ap.parse_args()
    log("=" * 72)
    log("===== PHASE 7 第三层：Unsloth QLoRA + DPO 一键进化 =====")
    res = run_dpo_evolution(min_samples=args.min_samples, dry_run=args.dry_run)
    print(json.dumps({"PHASE7_EVOLVE": res}, ensure_ascii=False))
