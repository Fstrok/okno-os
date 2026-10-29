#!/usr/bin/env python3
"""Run and drive Okno OS in QEMU for tests.

  vm.py start NAME --arch x86|x64 --iso FILE [--disk FILE] [--data FILE] [--kvm]
  vm.py shot NAME OUT.png        screenshot
  vm.py keys NAME KEY...         QEMU key names (ret, alt-n, meta_l-r, ...); 'sleepN' pauses N seconds
  vm.py type NAME TEXT           type text with the US layout
  vm.py wait NAME REGEX [SECS]   wait until the serial log matches REGEX (exit 1 on timeout)
  vm.py stop NAME

State lives in $OKNO_VM_DIR (default ./vm): NAME.mon (monitor socket), NAME.serial (debug log).
The machine is q35 with AHCI disks: the stock i440FX IDE path crashes x64 builds (pciidex.sys).
"""
import os, re, socket, subprocess, sys, time

VM_DIR = os.environ.get("OKNO_VM_DIR", "vm")
KEYS = {" ": "spc", ".": "dot", ",": "comma", "-": "minus", "=": "equal", "/": "slash", "\\": "backslash",
        ";": "semicolon", "'": "apostrophe", "`": "grave_accent", "\n": "ret", "\t": "tab",
        ":": "shift-semicolon", "_": "shift-minus", "+": "shift-equal", "?": "shift-slash", "|": "shift-backslash",
        '"': "shift-apostrophe", "~": "shift-grave_accent", "<": "shift-comma", ">": "shift-dot",
        "!": "shift-1", "@": "shift-2", "#": "shift-3", "$": "shift-4", "%": "shift-5", "^": "shift-6",
        "&": "shift-7", "*": "shift-8", "(": "shift-9", ")": "shift-0"}


def path(name, ext):
    return os.path.join(VM_DIR, f"{name}.{ext}")


def monitor(name, cmd):
    with socket.socket(socket.AF_UNIX) as s:
        s.connect(path(name, "mon"))
        s.recv(4096)
        s.sendall(cmd.encode() + b"\n")
        time.sleep(0.3)
        return s.recv(65536).decode(errors="replace").split("\r\n", 1)[-1]


def start(name, args):
    opts = dict(zip(args[::2], args[1::2]))
    kvm = "--kvm" in args
    os.makedirs(VM_DIR, exist_ok=True)
    disk = opts.get("--disk") or path(name, "qcow2")
    if not os.path.exists(disk):
        subprocess.run(["qemu-img", "create", "-q", "-f", "qcow2", disk, "20G"], check=True)
    qemu = "qemu-system-x86_64" if opts["--arch"] == "x64" else "qemu-system-i386"
    cmd = [qemu, "-machine", "q35", "-m", "3072", "-smp", "2", "-cpu", "max",
           "-accel", "kvm" if kvm else "tcg,thread=multi",
           "-drive", f"file={disk},if=none,id=d0", "-device", "ide-hd,drive=d0,bus=ide.0",
           "-drive", f"file={opts['--iso']},media=cdrom,if=none,id=cd", "-device", "ide-cd,drive=cd,bus=ide.2,bootindex=0",
           "-vga", "std", "-display", "none", "-usb", "-device", "usb-tablet", "-nic", "user,model=e1000",
           "-monitor", f"unix:{path(name, 'mon')},server,nowait", "-serial", f"file:{path(name, 'serial')}"]
    if "--data" in opts:
        cmd += ["-drive", f"file={opts['--data']},format=raw,if=none,id=d1", "-device", "ide-hd,drive=d1,bus=ide.1"]
    subprocess.Popen(cmd, stdout=open(path(name, "log"), "w"), stderr=subprocess.STDOUT, start_new_session=True)
    for _ in range(50):
        if os.path.exists(path(name, "mon")):
            return
        time.sleep(0.1)
    sys.exit(open(path(name, "log")).read())


def shot(name, out):
    from PIL import Image
    ppm = os.path.abspath(out + ".ppm")
    monitor(name, f"screendump {ppm}")
    time.sleep(0.3)
    Image.open(ppm).save(out)
    os.remove(ppm)


def keys(name, items):
    for k in items:
        if k.startswith("sleep"):
            time.sleep(float(k[5:]))
        else:
            monitor(name, f"sendkey {k}")
            time.sleep(0.15)


def type_text(name, text):
    keys(name, [KEYS.get(c) or (f"shift-{c.lower()}" if c.isupper() else c) for c in text])


def wait(name, regex, secs=600):
    pattern, deadline = re.compile(regex.encode()), time.time() + float(secs)
    while time.time() < deadline:
        with open(path(name, "serial"), "rb") as f:
            if pattern.search(f.read()):
                return
        time.sleep(2)
    sys.exit(f"timeout waiting for {regex!r}")


if __name__ == "__main__":
    action, name, *rest = sys.argv[1:]
    if action == "start":
        start(name, rest)
    elif action == "shot":
        shot(name, rest[0])
    elif action == "keys":
        keys(name, rest)
    elif action == "type":
        type_text(name, " ".join(rest))
    elif action == "wait":
        wait(name, *rest)
    elif action == "stop":
        monitor(name, "quit")
    else:
        sys.exit(__doc__)
