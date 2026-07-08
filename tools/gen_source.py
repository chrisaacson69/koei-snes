#!/usr/bin/env python3
"""
Derive readable "source" for a KOEI SNES bytecode module: a linear annotated listing
where every routine gets its name as a label, calls resolve to callee names, and
immediates resolve to string/data/global symbols. This is the top layer of the layered
decompilation (raw bytes -> named disasm -> this labelled source).

    py -3 tools/gen_source.py <rom> --start 04:AB7E --base 7E:7208 --scan B800 \
        --syms <title>/data/comroot > comroot.src
"""
import argparse
import os
import sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..", "..", "snes-decompiler", "tools")))
from mapper import cpu_to_file, strip_copier_header, LOROM
import vm_disasm as D
import vm_opcodes as V
from symbols import Symbols

DC = {0xE9, 0xAC}; IC = {0xDD, 0xEA}; REL = {0xD8, 0xE3, 0xE4, 0xE5, 0xE6, 0xE7}


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("rom"); ap.add_argument("--start", required=True); ap.add_argument("--base", required=True)
    ap.add_argument("--scan", required=True); ap.add_argument("--syms", required=True)
    a = ap.parse_args(argv[1:])
    rom, _ = strip_copier_header(open(a.rom, "rb").read()); V.rom = rom
    S = Symbols(a.syms)
    pbase = cpu_to_file(LOROM, 0, D.PRIMARY); ebase = cpu_to_file(LOROM, 0, D.EXTENDED)
    prim = [rom[pbase + 2*i] | (rom[pbase + 2*i+1] << 8) for i in range(256)]
    ext = [rom[ebase + 2*i] | (rom[ebase + 2*i+1] << 8) for i in range(48)]
    psz = [D.opsize(h) for h in prim]
    sb, so = a.start.split(":"); off0 = cpu_to_file(LOROM, int(sb, 16), int(so, 16))
    vb, vo = a.base.split(":"); vaddr0 = int(vo, 16); end = int(a.scan, 16)

    def read(v):
        return rom[off0 + (v - vaddr0)]

    def declen(v):
        op = read(v)
        return (2 + D.opsize(ext[read(v + 1)])) if (op == D.EXT_PREFIX and read(v + 1) < 48) else 1 + psz[op]

    def s8(b):
        return b - 256 if b & 0x80 else b

    print("; ==== %s source (derived) — base $%s, %d symbols ====" % (a.syms.split("/")[-1], a.base, len(S.strings)))
    v = vaddr0
    while v < end:
        lbl = S.string(v)
        if lbl and read(v) == 0x20 and read(v + 1) == 0xE6:
            print("\n%s:" % lbl)                       # routine label
        op = read(v)
        try:
            ln = declen(v)
        except Exception:
            v += 1; continue
        mn = D.mnem(op)
        ann = ""
        if op in DC or op in IC:
            if op in IC:
                ann = "  ; -> *regA"
            else:
                t = read(v + 1) | (read(v + 2) << 8)
                ann = "  ; -> %s" % (S.string(t) or "$%04X" % t)
        elif op in REL:
            tgt = v + ln + s8(read(v + 1))
            ann = "  ; -> $%04X" % tgt
        elif ln == 3:
            val = read(v + 1) | (read(v + 2) << 8)
            nm = S.string(val)
            if nm:
                ann = "  ; = %s" % nm
        print("  $%04X  %-22s%s" % (v, mn, ann))
        v += ln


if __name__ == "__main__":
    main(sys.argv)
