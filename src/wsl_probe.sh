#!/usr/bin/env bash
echo "=== WSL PROBE ==="
echo -n "sudo: "; sudo -n true 2>/dev/null && echo SUDO_NOPASS_OK || echo SUDO_NEEDS_PASS
echo "tools:"
for t in git cmake ninja make gcc g++ nvcc pip3 python3; do
  printf "  %-8s %s\n" "$t" "$(command -v $t || echo MISSING)"
done
echo -n "venv_module: "; python3 -m venv --help >/dev/null 2>&1 && echo VENV_OK || echo VENV_MISSING
echo "network:"
for u in https://github.com https://hf-mirror.com https://download.pytorch.org/whl/cu128 https://pypi.org/simple/; do
  code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 15 "$u" || echo ERR)
  echo "  $u -> $code"
done
echo -n "cpu_cores: "; nproc
free -g | head -2
echo -n "cuda_toolkit_pkg: "; apt-cache policy cuda-toolkit-12-8 2>/dev/null | head -3 | tr '\n' ' '; echo
echo -n "nvcc_any: "; ls -d /usr/local/cuda* 2>/dev/null | tr '\n' ' '; echo
