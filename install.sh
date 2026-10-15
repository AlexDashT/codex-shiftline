#!/usr/bin/env bash
set -euo pipefail

if ! command -v python3 >/dev/null 2>&1; then
  echo 'Python 3 is required (Ubuntu: sudo apt install python3)' >&2
  exit 1
fi
python3 - <<'PY_VERSION'
import sys
if sys.version_info < (3,9):
    sys.exit('Python 3.9+ required')
PY_VERSION

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE="$SCRIPT_DIR/shiftline.py"
DEST="$HOME/.local/bin/shiftline"
[[ -f "$SOURCE" ]] || { echo "Missing $SOURCE" >&2; exit 1; }
mkdir -p "$HOME/.local/bin"
if [[ -L "$DEST" || -d "$DEST" ]]; then
  echo "Refusing to overwrite symlink or directory: $DEST" >&2
  exit 1
fi
if [[ -e "$DEST" ]]; then
  if ! grep -q 'Codex Shiftline:' "$DEST"; then
    echo "Refusing to overwrite unrelated existing program: $DEST" >&2
    exit 1
  fi
  BACKUP="$(mktemp "$HOME/.local/bin/shiftline.backup.XXXXXXXX")"
  cp -p -- "$DEST" "$BACKUP"
  echo "Backed up earlier Shiftline to $BACKUP"
fi
install -m 700 "$SOURCE" "$DEST"
echo "Installed: $DEST"
if [[ ":$PATH:" != *":$HOME/.local/bin:"* ]]; then
  echo 'Add to ~/.bashrc or ~/.zshrc: export PATH="$HOME/.local/bin:$PATH"'
fi
"$DEST" --version
