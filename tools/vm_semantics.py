#!/usr/bin/env python3
"""
Fingerprint every ROTK2-SNES bytecode handler for semantic naming.

For each opcode's native handler it records: stack push/pop balance, which VM
registers it reads/writes, the ALU mnemonics it uses, operand size, and the shared
tail it jumps to. From these fingerprints the ~200 ALU/stack/store handlers can be
named in clusters, then compared opcode-by-opcode to the NES engine.

VM model (from the handlers): regA=$0A regB=$0C regC=$0E reg32=$12-15 ; frame=$04 ;
scratch ptr=$00 ; PC=$06:$08 ; operand stack via PHA/PLA.

    py -3 tools/vm_semantics.py "<rom>.sfc"            # fingerprint all
    py -3 tools/vm_semantics.py "<rom>.sfc" --op B0    # detail one
"""
import argparse, os, sys
SN = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "..", "..", "snes-decompiler", "tools"))
sys.path.insert(0, SN); sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mapper import cpu_to_file, strip_copier_header, LOROM
import w65c816, vm_opcodes as V

REG = {0x0A: "A", 0x0B: "A", 0x0C: "B", 0x0D: "B", 0x0E: "C", 0x0F: "C",
       0x10: "D", 0x11: "D", 0x12: "W", 0x13: "W", 0x14: "W", 0x15: "W",
       0x16: "W2", 0x17: "W2", 0x04: "FP", 0x05: "FP", 0x00: "P", 0x01: "P", 0x08: "PB"}
ALU = {"ADC", "SBC", "AND", "ORA", "EOR", "ASL", "LSR", "ROL", "ROR", "CMP", "DEC", "INC", "BIT"}
PUSH = {"PHA", "PHX", "PHY"}
POP = {"PLA", "PLX", "PLY"}
LOOP = {0x9A8F, 0x9A90}


def ro(a):
    if a >= 0x8000:
        f = cpu_to_file(LOROM, 0, a)
        return f if f < len(rom) else None
    return None


def fingerprint(handler, cap=120):
    seen = set(); st = [(handler, False, False)]
    reads, writes, alu, calls = set(), set(), set(), set()
    push = pop = 0
    while st:
        a, m8, x8 = st.pop()
        while True:
            if a in seen or a in LOOP:
                break
            f = ro(a)
            if f is None:
                break
            seen.add(a)
            ins, m8, x8 = w65c816.decode(rom, f, 0, a, m8, x8)
            mn, md, raw, tgt = ins["mnem"], ins["mode"], ins["raw"], ins["target"]
            if mn in PUSH: push += 1
            if mn in POP: pop += 1
            if mn in ALU: alu.add(mn)
            if md in ("dp", "dpx", "dpy") and len(raw) > 1:
                r = REG.get(raw[1])
                if r:
                    if mn in ("STA", "STX", "STY", "STZ"): writes.add(r)
                    elif mn in ("INC", "DEC", "ASL", "LSR", "ROL", "ROR", "TSB", "TRB"):
                        writes.add(r); reads.add(r)
                    else: reads.add(r)
            if mn in ("JSR", "JSL") and tgt:
                calls.add(tgt[1])
                if md in ("abs", "abl") and tgt[0] == 0 and tgt[1] not in V.FETCH_HELPERS:
                    st.append((tgt[1], m8, x8))
            if mn in ("JMP", "JML"):
                if tgt and tgt[1] in LOOP: break
                if tgt and tgt[0] == 0: st.append((tgt[1], m8, x8))
                break
            if mn in ("RTS", "RTL", "RTI"): break
            if mn in ("BPL", "BMI", "BVC", "BVS", "BCC", "BCS", "BNE", "BEQ") and tgt and tgt[0] == 0:
                st.append((tgt[1], m8, x8))
            a += ins["len"]
    return dict(push=push, pop=pop, reads=reads, writes=writes, alu=alu, calls=calls)


def main(argv):
    global rom
    ap = argparse.ArgumentParser(); ap.add_argument("rom"); ap.add_argument("--op", default=None)
    a = ap.parse_args(argv[1:])
    rom, _ = strip_copier_header(open(a.rom, "rb").read()); V.rom = rom
    base = cpu_to_file(LOROM, 0, 0xA0E6)
    prim = [rom[base + 2*i] | (rom[base + 2*i+1] << 8) for i in range(256)]
    default = 0xA082
    ops = [int(a.op, 16)] if a.op else [i for i in range(0x80, 0x100)]
    print("op  hdlr   opnd stk       reads        writes       alu")
    for i in ops:
        h = prim[i]
        if h == default:
            print("%02X  $%04X  (nop/invalid)" % (i, h)); continue
        sz, ctrl = V.operand_size(h)
        fp = fingerprint(h)
        stk = "+%d-%d" % (fp["push"], fp["pop"])
        print("%02X  $%04X  %d   %-7s r:%-10s w:%-10s %s%s" % (
            i, h, sz, stk, ",".join(sorted(fp["reads"])), ",".join(sorted(fp["writes"])),
            ",".join(sorted(fp["alu"])), "  CTRL" if ctrl else ""))


if __name__ == "__main__":
    main(sys.argv)
