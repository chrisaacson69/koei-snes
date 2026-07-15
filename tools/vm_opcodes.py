#!/usr/bin/env python3
"""
Classify the ROTK2-SNES bytecode VM opcodes by walking each handler.

Two dispatch tables (see docs/03):
  - PRIMARY  $A0E6 : the $9A8F main loop dispatches here (opcode in X). Low entries
                     are frame-local loads; a default handler ($9C25) covers the rest.
  - EXTENDED $A2FE : reached via $A2E6 (a prefix opcode fetches a 2nd byte).

For a disassembler we need each opcode's OPERAND SIZE = how many bytecode bytes it
consumes. The signals, read straight from the handler:
  - `INC $06`      : advance the bytecode PC  -> +1 operand byte
  - `LDA [$06]`    : read an operand byte/word from the stream
  - `STA/STX $06`  : overwrite the PC          -> control flow (jump/branch/call)
  - `JSR $8C1D`    : invoke a syscall
  - `JMP $A2E6`    : the extended-dispatch prefix

    py -3 tools/vm_opcodes.py "<rom>.sfc"            # both tables
    py -3 tools/vm_opcodes.py "<rom>.sfc" --toml     # emit a draft opcode toml
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
SN = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    "..", "..", "snes-decompiler", "tools"))
sys.path.insert(0, SN)
from mapper import cpu_to_file, strip_copier_header, LOROM
import w65c816
from profile import load as _load_profile

# All title-specific addresses come from the profile (games.toml). Override the
# active game by setting vm_opcodes.PROFILE before use, or via GAME env var.
PROFILE = _load_profile(os.environ.get("KOEI_SNES_GAME"))

RET = {"RTS", "RTL", "RTI", "STP"}
_il = PROFILE["interpreter_loop"]
LOOP = {_il, _il + 1, PROFILE["run_vm_entry"]}   # returning here = end of a handler
SYSCALL_DISPATCH = PROFILE["syscall_dispatch"]
EXT_PREFIX = PROFILE["ext_interpreter"]


def ro(a):
    if a >= 0x8000:
        f = cpu_to_file(LOROM, 0, a)
        return f if f < len(rom) else None
    return None


def classify(addr, cap=200):
    seen = set(); st = [(addr, False, False, 0)]
    sig = dict(inc06=0, rd06=0, wr06=0, syscall=False, prefix=False, ext=False,
               insns=0, calls=set())
    while st:
        a, m8, x8, depth = st.pop()
        while True:
            if a in seen or sig["insns"] >= cap:
                break
            if a in LOOP:
                break
            f = ro(a)
            if f is None:
                break
            seen.add(a)
            ins, m8, x8 = w65c816.decode(rom, f, 0, a, m8, x8)
            sig["insns"] += 1
            mn, md, raw = ins["mnem"], ins["mode"], ins["raw"]
            dpb = raw[1] if len(raw) > 1 else None
            if mn == "INC" and md == "dp" and dpb == 0x06:
                sig["inc06"] += 1
            if md in ("idl", "idly") and dpb == 0x06:
                sig["rd06"] += 1
            if mn in ("STA", "STX", "STY", "STZ") and md == "dp" and dpb == 0x06:
                sig["wr06"] += 1
            tgt = ins["target"]
            if mn in ("JSR", "JSL") and tgt:
                sig["calls"].add(tgt[1])
                if tgt[1] == SYSCALL_DISPATCH:
                    sig["syscall"] = True
                if tgt[1] == EXT_PREFIX:
                    sig["prefix"] = True
                if md in ("abs", "abl") and depth < 1 and tgt[0] == 0:
                    st.append((tgt[1], m8, x8, depth + 1))
            if mn in ("JMP", "JML") and tgt:
                if tgt[1] == EXT_PREFIX:
                    sig["prefix"] = True
                if tgt[1] not in LOOP and md in ("abs", "abl") and tgt[0] == 0:
                    st.append((tgt[1], m8, x8, depth))
                break
            if mn in ("BRA", "BRL") and tgt:
                if tgt[1] not in LOOP:
                    st.append((tgt[1], m8, x8, depth))
                break
            if mn in RET:
                break
            if mn in ("BPL", "BMI", "BVC", "BVS", "BCC", "BCS", "BNE", "BEQ") and tgt:
                if tgt[1] not in LOOP:
                    st.append((tgt[1], m8, x8, depth))
            nx = a + ins["len"]
            if nx > 0xFFFF:
                break
            a = nx
    return sig


def kind(sig):
    if sig["wr06"]:
        return "CONTROL"          # writes the PC: jump/branch/call
    if sig["syscall"]:
        return "SYSCALL"
    if sig["prefix"]:
        return "PREFIX->ext"
    if sig["rd06"] or sig["inc06"]:
        return "IMM(%d)" % max(sig["inc06"], sig["rd06"])
    return "reg/frame"


# Operand-fetch helpers, decoded from native code -> exact bytes each pulls from [$06].
# FETCH_HELPERS is an optional per-game OVERRIDE; the advance is otherwise auto-derived
# from the ROM by following the called sub (_sub_advance), so a game's fetch helpers do
# not have to be hand-listed -- the engine reads each title's own handlers.
FETCH_HELPERS = PROFILE.get("fetch_helpers", {})
_LOOP_RET = {_il, _il + 1}

_ADV_CACHE = {}


def _sub_advance(entry, cap=48):
    """Bytes a called sub pulls from the bytecode PC ($06): count INC $06 (and nested
    fetch subs) on its primary path -- fall-through, always-taken CLC branches, and
    unconditional jumps -- stopping at RTS/RTL. Auto-derives a fetch helper's operand
    width with no hand-list; robust to helpers that branch (sign-extend, frame-resolve)."""
    if entry in _ADV_CACHE:
        return _ADV_CACHE[entry]
    _ADV_CACHE[entry] = 0  # cycle guard
    a, m8, x8, total, just = entry, False, False, 0, False
    for _ in range(cap):
        f = _ro(a)
        if f is None:
            break
        ins, m8, x8 = w65c816.decode(rom, f, 0, a, m8, x8)
        mn, md, raw, tgt = ins["mnem"], ins["mode"], ins["raw"], ins["target"]
        now = False
        if mn in ("JSR", "JSL") and tgt and tgt[0] == 0:
            s = _sub_advance(tgt[1], cap)
            if s:
                total += s; now = True
        if mn == "INC" and md == "dp" and len(raw) > 1 and raw[1] == 0x06:
            total += 1; now = True
        if mn in ("BCC", "BCS") and just and tgt and tgt[0] == 0:
            a = tgt[1]; just = False; continue
        if mn in ("JMP", "JML"):
            if tgt and tgt[1] in _LOOP_RET:
                break
            if tgt and tgt[0] == 0:
                a = tgt[1]; continue
            break
        if mn in ("RTS", "RTL", "RTI"):
            break
        just = now; a += ins["len"]
    _ADV_CACHE[entry] = total
    return total


def operand_size(handler, cap=80):
    """Exact operand bytes: walk the handler's PRIMARY path (fall-through + always-
    taken unconditional jumps), summing fetch-helper pulls + direct INC $06, until the
    loop return. Also report control (writes $06). Returns (bytes, is_control)."""
    a, m8, x8 = handler, False, False
    total, control, seen, just_fetched = 0, False, set(), False
    for _ in range(cap):
        if a in seen:
            break
        seen.add(a)
        f = _ro(a)
        if f is None:
            break
        ins, m8, x8 = w65c816.decode(rom, f, 0, a, m8, x8)
        mn, md, raw = ins["mnem"], ins["mode"], ins["raw"]
        tgt = ins["target"]
        fetched_now = False
        if mn in ("JSR", "JSL") and tgt and tgt[0] == 0:
            adv = FETCH_HELPERS[tgt[1]] if tgt[1] in FETCH_HELPERS else _sub_advance(tgt[1])
            if adv:
                total += adv; fetched_now = True
        if mn == "INC" and md == "dp" and len(raw) > 1 and raw[1] == 0x06:
            total += 1
        if mn in ("STA", "STX") and md == "dp" and len(raw) > 1 and raw[1] == 0x06:
            control = True
        # a BCC/BCS right after a fetch helper is always taken (helpers CLC): follow it
        if mn in ("BCC", "BCS") and just_fetched and tgt and tgt[0] == 0:
            a = tgt[1]; just_fetched = False; continue
        if mn in ("JMP", "JML"):
            if tgt and tgt[1] in _LOOP_RET:
                break
            if tgt and tgt[0] == 0:            # follow unconditional jump
                a = tgt[1]; continue
            break
        if mn in ("RTS", "RTL", "RTI"):
            break
        just_fetched = fetched_now
        a += ins["len"]
    return total, control


def _ro(a):
    if a >= 0x8000:
        f = cpu_to_file(LOROM, 0, a)
        return f if f < len(rom) else None
    return None


def dump_table(name, base, n):
    tbl = cpu_to_file(LOROM, 0, base)
    ent = [rom[tbl + 2 * i] | (rom[tbl + 2 * i + 1] << 8) for i in range(n)]
    print("==== %s table @ $%04X (%d entries) ====" % (name, base, n))
    print("op  handler  kind        operand  insns  notes")
    rows = []
    for i, h in enumerate(ent):
        if h == 0 or not (0x8000 <= h <= 0xFFFF):
            print("%02X  $%04X   (null/end)" % (i, h)); rows.append((i, h, "null", 0)); continue
        s = classify(h); k = kind(s)
        opnd = max(s["inc06"], s["rd06"]) if ("IMM" in k) else (2 if k == "CONTROL" else 0)
        note = []
        if s["syscall"]: note.append("syscall")
        if s["prefix"]: note.append("->A2E6 ext")
        print("%02X  $%04X   %-11s %-7s %-5d  %s" % (i, h, k, opnd, s["insns"], " ".join(note)))
        rows.append((i, h, k, opnd))
    print()
    return rows


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("rom"); ap.add_argument("--toml", action="store_true")
    args = ap.parse_args()
    rom, _ = strip_copier_header(open(args.rom, "rb").read())
    dump_table("PRIMARY", PROFILE["primary_table"], 256)
    dump_table("EXTENDED", PROFILE["extended_table"], 48)
