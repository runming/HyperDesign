# HyperDesign Phase 7 - 周末夜间一键进化驱动 (Windows 侧)
# 用法: powershell -ExecutionPolicy Bypass -File D:\hyperdesign\src\weekend_evolve.ps1 [-MinSamples 50] [-SkipTrain]
param(
  [int]$MinSamples = 50,
  [switch]$SkipTrain,
  [string]$OldModel = "qwen38-uncensored-128k:latest"
)
$ErrorActionPreference = "Continue"
$root = "D:\hyperdesign"
$log  = Join-Path $root "progress.log"
function Log($m) {
  $line = "[{0}] $m" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss")
  Write-Host $line
  Add-Content -Path $log -Value $line -Encoding UTF8
}

Log "===== PHASE 7 周末夜间一键进化 启动 (MinSamples=$MinSamples, SkipTrain=$SkipTrain) ====="

# 0) 数据自检：DPO 样本量
$dpoDir = Join-Path $root "models\checkpoints\dpo_dataset"
$n = 0
Get-ChildItem $dpoDir -Filter *.jsonl -ErrorAction SilentlyContinue | ForEach-Object {
  $n += (Get-Content $_.FullName | Where-Object { $_.Trim() -ne "" }).Count
}
Log "DPO 偏好样本累计: $n 条 (目录 $dpoDir)"
if ($n -lt $MinSamples) {
  Log "[warn] 样本量不足 $MinSamples 条 —— 仍可演练 (加 -MinSamples $n)，但工程文件建议攒够 50~100 条再训"
}

# 1) WSL: 环境自检 + QLoRA/DPO 训练 -> GGUF
if (-not $SkipTrain) {
  Log "→ 调用 WSL hd_unsloth 执行 QLoRA + DPO 训练..."
  wsl -d Ubuntu-22.04 -- bash -lc "source /home/omegahyper/hd_unsloth/bin/activate 2>/dev/null || { echo 'NO_ENV: 先运行 bash /mnt/d/hyperdesign/src/wsl_setup_unsloth.sh'; exit 9; }; export HF_ENDPOINT=https://hf-mirror.com; python /mnt/d/hyperdesign/src/phase7_unsloth_dpo_trainer.py --min-samples $MinSamples"
  if ($LASTEXITCODE -ne 0) { Log "[error] 训练阶段失败(rc=$LASTEXITCODE)，终止进化流程"; exit $LASTEXITCODE }
}

# 2) 注册新模型到 Ollama（取最新 lora_v* 目录里的 Modelfile）
$latest = Get-ChildItem (Join-Path $root "models\checkpoints") -Directory -Filter "lora_v*" |
          Sort-Object Name -Descending | Select-Object -First 1
if ($latest) {
  $tag = $latest.Name -replace "^lora_", ""
  $mf  = Join-Path $latest.FullName "gguf\Modelfile"
  if (Test-Path $mf) {
    Log "→ ollama create hd-brain:$tag -f $mf"
    ollama create "hd-brain:$tag" -f $mf
    $newModel = "hd-brain:$tag"
  } else {
    Log "[warn] 未找到 $mf（GGUF 导出可能失败），跳过注册"
  }
} else {
  Log "[warn] 未找到 lora_v* 输出目录"
}

# 3) 守门员：黄金基准集回归对比（新模型必须全面 >= 旧模型才允许切流）
if ($newModel) {
  Log "→ 黄金基准集回归对比: $OldModel  vs  $newModel"
  & "E:\hyperdesign\venvs\hd_brain\Scripts\python.exe" "$root\src\phase7_benchmark_eval.py" --models $OldModel $newModel
  Log "→ 成绩单见 $root\models\checkpoints\benchmark_*.json（allowed_to_switch=true 才可切流上线）"
} else {
  Log "→ 仅运行旧模型基线测量"
  & "E:\hyperdesign\venvs\hd_brain\Scripts\python.exe" "$root\src\phase7_benchmark_eval.py" --models $OldModel
}
Log "===== PHASE 7 周末夜间一键进化 结束 ====="
