#!/usr/bin/env python3
"""
Recursive-descent walker for the ROTK2-SNES bytecode VM.

The bytecode analog of `snes-decompiler/tools/walk65816.py`: follow control flow
(jmp / brel / conditional branches / ret) from an entry point, decoding via the
opcode table (`vm_disasm`/`vm_opcodes`). Everything reached is CODE; everything else
in the routine's span is DATA. Conflicts (a branch target landing inside an already-
decoded instruction) flag a bad decode or a data region -- the second, independent
method for telling code from data.

call.n / hostcall are bytecode subroutine calls: the walk follows the target and
continues past the call. switch (D5/D9/E8) is an inline jump table -> its case targets
are parsed and followed (local control flow). call.ind/ind2 (regA) stay unresolved.

    py -3 tools/vm_walk.py "<rom>.sfc" --start 01:8008 --base 7E:2008 [--list]
"""
import argparse, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..", "..", "snes-decompiler", "tools")))
sys.path.insert(0, HERE)
from mapper import cpu_to_file, strip_copier_header, LOROM
import vm_disasm as D
import vm_opcodes as V

RET = {0xCF}
JMP_ABS = {0xD6}
CJMP_ABS = {0xD7}            # skipnz: if regA!=0 JMP <abs16>, else fall through
BREL_UNCOND = {0xE3, 0xE6}
BREL_COND = {0xD8, 0xE5, 0xE4, 0xE7}
SWITCH = {0xD5, 0xD9, 0xE8}
CALL = {0xE9, 0xAC}          # hostcall/call.n: operand[0:2] = a bytecode subroutine entry


def s8(b):
    return b - 256 if b & 0x80 else b


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("rom"); ap.add_argument("--start", required=True); ap.add_argument("--base", required=True)
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--syms", default=None, help="title data dir for name annotations")
    ap.add_argument("--auto", type=lambda s: int(s, 16), default=None,
                    help="auto-cover: END virtual addr; seed each ret+1 as a new routine entry")
    a = ap.parse_args(argv[1:])
    rom, _ = strip_copier_header(open(a.rom, "rb").read()); V.rom = rom
    pbase = cpu_to_file(LOROM, 0, D.PRIMARY); ebase = cpu_to_file(LOROM, 0, D.EXTENDED)
    prim = [rom[pbase + 2*i] | (rom[pbase + 2*i+1] << 8) for i in range(256)]
    ext = [rom[ebase + 2*i] | (rom[ebase + 2*i+1] << 8) for i in range(48)]
    psz = [D.opsize(h) for h in prim]

    sb, so = a.start.split(":"); start_off = cpu_to_file(LOROM, int(sb, 16), int(so, 16))
    vb, vo = a.base.split(":"); vbank, vaddr0 = int(vb, 16), int(vo, 16)

    def read(v):                       # virtual addr -> byte (flat overlay)
        return rom[start_off + (v - vaddr0)]

    def declen(v):
        op = read(v)
        if op == D.EXT_PREFIX:
            eop = read(v + 1); return 2 + D.opsize(ext[eop])
        return 1 + psz[op]

    starts, interior, conflicts = {}, set(), []
    switches, rets = [], []
    work = [vaddr0]
    while work:
        v = work.pop()
        while True:
            if v in starts:
                break
            if v in interior:
                conflicts.append(v); break
            ln = declen(v)
            starts[v] = ln
            for k in range(1, ln):
                interior.add(v + k)
            op = read(v); nxt = v + ln
            if op in RET:
                rets.append(nxt); break
            if op in SWITCH:                     # two formats (see vm_callgraph / native handlers)
                switches.append(v)
                r16 = lambda a: read(a) | (read(a + 1) << 8)
                if op == 0xD5:                   # indexed: <base i16><bound u16><target u16 x bound+1>
                    bound = r16(v + 3)
                    tgts = [r16(v + 5 + 2*i) for i in range(bound + 1)] if bound <= 64 else []
                else:                            # D9/E8 key-value: <count u16><(key,target) x count><default>
                    cnt = r16(v + 1)
                    tgts = ([r16(v + 3 + 4*i + 2) for i in range(cnt)] + [r16(v + 3 + 4*cnt)]) if cnt <= 64 else []
                for t in tgts:
                    if t not in starts:
                        work.append(t)
                break
            if op in CALL:                       # bytecode subroutine call -> follow target, then continue
                t = read(v + 1) | (read(v + 2) << 8)
                if t not in starts:
                    work.append(t)
                v = nxt; continue
            if op in CJMP_ABS:                   # conditional absolute jump: target + fall-through
                t = read(v + 1) | (read(v + 2) << 8)
                if t not in starts:
                    work.append(t)
                v = nxt; continue
            if op in JMP_ABS:
                t = read(v + 1) | (read(v + 2) << 8)
                if t not in starts:
                    work.append(t)
                break
            if op in BREL_UNCOND:
                work.append(nxt + s8(read(v + 1))); break
            if op in BREL_COND:
                work.append(nxt + s8(read(v + 1)))
            v = nxt                     # fall through
        # --auto: routines run back-to-back; seed the byte after each ret as a new entry
        if not work and a.auto:
            for r in rets:
                if r < a.auto and r not in starts and r not in interior:
                    work.append(r); break

    lo, hi = min(starts), max(k + starts[k] for k in starts)
    covered = sum(starts.values())
    print("== bytecode walk from $%02X:%04X ==" % (vbank, vaddr0))
    print("reached instructions : %d   code bytes: %d   span: $%04X-$%04X" % (len(starts), covered, lo, hi))
    print("conflicts (code/data): %d%s" % (len(conflicts), "  " + ",".join("$%04X" % c for c in sorted(conflicts)[:8]) if conflicts else ""))
    print("unresolved switches  : %d%s" % (len(switches), "  " + ",".join("$%04X" % s for s in sorted(switches)) if switches else ""))
    # data gaps: unreached bytes inside the span
    gaps, v = [], lo
    while v < hi:
        if v in starts:
            v += starts[v]
        else:
            g0 = v
            while v < hi and v not in starts:
                v += 1
            gaps.append((g0, v))
    if gaps:
        print("data gaps            : " + ", ".join("$%04X-$%04X(%d)" % (g0, g1, g1 - g0) for g0, g1 in gaps[:12]))

    if a.list:
        from symbols import Symbols
        S = Symbols(a.syms)
        print("\n== reachable disassembly ==")
        for v in sorted(starts):
            ln = starts[v]; raw = " ".join("%02X" % read(v + k) for k in range(ln))
            op = read(v)
            ann = ""
            if op == D.EXT_PREFIX:
                nm = D.EXT_NAMES.get(read(v + 1), "ext_%02X" % read(v + 1))
            else:
                nm = D.mnem(op)
                if ln >= 3:                               # 2-byte operand -> maybe a string/global
                    lbl = S.string(read(v + 1) | (read(v + 2) << 8))
                    if lbl:
                        ann = "   ; =%s" % lbl
            print("$%02X:%04X  %-11s %s%s" % (vbank, v, raw, nm, ann))


if __name__ == "__main__":
    main(sys.argv)
