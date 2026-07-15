#!/usr/bin/env python3
"""
ROTK2-SNES bytecode disassembler (full 256-opcode primary table + $B7 extended).

The VM (docs/05, corrected in docs/07): main loop $9A8F dispatches the PRIMARY table
$A0E6 (256 entries, $A0E6..$A2E5). Opcode $B7 is the extended prefix -> $A2E6 fetches
one more byte and dispatches the EXTENDED table $A2FE (32-bit math). Per-opcode
operand sizes are derived at runtime from each handler (via vm_opcodes.classify), so
the map stays grounded in the ROM.

Register/frame model: $0A=regA $0C=regB $0E=regC $12-15=reg32; $04=frame ptr; $06=PC.

    py -3 tools/vm_disasm.py "<rom>.sfc" --start 01:8008 --base 7E:2008 -n 40
"""
import argparse, os, sys
SN = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "..", "..", "snes-decompiler", "tools"))
sys.path.insert(0, SN); sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mapper import cpu_to_file, strip_copier_header, LOROM
import vm_opcodes as V

PRIMARY = V.PROFILE["primary_table"]
EXTENDED = V.PROFILE["extended_table"]
EXT_PREFIX = V.PROFILE["extended_prefix"]


def opsize(handler):
    n, _ctrl = V.operand_size(handler)   # exact: from fetch-helper pulls + INC $06
    return n


# Per-opcode names, each decoded from its native handler (docs/07 recon #11-12).
# g=global/abs pointer, L=frame-local pointer; .b/.w = byte/word; # = immediate.
NAMES = {
    # load/store/push matrix (odd=1-byte operand, even=2-byte)
    0x81: "ldA    g8", 0x82: "ldA    g16", 0x83: "ldC    g8", 0x84: "ldC    g16",
    0x85: "stA    g8", 0x86: "stA    g16", 0x87: "push   g8", 0x88: "push   g16",
    0x89: "ldA    #i8", 0x8A: "ldA    #i16", 0x8B: "ldC    #i8", 0x8C: "ldC    #i16",
    0x8D: "push   #i8", 0x8E: "push   #i16", 0x8F: "addA   #i8", 0x90: "addA   #i16",
    0xA0: "ldA.b  L", 0xA1: "ldC.b  L", 0xA2: "stA.b  L", 0xA3: "push.b L",
    0xA4: "ldA.w  L", 0xA5: "ldA.b  L'", 0xA6: "ldC.w  L", 0xA7: "ldC.b  L",
    0xA8: "stA.w  L", 0xA9: "stA.b  L", 0xAA: "push.w L", 0xAB: "push.b L",
    0xAC: "call.n", 0xAD: "blkcopy", 0xAE: "sp_adj #i8", 0xAF: "sp_adj #i16",
    # stack/reg + arithmetic
    0xB0: "ldA.mem", 0xB1: "stA.w[pop]", 0xB3: "pushA", 0xB4: "popC",
    0xB5: "mul16", 0xB6: "sdivmod", 0xB8: "udivmod", 0xB9: "sdiv", 0xBA: "udiv",
    0xBB: "add", 0xBC: "sub", 0xBD: "mul", 0xBE: "shr", 0xBF: "sar",
    # compares (all -> regA = 0/1)
    0xC0: "eq", 0xC1: "ne", 0xC2: "ge.s", 0xC3: "gt.s", 0xC4: "le.s", 0xC5: "lt.s",
    0xC6: "ge.u", 0xC7: "gt.u", 0xC8: "le.u", 0xC9: "lt.u",
    0xCA: "lnot", 0xCB: "neg", 0xCC: "not", 0xCD: "swapAC", 0xCF: "ret",
    # unary + control
    0xD0: "inc", 0xD1: "dec", 0xD2: "shl", 0xD3: "ldA.b[p]", 0xD4: "stA.b[pop]",
    0xD5: "switch", 0xD6: "jmp", 0xD7: "skipnz", 0xD8: "brz",
    0xD9: "switch2", 0xDA: "and", 0xDB: "or", 0xDC: "xor", 0xDD: "call.ind",
    0xDE: "ldA    g16'", 0xDF: "ldC    g16'",
    0xE0: "mul32  #", 0xE1: "sdiv32 #", 0xE2: "udiv32 #",
    0xE3: "brel", 0xE4: "brnz", 0xE5: "brz", 0xE6: "brel'", 0xE7: "brnz'", 0xE8: "switch3",
    0xE9: "hostcall", 0xEA: "call.ind2",
}
CALL_OPS = {0xAC, 0xE9}                       # 2-byte operand[0:2] is a native address
JMP_OPS = {0xD6}                              # 2-byte operand is an absolute VM target
REL_OPS = {0xE3, 0xE5, 0xE6, 0xD8}            # 1-byte signed PC-relative offset

# Extended table $A2FE (via $B7), the 32-bit arithmetic set. reg32 = W ($12-15).
EXT_NAMES = {
    0x01: "mul32", 0x02: "smul32", 0x03: "add32", 0x04: "sub32", 0x05: "neg32",
    0x06: "eq32", 0x07: "ne32", 0x08: "lt.s32", 0x09: "le.s32", 0x0A: "gt.s32", 0x0B: "ge.s32",
    0x0C: "ldW    g16", 0x0D: "ldW2   g16", 0x0E: "stW    g16", 0x0F: "push32 g16",
    0x10: "ldW.b  L", 0x11: "ldW2.b L", 0x12: "stW    L", 0x13: "push32 L",
    0x14: "stW.p", 0x15: "pop32", 0x16: "stW.pA", 0x17: "pop32'",
    0x18: "ldW    #i", 0x19: "ldW2   #i", 0x1A: "swap32", 0x1B: "add32r", 0x1C: "add32c",
    0x1D: "cmp.s32", 0x1E: "smul32'", 0x1F: "neg32'", 0x20: "abs32",
    0x21: "xor32", 0x22: "and32", 0x23: "or32", 0x24: "xor32'",
    0x25: "sign32", 0x26: "clrW2", 0x27: "nop", 0x28: "cmp32", 0x29: "geu.32", 0x2A: "ltu.32",
    0x2B: "leu.32", 0x2C: "gtu.32", 0x2D: "add32'", 0x2E: "div32", 0x2F: "smul32''",
}


def mnem(op):
    if op <= 0x0F: return "load    fA[%X]" % op
    if op <= 0x1F: return "load    fC[%X]" % (op & 0xF)
    if op <= 0x2F: return "store   fA[%X]" % (op & 0xF)
    if op <= 0x3F: return "push    f[%X]" % (op & 0xF)
    # $40-$7F: four distinct nibble-immediate ops (verified: handlers $A4DE/$A4EC/$A4F1/$A502;
    # $40=STY regA, $50=STY regC, $60=push, $70=fetch+add). Low nibble is the immediate.
    if op <= 0x4F: return "ldA    #$%X" % (op & 0xF)
    if op <= 0x5F: return "ldC    #$%X" % (op & 0xF)
    if op <= 0x6F: return "push   #$%X" % (op & 0xF)
    if op <= 0x7F: return "addA   #$%X" % (op & 0xF)
    return NAMES.get(op, "op_%02X" % op)


def main(argv):
    from symbols import Symbols
    ap = argparse.ArgumentParser()
    ap.add_argument("rom"); ap.add_argument("--start", required=True)
    ap.add_argument("--base", default=None); ap.add_argument("-n", "--count", type=int, default=40)
    ap.add_argument("--syms", default=None, help="title data dir (strings.toml + enums.py) for name annotations")
    a = ap.parse_args(argv[1:])
    S = Symbols(a.syms)
    rom, _ = strip_copier_header(open(a.rom, "rb").read()); V.rom = rom
    pbase = cpu_to_file(LOROM, 0, PRIMARY); ebase = cpu_to_file(LOROM, 0, EXTENDED)
    prim = [rom[pbase + 2*i] | (rom[pbase + 2*i+1] << 8) for i in range(256)]
    ext = [rom[ebase + 2*i] | (rom[ebase + 2*i+1] << 8) for i in range(48)]
    psz = [opsize(h) for h in prim]

    b, o = a.start.split(":"); off = cpu_to_file(LOROM, int(b, 16), int(o, 16))
    va = None
    if a.base:
        vb, v = a.base.split(":"); va = (int(vb, 16), int(v, 16))
    for _ in range(a.count):
        op = rom[off]
        loc = ("$%02X:%04X" % va) if va else "+%05X" % off
        if op == EXT_PREFIX:
            eop = rom[off + 1]; esz = opsize(ext[eop]); operand = rom[off + 2:off + 2 + esz]
            en = EXT_NAMES.get(eop, "ext_%02X" % eop)
            ops = ("  " + " ".join("%02X" % x for x in operand)) if esz else ""
            txt = en + ops
            ln = 2 + esz
        else:
            sz = psz[op]; operand = rom[off + 1:off + 1 + sz]
            ops = ("  " + " ".join("%02X" % x for x in operand)) if sz else ""
            if sz >= 2 and op in JMP_OPS:
                ops += "   ; -> $%04X" % (operand[0] | (operand[1] << 8))
            elif sz >= 2 and op in CALL_OPS:
                ops += "   ; call $%04X" % (operand[0] | (operand[1] << 8))
            elif sz >= 1 and op in REL_OPS and va:
                d = operand[0] - 256 if operand[0] & 0x80 else operand[0]
                ops += "   ; -> $%04X" % ((va[1] + (1 + sz) + d) & 0xFFFF)
            # symbol annotation: a 2-byte operand that matches a known string/global
            if sz >= 2 and op not in JMP_OPS and op not in CALL_OPS:
                lbl = S.string(operand[0] | (operand[1] << 8))
                if lbl:
                    ops += "   ; =%s" % lbl
            txt = mnem(op) + ops
            ln = 1 + sz
        raw = " ".join("%02X" % rom[off + k] for k in range(ln))
        print("%s  %-11s %s" % (loc, raw, txt))
        off += ln
        if va:
            va = (va[0], (va[1] + ln) & 0xFFFF)


if __name__ == "__main__":
    main(sys.argv)
