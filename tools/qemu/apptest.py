#!/usr/bin/env python3
"""Unattended install + app-compatibility run of an Okno OS build in QEMU.

  apptest.py --arch x86|x64 --iso build/bootcdregtest.iso --apps tools/qemu/apps.tsv
             --cache DIR --out DIR [--kvm] [--timeout SECS]

bootcdregtest.iso installs the system without questions and, after the first logon, runs
regtest.cmd; that hands over to \\okno\\run.cmd on the test disk built here. run.cmd reports
over the kernel debug log (COM1) with `dbgprint OKNO:...` lines, which this script reads:

  OKNO:BEGIN               desktop is up and autorun works (smoke test passed)
  OKNO:SHOT:<app>          take a screenshot now
  OKNO:PASS:<app> / FAIL   the app's process is alive after its wait / is gone
  OKNO:END                 suite finished

apps.tsv columns: name, arch, url, kind, args, exe, check, wait
  run            start the downloaded file with args; PASS if process `check` is alive after `wait` s
  install        run the installer with args and wait; then start `exe`, check process `check`
  install-check  run the installer; then run `exe check` synchronously; PASS if it exits with 0
Downloads are cached in --cache as <name>.<ext>.
"""
import argparse, json, os, re, shutil, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
CRASH = re.compile(rb"\*\*\* Fatal System Error|KeBugCheckEx|kdb:>|Entered debugger|\*\*\* STOP")


def load_apps(path, arch):
    apps = []
    for line in open(path):
        if line.strip() and not line.startswith("#"):
            name, a, url, kind, args, exe, check, wait = (line.rstrip("\n").split("\t") + [""] * 8)[:8]
            if a == arch:
                ext = ".msi" if url.lower().endswith(".msi") else ".zip" if url.lower().endswith(".zip") else ".exe"
                apps.append(dict(name=name, url=url, file=name + ext, kind=kind, args=args, exe=exe,
                                 check=check, wait=int(wait or 20)))
    return apps


def fetch(apps, cache):
    os.makedirs(cache, exist_ok=True)
    for a in apps:
        path = os.path.join(cache, a["file"])
        if not os.path.exists(path):
            subprocess.run(["curl", "-sSfL", "--retry", "3", "-o", path + ".part", a["url"]], check=True)
            os.rename(path + ".part", path)


def run_cmd(apps):
    out = ["@echo off", "set D=%1", "dbgprint OKNO:BEGIN"]
    for a in apps:
        n, file = a["name"], f'"%D%\\okno\\apps\\{a["file"]}"'
        launch = f"msiexec /i {file}" if file.endswith('.msi"') else file
        if a["kind"] == "run":
            out.append(f'start "" {launch} {a["args"]}')
        else:
            out += [f"dbgprint OKNO:INSTALL:{n}", f'start "" /wait {launch} {a["args"]}']
        if a["kind"] == "install-check":
            out += [f'"{a["exe"]}" {a["check"]}',
                    f"if errorlevel 1 (dbgprint OKNO:FAIL:{n}) else (dbgprint OKNO:PASS:{n})"]
            continue
        if a["kind"] == "install":
            out.append(f'start "" "{a["exe"]}"')
        out += [f"timeout /t {a['wait']} /nobreak >nul",
                f"dbgprint OKNO:SHOT:{n}",
                "timeout /t 3 /nobreak >nul",
                f'tasklist | find /i "{a["check"]}" >nul',
                f"if errorlevel 1 (dbgprint OKNO:FAIL:{n}) else (dbgprint OKNO:PASS:{n})",
                f"taskkill /f /im {a['check']} >nul 2>&1"]
    out += ["dbgprint OKNO:END", "shutdown -s -t 0", ""]
    return "\r\n".join(out)


def make_disk(path, apps, cache):
    size = sum(os.path.getsize(os.path.join(cache, a["file"])) for a in apps) + (64 << 20)
    size = (size + (1 << 20) - 1) & ~((1 << 20) - 1)
    with open(path, "wb") as f:
        f.truncate(size)
        total, start = size // 512, 2048
        f.seek(446)  # one bootable FAT32 (LBA) partition from 1 MiB
        f.write(bytes([0x80, 0xFE, 0xFF, 0xFF, 0x0C, 0xFE, 0xFF, 0xFF]) + start.to_bytes(4, "little") + (total - start).to_bytes(4, "little"))
        f.seek(510)
        f.write(b"\x55\xaa")
    subprocess.run(["mkfs.vfat", "-F", "32", "-n", "OKNOTEST", "--offset", "2048", path, str((size // 512 - 2048) // 2)],
                   check=True, stdout=subprocess.DEVNULL)
    img = path + "@@1M"
    subprocess.run(["mmd", "-i", img, "::/okno", "::/okno/apps"], check=True)
    script = os.path.join(os.path.dirname(path), "run.cmd")
    open(script, "w", newline="").write(run_cmd(apps))
    subprocess.run(["mcopy", "-i", img, script, "::/okno/run.cmd"], check=True)
    for a in apps:
        subprocess.run(["mcopy", "-i", img, os.path.join(cache, a["file"]), "::/okno/apps/"], check=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arch", required=True)
    ap.add_argument("--iso", required=True)
    ap.add_argument("--apps", required=True)
    ap.add_argument("--cache", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--kvm", action="store_true")
    ap.add_argument("--timeout", type=int, default=3600)
    o = ap.parse_args()

    os.makedirs(o.out, exist_ok=True)
    os.environ["OKNO_VM_DIR"] = vm_dir = os.path.abspath(os.path.join(o.out, "vm"))
    shutil.rmtree(vm_dir, ignore_errors=True)
    apps = load_apps(o.apps, o.arch)
    fetch(apps, o.cache)
    data = os.path.join(o.out, "testdisk.img")
    make_disk(data, apps, o.cache)
    vm = [sys.executable, os.path.join(HERE, "vm.py")]
    subprocess.run(vm + ["start", "t", "--arch", o.arch, "--iso", o.iso, "--data", data, "--install"] + (["--kvm"] if o.kvm else []), check=True)

    serial = os.path.join(vm_dir, "t.serial")
    results, status, seen, deadline = {}, "timeout", 0, time.time() + o.timeout
    while time.time() < deadline:
        time.sleep(2)
        log = open(serial, "rb").read() if os.path.exists(serial) else b""
        for m in re.finditer(rb"OKNO:(\w+)(?::([\w.+-]+))?", log[seen:]):
            kind, app = m.group(1).decode(), (m.group(2) or b"").decode()
            if kind == "BEGIN":
                results["_desktop"] = "PASS"
            elif kind == "SHOT":
                subprocess.run(vm + ["shot", "t", os.path.join(o.out, f"{app}.png")])
            elif kind in ("PASS", "FAIL"):
                results[app] = kind
        seen = max(seen, len(log) - 200)
        if CRASH.search(log):
            status = "crash"
            subprocess.run(vm + ["shot", "t", os.path.join(o.out, "crash.png")])
            break
        if b"OKNO:END" in log:
            status = "done"
            break
    subprocess.run(vm + ["stop", "t"], stderr=subprocess.DEVNULL)
    shutil.copy(serial, os.path.join(o.out, "serial.log"))

    passed = sum(1 for k, v in results.items() if not k.startswith("_") and v == "PASS")
    summary = dict(status=status, desktop=results.get("_desktop", "FAIL"), passed=passed, total=len(apps),
                   apps={a["name"]: results.get(a["name"], "NOT RUN") for a in apps})
    json.dump(summary, open(os.path.join(o.out, "results.json"), "w"), indent=2)
    lines = [f"# App test: {o.arch}", "", f"Status: **{status}**, desktop: **{summary['desktop']}**, "
             f"apps: **{passed}/{len(apps)}**", "", "| App | Result |", "|---|---|"]
    lines += [f"| {n} | {r} |" for n, r in summary["apps"].items()]
    open(os.path.join(o.out, "results.md"), "w").write("\n".join(lines) + "\n")
    print("\n".join(lines))
    sys.exit(0 if status == "done" and summary["desktop"] == "PASS" else 1)


if __name__ == "__main__":
    main()
