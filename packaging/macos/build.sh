#!/bin/bash
set -euo pipefail
project_directory="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$project_directory"
uv_command="$(command -v uv || true)"
if [ -z "$uv_command" ] && [ -x .venv/bin/uv ]; then uv_command="$project_directory/.venv/bin/uv"; fi
if [ -z "$uv_command" ]; then echo 'Instale uv para gerar o pacote.' >&2; exit 1; fi
export UV_PROJECT_ENVIRONMENT="$project_directory/.tools/macos-venv"
export MACOSX_DEPLOYMENT_TARGET=15.0
export PYTHONPATH="$project_directory/src"
"$uv_command" sync --locked --managed-python --python 3.12 --extra gui-test --extra recognition --extra macos-build --extra dev
build_python="$UV_PROJECT_ENVIRONMENT/bin/python"
mkdir -p build/macos
"$build_python" packaging/macos/prepare.py > build/macos/prepare.log 2>&1
"$build_python" -m PyInstaller --noconfirm --clean --distpath build/macos/dist --workpath build/macos/pyinstaller packaging/macos/Afinario.spec > build/macos/pyinstaller.log 2>&1
"$build_python" packaging/macos/release.py
