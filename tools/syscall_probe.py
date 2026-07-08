#!/usr/bin/env python3
"""
Fingerprint the ROTK2-SNES syscall table ($00:937B, 69 entries) by walking each
handler and recording the hardware registers it touches (named via snes_regs).

The dispatcher $8C1D calls JSR ($937B,X) with index = byte 0 of the 22-byte param
block, entering handlers in m16/x16. For each handler we follow branches + descend
one level into JSR/JSL callees, classify each absolute access as R/W/RMW, and map
register addresses to names -> a per-syscall subsystem fingerprint to name it from.

    py -3 tools/syscall_probe.py "<rom>.sfc"
    py -3 tools/syscall_probe.py "<rom>.sfc" --id 0x10     # detail one syscall
"""
import argparse
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
_SNES = os.path.normpath(os.path.join(_HERE, "..", "..", "snes-decompiler", "tools"))
sys.path.insert(0, _SNES)
from mapper import cpu_to_file, strip_copier_header, LOROM       # noqa: E402
from header_parse import detect                                   # noqa: E402
import w65c816                                                    # noqa: E402
import snes_regs                                                  # noqa: E402
from profile import load as _load_profile                         # noqa: E402

_P = _load_profile(os.environ.get("KOEI_SNES_GAME"))
TABLE_ADDR = _P["syscall_table"]
TABLE_LEN = _P["syscall_count"]

WRITE = {"STA", "STX", "STY", "STZ"}
RMW = {"INC", "DEC", "ASL", "LSR", "ROL", "ROR", "TSB", "TRB"}
ABSMODES = {"abs", "abx", "aby", "abl", "alx"}
RET = {"RTS", "RTL", "RTI", "STP"}
CALL = {"JSR", "JSL"}
UNCOND_BR = {"BRA", "BRL"}
JUMP = {"JMP", "JML"}
COND = {"BPL", "BMI", "BVC", "BVS", "BCC", "BCS", "BNE", "BEQ"}


def rom_off(rom, bank, addr):
    if (bank & 0x7F) <= 0x7D and addr >= 0x8000:
        f = cpu_to_file(LOROM, bank, addr)
        return f if f < len(rom) else None
    return None


def probe(rom, bank, addr, m8=False, x8=False, max_insns=1200, max_depth=1):
    visited, regs, subs, callees = set(), {}, {}, set()
    count = [0]
    stack = [(bank, addr, m8, x8, 0)]
    while stack:
        b, a, mm, xx, depth = stack.pop()
        while True:
            key = (b << 16) | a
            if key in visited:
                break
            visited.add(key)
            foff = rom_off(rom, b, a)
            if foff is None or count[0] >= max_insns:
                break
            ins, mm, xx = w65c816.decode(rom, foff, b, a, mm, xx)
            count[0] += 1
            mnem, mode, raw = ins["mnem"], ins["mode"], ins["raw"]
            if mode in ABSMODES and len(raw) >= 3:
                operand = raw[1] | (raw[2] << 8)
                nm, sub = snes_regs.name(operand)
                if nm:
                    rw = "W" if mnem in WRITE else ("M" if mnem in RMW else "R")
                    regs.setdefault(nm, set()).add(rw)
                    subs[sub] = subs.get(sub, 0) + 1
            if mnem in RET:
                break
            if mnem in CALL:
                if mode in ("abs", "abl") and ins["target"]:
                    callees.add(ins["target"])
                    if depth < max_depth:
                        stack.append((ins["target"][0], ins["target"][1], mm, xx, depth + 1))
            elif mnem in UNCOND_BR:
                if ins["target"]:
                    stack.append((ins["target"][0], ins["target"][1], mm, xx, depth))
                break
            elif mnem in JUMP:
                if mode in ("abs", "abl") and ins["target"]:
                    stack.append((ins["target"][0], ins["target"][1], mm, xx, depth))
                break
            elif mnem in COND and ins["target"]:
                stack.append((ins["target"][0], ins["target"][1], mm, xx, depth))
            nxt = a + ins["len"]
            if nxt > 0xFFFF:
                break
            a = nxt
    return regs, subs, callees, count[0]


def fmt_regs(regs, kinds):
    out = [r for r, k in sorted(regs.items()) if k & set(kinds)]
    return out


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("rom")
    ap.add_argument("--id", default=None, help="hex id to detail (e.g. 0x10)")
    args = ap.parse_args(argv[1:])
    rom, _ = strip_copier_header(open(args.rom, "rb").read())
    score, f = detect(rom)
    mapping = f["mapping_guess"]

    base = cpu_to_file(mapping, 0x00, TABLE_ADDR)
    entries = [rom[base + 2 * i] | (rom[base + 2 * i + 1] << 8) for i in range(TABLE_LEN)]

    ids = [int(args.id, 16)] if args.id else range(TABLE_LEN)
    if not args.id:
        print("id   addr    n    subsystems            writes/RMW (control regs)")
        print("-" * 92)
    for i in ids:
        h = entries[i]
        regs, subs, callees, n = probe(rom, 0x00, h)
        subline = " ".join("%s:%d" % (s, c) for s, c in sorted(subs.items(), key=lambda kv: -kv[1]))
        wr = [r for r, k in sorted(regs.items()) if "W" in k or "M" in k]
        rd = [r for r, k in sorted(regs.items()) if k == {"R"}]
        if args.id:
            print("syscall $%02X -> $00:%04X  (%d insns)" % (i, h, n))
            print("  subsystems :", subline or "(none — pure logic/data)")
            print("  writes/RMW :", ", ".join(wr) or "(none)")
            print("  reads      :", ", ".join(rd) or "(none)")
            print("  callees    :", ", ".join("$%02X:%04X" % c for c in sorted(callees)[:12]))
        else:
            print("%02X   $%04X  %-4d %-21s %s" % (i, h, n, subline or "-", ", ".join(wr[:10]) or "-"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
