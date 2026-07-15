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
        regA, regC, st, out = "arg", "0", [], []
        v = entry
        # skip the native trampoline stub -> bytecode body
        if is_entry(v):
            v += BODY_OFF
        guard = 0
        while guard < 400:
            guard += 1
            op = read(v); ln = declen(v); m = D.mnem(op); base = m.split()[0]
            nx = v + ln
            def opnd():
                if ln == 3: return read(v + 1) | (read(v + 2) << 8)
                if ln == 2: return read(v + 1)
                return None
            def frameref():
                return m.split(None, 1)[1].strip().replace("[", "_").replace("]", "") if " " in m else "f"
            if base in ("load",):                        # load f[n] -> regA
                regA = frameref()
            elif base in ("store",):
                out.append("%s = %s;" % (frameref(), regA))
            elif base in ("pushA", "push", "push.w", "push.b"):
                sym = S.string(opnd()) if opnd() is not None else None
                st.append(sym or (regA if base == "pushA" else ("$%X" % opnd() if opnd() is not None else regA)))
            elif base in ("loadc", "ldA", "ldA.b", "ldA.w", "ldA.mem"):
                val = opnd(); sym = S.string(val) if val is not None else None
                regA = ("mem[%s]" % regA) if base == "ldA.mem" else (sym or ("$%X" % val if val is not None else "0"))
            elif base in ("ldC",):
                val = opnd(); regC = S.string(val) or ("$%X" % val if val is not None else "0")
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
                out.append("%s = %s(%s);" % (regA, fn, args) if base == "call.n" else "%s(%s);" % (fn, args))
            elif base in ("call.ind", "call.ind2"):
                out.append("(*%s)();" % regA)
            elif base in ("stA.b[pop]", "stA.w[pop]", "stA.b", "stA.w"):
                dst = st.pop() if st else ("$%X" % opnd() if opnd() is not None else "ptr")
                out.append("mem[%s] = %s;" % (dst, regA))
            elif base in ("brz", "brnz", "skipnz"):
                tgt = (v + ln + s8(read(v + 1))) if base != "skipnz" else opnd()
                cond = "!%s" % regA if base == "brz" else regA
                out.append("if (%s) goto L%04X;" % (cond, tgt))
            elif base in ("jmp", "brel", "brel'"):
                tgt = (read(v + 1) | (read(v + 2) << 8)) if base == "jmp" else v + ln + s8(read(v + 1))
                out.append("goto L%04X;" % tgt); out.append("__END__"); break
            elif base == "ret":
                out.append("return %s;" % regA); break
            elif base in ("inc",):
                regA = "(%s + 1)" % regA
            elif base in ("dec",):
                regA = "(%s - 1)" % regA
            else:
                out.append("/* %s */" % m)
            v = nx
        return [x for x in out if x != "__END__"]

    def emit(entry):
        name = S.string(entry) or "sub_%04X" % entry
        print("\nvoid %s() {" % name)
        for s in lift(entry):
            print("    " + s)
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
