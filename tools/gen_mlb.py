#!/usr/bin/env python3
"""
Emit a Mesen(2) .mlb label file from the named KOEI SNES symbol registry, so the whole
decompiled program shows up with labels in Mesen's debugger.

    py -3 tools/gen_mlb.py --data <title>/data --out labels.mlb root comroot excsub1 [...]

The bytecode routines/data/text live in WRAM ($7E/$7F) -> `SnesWorkRam:<offset>:<label>`.
WorkRam offset = (bank-$7E)*$10000 + addr; for $7E:xxxx that is just xxxx.

Overlays SHARE WRAM addresses ($7200 slot: comroot/settei/kisetsu; $C300 slot:
excsub1-6), so Mesen can hold only one set per slot -- list exactly one module per slot
on the command line (default root+comroot+excsub1). Resident root ($2xxx-$6xxx) and the
shared high-WRAM globals/records ($E000+/$F800+) are always emitted (first module wins).
A few native VM entry points (bank $00) are added from games.toml as `SnesPrgRom`.
"""
import argparse
import os
import re
import sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..", "..", "snes-decompiler", "tools")))
from mapper import cpu_to_file, LOROM
_LINE = re.compile(r'(0x[0-9A-Fa-f]+)\s*=\s*"([^"]+)"(?:\s*#\s*"([^"]*)")?')


def load_labels(mdir):
    """addr -> (label, comment) from routines.toml + strings.toml + enums.py."""
    out = {}
    for fn in ("routines.toml", "strings.toml"):
        p = os.path.join(mdir, fn)
        if not os.path.exists(p):
            continue
        for line in open(p, encoding="utf-8"):
            body = line.split("#", 1)[0]
            m = _LINE.match(line.strip()) or re.match(r'(0x[0-9A-Fa-f]+)\s*=\s*"([^"]+)"', body.strip())
            if m:
                addr = int(m.group(1), 0)
                out[addr] = (m.group(2), (m.group(3) if m.lastindex and m.lastindex >= 3 else "") or "")
    ep = os.path.join(mdir, "enums.py")
    if os.path.exists(ep):
        ns = {}
        exec(compile(open(ep, encoding="utf-8").read(), ep, "exec"), ns)
        for name, base in ns.get("STRING_TABLE_BASE", {}).items():
            out.setdefault(base, ("tbl_" + name, ""))
    return out


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("modules", nargs="+")
    ap.add_argument("--data", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv[1:])
    merged = {}                                  # addr -> (label, comment, module)
    for mod in a.modules:                        # first module to claim an address wins
        for addr, (label, cmt) in load_labels(os.path.join(a.data, mod)).items():
            if addr not in merged and label != "DRIFT":
                merged[addr] = (label, cmt, mod)
    lines = []
    for addr in sorted(merged):
        label, cmt, mod = merged[addr]
        off = addr if addr < 0x10000 else addr    # $7E:xxxx WorkRam offset = xxxx
        note = ("%s" % mod) + ((" | " + cmt) if cmt else "")
        lines.append("SnesWorkRam:%X:%s:%s" % (off, label, note))
    # native VM entry points (bank $00 ROM) from the profile, as SnesPrgRom offsets
    try:
        sys.path.insert(0, HERE)
        from profile import load as load_profile
        P = load_profile("rot3k2")
        native = {"vm_interp_loop": P.get("interpreter_loop"), "vm_run_entry": P.get("run_vm_entry"),
                  "syscall_dispatch": P.get("syscall_dispatch"), "resource_loader": P.get("loader")}
        for name, addr in native.items():
            if addr:
                lines.append("SnesPrgRom:%X:%s:native VM" % (cpu_to_file(LOROM, 0, addr), name))
    except Exception as e:
        print("  (native labels skipped: %s)" % e, file=sys.stderr)
    open(a.out, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print("wrote %s: %d labels (%d modules: %s)" % (a.out, len(lines), len(a.modules), ", ".join(a.modules)))


if __name__ == "__main__":
    main(sys.argv)
