#!/usr/bin/env python3
"""
EXPERIMENT: lift KOEI SNES bytecode to C-like pseudocode.

The VM is an accumulator/stack hybrid: working registers regA/regC (+ a 32-bit W), an
operand stack for call args and saves, and frame slots f[]. This lifter symbolically
executes a routine, building expressions in regA/regC/stack and emitting a statement per
side effect (store / memory write / call / branch / return). First pass -- readable for
the common shapes (accessors, display calls, wrappers); complex/rare ops fall back to a
`/* mnem */` comment. Names resolve via the symbol layer.

    py -3 tools/vm_lift.py <rom> --start 04:AB7E --base 7E:7208 --at 7698 --syms data/comroot
    (--at ADDR lifts one routine; omit to lift every named routine in the module)
"""
import argparse, os, re, sys
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..", "..", "snes-decompiler", "tools")))
from mapper import cpu_to_file, strip_copier_header, LOROM
import vm_disasm as D
import vm_opcodes as V
from symbols import Symbols

BINOP = {"add": "+", "sub": "-", "mul": "*", "mul16": "*", "udiv": "/", "sdiv": "/",
         "and": "&", "or": "|", "xor": "^", "shl": "<<", "shr": ">>", "eq": "==",
         "ne": "!=", "lt.s": "<", "lt.u": "<", "gt.s": ">", "gt.u": ">", "le.u": "<=",
         "ge.u": ">=", "ge.s": ">=", "add32": "+", "sub32": "-", "smul32": "*"}


def load_syscalls(syms_dir):
    """id -> name from <repo>/data/syscall_names.toml (the [[syscall]] array); [] blocks
    list `id = 0xNN` then `name = "..."`. Lets the lifter render `sys_<name>(...)` instead
    of `do_syscall(..., $id)` -- the id is the last-pushed #i8 (param-block byte 0 / $52)."""
    path = os.path.join(os.path.dirname(os.path.normpath(syms_dir)), "syscall_names.toml")
    out, cur = {}, None
    if os.path.isfile(path):
        for line in open(path, encoding="utf-8"):
            m = re.match(r"\s*id\s*=\s*0x([0-9A-Fa-f]+)", line)
            if m:
                cur = int(m.group(1), 16)
            n = re.match(r'\s*name\s*=\s*"([^"]+)"', line)
            if n and cur is not None:
                out[cur] = n.group(1); cur = None
    return out


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("rom"); ap.add_argument("--start", required=True); ap.add_argument("--base", required=True)
    ap.add_argument("--syms", required=True); ap.add_argument("--at", default=None)
    ap.add_argument("--scan", default=None)   # module-mode end addr (else base+0x4000)
    a = ap.parse_args(argv[1:])
    rom, _ = strip_copier_header(open(a.rom, "rb").read()); V.rom = rom
    S = Symbols(a.syms)
    SYSCALLS = load_syscalls(a.syms)
    pbase = cpu_to_file(LOROM, 0, D.PRIMARY); ebase = cpu_to_file(LOROM, 0, D.EXTENDED)
    prim = [rom[pbase + 2*i] | (rom[pbase + 2*i+1] << 8) for i in range(256)]
    ext = [rom[ebase + 2*i] | (rom[ebase + 2*i+1] << 8) for i in range(48)]
    psz = [D.opsize(h) for h in prim]
    sb, so = a.start.split(":"); off0 = cpu_to_file(LOROM, int(sb, 16), int(so, 16))
    vb, vo = a.base.split(":"); vaddr0 = int(vo, 16)

    def read(v):
        return rom[off0 + (v - vaddr0)]

    def declen(v):
        op = read(v)
        return (2 + D.opsize(ext[read(v + 1)])) if (op == D.EXT_PREFIX and read(v + 1) < 48) else 1 + psz[op]

    def s8(b):
        return b - 256 if b & 0x80 else b

    # Per-routine native trampoline (profile-driven, works for every KOEI SNES title):
    # the entry is the SIG stub; the bytecode body starts a fixed BODY_OFF bytes in.
    SIG = V.PROFILE.get("routine_sig", [0x20, 0xE6])
    BODY_OFF = V.PROFILE.get("routine_body_offset", 0)

    def is_entry(vv):
        try:
            return all(read(vv + i) == SIG[i] for i in range(len(SIG)))
        except Exception:
            return False

    def lift(entry):
        regA, regC, st = "arg", "0", []
        insns = []          # (addr, stmt or None) for the whole routine body
        targets = set()     # goto target addresses (so we emit only referenced labels)
        v = entry + BODY_OFF if is_entry(entry) else entry
        body = maxtgt = v
        guard = 0
        while guard < 800:
            guard += 1
            if v != body and is_entry(v):                # reached the next routine's trampoline -> body end
                break
            op = read(v); ln = declen(v); m = D.mnem(op); base = m.split()[0]
            nx = v + ln
            def opnd():
                if ln >= 4: return read(v + 1) | (read(v + 2) << 8) | (read(v + 3) << 16)   # long (24-bit) address
                if ln == 3: return read(v + 1) | (read(v + 2) << 8)
                if ln == 2: return read(v + 1)
                return None
            def frameref():
                return m.split(None, 1)[1].strip().replace("[", "_").replace("]", "") if " " in m else "f"
            mode = m.split()[1] if len(m.split()) > 1 else ""    # g8/g16/g16'/#i8/#i16/L = addressing mode
            def gref():          # a global/long memory operand: its name, else g_XXXX (ready for a data-walk)
                a = opnd()
                if a is None: return "g?"
                return S.string(a) or S.string(a & 0xFFFF) or ("g_%04X" % a if a <= 0xFFFF else "g_%06X" % a)
            def imm():           # an immediate: a symbol if it resolves (string/record), else the literal
                a = opnd(); return (S.string(a) or ("$%X" % a)) if a is not None else "0"
            def operand():       # by addressing mode: # = immediate, otherwise a memory reference
                return imm() if mode.startswith("#") else gref()
            stmt = None
            if 0x40 <= op <= 0x7F:                       # nibble-immediate family: value = low nibble
                nib = "$%X" % (op & 0x0F)                 # (NOT an operand byte -- the mnemonic "loadc" is a legacy label)
                fam = op >> 4
                if fam == 0x4:   regA = nib               # ldA #n
                elif fam == 0x5: regC = nib               # ldC #n
                elif fam == 0x6: st.append(nib)           # push #n  <- syscall ids ride here
                else:            regA = "(%s + %s)" % (regA, nib)   # addA #n
            elif base in ("load",):                      # load f[n] -> regA
                regA = frameref()
            elif base in ("store",):
                stmt = "%s = %s;" % (frameref(), regA)
            elif base == "pushA":
                st.append(regA)
            elif base in ("push", "push.w", "push.b"):
                st.append(operand())
            elif base == "ldA.mem":
                regA = "mem[%s]" % regA
            elif base in ("ldA", "ldA.b", "ldA.w"):
                regA = operand()
            elif base in ("ldC", "ldC.b", "ldC.w"):
                regC = operand()
            elif base == "addA":                         # addA #i8/#i16 (byte/word immediate add)
                regA = "(%s + %s)" % (regA, operand())
            elif base in ("popC",):
                regC = st.pop() if st else "top"
            elif base in BINOP:
                regA = "(%s %s %s)" % (regA, BINOP[base], regC)
            elif base in ("hostcall", "call.n"):
                t = read(v + 1) | (read(v + 2) << 8); fn = S.string(t) or "sub_%04X" % t
                if "syscall" in fn and st:               # syscall bridge: id = last pushed ($52)
                    idv = st.pop()
                    mi = re.match(r"\$([0-9A-Fa-f]+)$", idv)
                    fn = (SYSCALLS.get(int(mi.group(1), 16)) if mi else None) or "%s[%s]" % (fn, idv)
                args = ", ".join(reversed([st.pop() for _ in range(min(len(st), 3))])) if st else ""
                stmt = "%s = %s(%s);" % (regA, fn, args) if base == "call.n" else "%s(%s);" % (fn, args)
            elif base in ("call.ind", "call.ind2"):
                stmt = "(*%s)();" % regA
            elif base in ("stA", "stA.b", "stA.w") and mode != "" and "[pop]" not in m:
                stmt = "%s = %s;" % (gref(), regA)       # stA g8/g16 or stA.b/.w L -> store to a named global/long
            elif base in ("stA.b[pop]", "stA.w[pop]", "stA.b", "stA.w"):
                dst = st.pop() if st else ("$%X" % opnd() if opnd() is not None else "ptr")
                stmt = "mem[%s] = %s;" % (dst, regA)
            elif base in ("brz", "brnz", "skipnz"):
                tgt = (v + ln + s8(read(v + 1))) if base != "skipnz" else opnd()
                cond = "!%s" % regA if base == "brz" else regA
                targets.add(tgt); maxtgt = max(maxtgt, tgt); stmt = "if (%s) goto L%04X;" % (cond, tgt)
            elif base in ("jmp", "brel", "brel'"):
                tgt = (read(v + 1) | (read(v + 2) << 8)) if base == "jmp" else v + ln + s8(read(v + 1))
                targets.add(tgt); maxtgt = max(maxtgt, tgt); stmt = "goto L%04X;" % tgt
            elif base == "ret":
                stmt = "return %s;" % regA
            elif base in ("inc",):
                regA = "(%s + 1)" % regA
            elif base in ("dec",):
                regA = "(%s - 1)" % regA
            else:
                stmt = "/* %s */" % m
            insns.append((v, stmt))
            v = nx
            if base in ("ret", "jmp", "brel", "brel'") and v > maxtgt:
                break                                    # terminator with no forward target beyond -> routine end

        # emit only labels that are actually branched-to; drop gotos to labels we never lifted
        present = {a for a, _ in insns}
        live = {t for t in targets if t in present}
        out = []
        for addr, stmt in insns:
            if addr in live:
                out.append("L%04X:" % addr)
            if stmt is None:
                continue
            mg = re.search(r"goto L([0-9A-F]{4});", stmt)
            if mg and int(mg.group(1), 16) not in live:    # target off the lifted body -> keep addr, no dangling label
                stmt = stmt.replace("goto L%s;" % mg.group(1), "goto $%s;  /* out-of-body */" % mg.group(1))
            out.append(stmt)
        # drop a `goto Lxxxx;` immediately followed by its own `Lxxxx:` label (redundant fall-through)
        dedup = []
        for j, s in enumerate(out):
            mg = re.match(r"goto L([0-9A-F]{4});$", s)
            if mg and j + 1 < len(out) and out[j + 1] == "L%s:" % mg.group(1):
                continue
            dedup.append(s)
        out = dedup
        # peephole: `x = f(...); return x;`  ->  `return f(...);`
        peep = []
        i = 0
        while i < len(out):
            cur = out[i]; nxt = out[i + 1] if i + 1 < len(out) else None
            ma = re.match(r"^(\w+) = (.+);$", cur)
            if ma and nxt == "return %s;" % ma.group(1):
                peep.append("return %s;" % ma.group(2)); i += 2; continue
            peep.append(cur); i += 1
        return peep

    def emit(entry):
        name = S.string(entry) or "sub_%04X" % entry
        print("\nword %s() {" % name)          # VM routines return the accumulator (regA); word = its width
        for s in lift(entry):
            print(("  " if s.endswith(":") else "    ") + s)
        print("}")

    if a.at:
        emit(int(a.at, 16))
    else:
        v = vaddr0; end = int(a.scan, 16) if a.scan else vaddr0 + 0x4000
        while v < end:
            if is_entry(v) and S.string(v):
                emit(v)
            v += 1


if __name__ == "__main__":
    main(sys.argv)
