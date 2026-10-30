#!/usr/bin/env python3
"""Import (or re-import) a Wine DLL into the Okno OS tree.

  import_dll.py WINE_SRC NAME [NAME...] [--tag wine-11.20] [--dry-run]

For each dlls/NAME of the Wine tree it:
  - copies the sources listed in Makefile.in (and the PARENTSRC ones) to dll/win32/NAME,
  - copies Wine headers/IDL the sources include but our SDK lacks into sdk/include/psdk
    (IDL files are added to the psdk header list),
  - turns `#pragma makedep register` IDL into a WINE_REGISTRY .rgs script (widl -r),
  - writes CMakeLists.txt, wires add_subdirectory(), COM registration in syssetup.inf
    and a WINESYNC.txt entry.
It never touches DLLs that ReactOS itself maintains: refuse if dll/win32/NAME exists
without our marker comment, unless --force.
"""
import os, re, shutil, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MARKER = "# Imported from Wine by tools/wine/import_dll.py"
STATIC_LIBS = {"uuid", "dxguid", "strmiids", "dmoguids", "mfuuid", "wmcodecdspuuid", "strmbase", "wbemuuid",
               "dinput8", "dinput", "dxerr8", "dxerr9", "ntoskrnl", "hal"}  # linked statically or as libs
SKIP_IMPORTS = {"winecrt0", "kernelbase"}
INCLUDE_DIRS = ["sdk/include/psdk", "sdk/include/ddk", "sdk/include/crt", "sdk/include/reactos",
                "sdk/include/reactos/wine", "sdk/include/wine", "sdk/include/dxsdk", "sdk/include/vcruntime",
                "sdk/include/ndk", "sdk/include/winrt", "sdk/include/ucrt", "sdk/include"]
WIDL = os.environ.get("WIDL")


def parse_makefile(path):
    text = open(path).read().replace("\\\n", " ")
    return {m.group(1): m.group(2).split() for m in re.finditer(r"^(\w+)\s*=\s*(.*)$", text, re.M)}


def have_header(name, local_dirs):
    rel = name.replace("\\", "/")
    for d in local_dirs + [os.path.join(ROOT, d) for d in INCLUDE_DIRS]:
        base = os.path.join(d, rel)
        if os.path.exists(base) or os.path.exists(base[:-2] + ".idl"):
            return True
    return False


def missing_headers(files, wine, local_dirs, seen):
    """Wine headers needed by files that our SDK lacks (transitively)."""
    out = []
    for f in files:
        for inc in re.findall(r'^\s*#\s*(?:include|import)\s*[<"]([^>"]+)[>"]', open(f, errors="ignore").read(), re.M):
            if inc in seen or have_header(inc, local_dirs):
                continue
            seen.add(inc)
            for cand in (inc[:-2] + ".idl" if inc.endswith(".h") else None, inc):
                src = cand and os.path.join(wine, "include", cand)
                if src and os.path.exists(src):
                    out.append(src)
                    out += missing_headers([src], wine, local_dirs, seen)
                    break
    return out


def insert_sorted_line(path, line, pattern):
    lines = open(path).read().split("\n")
    if line in lines:
        return
    idx = [i for i, l in enumerate(lines) if re.match(pattern, l)]
    pos = next((i for i in idx if lines[i] > line), idx[-1] + 1)
    lines.insert(pos, line)
    open(path, "w").write("\n".join(lines))


def import_dll(wine, name, tag, force, dry):
    src = os.path.join(wine, "dlls", name)
    mk = parse_makefile(os.path.join(src, "Makefile.in"))
    module = mk["MODULE"][0]
    if not module.endswith(".dll") or "UNIXLIB" in mk:
        return f"skip {name}: {'unix-backed' if 'UNIXLIB' in mk else 'not a dll'}"
    dest = os.path.join(ROOT, "dll/win32", name)
    cml = os.path.join(dest, "CMakeLists.txt")
    if os.path.exists(cml) and MARKER not in open(cml).read() and not force:
        return f"skip {name}: maintained in tree (use --force to replace)"
    parent = os.path.normpath(os.path.join(src, mk["PARENTSRC"][0])) if "PARENTSRC" in mk else None

    def locate(f):
        for d in (src, parent):
            if d and os.path.exists(os.path.join(d, f)):
                return os.path.join(d, f)
        raise FileNotFoundError(f"{name}: {f}")

    sources = [locate(f) for f in mk.get("SOURCES", [])]
    spec = os.path.join(src, name + ".spec")
    if not os.path.exists(spec):
        spec = locate(os.path.basename(parent) + ".spec") if parent else spec
    headers = [os.path.join(d, h) for d in (src, parent) if d for h in os.listdir(d) if h.endswith(".h")]
    new_sdk = missing_headers(sources + headers, wine, [src] + ([parent] if parent else []), set())
    if dry:
        return f"{name}: {len(sources)} sources, sdk +{[os.path.basename(h) for h in new_sdk]}"

    if os.path.isdir(dest):
        shutil.rmtree(dest)
    os.makedirs(dest)
    for f in set(sources + headers + [spec]):
        shutil.copy2(f, os.path.join(dest, os.path.basename(f) if f != spec else name + ".spec"))
    for h in new_sdk:
        target = os.path.join(ROOT, "sdk/include/psdk", os.path.relpath(h, os.path.join(wine, "include")))
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copy2(h, target)
        if h.endswith(".idl") and os.sep not in os.path.relpath(h, os.path.join(wine, "include")):
            insert_sorted_line(os.path.join(ROOT, "sdk/include/psdk/CMakeLists.txt"),
                               "    " + os.path.basename(h), r"    [\w.-]+\.idl$")

    c_files = [os.path.basename(f) for f in sources if f.endswith((".c", ".cpp"))]
    rc_files = [os.path.basename(f) for f in sources if f.endswith(".rc")]
    idl_kinds = {}
    for f in sources:
        if f.endswith(".idl"):
            kinds = set()
            for m in re.findall(r"#pragma makedep (.*)", open(f).read()):
                kinds.update(m.split())
            idl_kinds[os.path.basename(f)] = kinds
    rgs = []
    for idl, kinds in idl_kinds.items():
        if "register" in kinds:
            out = idl[:-4] + ".rgs"
            inc = [f"-I{os.path.join(ROOT, d)}" for d in INCLUDE_DIRS] + [f"-I{dest}"]
            subprocess.run([WIDL, "-r", *inc, "-o", os.path.join(dest, out), os.path.join(dest, idl)], check=True)
            rgs.append(out)
    rc = None
    if rc_files or rgs:
        rc = f"{name}_okno.rc" if rc_files and rgs else (rc_files[0] if rc_files else f"{name}.rc")
        if rgs:
            body = "".join(f'#include "{r}"\n' for r in rc_files)
            body += "".join(f'{i + 1} WINE_REGISTRY "{r}"\n' for i, r in enumerate(rgs))
            open(os.path.join(dest, rc), "w").write(body)

    imports = [i for i in mk.get("IMPORTS", []) if i not in SKIP_IMPORTS]
    static = ["uuid"] + [i for i in imports if i in STATIC_LIBS and i != "uuid"]
    # Wine's winecrt0 supplies default Dll* entry points; here they come from libwine helpers
    spec_text = open(spec).read()
    code = "".join(open(f, errors="ignore").read() for f in sources if f.endswith((".c", ".cpp")))
    for entry, lib in (("DllCanUnloadNow", "wine_dll_canunload"), ("DllRegisterServer", "wine_dll_register")):
        if entry in spec_text and not re.search(rf"\b{entry}\s*\(\s*(void)?\s*\)\s*\{{?\s*$", code, re.M) \
                and not re.search(rf"WINAPI\s+{entry}\s*\(", code):
            static.append(lib)
    dynamic = [i for i in imports if i not in STATIC_LIBS]
    delay = mk.get("DELAYIMPORTS", [])
    defs = " ".join(mk.get("EXTRADEFS", []))
    headers_idl = [i for i, k in idl_kinds.items() if k & {"header"} or (k & {"ident", "proxy", "client", "server"})]
    lines = [MARKER + f" ({tag})", ""]
    if defs:
        lines.append(f"add_definitions({defs})")
    lines += [f"spec2def({module} {name}.spec{' ADD_IMPORTLIB' if 'IMPORTLIB' in mk else ''})", "",
              "list(APPEND SOURCE"] + [f"    {c}" for c in c_files] + [f"    ${{CMAKE_CURRENT_BINARY_DIR}}/{name}.def)", ""]
    for idl in headers_idl:
        lines.append(f"add_idl_headers({name}_{idl[:-4]}_header {idl})")
    lines.append(f"add_library({name} MODULE ${{SOURCE}}{' ' + rc if rc else ''})")
    if rc and rgs:
        lines.append(f"set_source_files_properties({rc} PROPERTIES OBJECT_DEPENDS \"{';'.join('${CMAKE_CURRENT_SOURCE_DIR}/' + r for r in rgs)}\")")
    lines += [f"set_module_type({name} win32dll)",
              f"target_compile_definitions({name} PRIVATE __WINESRC__ __ROS_LONG64__)",
              f"target_link_libraries({name} {' '.join(['wine'] + static)} oldnames)",
              f"add_importlibs({name} {' '.join(dynamic + ['msvcrt', 'kernel32', 'ntdll'])})"]
    if delay:
        lines.append(f"add_delay_importlibs({name} {' '.join(delay)})")
    for idl in headers_idl:
        lines.append(f"add_dependencies({name} {name}_{idl[:-4]}_header)")
    lines += [f"add_dependencies({name} psdk)", f"add_cd_file(TARGET {name} DESTINATION reactos/system32 FOR all)",
              f"set_wine_module({name})", ""]
    open(cml, "w").write("\n".join(lines))

    insert_sorted_line(os.path.join(ROOT, "dll/win32/CMakeLists.txt"), f"add_subdirectory({name})", r"add_subdirectory\(")
    if rgs:
        inf = os.path.join(ROOT, "media/inf/syssetup.inf")
        s = open(inf).read()
        entry = f"11,,{module},1"
        if entry not in s:
            anchor = "[OleControlDlls]\n"
            s = s.replace(anchor, anchor + entry + "\n", 1)
            open(inf, "w").write(s)
    sync = os.path.join(ROOT, "media/doc/WINESYNC.txt")
    s = open(sync).read()
    entry = f"dll/win32/{name}".ljust(32) + f"# Synced to {tag.capitalize()}"
    s = re.sub(rf"^dll/win32/{re.escape(name)}\s+#.*$\n?", "", s, flags=re.M)
    open(sync, "w").write(s.rstrip("\n") + "\n" + entry + "\n")
    return f"{name}: {len(c_files)} C files, imports {dynamic}, rgs {rgs}, sdk +{len(new_sdk)}"


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    opts = sys.argv[1:]
    tag = next((opts[i + 1] for i, a in enumerate(opts) if a == "--tag"), "wine-11.20")
    args = [a for a in args if a != tag]
    if not WIDL and "--dry-run" not in opts:
        sys.exit("set WIDL to the host widl (build/host-tools/bin/widl)")
    for n in args[1:]:
        print(import_dll(args[0], n, tag, "--force" in opts, "--dry-run" in opts))
