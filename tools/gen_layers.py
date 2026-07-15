#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Deterministic driver that generates the layered source deliverable for a KOEI SNES title,
straight from the ROM's own resource archive (single source of truth -- no hand-kept module
table to drift). Three layers, mirroring how the program is actually built:

    assembly  ->  src/native.asm        (gen_native.py : the native 65C816 kernel/VM engine)
    bytecode  ->  src/<module>.src      (gen_source.py : named per-module bytecode listing)
    C         ->  src/<module>.c         (vm_lift.py    : C-like lift of each module)

The per-module ROM location / WRAM base / length come from the $00:F800 archive directory
(16-byte [name][bank][addr][len] entries); the WRAM base is read from each module's own
`JMP base+3` header, and a module counts as CODE iff the repo has data/<name>/routines.toml.
This reproduces the validated per-module walk params exactly (e.g. comroot 04:AB79 / 7E:7203).

    KOEI_SNES_GAME=<game> py -3 tools/gen_layers.py <rom> <title-repo> [--native-end BA60] [--only m1,m2]
"""
import argparse
import os
import subprocess
import sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..", "..", "snes-decompiler", "tools")))
from mapper import cpu_to_file, strip_copier_header, LOROM  # noqa: E402


def archive_code_modules(rom, repo):
    """Yield (name, start 'bk:ad', base '7E:xxxx', scan 'xxxx', length) for each CODE module."""
    base = cpu_to_file(LOROM, 0, 0xF800)
    for i in range(64):
        e = rom[base + 16 * i: base + 16 * i + 16]
        name = bytes(e[0:8]).split(b"\x00")[0]
        if not name or not all(32 <= c < 127 for c in name):
            break
        nm = name.decode()
        rt = os.path.join(repo, "data", nm, "routines.toml")
        if not os.path.isfile(rt):
            continue                                      # strings/data-only or unwalked -> skip
        if not any(l.lstrip().startswith("0x") for l in open(rt, encoding="utf-8")):
            continue                                      # routines.toml is an empty/data stub (e.g. cbmdata1) -> not code
        bank, addr, ln = e[8], e[10] | (e[11] << 8), e[12] | (e[13] << 8)
        fo = cpu_to_file(LOROM, bank, addr)
        if rom[fo] != 0x4C:                               # no JMP base+3 header -> data blob
            continue
        jmp = rom[fo + 1] | (rom[fo + 2] << 8)
        slot = jmp - 3
        yield (nm, "%02X:%04X" % (bank, addr + 3), "7E:%04X" % jmp, "%04X" % (slot + ln), ln)


def run(tool, args, outpath):
    with open(outpath, "w", encoding="utf-8") as fh:
        r = subprocess.run([sys.executable, os.path.join(HERE, tool)] + args,
                           stdout=fh, stderr=subprocess.PIPE, text=True)
    lines = sum(1 for _ in open(outpath, encoding="utf-8"))
    return lines, r.returncode, (r.stderr or "").strip()


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("rom"); ap.add_argument("repo")
    ap.add_argument("--native-end", default=None, help="native kernel stop addr (hex); default from table")
    ap.add_argument("--native-mx", default="8,16", help="native M/X widths (kernel steady state)")
    ap.add_argument("--only", default=None, help="comma list of modules to (re)generate")
    a = ap.parse_args(argv[1:])

    rom, _ = strip_copier_header(open(a.rom, "rb").read())
    srcdir = os.path.join(a.repo, "src")
    os.makedirs(srcdir, exist_ok=True)
    only = set(a.only.split(",")) if a.only else None

    print("=== layered source: %s ===" % os.path.basename(a.repo.rstrip("/\\")))

    # --- assembly layer: native kernel ---
    nat = os.path.join(a.repo, "data", "native", "routines.toml")
    if only is None or "native" in only:
        if os.path.isfile(nat):
            end = a.native_end or ("%X" % (max(int(l.split("=")[0].strip(), 16)
                                    for l in open(nat, encoding="utf-8")
                                    if l.strip().startswith("0x")) + 0x40))
            ln, rc, err = run("gen_native.py", [a.rom, "--start", "00:8000", "--end", end,
                                                "--syms", nat, "--mx", a.native_mx],
                              os.path.join(srcdir, "native.asm"))
            print("  [asm ] native.asm            %5d lines%s" % (ln, "  ERR:" + err if rc else ""))
        else:
            print("  [asm ] (no data/native/routines.toml - native symbols are in games.toml; skipped)")

    # --- bytecode + C layers, per code module ---
    mods = list(archive_code_modules(rom, a.repo))
    tot_src = tot_c = 0
    for nm, start, base, scan, length in mods:
        if only is not None and nm not in only:
            continue
        syms = os.path.join(a.repo, "data", nm)
        s_ln, s_rc, s_err = run("gen_source.py", [a.rom, "--start", start, "--base", base,
                                                  "--scan", scan, "--syms", syms],
                                os.path.join(srcdir, nm + ".src"))
        c_ln, c_rc, c_err = run("vm_lift.py", [a.rom, "--start", start, "--base", base,
                                               "--scan", scan, "--syms", syms],
                                os.path.join(srcdir, nm + ".c"))
        tot_src += s_ln; tot_c += c_ln
        flag = ("  SRC-ERR:" + s_err) if s_rc else (("  C-ERR:" + c_err) if c_rc else "")
        print("  [byte] %-10s %s -> %-9s .src %5d  .c %5d%s" % (nm, start, base, s_ln, c_ln, flag))
    print("  --- %d modules: %d .src lines + %d .c lines ---" % (len(mods), tot_src, tot_c))


if __name__ == "__main__":
    main(sys.argv)
