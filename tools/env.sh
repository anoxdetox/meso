# SPDX-License-Identifier: GPL-3.0-or-later
# Shared paths for the test runners and spikes (sourced, never run).
#
#   B   the Blender 5.2 binary     (default: `blender` on PATH)
#   PY  its bundled Python 3.13    (default: <B's install dir>/5.2/python/bin/python3.*)
#
# Put machine-specific values in an untracked `local.env` at the repo root (gitignored), e.g.
#   B=/opt/blender-5.2.2-linux-x64/blender
#   MESO_EXTENSIONS_DIR=~/.config/blender/5.2/extensions/user_default   (tools/dev_link.py)
# It is sourced first; values already in the environment win over it.

_meso_root="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." && pwd)"
if [ -f "$_meso_root/local.env" ]; then
    _meso_b="${B:-}" _meso_py="${PY:-}"
    # shellcheck disable=SC1091
    . "$_meso_root/local.env"
    [ -n "$_meso_b" ] && B="$_meso_b"
    [ -n "$_meso_py" ] && PY="$_meso_py"
    unset _meso_b _meso_py
fi
B="${B:-$(command -v blender || echo blender)}"
if [ -z "${PY:-}" ]; then
    _meso_bin="$(readlink -f "$(command -v "$B" 2>/dev/null || echo "$B")")"
    PY="$(ls "$(dirname "$_meso_bin")"/5.2/python/bin/python3.[0-9]* 2>/dev/null | head -n 1)"
    unset _meso_bin
fi
export B PY
unset _meso_root
