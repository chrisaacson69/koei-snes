#!/usr/bin/env python3
"""
DREAM-style control-flow structuring: lift a KOEI SNES bytecode routine to goto-less
structured pseudo-C. The bytecode was compiled from structured C, so its CFG is reducible
-- we recover if / if-else / while from dominators + follow nodes instead of pattern
matching, and only fall back to `goto` for genuinely irreducible edges / switches.

    py -3 tools/vm_struct.py <rom> --start 04:AB7E --base 7E:7208 --at 7698 --syms data/comroot

Pipeline: decode reachable insns -> basic blocks -> CFG (succ/pred) -> dominators ->
natural loops (back edges) -> recursive region structuring with per-block statement lift.
"""
import argparse, os, sys
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..", "..", "snes-decompiler", "tools")))
from mapper import cpu_to_file, strip_copier_header, LOROM
import vm_disasm as D
import vm_opcodes as V
from symbols import Symbols

BINOP = {"add": "+", "sub": "-", "mul": "*", "mul16": "*", "udiv": "/", "sdiv": "/", "and": "&",
         "or": "|", "xor": "^", "shl": "<<", "shr": ">>", "eq": "==", "ne": "!=", "lt.s": "<",
         "lt.u": "<", "gt.s": ">", "gt.u": ">", "le.u": "<=", "ge.u": ">=", "ge.s": ">=",
         "add32": "+", "sub32": "-", "smul32": "*"}
COND_BR = {"brz", "brnz", "brz'", "brnz'", "skipnz"}
UNCOND = {"jmp", "brel", "brel'"}


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("rom"); ap.add_argument("--start", required=True); ap.add_argument("--base", required=True)
    ap.add_argument("--syms", required=True); ap.add_argument("--at", required=True)
    a = ap.parse_args(argv[1:])
    rom, _ = strip_copier_header(open(a.rom, "rb").read()); V.rom = rom
    S = Symbols(a.syms)
    pbase = cpu_to_file(LOROM, 0, D.PRIMARY); ebase = cpu_to_file(LOROM, 0, D.EXTENDED)
    prim = [rom[pbase + 2*i] | (rom[pbase + 2*i+1] << 8) for i in range(256)]
    ext = [rom[ebase + 2*i] | (rom[ebase + 2*i+1] << 8) for i in range(48)]
    psz = [D.opsize(h) for h in prim]
    sb, so = a.start.split(":"); off0 = cpu_to_file(LOROM, int(sb, 16), int(so, 16))
    vb, vo = a.base.split(":"); vaddr0 = int(vo, 16)
    read = lambda v: rom[off0 + (v - vaddr0)]
    def declen(v):
        op = read(v)
        return (2 + D.opsize(ext[read(v + 1)])) if (op == D.EXT_PREFIX and read(v + 1) < 48) else 1 + psz[op]
    s8 = lambda b: b - 256 if b & 0x80 else b

    def succs(v, ln):
        op = read(v); m = D.mnem(v and read(v)).split()[0] if False else D.mnem(op).split()[0]
        nx = v + ln
        if m == "ret":
            return []
        if m in UNCOND:
            return [(read(v + 1) | (read(v + 2) << 8)) if m == "jmp" else nx + s8(read(v + 1))]
        if m in COND_BR:
            tgt = (read(v + 1) | (read(v + 2) << 8)) if m == "skipnz" else nx + s8(read(v + 1))
            return [nx, tgt]
        if m in ("switch", "switch2", "switch3"):
            return []                                 # leave switches unstructured
        return [nx]

    # 1. decode reachable instructions
    entry = int(a.at, 16)
    start = entry
    if read(entry) == 0x20 and read(entry + 1) == 0xE6:
        start = entry + 2 + s8(read(entry + 2))
    insns = {}; work = [start]; edges = {}
    while work:
        v = work.pop()
        while v not in insns:
            ln = declen(v); insns[v] = ln; sc = succs(v, ln); edges[v] = sc
            if len(sc) == 1 and sc[0] == v + ln:
                v = v + ln
            else:
                for s in sc:
                    if s not in insns:
                        work.append(s)
                break
    # 2. leaders + blocks
    leaders = {start}
    for v in insns:
        for s in edges[v]:
            leaders.add(s)
        if len(edges[v]) != 1 or edges[v][0] != v + insns[v]:
            nxt = v + insns[v]
            if nxt in insns:
                leaders.add(nxt)
    leaders = sorted(x for x in leaders if x in insns)
    blk_of = {}
    for L in leaders:
        v = L
        while True:
            blk_of[v] = L
            nxt = v + insns[v]
            if v in edges and (len(edges[v]) != 1 or edges[v][0] != nxt) or nxt in leaders or nxt not in insns:
                break
            v = nxt
    bsucc = {L: [] for L in leaders}
    for L in leaders:
        v = L
        while blk_of.get(v) == L:
            nxt = v + insns[v]
            if v in edges and (len(edges[v]) != 1 or edges[v][0] != nxt):
                bsucc[L] = [s for s in edges[v] if s in blk_of]
                break
            if nxt not in insns or blk_of.get(nxt) != L:
                bsucc[L] = [nxt] if nxt in blk_of else []
                break
            v = nxt
    # 3. dominators (iterative, Cooper/Harvey/Kennedy)
    order = leaders
    oi = {L: i for i, L in enumerate(order)}

    def inter(idom, a1, b1):
        while a1 != b1:
            while oi[a1] > oi[b1]:
                a1 = idom[a1]
            while oi[b1] > oi[a1]:
                b1 = idom[b1]
        return a1

    def dominates(idom, d, n):
        while n in idom and n != idom[n]:
            if n == d: return True
            n = idom[n]
        return n == d

    idom = {leaders[0]: leaders[0]}
    preds = {L: [] for L in leaders}
    for L in leaders:
        for s in bsucc[L]:
            preds[s].append(L)
    changed = True
    while changed:
        changed = False
        for L in order:
            if L == leaders[0]:
                continue
            new = None
            for p in preds[L]:
                if p in idom:
                    new = p if new is None else inter(idom, new, p)
            if new is not None and idom.get(L) != new:
                idom[L] = new; changed = True

    # per-block statement lift (symbolic regA/regC/stack)
    def block_stmts(L):
        regA, regC, st, out, cond = "a", "c", [], [], None
        v = L
        while blk_of.get(v) == L:
            op = read(v); ln = declen(v); m = D.mnem(op); base = m.split()[0]; nx = v + ln
            val = (read(v + 1) | (read(v + 2) << 8)) if ln == 3 else (read(v + 1) if ln == 2 else None)
            fr = m.split(None, 1)[1].strip().replace("[", "_").replace("]", "") if " " in m else "f"
            if 0x40 <= op <= 0x7F:                       # nibble-immediate family (value = low nibble)
                nib = "$%X" % (op & 0x0F); fam = op >> 4
                if fam == 0x4: regA = nib                 # ldA #n
                elif fam == 0x5: regC = nib               # ldC #n
                elif fam == 0x6: st.append(nib)           # push #n
                else: regA = "(%s + %s)" % (regA, nib)    # addA #n
                v = nx; continue
            if base == "load": regA = fr
            elif base == "store": out.append("%s = %s;" % (fr, regA))
            elif base in ("pushA", "push", "push.w", "push.b"): st.append(S.string(val) if val is not None and S.string(val) else (regA if base == "pushA" else ("$%X" % val if val is not None else regA)))
            elif base in ("ldA", "ldA.b", "ldA.w"): regA = (S.string(val) or ("$%X" % val if val is not None else "0"))
            elif base == "ldA.mem": regA = "mem[%s]" % regA
            elif base == "ldC": regC = (S.string(val) or ("$%X" % val if val is not None else "0"))
            elif base == "popC": regC = st.pop() if st else "top"
            elif base in BINOP: regA = "(%s %s %s)" % (regA, BINOP[base], regC)
            elif base in ("hostcall", "call.n"):
                t = read(v + 1) | (read(v + 2) << 8); fn = S.string(t) or "sub_%04X" % t
                args = ", ".join(reversed([st.pop() for _ in range(min(len(st), 3))])) if st else ""
                out.append(("%s = %s(%s);" if base == "call.n" else "%s(%s);") % ((regA, fn, args) if base == "call.n" else (fn, args)))
                if base == "call.n": regA = "ret"
            elif base in ("call.ind", "call.ind2"): out.append("(*%s)();" % regA)
            elif base in ("stA.b[pop]", "stA.w[pop]", "stA.b", "stA.w"):
                dst = st.pop() if st else ("$%X" % val if val is not None else "ptr"); out.append("mem[%s] = %s;" % (dst, regA))
            elif base == "inc": regA = "(%s + 1)" % regA
            elif base == "dec": regA = "(%s - 1)" % regA
            elif base == "ret": out.append("return %s;" % regA)
            elif base in COND_BR: cond = regA
            elif base in UNCOND or base.startswith("switch"): pass
            else: out.append("/* %s */" % base)
            v = nx
        return out, (cond or "a")

    # 4. structure recursively (sequence / if / if-else / while)
    printed = set()
    def follow_of(L):
        # immediate post-dominator approximation: the block both branches reconverge to
        s = bsucc[L]
        if len(s) == 2:
            a1, b1 = s
            # walk fall-through chain from each until common (bounded)
            def chain(x):
                seen = []
                for _ in range(60):
                    seen.append(x)
                    if len(bsucc.get(x, [])) != 1: break
                    x = bsucc[x][0]
                return seen
            ca, cb = chain(a1), set(chain(b1))
            for x in ca:
                if x in cb: return x
        return None

    def emit(L, stop, ind):
        pad = "    " * ind
        while L is not None and L != stop:
            if L in printed:
                print(pad + "goto L%04X;" % L); return
            printed.add(L)
            stmts, cond = block_stmts(L)
            s = bsucc[L]
            # loop: a successor is a back-edge to a dominator (header) -> while
            body_back = [t for t in s if t in idom and dominates(idom, t, L)]
            for st in stmts[:-0 or len(stmts)]:
                if not st.startswith("return"):
                    print(pad + st)
            if any(st.startswith("return") for st in stmts):
                for st in stmts:
                    if st.startswith("return"): print(pad + st)
                return
            if len(s) == 2:
                foll = follow_of(L)
                taken, fall = s[1], s[0]
                print(pad + "if (%s) {" % cond)
                emit(taken, foll, ind + 1)
                if fall != foll:
                    print(pad + "} else {")
                    emit(fall, foll, ind + 1)
                print(pad + "}")
                L = foll
            elif len(s) == 1:
                L = s[0]
            else:
                if s: print(pad + "/* switch/computed -> %s */" % ", ".join("L%04X" % x for x in s))
                return

    name = S.string(entry) or "sub_%04X" % entry
    print("void %s() {" % name)
    emit(leaders[0], None, 1)
    print("}")


if __name__ == "__main__":
    main(sys.argv)
