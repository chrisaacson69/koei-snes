#!/usr/bin/env python3
"""
Build the KOEI SNES bytecode call-graph and rank routines leaves-first.

The unified (segmented) memory model means the whole module is one address space --
one call-graph, no cross-bank resolution. Call methods (all four):
  direct   : hostcall $E9 (+1-byte arg), call.n $AC   -> operand[0:2] = callee entry
  indirect : call.ind $DD, call.ind2 $EA              -> target = regA (unresolved)

From a seed entry it discovers routines (a routine = entry .. its ret(s), following
internal branches/jmp/brel), records caller->callee edges, and reports: leaves (no
outgoing direct calls -> name these first, bottom-up), indirect-call sites, external
(non-bytecode) targets, and a leaves-first order for naming.

    py -3 tools/vm_callgraph.py <rom> --start 01:8008 --base 7E:2008 [--leaves]
"""
import argparse, os, sys
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..", "..", "snes-decompiler", "tools")))
from mapper import cpu_to_file, strip_copier_header, LOROM
import vm_disasm as D
import vm_opcodes as V

RET = {0xCF}; SWITCH = {0xD5, 0xD9, 0xE8}
JMP_ABS = {0xD6}; CJMP_ABS = {0xD7}         # skipnz: if regA!=0 JMP <abs16>, else fall through
BREL_U = {0xE3, 0xE6}; BREL_C = {0xD8, 0xE5, 0xE4, 0xE7}
DIRECT_CALL = {0xE9, 0xAC}; INDIRECT_CALL = {0xDD, 0xEA}


def s8(b):
    return b - 256 if b & 0x80 else b


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("rom"); ap.add_argument("--start", required=True); ap.add_argument("--base", required=True)
    ap.add_argument("--leaves", action="store_true"); ap.add_argument("--syms", default=None)
    ap.add_argument("--dump-leaves", dest="dump_leaves", action="store_true")
    ap.add_argument("--unnamed", action="store_true", help="report named/unnamed + naming frontier")
    ap.add_argument("--dump-frontier", dest="dump_frontier", action="store_true", help="dump frontier routine bodies")
    ap.add_argument("--tree", action="store_true", help="print top-down call forest (for the walk-down)")
    ap.add_argument("--scan", type=lambda s: int(s, 16), default=None,
                    help="also seed from every direct-call target found up to this END addr")
    a = ap.parse_args(argv[1:])
    rom, _ = strip_copier_header(open(a.rom, "rb").read()); V.rom = rom
    pbase = cpu_to_file(LOROM, 0, D.PRIMARY); ebase = cpu_to_file(LOROM, 0, D.EXTENDED)
    prim = [rom[pbase + 2*i] | (rom[pbase + 2*i+1] << 8) for i in range(256)]
    ext = [rom[ebase + 2*i] | (rom[ebase + 2*i+1] << 8) for i in range(48)]
    psz = [D.opsize(h) for h in prim]
    sb, so = a.start.split(":"); start_off = cpu_to_file(LOROM, int(sb, 16), int(so, 16))
    vb, v0 = a.base.split(":"); vbank, vaddr0 = int(vb, 16), int(v0, 16)

    def read(v):
        return rom[start_off + (v - vaddr0)]

    # Per-routine call convention (profile-driven; defaults = rot3k2). A call target points
    # at a native trampoline whose signature is SIG; the bytecode body begins BODY_OFF bytes in.
    SIG = V.PROFILE.get("routine_sig", [0x20, 0xE6])
    BODY_OFF = V.PROFILE.get("routine_body_offset", 0)

    def is_entry(t):
        try:
            return all(read(t + i) == SIG[i] for i in range(len(SIG)))
        except Exception:
            return False

    def declen(v):
        op = read(v)
        if op == D.EXT_PREFIX:
            eo = read(v + 1)
            return 2 + (D.opsize(ext[eo]) if eo < len(ext) else 0)
        return 1 + psz[op]

    def r16(a):
        return read(a) | (read(a + 1) << 8)

    def switch_targets(v):
        # Two inline-table formats (from the native handlers):
        #  switch  $D5: indexed   <base:i16><bound:u16><target:u16 x (bound+1)>
        #  switch2 $D9 / switch3 $E8: key-value <count:u16><(key:u16,target:u16) x count><default:u16>
        op = read(v)
        if op == 0xD5:
            bound = r16(v + 3)
            if bound > 64:
                return []
            return [r16(v + 5 + 2*i) for i in range(bound + 1)]
        count = r16(v + 1)
        if count > 64:
            return []
        tgts = [r16(v + 3 + 4*i + 2) for i in range(count)]   # target of each (key,target) pair
        tgts.append(r16(v + 3 + 4*count))                     # trailing default target
        return tgts

    def walk_routine(entry):
        starts, interior, calls, indirect, conflict, order = set(), set(), set(), 0, 0, []
        work = [entry + BODY_OFF]      # skip the native trampoline; decode from the bytecode body
        while work:
            v = work.pop()
            while True:
                if v in starts:
                    break
                if v in interior:
                    conflict += 1; break
                try:
                    ln = declen(v)
                except Exception:
                    conflict += 1; break
                starts.add(v); order.append(v)
                for k in range(1, ln):
                    interior.add(v + k)
                op, nxt = read(v), v + ln
                if op in SWITCH:                     # inline jump table -> case blocks are local
                    for t in switch_targets(v):
                        work.append(t)
                    break
                if op in RET:
                    break
                if op in DIRECT_CALL:
                    calls.add(read(v + 1) | (read(v + 2) << 8)); v = nxt; continue
                if op in INDIRECT_CALL:
                    indirect += 1; v = nxt; continue
                if op in CJMP_ABS:                   # conditional absolute jump: target + fall-through
                    work.append(read(v + 1) | (read(v + 2) << 8)); v = nxt; continue
                if op in JMP_ABS:
                    work.append(read(v + 1) | (read(v + 2) << 8)); break
                if op in BREL_U:
                    work.append(nxt + s8(read(v + 1))); break
                if op in BREL_C:
                    work.append(nxt + s8(read(v + 1)))
                v = nxt
        return dict(size=len(starts), calls=calls, indirect=indirect, conflict=conflict, order=order)

    seeds = [vaddr0]
    if a.scan:
        if BODY_OFF:                 # trampolined module: the native stubs make a linear bytecode
            v = vaddr0               # scan drift, so seed from every trampoline SIGNATURE directly
            while v < a.scan:        # (walk_routine validates each; junk matches get rejected).
                if is_entry(v):
                    seeds.append(v); v += BODY_OFF
                else:
                    v += 1
        else:                        # scan the code region for call targets to seed discovery.
            v = vaddr0               # SCAN seeds must carry the prologue (kills linear-drift
            while v < a.scan:        # false entries); real call edges found while walking are
                op = read(v)         # trusted below even without it (some routines, e.g. the
                if op in DIRECT_CALL:  # HW-math $6B45, are called but use a different prologue).
                    t = read(v + 1) | (read(v + 2) << 8)
                    if vaddr0 <= t < a.scan and is_entry(t):
                        seeds.append(t)
                v += declen(v)
    routines, work, external = {}, list(seeds), set()
    while work:
        e = work.pop()
        if e in routines or e in external:
            continue
        # entries must lie within this module's code region (a call target past --scan END
        # is reading the next module's ROM -> false entry, e.g. root reaching into settei).
        if a.scan and not (vaddr0 <= e < a.scan):
            external.add(e); continue
        # prologue ($20 $E6) marks a true entry; a non-prologue target is a mid-routine
        # point from data mis-decode (esp. the data-heavy HW-math routine). Excluded from
        # the routine set; if it is genuinely called it can still be named in routines.toml
        # (annotation), and the frontier logic below does not block on non-routine callees.
        if e != vaddr0 and not is_entry(e):
            external.add(e); continue
        r = walk_routine(e)
        # a "clean" bytecode routine has no immediate conflict and some size
        if r["size"] == 0 or r["conflict"] > r["size"] // 4:
            external.add(e); continue
        routines[e] = r
        for c in r["calls"]:
            if c not in routines:
                work.append(c)

    def compact_body(e, S):
        parts = []
        for v in sorted(routines[e]["order"]):
            op = read(v)
            if op == D.EXT_PREFIX:
                parts.append(D.EXT_NAMES.get(read(v + 1), "ext%02X" % read(v + 1))); continue
            m = D.mnem(op).split()[0]
            ln = declen(v)
            if op in DIRECT_CALL:
                t = read(v + 1) | (read(v + 2) << 8); m = ">" + (S.string(t) or "$%04X" % t)
            elif op in INDIRECT_CALL:
                m = ">*regA"
            elif ln == 3:
                val = read(v + 1) | (read(v + 2) << 8); lbl = S.string(val)
                m += "=" + (lbl if lbl else "$%04X" % val)
            elif ln == 2:
                m += " $%02X" % read(v + 1)
            parts.append(m)
        return "  ".join(parts)

    if a.tree:
        from symbols import Symbols
        S = Symbols(a.syms)
        called = set()
        for r in routines.values():
            called |= {c for c in r["calls"] if c in routines}
        tops = [vaddr0] + sorted(e for e in routines if e not in called and e != vaddr0)
        nm = lambda e: S.string(e) or "$%04X" % e
        seen = set()

        def pr(e, depth):
            tag = nm(e)
            if e not in routines:
                print("  " * depth + "> " + tag + " [ext]"); return
            if e in seen:
                print("  " * depth + "> " + tag + " ..."); return
            seen.add(e)
            print("  " * depth + ("" if depth == 0 else "> ") + tag)
            for c in sorted(routines[e]["calls"]):
                pr(c, depth + 1)
        print("== top-down call forest (%d top-level entries) ==" % len(tops))
        for t in tops:
            pr(t, 0)
        return
    if a.unnamed or a.dump_frontier:
        from symbols import Symbols
        S = Symbols(a.syms)
        named = [e for e in routines if S.string(e)]
        unn = [e for e in routines if not S.string(e)]
        # naming frontier: unnamed routines whose every callee THAT IS A ROUTINE is named.
        # A callee not in `routines` (native, data-mis-decode, or a separately-named blob) is
        # not a nameable routine, so it must not block the frontier -- only real routines do.
        def callee_ok(c):
            return (c not in routines) or bool(S.string(c))
        frontier = [e for e in unn if all(callee_ok(c) for c in routines[e]["calls"])]
        if a.dump_frontier:
            print("== frontier bodies (%d; >name = call to named routine) ==" % len(frontier))
            for e in sorted(frontier):
                print("$%04X: %s" % (e, compact_body(e, S)))
            return
        print("== naming status (segment @ $%02X:%04X) ==" % (vbank, vaddr0))
        print("routines: %d   named: %d   unnamed: %d" % (len(routines), len(named), len(unn)))
        print("naming frontier (unnamed, all callees named): %d" % len(frontier))
        print("\nfrontier (name these next; size, #calls):")
        for e in sorted(frontier)[:40]:
            r = routines[e]
            print("  $%04X  (%d insns, %d calls%s)" % (e, r["size"], len(r["calls"]),
                  ", indirect" if r["indirect"] else ""))
        return
    leaves = [e for e, r in routines.items() if not r["calls"]]
    with_ind = [e for e, r in routines.items() if r["indirect"]]
    print("== bytecode call-graph from $%02X:%04X ==" % (vbank, vaddr0))
    print("routines discovered  : %d" % len(routines))
    print("leaves (no direct call): %d   <- name these first (bottom-up)" % len(leaves))
    print("routines w/ indirect : %d   (call.ind targets = regA, unresolved)" % len(with_ind))
    print("external call targets: %d   (native/data, not bytecode)" % len(external))
    edges = sum(len(r["calls"]) for r in routines.values())
    print("direct call edges    : %d" % edges)
    if a.leaves:
        print("\nleaf routines (entry: size):")
        for e in sorted(leaves):
            print("  $%02X:%04X  (%d insns, %s)" % (vbank, e, routines[e]["size"],
                  "indirect" if routines[e]["indirect"] else "pure leaf"))
    if a.dump_leaves:
        from symbols import Symbols
        S = Symbols(a.syms)
        print("\n== leaf bodies (compact; %d leaves) ==" % len(leaves))
        for e in sorted(leaves):
            parts = []
            for v in sorted(routines[e]["order"]):
                op = read(v)
                if op == D.EXT_PREFIX:
                    parts.append(D.EXT_NAMES.get(read(v + 1), "ext%02X" % read(v + 1))); continue
                m = D.mnem(op).split()[0]
                ln = declen(v)
                if ln == 3:
                    val = read(v + 1) | (read(v + 2) << 8)
                    lbl = S.string(val)
                    m += "=" + (lbl if lbl else "$%04X" % val)
                elif ln == 2:
                    m += " $%02X" % read(v + 1)
                parts.append(m)
            print("$%04X: %s" % (e, "  ".join(parts)))


if __name__ == "__main__":
    main(sys.argv)
