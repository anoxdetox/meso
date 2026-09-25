# SPDX-License-Identifier: GPL-3.0-or-later
"""gdb script: the Blender 5.2.2 preview render race, made deterministic (run.sh drives it).

The race (docs/verified-facts-5.2.md, "Preview render race"): ``RE_NewRender`` (render
pipeline.cc) adds a new ``Render`` to the global ``std::forward_list`` ``render_list`` with no
lock. It is called from the preview job's worker thread (``shader_preview_render``) the first
time a data-block's preview is rendered, while the main thread walks the same list after every
notifier pass (``RE_FreeUnusedGPUResources``, wm_event_system.cc). The release build stores the
new list head *before* it writes the node ({next, Render *}); a main-thread walk in between reads
an unset ``Render *`` and segfaults at ``re->owner``.

Offsets are for the official stripped 5.2.2 build (hash d13f752e3b9c, non-PIE), checked by
their instruction bytes before the run:
  0x1613fa0  RE_NewRender, the "no Render for this owner yet" branch (rbp = owner)
  0x1613fea  RE_NewRender, the node write right after the head was published
  0x16121fc  RE_FreeUnusedGPUResources, ``mov 0x90(%rbp),%rsi`` (re->owner), the crash site

RACE_MODE=widen (default): a worker thread that reaches 0x1613fea is held RACE_DELAY s (0.5)
while the other threads run on (gdb non-stop mode), so an unguarded first preview always
crashes. RACE_MODE=count: only logs every new Render and its thread at 0x1613fa0 (before the
publish, so it widens nothing). RACE_LOG: the log file (default stderr). Every line starts
with ``RACE``; a crash logs ``RACE SIGSEGV pc=...`` and exits 139.
"""

import os
import time

import gdb

LOG = open(os.environ.get("RACE_LOG", "/dev/stderr"), "a", buffering=1)
MODE = os.environ.get("RACE_MODE", "widen")
DELAY = float(os.environ.get("RACE_DELAY", "0.5"))

NEW_RENDER = 0x1613fa0
PUBLISHED = 0x1613fea
CRASH_SITE = 0x16121fc
EXPECT = {
    NEW_RENDER: bytes.fromhex("b901000000"),         # mov $0x1,%ecx
    PUBLISHED: bytes.fromhex("0f1100"),              # movups %xmm0,(%rax)
    CRASH_SITE: bytes.fromhex("488bb590000000"),     # mov 0x90(%rbp),%rsi
}


def read(addr, n):
    return bytes(gdb.selected_inferior().read_memory(addr, n))


def log(msg):
    LOG.write(f"RACE {msg} t={time.time():.2f}\n")
    LOG.flush()


class NewRender(gdb.Breakpoint):
    def stop(self):
        th = gdb.selected_thread()
        owner = int(gdb.parse_and_eval("$rbp"))
        worker = th.num != 1
        log(f"new Render thread={th.num} worker={worker} owner={owner:#x} mode={MODE}")
        if worker and MODE == "widen" and DELAY > 0:
            time.sleep(DELAY)
        return False


def on_stop(event):
    if isinstance(event, gdb.SignalEvent) and event.stop_signal == "SIGSEGV":
        pc = int(gdb.parse_and_eval("$pc"))
        where = "RE_FreeUnusedGPUResources" if pc == CRASH_SITE else "elsewhere"
        log(f"SIGSEGV pc={pc:#x} ({where}) thread={gdb.selected_thread().num}")
        gdb.execute("kill")
        os._exit(139)


for cmd in ("set pagination off", "set confirm off", "set non-stop on",
            "set debuginfod enabled off", "handle SIGPIPE nostop noprint pass",
            "handle SIG32 nostop noprint pass", "handle SIG33 nostop noprint pass"):
    gdb.execute(cmd)
gdb.execute("starti")
bad = [f"{a:#x}" for a, want in EXPECT.items() if read(a, len(want)) != want]
if bad:
    log(f"wrong Blender binary (not 5.2.2 d13f752e3b9c): bytes differ at {bad}")
    gdb.execute("kill")
    os._exit(2)
NewRender(f"*{PUBLISHED if MODE == 'widen' else NEW_RENDER:#x}")
gdb.events.stop.connect(on_stop)
gdb.execute("continue")
