#!/usr/bin/env python3
"""apigap: static Windows API gap analyzer for Okno OS.

Reads only PE import/export tables (clean-room: no disassembly, no decompilation).

  exports <dir|iso>... -o exports.json     DLL exports of a system tree, ISO or build dir
  imports <file|dir>... -o imports.json    imports of every PE of an app (installers are unpacked)
  gap <json>... [--ros-src DIR] -o gap.md  missing DLLs/functions per app + global ranking (+ gap.json)
  fetch <apps.tsv> <cache> [--check]       download (or only verify) the installers from the app list
"""
import argparse, collections, json, lzma, mmap, os, re, shutil, struct, subprocess, sys, tempfile, urllib.request
import pefile

ARCH = {0x14c: 'i386', 0x8664: 'amd64', 0xaa64: 'arm64', 0x1c4: 'arm'}
SIGS = [(b'MZ', 'pe'), (b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1', 'msi'), (b'PK\x03\x04', 'zip'), (b'7z\xbc\xaf\x27\x1c', '7z'),
        (b'MSCF\0\0\0\0', 'cab'), (b'\xfd7zXZ\0', 'xz'), (b'Rar!\x1a\x07', 'rar')]
NEST_EXT = {'', '.exe', '.zip', '.7z', '.cab', '.msi', '.nupkg', '.msix', '.appx', '.xz', '.bin', '.dat', '.rar', '.tar'}
DIRS = [pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_' + d] for d in ('IMPORT', 'DELAY_IMPORT', 'EXPORT', 'COM_DESCRIPTOR')]
MAX_DEPTH = 6


def magic(head):
    return next((k for sig, k in SIGS if head.startswith(sig)), None)


def file_magic(path):
    try:
        with open(path, 'rb') as f:
            head = f.read(512)
        return magic(head) or ('tar' if head[257:262] == b'ustar' else None)
    except OSError:
        return None


def run(*cmd):
    return subprocess.run(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, errors='replace')


def nonempty(d):
    return any(files for _, _, files in os.walk(d))


def dllname(name):
    name = name.lower()
    return name if os.path.splitext(name)[1] else name + '.dll'


def open_pe(path):
    try:
        pe = pefile.PE(path, fast_load=True)
        pe.parse_data_directories(directories=DIRS)
        return pe
    except Exception:
        return None


def pe_exports(pe):
    names, ords = {}, {}
    for s in getattr(getattr(pe, 'DIRECTORY_ENTRY_EXPORT', None), 'symbols', []):
        fwd = s.forwarder.decode('latin1') if s.forwarder else None
        ords[str(s.ordinal)] = fwd
        if s.name:
            names[s.name.decode('latin1')] = fwd
    return names, ords


def pe_imports(entries):
    out = collections.defaultdict(set)
    for e in entries or []:
        for i in e.imports:
            out[dllname(e.dll.decode('latin1'))].add(i.name.decode('latin1') if i.name else f'#{i.ordinal}')
    return {k: sorted(v) for k, v in out.items()}


def pe_record(pe):
    rec = {'arch': ARCH.get(pe.FILE_HEADER.Machine, hex(pe.FILE_HEADER.Machine)),
           'imports': pe_imports(getattr(pe, 'DIRECTORY_ENTRY_IMPORT', None)),
           'delay': pe_imports(getattr(pe, 'DIRECTORY_ENTRY_DELAY_IMPORT', None))}
    clr = getattr(pe, 'DIRECTORY_ENTRY_COM_DESCRIPTOR', None)
    if clr is not None:
        rec['clr'] = 'il-only' if clr.struct.Flags & 1 else 'mixed'
    names, ords = pe_exports(pe)
    fwd = {k: v for k, v in names.items() if v}
    fwd.update({'#' + k: v for k, v in ords.items() if v})
    if fwd:
        rec['fwd'] = fwd
    return rec


# ---------------------------------------------------------------- unpacking

def z7_type(path):
    out = run('7z', 'l', '-slt', '-p-', path).stdout
    m = re.search(r'^Type = (\S+)', out.split('\n--\n', 1)[-1], re.M)
    return m.group(1) if m else None


def z7x(path, out, *filters):
    run('7z', 'x', '-y', '-p-', '-bso0', '-bsp0', '-o' + out, path, *filters)
    return nonempty(out)


BCJ2_JUMP = re.compile(rb'[\xe8\xe9]|\x0f[\x80-\x8f]')


def bcj2(buf):
    """Decode a raw 4-stream BCJ2 container (LZMA SDK filter, public domain): <5 x u32 sizes> main call jump rc."""
    out_size, n0, n1, n2, n3 = struct.unpack_from('<5I', buf)
    main, o = buf[20:20 + n0], 20 + n0
    call, jump, rc = buf[o:o + n1], buf[o + n1:o + n1 + n2], buf[o + n1 + n2:]
    prob, code, rng, ri, ci, ji = [1024] * 258, int.from_bytes(rc[:5], 'big'), 0xFFFFFFFF, 5, 0, 0
    out, pos, prev = bytearray(), 0, 0
    while pos < len(main) and len(out) < out_size:
        if prev == 0x0F and 0x80 <= main[pos] <= 0x8F:
            j = pos
        else:
            m = BCJ2_JUMP.search(main, pos)
            if not m:
                out += main[pos:]
                break
            j = m.start() + (main[m.start()] == 0x0F)
            prev = main[j - 1] if j > pos else prev
        b = main[j]
        out += main[pos:j + 1]
        pos = j + 1
        if len(out) >= out_size:
            break
        i = prev if b == 0xE8 else 256 if b == 0xE9 else 257
        t = prob[i]
        bound = (rng >> 11) * t
        if code < bound:
            rng, prob[i], bit = bound, t + ((2048 - t) >> 5), 0
        else:
            rng, code, prob[i], bit = rng - bound, code - bound, t - (t >> 5), 1
        if rng < 1 << 24:
            rng, code, ri = (rng << 8) & 0xFFFFFFFF, ((code << 8) | rc[ri]) & 0xFFFFFFFF, ri + 1
        if bit:
            if b == 0xE8:
                src, ci = int.from_bytes(call[ci:ci + 4], 'big'), ci + 4
            else:
                src, ji = int.from_bytes(jump[ji:ji + 4], 'big'), ji + 4
            dest = (src - len(out) - 4) & 0xFFFFFFFF
            out += dest.to_bytes(4, 'little')
            prev = dest >> 24
        else:
            prev = b
    return bytes(out)


def unwrap(blob):
    """Payload of an embedded blob: as is if it has a known magic; LZMA-alone (+BCJ2) as used by Edge/WebView2 installers."""
    if magic(blob[:8]):
        return blob
    dic = int.from_bytes(blob[1:5], 'little')
    if blob[:1] != b'\x5d' or dic & (dic - 1) or not 1 << 16 <= dic <= 1 << 30:
        return None
    try:
        data = lzma.decompress(blob, format=lzma.FORMAT_ALONE)
    except lzma.LZMAError:
        return None
    if len(data) > 20:
        size, n0, n1, n2, n3 = struct.unpack_from('<5I', data)
        if size == n0 + n1 + n2 and 20 + n0 + n1 + n2 + n3 == len(data):
            data = bcj2(data)
    if data[257:262] == b'ustar':
        return data
    return data if magic(data[:8]) else None


def carve(pe, path, out):
    """Dump archives embedded as resources or appended to the PE: WiX Burn containers, Squirrel, Chromium/Edge
    installers, SFX stubs that 7-Zip itself does not recognise. Returns the number of dumped blobs."""
    n = 0
    os.makedirs(out, exist_ok=True)
    pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_RESOURCE']])
    stack = list(getattr(getattr(pe, 'DIRECTORY_ENTRY_RESOURCE', None), 'entries', []))
    while stack:
        e = stack.pop()
        if hasattr(e, 'directory'):
            stack += e.directory.entries
        elif hasattr(e, 'data') and e.data.struct.Size >= 256 << 10:
            data = unwrap(pe.get_data(e.data.struct.OffsetToData, e.data.struct.Size))
            if data:
                with open(os.path.join(out, f'res{n}.{magic(data[:8]) or "tar"}'), 'wb') as f:
                    f.write(data)
                n += 1
    start = pe.get_overlay_data_start_offset()
    if start is None:
        return n
    with open(path, 'rb') as f, mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as m:
        window = m[start:start + (1 << 20)]
        hits = sorted((window.find(sig), k) for sig, k in SIGS[2:] if window.find(sig) >= 0)
        if hits and hits[0][1] != 'cab':
            with open(os.path.join(out, f'overlay.{hits[0][1]}'), 'wb') as o:
                o.write(m[start + hits[0][0]:])
            return n + 1
        pos = m.find(b'MSCF\0\0\0\0', start)
        while pos >= 0:
            size = struct.unpack_from('<I', m, pos + 8)[0]
            if m[pos + 24:pos + 26] == b'\x03\x01' and pos + size <= len(m):
                with open(os.path.join(out, f'overlay{n}.cab'), 'wb') as o:
                    o.write(m[pos:pos + size])
                n += 1
                pos = m.find(b'MSCF\0\0\0\0', pos + size)
            else:
                pos = m.find(b'MSCF\0\0\0\0', pos + 4)
    return n


def is_container(pe, size):
    ov = pe.get_overlay_data_start_offset()
    rsrc = max((s.SizeOfRawData for s in pe.sections if s.Name.rstrip(b'\0') == b'.rsrc'), default=0)
    return (ov is not None and size - ov > 128 << 10) or rsrc > 1 << 20


def unpack_pe(pe, path, out):
    with open(path, 'rb') as f, mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as m:
        inno = m.find(b'Inno Setup Setup Data') >= 0
    if inno:
        run('innoextract', '-s', '-q', '-e', '-d', out, path)
        if nonempty(out):
            return 'inno'
        return 'inno-FAILED'
    t = z7_type(path)
    if t and t not in ('PE', 'TE') and z7x(path, out):
        return t.lower()
    return 'embedded' if carve(pe, path, out) else None


def unpack_archive(kind, path, out):
    if kind == 'msi':
        run('msiextract', '-C', out, path)
        ok = nonempty(out)
        z7x(path, os.path.join(out, '.msi-binary'), '-i!Binary.*')  # custom-action DLLs live in the Binary table
        return ('msi' if ok else None) or (z7x(path, out) and 'msi-7z')
    return z7x(path, out) and kind


class AppScan:
    def __init__(self, work):
        self.work, self.pes, self.methods, self.n = work, {}, collections.Counter(), 0

    def newdir(self):
        self.n += 1
        return os.path.join(self.work, f'u{self.n}')

    def walk(self, d, prefix, depth):
        for dp, _, files in os.walk(d):
            for f in sorted(files):
                p = os.path.join(dp, f)
                if not os.path.islink(p):
                    self.visit(p, prefix + os.path.relpath(p, d).replace(os.sep, '/'), depth)

    def visit(self, path, rel, depth):
        kind = file_magic(path)
        ext = os.path.splitext(path)[1].lower()
        if kind == 'pe':
            pe = open_pe(path)
            if not pe:
                return
            if pe.OPTIONAL_HEADER.Subsystem not in (10, 11, 12, 13):  # skip EFI images
                self.pes[rel] = pe_record(pe)
            if depth < MAX_DEPTH and is_container(pe, os.path.getsize(path)):
                out = self.newdir()
                how = unpack_pe(pe, path, out)
                pe.close()
                if how:
                    self.methods[how] += 1
                    self.walk(out, rel + '!', depth + 1)
                shutil.rmtree(out, ignore_errors=True)
            else:
                pe.close()
        elif kind and depth < MAX_DEPTH and (depth == 0 or ext in NEST_EXT or kind in ('msi', 'cab')):
            out = self.newdir()
            how = unpack_archive(kind, path, out)
            if how:
                self.methods[how] += 1
                self.walk(out, rel + '!', depth + 1)
            shutil.rmtree(out, ignore_errors=True)


def cmd_imports(a):
    result = {'kind': 'imports', 'apps': {}}
    for src in a.src:
        name = os.path.basename(os.path.normpath(src))
        name = name if os.path.isdir(src) else os.path.splitext(name)[0]
        work = tempfile.mkdtemp(prefix='apigap-', dir=a.work)
        scan = AppScan(work)
        try:
            if os.path.isdir(src):
                scan.walk(src, '', 1)
            else:
                scan.visit(src, os.path.basename(src), 0)
        finally:
            shutil.rmtree(work, ignore_errors=True)
        archs = collections.Counter(p['arch'] for p in scan.pes.values() if p.get('clr') != 'il-only')
        result['apps'][name] = {
            'source': os.path.basename(src), 'arch': archs.most_common(1)[0][0] if archs else None,
            'archs': dict(archs), 'pe_count': len(scan.pes), 'unpacked': dict(scan.methods),
            'dotnet': sorted(r for r, p in scan.pes.items() if p.get('clr') == 'il-only'), 'pes': scan.pes}
        print(f'{name}: {len(scan.pes)} PE, {dict(archs)}, unpacked {dict(scan.methods)}', file=sys.stderr)
    dump_json(result, a.o)


# ---------------------------------------------------------------- exports

def cmd_exports(a):
    dlls, work = {}, tempfile.mkdtemp(prefix='apigap-', dir=a.work)
    try:
        roots = []
        for src in a.src:
            if os.path.isdir(src):
                roots.append(src)
            else:
                out = os.path.join(work, f'iso{len(roots)}')
                if not z7x(src, out):
                    sys.exit(f'cannot extract {src}')
                roots.append(out)
        for i, cab in enumerate(p for r in list(roots) for p in walk_files(r) if p.lower().endswith('.cab')):
            out = os.path.join(work, f'cab{i}')
            if z7x(cab, out):
                roots.append(out)
        for root in roots:
            for p in walk_files(root):
                if file_magic(p) != 'pe':
                    continue
                pe = open_pe(p)
                if not pe or not hasattr(pe, 'DIRECTORY_ENTRY_EXPORT'):
                    pe and pe.close()
                    continue
                names, ords = pe_exports(pe)
                rec = {'arch': ARCH.get(pe.FILE_HEADER.Machine, hex(pe.FILE_HEADER.Machine)),
                       'path': os.path.relpath(p, root), 'exports': names, 'ordinals': ords}
                pe.close()
                key = os.path.basename(p).lower()
                old = dlls.get(key)
                rank = lambda r: ('system32' in r['path'].lower(), len(r['ordinals']))
                if old is None or rank(rec) > rank(old):
                    dlls[key] = rec
    finally:
        shutil.rmtree(work, ignore_errors=True)
    archs = collections.Counter(d['arch'] for d in dlls.values())
    arch = a.arch or archs.most_common(1)[0][0]
    dlls = {k: v for k, v in sorted(dlls.items()) if v['arch'] == arch}
    print(f'{len(dlls)} {arch} DLLs, {sum(len(d["ordinals"]) for d in dlls.values())} exports', file=sys.stderr)
    dump_json({'kind': 'exports', 'source': [os.path.basename(os.path.normpath(s)) for s in a.src], 'arch': arch, 'dlls': dlls}, a.o)


def walk_files(root):
    for dp, _, files in os.walk(root):
        for f in files:
            p = os.path.join(dp, f)
            if os.path.isfile(p) and not os.path.islink(p):
                yield p


def dump_json(obj, path):
    with open(path, 'w') as f:
        json.dump(obj, f, separators=(',', ':'), sort_keys=True)


# ---------------------------------------------------------------- gap

def load_ros_src(root):
    """apisets.table.c (apiset -> host) and *.spec (functions that exist in source but are stubs or not exported)."""
    apisets, specs = {}, {}
    table = os.path.join(root, 'sdk/lib/apisets/apisets.table.c')
    if os.path.exists(table):
        for ln in open(table):
            m = re.match(r'\s*\{ RTL_CONSTANT_STRING\(L"([^"]+)"\), RTL_CONSTANT_STRING\(L"([^"]+)"\), [^}]+\},(?:\s*//\s*(\S+))?', ln)
            if m:
                apisets[m.group(1).lower() + '.dll'] = (m.group(2).lower(), (m.group(3) or m.group(2)).lower())
    for top in ('dll', 'win32ss', 'base', 'ntoskrnl', 'hal', 'drivers'):
        for dp, _, files in os.walk(os.path.join(root, top)):
            for f in files:
                if f.endswith('.spec'):
                    stem = f[:-5].lower().removesuffix('_ros')
                    if stem in specs:
                        continue
                    ent = specs[stem] = {}
                    for ln in open(os.path.join(dp, f), errors='replace'):
                        t = ln.split('#', 1)[0].split()
                        if len(t) < 3 or not (t[0] == '@' or t[0].isdigit()):
                            continue
                        flags = [x for x in t[2:] if x.startswith('-')]
                        name = next((x for x in t[2:] if not x.startswith('-')), '').split('(')[0]
                        if name:
                            ent[name] = 'stub' if t[1] == 'stub' or '-stub' in flags else \
                                'version' if any(x.startswith('-version') for x in flags) else 'source'
    return apisets, specs


class Resolver:
    def __init__(self, exports, apisets, specs):
        self.E, self.apisets, self.specs = exports, apisets, specs

    def dll(self, arch, name):
        """-> (export record or None, ReactOS host, Windows host, resolved via apiset table)"""
        d = self.E.get(arch, {}).get(name)
        if d is None and name in self.apisets:
            host, win = self.apisets[name]
            if host in self.E.get(arch, {}):
                return self.E[arch][host], host, win, True
        return d, name, name, False

    def src(self, host, fn):
        """status of a function in the ReactOS .spec files: stub | version | source | absent"""
        return self.specs.get(host.rsplit('.', 1)[0], {}).get(fn, 'absent')

    def func(self, arch, dll, fn, local=None, depth=0):
        """-> (status, host, fn, Windows host) where the lookup ended; status: ok | stub | missing | nodll.
        local = {dll: forwarders} of the app's own DLLs (present unless they forward somewhere missing)."""
        if local is not None and dll in local:
            tgt = local[dll].get(fn)
            return self.fwd(arch, tgt, local, depth) if tgt and depth < 8 else ('ok', dll, fn, dll)
        d, host, win, _ = self.dll(arch, dll)
        if d is None:
            return 'nodll', dll, fn, dll
        tbl, key = (d['ordinals'], fn[1:]) if fn.startswith('#') else (d['exports'], fn)
        if key not in tbl or (tbl[key] and depth >= 8):
            return 'missing', host, fn, win
        if tbl[key]:
            return self.fwd(arch, tbl[key], local, depth)
        return ('stub' if self.src(host, fn) == 'stub' else 'ok'), host, fn, win

    def fwd(self, arch, target, local, depth):
        mod, fn = target.rsplit('.', 1)
        st, *rest = self.func(arch, dllname(mod), fn, local, depth + 1)
        return ('missing' if st == 'nodll' else st, *rest)


def basename(rel):
    return re.split(r'[/!]', rel)[-1].lower()


def analyse_app(app, R, verdict):
    """verdict=False: only list what the app needs (no export set of its arch)."""
    local = collections.defaultdict(dict)  # arch -> {dll: forwarders}
    for rel, p in app['pes'].items():
        local[p['arch']][basename(rel)] = p.get('fwd', {})
    dd = lambda: collections.defaultdict(set)
    res = {'missing_dll': dd(), 'delay_dll': dd(), 'missing_fn': dd(), 'delay_fn': dd(), 'stub': dd(),
           'apisets': set(), 'needs': dd(), 'win': {}, 'other_arch': 0}
    for rel, p in app['pes'].items():
        if p.get('clr') == 'il-only':
            continue
        arch, loc = p['arch'], local[p['arch']]
        if verdict and arch != app['arch']:
            res['other_arch'] += 1
            continue
        for kind in ('imports', 'delay'):
            for dll, fns in p[kind].items():
                if dll in loc:
                    fns = [f for f in fns if f in loc[dll]]  # app-local DLL: only its forwarders can be missing
                elif kind == 'imports':
                    res['needs'][dll].update(fns)
                if not verdict or not fns:
                    continue
                d, _, _, via = R.dll(arch, dll)
                if d is None and dll not in loc:
                    res['missing_dll' if kind == 'imports' else 'delay_dll'][dll].add(rel)
                    continue
                if via:
                    res['apisets'].add(dll)
                for f in fns:
                    st, host, fn, win = R.func(arch, dll, f, loc)
                    if st in ('missing', 'nodll'):
                        res['missing_fn' if kind == 'imports' else 'delay_fn'][(host, fn)].add(rel)
                        res['win'][(host, fn)] = win
                    elif st == 'stub':
                        res['stub'][(host, fn)].add(rel)
    return res


def ranked(d):
    return sorted(d.items(), key=lambda kv: (-len(kv[1][0] | kv[1][1]), -len(kv[1][0]), kv[0]))


def cmd_gap(a):
    exports, apps = {}, {}
    for path in a.json:
        j = json.load(open(path))
        if j.get('kind') == 'exports':
            exports[j['arch']] = j['dlls']
        else:
            apps.update(j['apps'])
    R = Resolver(exports, *(load_ros_src(a.ros_src) if a.ros_src else ({}, {})))
    per_app, rank_fn, rank_dll, win = {}, collections.defaultdict(lambda: (set(), set())), collections.defaultdict(lambda: (set(), set())), {}
    shipped = collections.defaultdict(set)  # DLL name -> apps of the set that ship it (redistributables)
    for name in sorted(apps):
        app = apps[name]
        r = per_app[name] = analyse_app(app, R, app['arch'] in exports)
        for rel in app['pes']:
            shipped[basename(rel)].add(name)
        for key, i in (('missing_fn', 0), ('delay_fn', 1)):
            for k in r[key]:
                rank_fn[k][i].add(name)
        for key, i in (('missing_dll', 0), ('delay_dll', 1)):
            for k in r[key]:
                rank_dll[k][i].add(name)
        win.update(r['win'])
    ctx = dict(a=a, apps=apps, exports=exports, per_app=per_app, rank_fn=ranked(rank_fn), rank_dll=ranked(rank_dll),
               shipped=shipped, win=win, R=R)
    with open(a.o, 'w') as f:
        f.write(render_md(**ctx))
    js = lambda d: {f'{k[0]}!{k[1]}' if isinstance(k, tuple) else k: sorted(v) for k, v in sorted(d.items())}
    out = {'apps': {n: {'arch': apps[n]['arch'], 'verdict': apps[n]['arch'] in exports, 'pe_count': apps[n]['pe_count'],
                        'dotnet': len(apps[n]['dotnet']), 'apisets': sorted(r['apisets']),
                        'needs': {k: len(v) for k, v in sorted(r['needs'].items())},
                        **{k: js(r[k]) for k in ('missing_dll', 'delay_dll', 'missing_fn', 'delay_fn', 'stub')}}
                    for n, r in per_app.items()},
           'rank_fn': [{'host': h, 'fn': f, 'windows': win[(h, f)], 'source': R.src(h, f), 'apps': sorted(s), 'delay_only': sorted(dl - s)}
                       for (h, f), (s, dl) in ctx['rank_fn']],
           'rank_dll': [{'dll': d, 'apps': sorted(s), 'delay_only': sorted(dl - s), 'shipped_by': sorted(shipped.get(d, ()))}
                        for d, (s, dl) in ctx['rank_dll']]}
    dump_json(out, os.path.splitext(a.o)[0] + '.json')
    print(f'written {a.o} and {os.path.splitext(a.o)[0]}.json', file=sys.stderr)


SRC_LABEL = {'absent': 'нет', 'stub': 'заглушка', 'version': 'есть, скрыт -version', 'source': 'есть, не экспортирован'}


def render_md(a, apps, exports, per_app, rank_fn, rank_dll, shipped, win, R):
    ok = lambda r: not r['missing_dll'] and not r['missing_fn']
    judged = [n for n in per_app if apps[n]['arch'] in exports]
    clean = [n for n in judged if ok(per_app[n])]
    strict = [n for n in clean if not per_app[n]['apisets']]
    src = ', '.join(f'{k}: {len(v)} DLL, {sum(len(d["ordinals"]) for d in v.values())} экспортов' for k, v in exports.items())
    L = ['# Пробелы API: замер анализатором импортов', '',
         f'Набор экспортов — {src}. Программ: {len(per_app)}; с вердиктом (та же архитектура): {len(judged)}; '
         f'только потребности (нет набора экспортов их архитектуры): {len(per_app) - len(judged)}.', '',
         f'- **Без пробелов в статических импортах: {len(clean)} из {len(judged)}**'
         + (f'; из них не нуждаются в перенаправлении api-ms-win-* (apiset): {len(strict)}' if R.apisets else '') + '.',
         '- «Нет DLL» — её нет ни в системе, ни в составе программы. «Нет функции» — DLL есть, функции нет '
         'или переадресация ведёт в никуда. Отложенные (delay-load) импорты отдельно: они ломают только тот путь, где вызываются.',
         '- Статический анализ таблиц импорта/экспорта. Заглушки (`-stub` в .spec) считаются «есть», но перечислены отдельно. '
         'GetProcAddress/LoadLibrary в рантайме не видны.', '',
         '## Сводка по программам', '',
         '| Программа | Арх. | PE | .NET | Нет DLL | Нет функций | Отложенно: DLL / функций | Заглушки | apiset | Итог |',
         '|---|---|---|---|---|---|---|---|---|---|']
    for n, r in per_app.items():
        app = apps[n]
        if n in judged:
            L.append(f'| {n} | {app["arch"]} | {app["pe_count"]} | {len(app["dotnet"])} | {len(r["missing_dll"])} | {len(r["missing_fn"])} | '
                     f'{len(r["delay_dll"])} / {len(r["delay_fn"])} | {len(r["stub"])} | {len(r["apisets"])} | {"грузится" if ok(r) else "нет"} |')
        else:
            L.append(f'| {n} | {app["arch"]} | {app["pe_count"]} | {len(app["dotnet"])} | | | | | | нет вердикта |')
    L += ['', f'## Топ-{a.top} недостающих функций', '',
          '«Хост ReactOS» — DLL, где функцию ищет загрузчик (для api-ms-win-* — по `sdk/lib/apisets/apisets.table.c`); '
          '«Windows» — DLL Windows 10, где она живёт; «В исходниках» — что о ней говорят `.spec` ReactOS.', '',
          '| # | Функция | Хост ReactOS | Windows | Программ | + только отложенно | В исходниках |', '|---|---|---|---|---|---|---|']
    for i, ((h, f), (s, dl)) in enumerate(rank_fn[:a.top], 1):
        L.append(f'| {i} | `{f}` | {h} | {win[(h, f)]} | {len(s)} | {len(dl - s)} | {SRC_LABEL[R.src(h, f)]} |')
    L += ['', f'## Недостающие DLL (топ-{a.top})', '', '| DLL | Программ | + только отложенно | Есть в составе программ из списка |', '|---|---|---|---|']
    for d, (s, dl) in rank_dll[:a.top]:
        by = sorted(shipped.get(d, ()))
        L.append(f'| {d} | {len(s)} | {len(dl - s)} | {", ".join(by[:4]) + (f" +{len(by) - 4}" if len(by) > 4 else "") or "—"} |')
    L += ['', '## По программам', '']
    for n, r in per_app.items():
        app = apps[n]
        L += [f'### {n}', '', f'`{app["source"]}`: {app["pe_count"]} PE {app["archs"]}, .NET IL-only: {len(app["dotnet"])}, '
              f'распаковка: {", ".join(f"{k}×{v}" for k, v in app["unpacked"].items()) or "—"}', '']
        if n not in judged:
            needs = sorted(r['needs'].items(), key=lambda kv: (-len(kv[1]), kv[0]))
            L += [f'- нет набора экспортов {app["arch"]}, вердикта нет. Нужны {len(needs)} внешних DLL, '
                  f'{sum(map(len, r["needs"].values()))} функций: ' + ', '.join(f'{d} ({len(s)})' for d, s in needs), '']
            continue
        for title, key in (('Нет DLL', 'missing_dll'), ('Нет функций', 'missing_fn'), ('Отложенно, нет DLL', 'delay_dll'),
                           ('Отложенно, нет функций', 'delay_fn'), ('Заглушки', 'stub')):
            g = r[key]
            if not g:
                continue
            if key.endswith('dll'):
                items = [f'{d} ← {basename(min(s))}' + (f' +{len(s) - 1}' if len(s) > 1 else '') for d, s in sorted(g.items())]
            else:
                by = collections.defaultdict(list)
                for h, f in sorted(g):
                    by[h].append(f)
                items = [f'{h}: {" ".join(fs)}' for h, fs in sorted(by.items())]
            L.append(f'- **{title}** ({len(g)}): ' + '; '.join(items))
        if ok(r) and not r['delay_dll'] and not r['delay_fn']:
            L.append('- пробелов нет')
        if r['apisets']:
            L.append(f'- api-ms-win-* через перенаправление apiset ({len(r["apisets"])}): {", ".join(sorted(r["apisets"]))}')
        if r['other_arch']:
            L.append(f'- PE другой архитектуры пропущено: {r["other_arch"]}')
        L.append('')
    return '\n'.join(L) + '\n'


# ---------------------------------------------------------------- fetch

UAS = [None, 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)']  # SourceForge wants a non-browser UA, Yandex a Windows one
EXT = {'pe': '.exe', 'msi': '.msi', 'zip': '.zip', '7z': '.7z', 'cab': '.cab', 'xz': '.xz', 'rar': '.rar'}


def read_apps(path):
    for ln in open(path):
        t = ln.rstrip('\n').split('\t')
        if len(t) >= 3 and not t[0].startswith('#'):
            yield t[0], t[1], t[2]


def download(url, dst, check):
    err = None
    for _ in range(3):
        for ua in UAS:
            hdr = {'User-Agent': ua} if ua else {}
            if check:
                hdr['Range'] = 'bytes=0-4095'
            try:
                with urllib.request.urlopen(urllib.request.Request(url, headers=hdr), timeout=120) as r:
                    head = r.read(8)
                    kind = magic(head)
                    if not kind or 'text/html' in r.headers.get('Content-Type', ''):
                        err = f'not a binary ({r.headers.get("Content-Type")})'
                        continue
                    size = int((r.headers.get('Content-Range') or '/0').rsplit('/', 1)[1] or 0) or int(r.headers.get('Content-Length') or 0)
                    if check:
                        return f'{kind} {size >> 20} MB {r.geturl()[:100]}'
                    path = dst + EXT[kind]
                    with open(path + '.part', 'wb') as f:
                        f.write(head)
                        shutil.copyfileobj(r, f, 1 << 20)
                    got = os.path.getsize(path + '.part')
                    if size and got != size:
                        raise IOError(f'short download {got}/{size}')
                    os.replace(path + '.part', path)
                    return f'{kind} {got >> 20} MB'
            except Exception as e:
                err = str(e)
    raise RuntimeError(err)


def cmd_fetch(a):
    os.makedirs(a.cache, exist_ok=True)
    have = {os.path.splitext(f)[0] for f in os.listdir(a.cache) if not f.endswith('.part')}
    bad = 0
    for name, arch, url in read_apps(a.apps):
        if a.only and name not in a.only.split(','):
            continue
        if name in have and not a.check:
            print(f'{name}: cached')
            continue
        try:
            print(f'{name}: {download(url, os.path.join(a.cache, name), a.check)}', flush=True)
        except Exception as e:
            bad += 1
            print(f'{name}: FAILED {e}', flush=True)
    sys.exit(1 if bad else 0)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest='cmd', required=True)
    s = sub.add_parser('exports', help='collect DLL exports of a dir, ISO or build dir')
    s.add_argument('src', nargs='+')
    s.add_argument('-o', default='exports.json')
    s.add_argument('--arch', help='keep only this arch (default: the most common)')
    s.add_argument('--work', help='dir for temporary extraction')
    s.set_defaults(fn=cmd_exports)
    s = sub.add_parser('imports', help='collect imports of apps (each src is one app)')
    s.add_argument('src', nargs='+')
    s.add_argument('-o', default='imports.json')
    s.add_argument('--work', help='dir for temporary extraction')
    s.set_defaults(fn=cmd_imports)
    s = sub.add_parser('gap', help='compare imports with exports')
    s.add_argument('json', nargs='+', help='exports and imports JSON files (any order)')
    s.add_argument('-o', default='gap.md', help='Markdown report; JSON goes next to it')
    s.add_argument('--ros-src', help='ReactOS source tree: apiset table + .spec files')
    s.add_argument('--top', type=int, default=40)
    s.set_defaults(fn=cmd_gap)
    s = sub.add_parser('fetch', help='download installers from the app list')
    s.add_argument('apps')
    s.add_argument('cache')
    s.add_argument('--check', action='store_true', help='only verify that each URL serves a binary')
    s.add_argument('--only', help='comma-separated app names')
    s.set_defaults(fn=cmd_fetch)
    a = p.parse_args()
    a.fn(a)


if __name__ == '__main__':
    main()
