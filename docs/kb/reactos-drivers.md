# ReactOS drivers: state, driver models, PnP/INF, tasks (for Okno OS)

Snapshot: ReactOS master `e46f4bb1` (2026-10-25), shallow clone. Area: `drivers/`, `win32ss/drivers/`, `sdk/lib/drivers/`, `sdk/include/ddk` (+ wdf/ucx headers).
Paths below are relative to the ReactOS root. "Lines" = `.c/.cpp/.h/.hpp/.S/.asm` lines (`find | xargs cat | wc -l`), rounded.
`U` = lines containing `UNIMPLEMENTED`, `T` = lines containing `TODO`/`FIXME` (grep counts). "Built" = listed by `add_subdirectory` in the parent `CMakeLists.txt`; "shipped" = has an active `add_cd_file`.
License marks: **[MS-PL: own .sys]** = Microsoft Public License, NOT GPL-compatible: allowed only as a separate module (its own .sys/.dll), never copied into GPL files. **[GPLv2-only]** / **[Linux-derived]** = cannot stay in a GPL-2.0-or-later product without a rewrite.

---

## 1. Summary

- **Size.** `drivers/` ≈1.31M lines, `win32ss/drivers` ≈31k, `sdk/lib/drivers` ≈338k (WDF alone 241k), `sdk/include/ddk` ≈71k. Most of the bulk is third-party: ACPICA 120k, lwIP 148k, Ext2Fsd 105k, WinBtrfs 98k, UDF 76k, MS fastfat 75k, MS classpnp/disk/cdrom 94k. These trees have 763 `UNIMPLEMENTED` lines.
- **Driver-model level is XP/2003, with a few Win10 islands.** The Win10-level parts are:
  - KMDF 1.17: WDF source from the Win10 10586 release, Dec 2015.
  - A KMDF/UCX xHCI skeleton.
  - The Microsoft Win10 classpnp/disk/cdrom.
  - CoolStar's HDA bus driver.
  - A WSK provider (netio).

  Everything vendor Win10 drivers need beyond that is missing or XP-level:
  - NDIS 5.x only: 292 exports and no NDIS 6 entry point.
  - StorPort implements 4 of its extended functions.
  - No MSI/MSI-X.
  - No dxgkrnl.
  - No SpbCx, GpioClx or hidi2c.
  - No UMDF host and no cng.sys.
- **Four cross-cutting blockers for real PCs (stage 3):**
  1. Message-signaled interrupts are not implemented, and the call still reports success: `irq.c:211-219` logs the problem and returns `STATUS_SUCCESS` without connecting anything. The PCI drivers have no MSI code.
  2. PCI interrupt lines come from the config-space `InterruptLine` (`hal/halx86/legacy/bus/pcibus.c:733`). ACPI `_PRT` is never evaluated outside the ACPICA library.
  3. All 9 `ACPI_INTERFACE_STANDARD` functions are stubs (`drivers/bus/acpi/interface.c`), and there is no Embedded Controller handler.
  4. The WDF loader refuses any driver built for KMDF newer than 1.17 (`sdk/lib/drivers/wdf/kmdf/src/dynamic/version/version.cpp:488`).
- **Worth keeping:**
  - The new ATA/AHCI stack: `atapi` + `pciidex/chipset`, MIT/BSD-2, 2026.
  - `pcix`: a Windows-like PCI bus driver with ECAM, PCIe and Resizable BAR code added in 2026.
  - The MS classpnp/disk/cdrom/fastfat/cdfs drivers (MS-PL, each kept as its own .sys).
  - WDF (MIT; needs an update) and hdaudbus (BSD-3, already at upstream HEAD).
  - usbport + EHCI/OHCI/UHCI, i8042/kbdclass/mouclass/HID class, partmgr/mountmgr, netio (MIT), compbatt (MIT).
- **Rewrite or replace:**
  - acpi.sys: rebuild on uACPI 7.0.0 (MIT, NT-compatible AML behavior).
  - storport: bring to Win10 level.
  - ndis: implement NDIS 6.50+ and keep a shim for NDIS 5 drivers.
  - tcpip: make it an NDIS 6 protocol on lwIP 2.2.1 with IPv6 and UDP, serving TDI and WSK.
  - xHCI/UCX/hub3: write the bodies, using Haiku (MIT) and FreeBSD (BSD) as references.
  - NTFS: no production-ready option exists in tree.
  - processr (GPLv2-only) and storahci (GPLv2-only, never shipped): replace.
- **Add (missing entirely):**
  - NVMe: port the OFA nvmewin 1.5 driver (BSD-style StorPort miniport).
  - A display driver for the UEFI GOP framebuffer.
  - An HDA codec function driver (counterpart of Microsoft's hdaudio.sys).
  - In-box NDIS 6 drivers for Intel I219/I225 and Realtek 8111/8125 NICs.
  - SpbCx, GpioClx, the ACPI resource hub and hidi2c.
  - A WDI Wi-Fi host, the UMDF 2 host, and cng.sys built on SymCrypt.
  - dxgkrnl (stage 5). The first test miniport is Microsoft's KMDOD sample (MS-PL, its own .sys).
- **Third-party updates:**

  | Component | In tree | Upstream latest |
  |---|---|---|
  | ACPICA (only if kept) | 20221020 | 20260408 |
  | WDF | d9c6040 | 3b9780e (KMDF 1.33 / UMDF 2.33) |
  | WinBtrfs | 1.8.1 | 1.10 |
  | lwIP | 2.2.0 | 2.2.1 |
  | virtio library | 4c4d181 (2023) | HEAD |
  | NetKVM | NDIS5 version (2018) | NetKVM wlh (NDIS 6) |
  | Ext2Fsd | 0.69 | Ext4Fsd 0.71 |
  | FreeType | 2.10.0 | 2.15.0 |
- **Drop (legacy hardware or dead code):**
  - Buses: ISA PnP card enumeration, pcmcia.
  - Floppy: fdc, floppy, sfloppy, flpydisk.
  - Input and ports: inport, sermouse, parport.
  - Storage: buslogic, uniata (once the new stack is validated), atapi_old, usbstor_new.
  - Network: lan, nvnet, ne2000.
  - Sound: CMIDriver, sb16, mpu401, `multimedia/audio/*`.
  - Video: pc98vid, xboxvmp, vga_new, vmx_svga.
  - Other: vfatfs (Xbox only), fbtusb.
- **License flags:**
  - MS-PL code must stay in its own .sys: cdrom, classpnp, disk, sfloppy, fastfat, cdfs, and any Windows-driver-samples code.
  - GPL-2.0-only: storahci, processr, fdc. udfs says only "released under the GPLv2" (the "or later" part is unclear).
  - Ported from Linux `pci.h`: `drivers/bus/pci/pcidef.h`.
  - WinBtrfs is LGPL-3.0-or-later: keep it as its own .sys.
  - Not GPL-compatible: `atapi_old` (Microsoft EULA) and `win32ss/drivers/displays/vga_new` ("Microsoft NT4 DDK Sample Code License").
  - `fbtusb` points to a LICENSE.TXT that is not in the tree.

---

## 2. Component table

Stage column = Okno plan stage where the action is needed (0 bench, 1 apps, 2 x64/WoW64/SMP, 3 desktop PC, 4 laptop, 5 WDDM); "—" = no action planned.

### 2.1 Bus, ACPI, power

| Win10 counterpart | ReactOS path | Lines | Origin / license | Real state (evidence) | Best option 2026 | Stage |
|---|---|---|---|---|---|---|
| acpi.sys | `drivers/bus/acpi` | 131k (ACPICA 120k, busmgr 3.9k, glue ~7k) | ACPICA 20221020 (BSD-3 / GPLv2 dual, header of `acpica/dispatcher/dsargs.c`); `busmgr/` derived from Linux ACPI bus driver (GPLv2-or-later header); own glue | Built, boot-start (`txtsetup.sif [BootBusExtenders.Load]`). All 9 functions in `interface.c` are `UNIMPLEMENTED` (GPE connect/enable, notifications). No EC address-space handler (`CONFIG_ACPI_EC` never defined; `busmgr/bus.c:1735`). No `_PRT` evaluation. Resource conversion covers only IRQ/DMA/IO/MEM/ADDRESS (`buspdo.c:905-1290`), with no GpioInt/I2cSerialBus → no `CmResourceTypeConnection`. FIXME "Generate unique id" (`buspdo.c:522`). | **Rewrite** as a Windows-compatible ACPI bus driver on uACPI (MIT; claims NT-compatible AML semantics; in-tree 7.0.0 = latest tag). Keep this acpi.sys as fallback until parity. Fallback interpreter: ACPICA 20260408. | 2 (start), 3–4 |
| (new acpi.sys) | `drivers/bus/acpi_new` | 35.8k (uACPI 35.4k) | uACPI 7.0.0 MIT + own `uacpiosl.c` | **Not built** (absent from `drivers/bus/CMakeLists.txt`). `main.c`: `DriverEntry` calls `ACPIInitUACPI()` then `UNIMPLEMENTED; return STATUS_NOT_IMPLEMENTED`. | Base of the rewrite | 2–3 |
| pci.sys | `drivers/bus/pci` | 3.5k | own (Casper Hornstrup era); `pcidef.h` "Ported from linux pci.h" **[Linux-derived]** | **This is the active PCI driver** (`hivesys.inf:2009` ImagePath `pci.sys`; txtsetup `*PNP0A03 = pci`). MSI only as `#define`s in `pcidef.h`; no ECAM. | **Drop** after pcix parity | 2 |
| pci.sys (Windows-style) | `drivers/bus/pcix` | 17.6k | own (BSD header) + 2026 MIT files `pci/ecam.c`, `pci/express.c`, `pci/rbar.c` (Justin Miller) | Built and shipped as `pcix.sys`, but **no service binds it**. U=0, T=3. Arbiters, bus interfaces (`intrface/routintf.c`), ECAM, PCIe capabilities, Resizable BAR. No MSI. | **Keep**: rename to pci.sys, add MSI/MSI-X (+ later PCIe hot-plug) | 2–3 |
| (msisadrv / ISA PnP) | `drivers/bus/isapnp` | 5.4k | own GPL-2.0+ | Built; bound to `*PNP0A00` **and `PCI\CC_0601` (LPC bridge on every PC)** in txtsetup. | **Drop** ISA-PnP card code; bind `PCI\CC_0601` to a tiny no-op bus driver like Windows `msisadrv` | 3 |
| pcmcia.sys | `drivers/bus/pcmcia` | 0.4k | own | Stub, U=3 | **Drop** | 2 |
| cmbatt.sys | `drivers/acpi/cmbatt` | 3.7k | own BSD | Built, U=4; on laptops needs ACPI notify + EC (both missing in acpi.sys) | Keep | 4 |
| battc.sys / compbatt.sys | `drivers/battery/battc`, `compbatt` | 0.4k / 2.8k | own GPL / MIT | Built | Keep | 4 |
| processr.sys (+ intelppm/amdppm) | `drivers/processor/processr` | 0.55k | own **[GPLv2-only]** | Minimal shell; no P-/C-state code | **Rewrite** (license + function): kernel PPM using `_PSS/_CST/_CPC` | 4 |
| Thermal zones, EC, lid/power buttons (inside Windows acpi.sys) | `drivers/bus/acpi/busmgr/button.c`, `buspdo.c:741-771` | — | Linux-derived | Buttons partly; thermal zones only get an ID; no EC | Implement in the new acpi.sys | 4 |
| PEP / PoFx (Modern Standby) | — | 0 | — | Missing | Later; S3 first | 4 |

### 2.2 Storage

| Win10 counterpart | ReactOS path | Lines | Origin / license | Real state (evidence) | Best option 2026 | Stage |
|---|---|---|---|---|---|---|
| storport.sys | `drivers/storage/port/storport` | 7.3k | own GPL-2.0+ (2017+) | 64 exports. `StorPortExtendedFunction` handles 4 codes (AllocatePool, FreePool, InitializeTimer, RequestTimer). Every other code hits `UNIMPLEMENTED` (`storport.c:859`). U=16, T=43; no MSI. `sdk/include/ddk/storport.h` enum stops at `ExtFunctionFreeTimer` (Win8-era). | **Complete / rewrite to Win10 level**: SRB_EX / `STORAGE_REQUEST_BLOCK`, MSI-X, perf optimizations, DPC/worker/timer, PoFx stubs. Test with virtio viostor/vioscsi (BSD-3), OFA NVMe, and the MS storahci sample **[MS-PL: own .sys]**. | 3 |
| stornvme.sys | — | 0 | — | **Missing**; no `PCI\CC_0108` mapping anywhere | **Port OFA NVMe Windows driver 1.5** (Dec 2016, BSD-style, StorPort miniport, SVN `svn.openfabrics.org/svnrepo/nvmewin`), then modernize. FreeBSD `nvme(4)` (BSD) as reference. | 3 |
| storahci.sys | `drivers/storage/port/storahci` | 3.3k | own GSoC 2016 **[GPLv2-only]** | **Not shipped** (`add_cd_file` commented; no HWID in txtsetup). No NCQ (`InquiryData->CommandQueue = 0`), no error recovery (`Notes.txt`). | **Drop**. AHCI already runs via pciidex + atapi. For StorPort-AHCI parity tests, use the MS storahci sample **[MS-PL: own .sys]**. | 3 |
| scsiport.sys | `drivers/storage/port/scsiport` | 8.3k | own GPL-2.0+ | Built; U=10, T=14 | Keep (legacy miniports; low priority) | — |
| (VMware BusLogic) | `drivers/storage/port/buslogic` | 4.6k | VMware GPL-2.0+ | BT-958 only | **Drop** | 3 |
| pciide.sys / pciidex.sys (AHCI + PATA controller) | `drivers/storage/ide/pciide`, `pciidex` | 0.1k / 15.3k | `pciidex.c` own 2005 ("See COPYING"); `chipset/*.c` MIT/BSD-2, 2026 (Dmitry Borisov) | **Active** for `PCI\CC_0101/0104/0105/0106` (txtsetup). Handles AHCI (`chipset/ahci_*.c`) and PATA chipsets (intel/amd/via/…); exports the `PciIdeX*` API. T=3. **x64 BSOD on QEMU i440FX PIIX IDE** (measured); q35 AHCI boots. | **Keep**; fix the x64 PIIX crash | 2 |
| ataport.sys role (ATA/ATAPI port + SATL) | `drivers/storage/ide/atapi` | 12.9k | own MIT 2026 | **Active** (`*PNP0600 = atapi`, plus channel PDOs from pciidex). SATL `satl.c` T=13, SMART, power, WMI. | **Keep** (best open option) | 2 |
| (legacy ISA IDE) | `drivers/storage/ide/legide` | 0.85k | MIT 2026 | Built only on i386 when `!ENABLE_UNIATA` | Keep for i386; not in amd64 product | — |
| (UniATA) | `drivers/storage/ide/uniata` | 36k | UniATA 0.47b BSD-like | Built, but commented out in txtsetup | **Drop** once the new stack is validated | 3 |
| — | `drivers/storage/ide/atapi_old` | 7k | **Microsoft EULA** text | Not built | **Delete** (license) | 2 |
| disk.sys / classpnp.sys | `drivers/storage/class/disk`, `classpnp` | 13.9k / 45.3k | Windows-driver-samples **[MS-PL: own .sys]**, commits 3428c5f / 88541f7 | Built, used | **Keep**; resync with samples repo HEAD f4c1ff8 (2026-10-28) | 3 |
| cdrom.sys | `drivers/storage/class/cdrom` | 35.2k | samples 96eb96d **[MS-PL: own .sys]**, KMDF driver | Built | Keep. Current samples repo has only `storage/class/{classpnp,disk}`, so the in-tree copy is now the only source. | — |
| sfloppy.sys | `drivers/storage/class/sfloppy` | 3.5k | **[MS-PL]** | Not built | **Drop** | 2 |
| ramdisk.sys | `drivers/storage/class/ramdisk` | 2.5k | own BSD | Used for RAM-disk / livecd boot | Keep | — |
| fdc/flpydisk | `drivers/storage/floppy/*` | 5.7k | own (`fdc` **[GPLv2-only]**) | fdc + floppy built; flpydisk not | **Drop** | 3 |
| partmgr.sys + volmgr.sys | `drivers/storage/partmgr` | 2.9k | own GPL-2.0+ (2020) | UpperFilter of the DiskDrive class (`hivesys.inf:402`). Creates `\Device\HarddiskVolumeN` (`partition.c:31`), so it also does volmgr's job ("volmgr.sys does not (yet) exist", `partmgr.c:8`). GPT OK. | **Keep**; split out volmgr only if needed | — |
| mountmgr.sys | `drivers/storage/mountmgr` | 9.9k | own GPL | Built, T=1 | Keep | — |
| uaspstor.sys | — | 0 | — | Missing | Later (StorPort miniport over UCX) | 3 (low) |
| Intel RST / AMD RAID / VMD (vendor) | — | — | vendor StorPort miniports | Need full StorPort + MSI | Covered by the storport task | 3 |

### 2.3 USB

| Win10 counterpart | ReactOS path | Lines | Origin / license | Real state (evidence) | Best option 2026 | Stage |
|---|---|---|---|---|---|---|
| USBXHCI.SYS | `drivers/usb/usbxhci` | 0.67k | own MIT; `kmdfdriver` + UCX client (links `ucxstub`) | Skeleton: U=8; `controller.cpp` has only WDF/UCX callback shells | **Keep the KMDF+UCX architecture and write the hardware layer** from the xHCI 1.2 spec. References: Haiku `xhci.cpp` (MIT), FreeBSD `xhci` (BSD-2). | 3 |
| UCX01000.SYS | `drivers/usb/ucx01000` | 0.84k | own MIT | U=23: every `UcxApi*` export is a stub | Implement from MS UCX docs + in-tree `sdk/include/ucx/1.6` | 3 |
| USBHUB3.SYS | `drivers/usb/usbhub3` | 0.17k | own MIT | U=4 | Implement | 3 |
| usbport.sys + usbehci/usbohci/usbuhci | `drivers/usb/usbport`, `usbehci`, `usbohci`, `usbuhci` | 18.7k + 5.3k / 3.8k / 3.8k | own GPL-2.0+ (Vadim Galyant) | Used (txtsetup `[InputDevicesSupport.Load]`); usbport U=35, T=51 | Keep (EHCI on pre-xHCI PCs; OHCI/UHCI for VMs) | — |
| usbhub.sys (USB 2) | `drivers/usb/usbhub` | 11.2k | own GPL-2.0+ | U=20, T=34 | Keep | — |
| usbccgp.sys / usbd.sys | `drivers/usb/usbccgp`, `usbd` | 3.8k / 0.7k | own GPL | Built | Keep | — |
| usbstor.sys | `drivers/usb/usbstor` | 4.3k | own GPL-2.0+ | Built; U=1, T=10 | Keep | — |
| — | `drivers/usb/usbstor_new` | 6.9k | own | Not built | **Delete** | 2 |
| usbaudio.sys / usbaudio2.sys | `drivers/usb/usbaudio` | 4k | own GPL | Not built; U=14 | **Rewrite** as a UAC1/UAC2 driver (portcls/AVStream) | 4 |
| UcmUcsiCx (USB-C) | — | — | — | Missing | Later; MS `usb/UcmUcsiAcpiSample` **[MS-PL: own .sys]** as reference | 4 |
| usbvideo.sys (UVC) | — | — | — | Missing | Write on KS/AVStream from the UVC 1.5 spec | 4 |

### 2.4 Network

| Win10 counterpart | ReactOS path | Lines | Origin / license | Real state (evidence) | Best option 2026 | Stage |
|---|---|---|---|---|---|---|
| ndis.sys | `drivers/network/ndis` | 13.7k | own (2000–2003) | **NDIS 3/4/5.x only**: `miniport.c:2744` switches on `MajorNdisVersion` 3/4/5. `ndis.spec` has 292 exports and none of `NdisMRegisterMiniportDriver`, `*NetBufferList*`, `NdisRegisterProtocolDriver`, `NdisFRegisterFilterDriver`. `ddk/ndis.h` defines the `NDIS_SUPPORT_NDIS6` macros but mentions `NET_BUFFER` only twice. U=102, T=27. | **Rewrite to NDIS 6.50+** (6.50 = Windows 10 1507 baseline): NBL data path, miniport/protocol/filter, OID requests, binding engine. Keep NDIS 5 miniports through a translation shim. MS samples `network/ndis/netvmini`, `filter`, `ndisprot` **[MS-PL: own .sys]** serve as tests. | 3 |
| tcpip.sys | `drivers/network/tcpip` | ≈25k own + 148k lwIP | own + lwIP 2.2.0 (modified BSD) | TCP via lwIP; `LWIP_UDP 0` (`include/lwip/lwipopts.h:34`); no `LWIP_IPV6` (no IPv6); own IPv4/ARP/ICMP/UDP; TDI only; NDIS 5 protocol | **Rewrite** as an NDIS 6 protocol + TDI + WSK provider on lwIP 2.2.1: IPv4+IPv6, UDP in lwIP, SACK/window scaling. Port FreeBSD netinet/netinet6 (BSD) only if lwIP throughput is not enough. Stub the WFP callout API. | 3 |
| afd.sys | `drivers/network/afd` | 6.5k | own | Built | Keep; rebase on the new tcpip | 3 |
| tdi.sys | `drivers/network/tdi` | 0.9k | own | Built | Keep (legacy TDI clients) | — |
| netio.sys (WSK) | `drivers/network/netio` | 1.5k | own MIT 2023–2025 | Exports `WskRegister/Deregister/CaptureProviderNPI/ReleaseProviderNPI`; implemented over TDI | **Keep**; move under the new tcpip, add IPv6/UDP | 3 |
| ndisuio.sys | `drivers/network/ndisuio` | 1.9k | own | Built (used by the WLAN config path) | Keep until the Wi-Fi rewrite | — |
| — | `drivers/network/lan` | 2k | own | Not built | **Delete** | 2 |
| e1g60 / e1i63 (Intel) | `drivers/network/dd/e1000` | 2.5k | own GPL-2.0+ | NDIS 5.0; 37 IDs, all 8254x. **No 82574L (DEV_10D3 = QEMU q35 default `e1000e`), no I21x/I22x.** | Keep for VMs (QEMU `-device e1000`, VirtualBox). Add an in-box NDIS 6 driver for I219/I225/I226 (FreeBSD `em`/`igc`, BSD, as reference); Intel's official Win10 drivers via NDIS 6. | 3 |
| rt640x64 (Realtek GbE/2.5GbE) | — | — | — | Missing (only the 100 Mbit `rtl8139`) | Write an in-box NDIS 6 driver for RTL8111/8168/8125 (FreeBSD `re`, OpenBSD `rge` as reference); Realtek's official driver via NDIS 6 | 3 |
| (VM NICs) | `dd/rtl8139`, `dd/pcnet` | 1.8k / 2.5k | own | NDIS 5 | Keep for the test bench | — |
| (legacy NICs) | `dd/ne2000`, `dd/nvnet`, `dd/dc21x4` | 3k / 7.4k / 9.6k | own (nvnet, dc21x4 GPL-2.0+) | NDIS 5.1 | **Drop** (dc21x4 only if a bench VM needs it) | 3 |
| netkvm (virtio-net) | `dd/netkvm` | 9.5k | virtio-win NDIS5 tree, 5e01b36 (2018), BSD-3 | NDIS 5.1 | **Replace** with upstream NetKVM `wlh` (NDIS 6, BSD-3) once NDIS 6 lands | 3 |
| Wi-Fi: WDI host (wdiwifi.sys), nwifi, WlanSvc | — | 0 | — | Missing. `psdk/windot11.h` (100 lines), `wlantypes.h` (13 lines); no `dot11wdi.h` | **Implement a WDI host** from public WDI docs (WDI was the "universal Wi-Fi driver model" of Windows 10, now in maintenance mode), so vendor Win10 Wi-Fi drivers load. wpa_supplicant 2.11 (BSD-3) for the supplicant. WiFiCx (Win11, NetAdapterCx-based) later. | 4 |
| bthport/bthusb | `drivers/bluetooth/fbtusb` | 8.1k | FreeBT 2004; LICENSE.TXT not in tree | Raw USB Bluetooth, not the Win10 model | **Drop**; write bthport/bthusb later | 4 (late) |

### 2.5 Audio, kernel streaming, multimedia

| Win10 counterpart | ReactOS path | Lines | Origin / license | Real state (evidence) | Best option 2026 | Stage |
|---|---|---|---|---|---|---|
| portcls.sys | `drivers/wdm/audio/backpln/portcls` | 19.2k | own | WaveCyclic/WavePci/WaveRT/Topology/DMus ports; U=41, T=36 (10 `UNIMPLEMENTED` in the WaveRT files) | **Keep, complete WaveRT** (Win10 audio drivers are WaveRT) | 3 |
| ks.sys | `drivers/ksfilter/ks` | 20k | own | U=76, T=69 | Keep; complete AVStream | 3–4 |
| sysaudio / kmixer / wdmaud / splitter / stream / drmk | `drivers/wdm/audio/{sysaudio,filters,legacy,drm}` | 1.8k / 1.1k / 3.2k / 0.6k / 1.4k / 0.1k | own | XP-style kernel mixing graph (kmixer U=10, drmk U=7) | Keep for now. Win10 mixes in user mode (audiodg); decide together with the user-mode KB. | 3 |
| HDAudBus.sys | `drivers/wdm/audio/hdaudbus` | 5.9k | CoolStar sklhdaudbus, BSD-3, KMDF. In-tree 5477b93 = upstream HEAD (2026-04-27). | Exposes `HDAUDIO_BUS_INTERFACE`, `_BDL`, `_V2`, `_V3` (`buspdo.cpp:517-552`). README: Skylake→Raptor Lake, AMD, NVIDIA HDMI; works with Windows codec drivers. | **Keep**, track upstream | 3 |
| HdAudio.sys (HDA codec function driver) | — | 0 | — | **Missing**: no INF matches `HDAUDIO\FUNC_01` | **Write** a WaveRT miniport from the Intel HDA spec. References: FreeBSD `snd_hda` (BSD), Haiku `hda` (MIT). MS `audio/sysvad` **[MS-PL: own .sys]** as a WaveRT reference only. | 3 |
| (VM AC'97) | `drivers/wdm/audio/drivers/ac97` | 14.2k | MS WDK 8.1 sample, MIT | Built | Keep for VMs | — |
| (legacy cards) | `wdm/audio/drivers/CMIDriver`, `sb16`, `mpu401`, `drivers/multimedia/audio/*` | 7.6k / 0.7k / 0.1k / 5k | BSD-3 / own | CMI built; the rest not built | **Drop** | 2 |
| BDA support | `drivers/multimedia/bdasup` | 1.1k | own | U=6 | Keep (low) | — |
| swenum.sys | `drivers/ksfilter/swenum` | 0.4k | own | Built | Keep | — |
| ACX (Win11 audio class extension) | — | — | — | Missing | Later | — |

### 2.6 Input, HID

| Win10 counterpart | ReactOS path | Lines | Origin / license | Real state (evidence) | Best option 2026 | Stage |
|---|---|---|---|---|---|---|
| i8042prt / kbdclass / mouclass | `drivers/input/*` | 4.7k / 1.3k / 1.3k | own GPL | Used (class UpperFilters in `hivesys.inf:414,421`) | Keep | — |
| (bus/serial mouse) | `drivers/input/inport`, `sermouse` | 1.4k / 1.2k | own | Legacy | **Drop** | 3 |
| hidclass / hidparse / hidusb / kbdhid / mouhid | `drivers/hid/*` + `sdk/lib/drivers/hidparser` | 3.1k / 0.1k+5.1k / 2.1k / 1.2k / 1.4k | own GPL | Used; hidparser U=35 | Keep; finish hidparser | 3 |
| hidi2c.sys | — | 0 | — | Missing | **Write** from the HID-over-I2C spec 1.0. References: FreeBSD `iichid` (BSD-2), Haiku `i2c_hid` (MIT). The only open Windows I2C touchpad driver found (MouseLikeTouchPad_I2C) is GPL-3.0, so not usable. | 4 |
| SpbCx, GpioClx, ACPI resource hub | — | 0 | — | Missing; no `spb.h`, `spbcx.h`, `gpioclx.h` | **Write** from MS docs. Validate with MS `spb/SkeletonI2C`, `SpbTestTool`, `gpio/samples` **[MS-PL: own .sys]**, then Intel Serial IO vendor drivers. | 4 |

### 2.7 File systems, filters

| Win10 counterpart | ReactOS path | Lines | Origin / license | Real state (evidence) | Best option 2026 | Stage |
|---|---|---|---|---|---|---|
| ntfs.sys | `drivers/filesystems/ntfs` | 20.6k | own GPL-2.0+ | Writes disabled by default: `EnableWriteSupport = FALSE` (`ntfs.c:84`); write/set-info return `STATUS_ACCESS_DENIED` (`dispatch.c:86-115`). U=7, T=52; no journal replay. | **Not production.** Best GPL-compatible base: libntfs-3g (GPL-2.0-or-later, mature read/write) inside a kernel FSD, or a rewrite. Paragon `ntfs3` is Linux GPLv2-only (excluded). **Owner decision needed; highest-risk FS item.** | 3 |
| fastfat.sys | `drivers/filesystems/fastfat` | 75k | samples 16022c5 **[MS-PL: own .sys]** | Used (`hivesys` `Services\fastfat`) | Keep | — |
| — | `drivers/filesystems/vfatfs` | 15.3k | own GPL-2.0+ | Shipped only when `SARCH == xbox` | **Drop** | 2 |
| cdfs.sys | `drivers/filesystems/cdfs` | 37.5k | samples f73e552 **[MS-PL: own .sys]** | Used | Keep | — |
| udfs.sys | `drivers/filesystems/udfs` | 76k | SKIF 1999–2013, "released under the GPLv2 on June 2015" (or-later unclear) | Built, T=21 | Keep (low); clarify license | — |
| exfat.sys | — | 0 | — | Missing | Write from Microsoft's published exFAT spec | 3 |
| (WinBtrfs) | `drivers/filesystems/btrfs` | 98k | WinBtrfs 1.8.1, LGPL-3.0-or-later (own .sys) | Built | **Update to 1.10** (2026-09-01) | 2 |
| (Ext2Fsd) | `drivers/filesystems/ext2` | 105k | Ext2Fsd 0.69, GPL-2.0+ | Built | **Update to Ext4Fsd 0.71** (bobranten fork, active 2026-04) | 3 |
| nfs41_driver | `drivers/filesystems/nfs` | 8.2k | CITI NFSv4.1, LGPL-2.1+ | Built | Keep (low) | — |
| npfs / msfs / mup / fs_rec | `drivers/filesystems/*` | 6.8k / 1.2k / 2.8k / 2.8k | own (npfs BSD) | Core; npfs U=10, mup U=5 | Keep | — |
| fltmgr.sys | `drivers/filters/fltmgr` | 5.5k | own GPL | U=6, T=7 | **Keep, complete** (minifilters: AV, cloud files, etc.) | 1–3 |
| rdbss + mrxsmb (SMB client) | `sdk/lib/drivers/rdbsslib`, `rxce` (libraries only) | 9.6k + 9.2k | own | No SMB mini-redirector | **Write** an SMB2/3 mini-redirector; libsmb2 (LGPL-2.1) as protocol core | 3 |
| cldflt / wof / luafv / bindflt | — | 0 | — | Missing | As apps need them (see usermode KB) | 1+ |

### 2.8 WDF and driver libraries

| Win10 counterpart | ReactOS path | Lines | Origin / license | Real state (evidence) | Best option 2026 | Stage |
|---|---|---|---|---|---|---|
| Wdf01000.sys + WdfLdr.sys (KMDF) | `sdk/lib/drivers/wdf` | 241k | microsoft/Windows-Driver-Frameworks (MIT) at d9c6040 = "Windows Release win-10.0.10586.0" (2015-12-11) | KMDF **1.17** (`__WDF_MINOR_VERSION=17`; headers `sdk/include/wdf/kmdf/1.17`). Binding fails when the driver's Minor > 17 (`version.cpp:488`). | **Update** to 3b9780e "win-10.0.22621.1" (2022-11-10): public headers up to KMDF 1.33 / UMDF 2.33. Last source release; repo's last commit is 2024-09-10. | 2 |
| UMDF 2 (WUDFHost, WUDFRd) | `sdk/lib/drivers/wdf/umdf/fxlib` only | — | MIT | No host, no reflector | Build the UMDF parts of the same repo + write the reflector | 4 |
| virtio library | `sdk/lib/drivers/virtio` | 3.4k | virtio-win, BSD-3, 4c4d181 (2023-12-12) | Built | **Update** to upstream HEAD (bd196cda, 2026-10-23). Add viostor, vioscsi, NetKVM `wlh`, vioinput, viogpu as bench drivers. | 3 |
| (helper libs) | `sdk/lib/drivers/{arbiter,csq,copysup,aux_klib,rtlver,sptilib,usbdex,ucxstub}` | 4.3k / 0.4k / 0.7k / 0.2k / … | own | Libraries | Keep | — |
| (Vista+ kernel helpers) | `sdk/lib/drivers/ntoskrnl_vista` | 0.8k | own | Static lib that gives *in-tree* drivers Vista+ APIs | Gotcha: vendor binaries need these as real `ntoskrnl.exe` exports (core KB) | 2 |
| cng.sys | — | 0 | — | Missing; `ksecdd.spec` has 39 exports | **Write** cng.sys over SymCrypt (MIT; in tree 103.11.0, upstream 103.13.0) | 3 |

### 2.9 Video, display, fonts (`win32ss/drivers`)

| Win10 counterpart | ReactOS path | Lines | Origin / license | Real state (evidence) | Best option 2026 | Stage |
|---|---|---|---|---|---|---|
| videoprt.sys (XPDM; Windows 8+ dropped it) | `win32ss/drivers/videoprt` | 9.5k | own BSD | 152 exports; U=24, T=33 | Keep for XPDM until dxgkrnl | — |
| dxgkrnl.sys / dxgmms2.sys | — | 0 | — | **Missing**. Headers exist: `ddk/d3dkmddi.h` (2.1k lines, MIT 2024), `ddk/dispmprt.h` (1.75k), `ddk/d3dkmthk.h` (6k, libdxg MIT), `DXGKDDI_INTERFACE_VERSION` up to WDDM 3.1 (`psdk/d3dukmdt.h:54`). No UMD DDI headers (`d3dumddi.h`, `d3d10umddi.h`, `d3d12umddi.h`). `win32ss/gdi/ntgdi/d3dkmt.c:29` has TODO "Let DxgKrnl know…". | **Write dxgkrnl** from MS docs: display-only (KMDOD) first, then render. First miniports: MS `video/KMDOD` sample **[MS-PL: own .sys]**, virtio `viogpu`. | 5 |
| BasicDisplay.sys (UEFI GOP) | — (`drivers/base/bootvid/framebuf` = boot screen only) | — | — | UEFI freeldr passes `CM_FRAMEBUF_DEVICE_DATA` (`boot/freeldr/freeldr/arch/uefi/uefihw.c:24`). Only bootvid (`lfbbvid`) and the Xbox code use it; no display miniport does. | **Write** an XPDM GOP-framebuffer miniport (stage 3); a WDDM Basic Display later | 3 |
| (VM/BIOS display) | `miniport/vga`, `vbe` (vgapnp), `bochs` | 0.9k / 1.6k / 0.8k | own | Used | Keep | — |
| — | `miniport/vmx_svga` | 0.4k | own | Not shipped; U=10 | **Drop** | 2 |
| — | `miniport/pc98vid`, `xboxvmp` | 1.1k / 0.7k | own GPL-2.0+ | i386 only | **Drop** | 2 |
| — | `miniport/vga_new`, `displays/vga_new` | 4.4k / 1.8k | BSD / **"Microsoft NT4 DDK Sample Code License"** | Not built | **Delete** | 2 |
| (XPDM display DLLs) | `displays/framebuf`, `displays/vga` | 1.9k / 4k | own | Used | Keep (XPDM) | — |
| (font driver) | `font/ftfd` | 1.7k | own glue + FreeType 2.10.0 (`sdk/lib/3rdparty/freetype`) | Built | Keep the glue; **update FreeType to 2.15.0** | 1 |
| — | `font/bmfd` | 1.5k | own | Built, not shipped | Keep (low) | — |
| watchdog.sys | `win32ss/drivers/watchdog` | 0.2k | own | U=26 | Keep; needed later for dxgkrnl TDR | 5 |

### 2.10 Base, debug, misc

| Win10 counterpart | ReactOS path | Lines | Origin / license | Real state (evidence) | Best option 2026 | Stage |
|---|---|---|---|---|---|---|
| beep.sys / null.sys | `drivers/base/beep`, `null` | 0.4k / 0.2k | own | OK | Keep | — |
| bootvid.dll | `drivers/base/bootvid` | 4.3k | own; framebuf variant GPL-2.0+ or MIT | VGA + generic linear framebuffer (`add_bootvid(lfbbvid …)`) | Keep | — |
| condrv.sys | `drivers/base/condrv` | 0.3k | own | Small | Keep; grows with the Win8+ console model (usermode KB) | 1 |
| kdcom.dll / kdnet.dll | `drivers/base/kdcom`, `kdgdb`, `kdvm`, `kdstub`, `kdrosdbg` | 1k / 3k / 0.8k / … | own | Serial KD, GDB stub, VirtualKD. **No KDNET** (only headers `sdk/include/reactos/kdnet*.h`). | Keep; add KDNET for PCs without a COM port | 3 |
| sacdrv.sys | `drivers/sac/driver` | 8.6k | own BSD | EMS console | Keep (zero cost) | — |
| serial.sys / serenum.sys | `drivers/serial/*` | 2.7k / 1.5k | own | T=32 / 15 | Keep (debug COM). MS samples `serial/serial`, `serenum` **[MS-PL: own .sys]** are an alternative. | — |
| parport.sys | `drivers/parallel/*` | 1.2k / 0.3k | own | parport built; parallel/parclass not | **Drop** | 3 |
| (setup console) | `drivers/setup/blue` | 1.8k | own GPL-2.0+ | Text-mode setup console | Keep while usetup exists | — |
| ksecdd.sys | `drivers/crypto/ksecdd` | 1.5k | own MIT | 39 exports | Keep; add cng.sys | 3 |
| wmilib.sys | `drivers/wmi` | 0.06k | own | OK | Keep | — |
| nmidebug | `drivers/base/nmidebug` | 0.07k | own BSD | OK | Keep | — |

---

## 3. Remember-once knowledge

### 3.1 Adding a driver to the build and the ISO (`sdk/cmake/CMakeMacros.cmake`)

1. Add `add_subdirectory(<dir>)` in the parent `CMakeLists.txt`. **Folders missing from the parent list are silently not built:** `acpi_new`, `usbstor_new`, `usbaudio`, `atapi_old`, `sfloppy`, `flpydisk`, `vga_new` (miniport), `lan`, `sb16`, `mpu401`, `parallel`, `parclass`, `multimedia/audio/*`.
2. Write the module itself:
   ```cmake
   add_library(foo MODULE ${SOURCE} foo.rc)
   set_module_type(foo kernelmodedriver)   # or wdmdriver | kmdfdriver
   add_importlibs(foo ntoskrnl hal)        # imports of other .sys go here
   ```
   - `kernelmodedriver` / `wdmdriver`: entry point is `DriverEntry`.
   - `kmdfdriver`: entry point is `FxDriverEntry`. It also links `wdfdriverentry`, imports `wdfldr`, and adds the include path `sdk/include/wdf/kmdf/1.17` (lines 653, 703).
   - gcc builds `kmdfdriver` as `wdmdriver` (`sdk/cmake/gcc.cmake:404`).
   - The `.sys` suffix and signing are set automatically.
3. Put the file on the ISO with `add_cd_file(TARGET foo DESTINATION reactos/system32/drivers [NO_CAB] FOR all)`.
   - `FOR all` = bootcd + livecd + regtest.
   - `NO_CAB` keeps the file out of `reactos.cab`. Boot-critical drivers that setupldr loads must be `NO_CAB`.
4. Choose how the driver gets its service entry:
   - **PnP driver with an INF:** `add_driver_inf(foo foo.inf)`. The INF is converted to UTF-16 and copied to `reactos/inf`.
   - **Registry-only service:** `add_registry_inf(foo_reg.inf)`. It is merged into the default hives at build time, like `boot/bootdata/hivesys.inf` (see `create_registry_hives`).
5. Boot-critical devices also need the `txtsetup.sif` entries (3.2).

### 3.2 Boot-critical drivers: `txtsetup.sif` + `hivesys.inf`

**`boot/bootdata/txtsetup.sif`** is read by setupldr and usetup during text-mode setup:
- `[SourceDisksFiles]` with flag `x`: setupldr loads the file.
- `[HardwareIdsDatabase]`: hardware ID → service during setup. usetup reads it in `base/setup/usetup/devinst.c`. Current mappings:
  - `PCI\CC_0101/0104/0105/0106` → `pciide` (storahci and uniata are commented out).
  - `*PNP0600` → `atapi`.
  - `PCI\CC_0C0300/10/20` → `usbuhci`/`usbohci`/`usbehci`.
  - **No mapping for xHCI (`PCI\CC_0C0330`) or NVMe (`PCI\CC_0108`).**
- Load sections: `[BootBusExtenders.Load]` (acpi, pci, isapnp), `[BusExtenders.Load]` (pciide, atapi), `[SCSI.Load]`, `[InputDevicesSupport.Load]`, `[Keyboard.Load]`. Architecture-specific entries go in `[SourceDisksFiles.x86]` / `[SourceDisksFiles.amd64]`.

**`boot/bootdata/hivesys.inf`** holds the default service keys (Group/Start/Tag/ImagePath) and class filters:
- DiskDrive UpperFilters = `partmgr` (line 402); Keyboard = `kbdclass` (414); Mouse = `mouclass` (421).
- 90 `CriticalDeviceDatabase` lines. The kernel uses them for boot devices (`ntoskrnl/io/pnpmgr/pnpmgr.c:50`).
- PCI is `Services\Pci` → `pci.sys` (lines 2007–2016).

### 3.3 PnP enumeration, driver loading and INF install at runtime

Kernel PnP:
- Lives in `ntoskrnl/io/pnpmgr/`.
- `devaction.c` enumerates devnodes, loads services (`IopLoadDriver`, line 473) and calls `AddDevice` (`PiCallDriverAddDevice`, line 595).
- Devices listed in CriticalDeviceDatabase start without user-mode help.
- For any other new device, the kernel queues a PnP event to user mode.

User-mode install chain:
1. `umpnpmgr` (`base/services/umpnpmgr`): `event.c` queues the device and `DeviceInstallThread` (`install.c:527`) calls `InstallDevice` (`install.c:55`).
2. `InstallDevice` starts `rundll32.exe newdev.dll,ClientSideInstall` as the user (`install.c:162`).
3. newdev (`dll/win32/newdev/newdev.c`) calls:
   - `SetupDiBuildDriverInfoList` (line 315)
   - `SetupDiCallClassInstaller(DIF_SELECTBESTCOMPATDRV)` (line 563)
   - `DIF_ALLOW_INSTALL`, then the install itself
4. setupapi (`dll/win32/setupapi`) searches `%SystemRoot%\inf\` (`driver.c:27`). It understands:
   - Decorated sections such as `.NTamd64` (`devinst.c:148-186`).
   - `Include=` / `Needs=` (`install.c:121-122, 1337-1349`).
   - Catalog adding via `CryptCATAdmin*` (`misc.c:1275`), but signatures are **not enforced**.

What Windows 10 INFs need that is missing:
- `[*.Wdf]` / `KmdfService` handling: no match for `KmdfService` in setupapi, newdev or umpnpmgr.
- DriverStore (`FileRepository`) and `pnputil.exe`: none in tree.
- Many Win10 vendor INFs assume these.

### 3.4 Driver-model headers (`sdk/include`)

| Model | Present | Notes |
|---|---|---|
| WDM / NTDDK / NTIFS | `xdk/`, `ddk/` (128 files), `ndk/` | Generated from `xdk` |
| KMDF | `wdf/kmdf/1.17` only | Upstream WDF repo has 1.15–1.33 and UMDF 2.15–2.33 |
| UCX | `ucx/1.6/{ucxclass,ucxcontroller,ucxendpoint,ucxfuncenum,ucxglobals,ucxobjects}.h` | Used by usbxhci/ucx01000 |
| StorPort | `ddk/storport.h` (3,279 lines) | Ext-function enum ends at `ExtFunctionFreeTimer` |
| NDIS | `ddk/ndis.h` (6,228 lines), `psdk/ntddndis.h` (548) | NDIS 6 version macros only; no NBL structures (no `ndis/nbl.h`), no NetAdapterCx/WiFiCx, no WDI |
| WSK / NetIO | `ddk/wsk.h` (622), `ddk/netioddk.h` (158), `psdk/netiodef.h` | No WFP kernel headers (`fwpsk.h`, `fwpmk.h` missing) |
| WDDM | `ddk/d3dkmddi.h` (2,074), `ddk/dispmprt.h` (1,754), `ddk/d3dkmthk.h` (6,038), `psdk/d3dukmdt.h`, `psdk/d3dkmdt.h` | Versions up to WDDM 3.1 defined. **UMD DDIs missing** (`d3dumddi.h`, `d3d10umddi.h`, `d3d12umddi.h`, `dxgiddi.h`). Partial vs WDK. |
| Audio | `ddk/portcls.h` (2,554), `ddk/hdaudio.h` (440, incl. V2/V3/BDL), `ddk/drmk.h`, `ddk/ksmedia` etc. | No ACX |
| HID / input | `ddk/hidport.h`, `hidclass.h`, `psdk/hidpi.h`, `kbdmou.h` | No `spb.h`, `spbcx.h`, `gpioclx.h`, `sercx.h` |
| Power / ACPI | `ddk/acpiioct.h`, `ddk/poclass.h`, `psdk/batclass.h` | No `pep_x.h` (PoFx/PEP) |
| Other missing | — | `wdmsec.h`, `iddcx.h`, `ufxclient.h`, `ucmcx.h`, `sdport.h`, `usbspec.h` (only a private copy in `sdk/lib/drivers/wdf/usbspec.h`) |

### 3.5 Storage stack layering (as it is now)

```
pci.sys (FDO on PNP0A03/PNP0A08)
 └─ pciide.sys  ← PCI\CC_0101/0104/0105/0106 (PATA, SATA-IDE, RAID, AHCI)
     + pciidex.sys (library/bus: AHCI and PATA controller code, chipset/*.c) → channel PDOs
        └─ atapi.sys (ATA port: ATA/ATAPI commands, SATL SCSI→ATA, SMART, power)
            └─ disk.sys / cdrom.sys (MS classpnp, MS-PL)
                └─ partmgr.sys (DiskDrive UpperFilter; makes partition + \Device\HarddiskVolumeN; also does volmgr work)
                    └─ mountmgr.sys (drive letters, unique IDs) → FS: fastfat / ntfs / btrfs / cdfs / udfs / ext2
Legacy: legide (x86, PNP0600 ISA IDE) → atapi;  scsiport ← buslogic / uniata;  storport ← (no shipped miniport)
USB:  usbehci|ohci|uhci → usbport → usbhub → usbccgp → usbstor → disk
```

How Windows 10 differs:
- AHCI is `storahci` (StorPort miniport) and NVMe is `stornvme` (StorPort miniport). pciide/pciidex + ataport handle PATA only.
- `volmgr.sys` is separate from partmgr.
- USB3 storage goes xHCI → UCX → usbhub3 → usbstor/uaspstor.

Okno plan: keep the pciidex+atapi path for AHCI/PATA and add a real StorPort for NVMe and vendor miniports.

### 3.6 Other stacks in one line each

- **USB 2:** USB2 controller miniport → `usbport` → `usbhub` (root and external hubs) → `usbccgp` / class drivers.
- **USB 3:** `usbxhci` (KMDF, UCX client) → `ucx01000` → `usbhub3`, all skeletons. KMDF drivers bind to WDF through `wdfldr` (`WdfVersionBind`); UCX binds through `ucxstub`.
- **Network:** NIC miniport (NDIS 5) → `ndis.sys` → `tcpip.sys` (NDIS 5 protocol; TDI upper edge) → `afd.sys` (Winsock) and `netio.sys` (WSK over TDI). `ndisuio` serves the user-mode WLAN tools.
- **Audio:** HW miniport → `portcls` (WaveCyclic/WavePci/WaveRT) → `ks` → `sysaudio` + `kmixer` → `wdmaud.sys` ↔ `wdmaud.drv` (user mode). HDA: `hdaudbus` → *(missing codec function driver)*.
- **Input:** `i8042prt` → `kbdclass`/`mouclass` (class UpperFilters); USB HID: `hidusb` → `hidclass` → `kbdhid`/`mouhid` → class drivers.
- **Display:** `videoprt` + miniport (vga/vbe/bochs) ↔ display DLL (framebuf/vga) in win32k. No dxgkrnl; boot screen via `bootvid`.

### 3.7 Gotchas

- **No MSI/MSI-X, and the failure is silent.** `IoConnectInterruptEx` with `CONNECT_MESSAGE_BASED` or `CONNECT_LINE_BASED` only prints "…UNIMPLEMENTED". It then **returns `STATUS_SUCCESS` without connecting anything** (`ntoskrnl/io/iomgr/irq.c:211-219`). A Win10 driver therefore believes it is connected and then hangs waiting for interrupts. Only `CONNECT_FULLY_SPECIFIED(_GROUP)` works. Make the stub fail with `STATUS_NOT_SUPPORTED` before MSI lands, so drivers fall back to line-based interrupts.
- **PCI IRQ = config-space `InterruptLine`** (`hal/halx86/legacy/bus/pcibus.c:733-742`); `_PRT`/`_PIC` are not used. On UEFI-only machines in APIC mode `InterruptLine` can be 0/0xFF, which means no IRQ.
- **KMDF 1.17 cap.** Drivers built for KMDF 1.19+ fail with `STATUS_OBJECT_TYPE_MISMATCH` (`version.cpp:488-514`). Most Win10 vendor KMDF drivers target 1.15–1.33.
- **pci.sys vs pcix.sys.** The service `Pci` loads the old `pci.sys`. `pcix.sys` is on the ISO but unused. Test pcix by changing `Services\Pci\ImagePath`.
- **acpi_new is not built** even though it has `add_cd_file`. Its `DriverEntry` returns `STATUS_NOT_IMPLEMENTED`.
- **AHCI does not go through storahci.** storahci is not on the ISO and has no hardware ID. `PCI\CC_0106` → `pciide`.
- **x64 on QEMU:** pciidex BSODs on i440FX PIIX IDE; use `-machine q35` (AHCI).
- **QEMU q35 default NIC is e1000e (82574L), which in-tree e1000 does not support.** Use `-device e1000` (82540EM), `rtl8139` or `pcnet`. virtio-net needs the NDIS5 `netkvm`.
- **`ndis.h` claims NDIS 6** (`NDIS_SUPPORT_NDIS6` macros, lines 257–297), but the NBL types and functions are absent. Do not trust the macros.
- **NTFS writes are off by default** (`EnableWriteSupport`, registry-controlled, `ntfs.c:84-114`).
- **`ntoskrnl_vista` is a static library for in-tree drivers only.** A vendor `.sys` resolves imports against the real `ntoskrnl.exe` export table, so check exports, not that library.
- **`UNIMPLEMENTED` counts understate gaps.** Many missing features are simply absent: no MSI code, no NDIS 6 exports, no EC handler.
- **MS-PL boundary.** Never move code from cdrom/classpnp/disk/fastfat/cdfs, or any Windows-driver-samples code, into GPL files (e.g. into storport or partmgr). Calling across `.sys` boundaries through exports and IRPs is fine.

---

## 4. Ordered task list (stages 2–5, this area)

Each task has an acceptance check. "Bench" = QEMU via `tools/qemu/vm.py`, plus real PCs from stage 3 on.

### Stage 2 — x64 by default, WoW64, SMP

1. **Fix the x64 pciidex BSOD on PIIX IDE** (`drivers/storage/ide/pciidex`, `chipset/intel.c`).
   *Accept:* the amd64 bootcd installs and boots 3× in a row on QEMU `pc` (i440FX, IDE) and on `q35` (AHCI); regtest runs.
2. **x64 driver sweep** of the in-tree drivers kept by this audit (e1000, rtl8139, pcnet, ac97, hdaudbus, usbehci/uhci/ohci + usbstor + hidusb, cdrom, btrfs).
   *Accept:* amd64 bench matrix passes: ping and HTTP download; USB keyboard/tablet input; USB stick mount + 100 MB copy with matching hash; AC'97/HDA WAV playback (driver loads, stream runs).
3. **SMP hardening.**
   *Accept:* `-smp 4` on amd64. A 12 h stress (disk copy + network download + USB I/O) finishes with no bugcheck and no `ASSERT`.
4. **Update WDF** to Windows-Driver-Frameworks 3b9780e (KMDF 1.33; headers `sdk/include/wdf/kmdf/1.33`; `kmdfdriver` include path).
   *Accept:* an MS sample built against KMDF 1.33 (`general/echo` kmdf, **[MS-PL: own .sys]**) loads and passes its test app. cdrom, usbxhci and hdaudbus still load.
5. **Switch PCI to pcix**: rename it to pci.sys, drop the old pci.sys and its Linux-derived `pcidef.h`.
   *Accept:* on i440FX, q35 and 2 real PCs the device tree dump (`devmgmt`/registry Enum) matches the old driver. Extended config space is readable via ECAM on q35.
6. **Start the new acpi.sys on uACPI** (`acpi_new`): enumeration, resources, power/sleep buttons, `IOCTL_ACPI_EVAL_METHOD`; old acpi.sys stays as fallback.
   *Accept:* on QEMU q35/i440FX the same PnP tree as old acpi.sys; shutdown via the ACPI power button works.
7. **Remove dead code** (stage-2 "Delete/Drop" rows: atapi_old, usbstor_new, lan, vga_new, vfatfs, vmx_svga, pc98vid, xboxvmp, sb16/mpu401/multimedia/audio, CMIDriver, pcmcia, sfloppy).
   *Accept:* full x86 + amd64 build plus bench boot pass; the ISO file list no longer contains them.
8. **Update WinBtrfs to 1.10.**
   *Accept:* create, write and read a 1 GB file on btrfs, then remount; `btrfs check` from a Linux live image of the test disk on the bench reports no errors.
9. **Quick win in `IoConnectInterruptEx`** (`irq.c:211-219`):
   - implement `CONNECT_LINE_BASED` by resolving the PDO's translated interrupt resource and connecting it fully specified;
   - make `CONNECT_MESSAGE_BASED` return `STATUS_NOT_SUPPORTED` until MSI lands, instead of a silent `STATUS_SUCCESS`.

   *Accept:* a rostests kernel test driver gets a working line-based ISR (interrupt count > 0) on q35, and a clean error for message-based.

### Stage 3 — modern desktop PC (UEFI/GOP, NVMe, xHCI, Ethernet, HDA)

1. **MSI/MSI-X end to end**: HAL vector allocation, `IoConnectInterruptEx(CONNECT_MESSAGE_BASED)`, pcix capability programming, `CM_RESOURCE_INTERRUPT_MESSAGE` resources.
   *Accept:* on q35 an MSI-capable device (AHCI or virtio) runs with MSI enabled (config-space MSI Enable bit = 1, interrupts counted) under `-smp 4`. MSI-X is shown on virtio-net or NVMe.
2. **ACPI for real PCs** in the new acpi.sys: `_PRT` routing in APIC mode (and pass it to pcix via `PCI_INT_ROUTE_INTERFACE`), `ACPI_INTERFACE_STANDARD2`, GPE, `_OSI("Windows 2015…2022")`, `_DSM`, S3/S5.
   *Accept:* on 2 UEFI-only PCs (Intel + AMD) every PCI device gets a working interrupt; S5 by power button; S3 resume on at least one.
3. **GOP framebuffer display miniport** (XPDM, uses `CM_FRAMEBUF_DEVICE_DATA` from UEFI freeldr).
   *Accept:* on a UEFI class-3 PC (CSM off) and on OVMF the desktop appears at the native GOP resolution; screenshot checked.
4. **StorPort to Win10 level.**
   *Accept:* virtio `viostor` and `vioscsi` (BSD-3, upstream HEAD) install and boot as the system disk on q35. The MS storahci sample **[MS-PL: own .sys]** boots the system from AHCI.
5. **NVMe**: port OFA nvmewin 1.5 as stornvme-equivalent, plus the `PCI\CC_0108` mapping in txtsetup.
   *Accept:* on QEMU `-device nvme`, plus 1 real NVMe SSD:
   - install + boot;
   - 10 GB sequential copy with matching hash;
   - TRIM IOCTL succeeds.
   Then a vendor Win10 NVMe driver (e.g. Samsung NVMe driver) loads on a matching SSD.
6. **xHCI / UCX / hub3**: implement them, plus the `PCI\CC_0C0330` mapping in txtsetup.
   *Accept:*
   - QEMU `qemu-xhci` with `usb-kbd`, `usb-tablet`, `usb-storage` works, including hot-plug, in setup and on the desktop;
   - 2 real PCs (Intel + AMD): keyboard in setup, and a USB 3 stick copy above 100 MB/s.
7. **NDIS 6.50+ core** with an NDIS 5 shim.
   *Accept:*
   - MS `netvmini` and `ndisprot` samples **[MS-PL: own .sys]** load and pass traffic;
   - existing NDIS 5 e1000/rtl8139 still work;
   - NetKVM `wlh` (NDIS 6) works on QEMU.
8. **New tcpip** (NDIS 6 protocol, lwIP 2.2.1, IPv4+IPv6+UDP, TDI + WSK via netio).
   *Accept:* DHCPv4 + SLAAC; `ping -6`; a browser test page loads over IPv4 and IPv6; iperf ≥ 900 Mbit/s on 1 GbE (bench); WSK echo sample works.
9. **NICs for real PCs**:
   - in-box NDIS 6 drivers for Intel I219/I225 and Realtek RTL8111/8125 (FreeBSD/OpenBSD as references);
   - official Intel/Realtek Win10 drivers via INF install.
   *Accept:* both chip families get DHCP and ≥ 900 Mbit/s on real hardware, with both the in-box and the vendor driver.
10. **HD Audio**: an HDA codec function driver (WaveRT) on hdaudbus; complete WaveRT in portcls.
    *Accept:* playback and capture on QEMU `intel-hda` + `hda-duplex` and on 2 real Realtek ALC codecs (WAV play + mic record round-trip).
11. **NTFS decision and implementation** (ntfs-3g-based kernel FSD or rewrite; owner decides).
    *Accept:* mount an NTFS volume created by Windows 10 read/write; run a file-ops torture suite (create/rename/delete/large files/ACL read); then on a Windows VM `chkdsk /f` reports no errors.
12. **Other stage-3 work, each with its own check:**
    - cng.sys over SymCrypt: a kernel BCrypt test driver (hash / AES / RNG) matches known vectors.
    - Resync classpnp/disk.
    - Ext4Fsd 0.71: read and write an ext4 volume and verify file hashes.
    - exFAT: create/read on a 64 GB exFAT stick formatted by Windows; files match.
    - SMB2/3 client: map a Samba share and copy 1 GB in both directions.
    - KDNET: kernel debugger over Ethernet on a COM-less PC.
13. **Drop legacy**: isapnp (keep a no-op `PCI\CC_0601` binding), floppy, inport, sermouse, parport, buslogic, uniata, ne2000, nvnet.
    *Accept:* build + bench boot pass; the LPC bridge shows a driver with no error state.

### Stage 4 — laptops

1. **Laptop ACPI**: EC operation-region handler, `_Qxx` events, lid and power buttons, thermal zones, battery via cmbatt/compbatt.
   *Accept:* on 2 laptops, battery % and charging state are correct; lid close → S3 → resume.
2. **GpioClx + SpbCx + ACPI resource hub** (`CmResourceTypeConnection`).
   *Accept:* MS `gpio/samples` (simgpio) and `spb/SkeletonI2C` + `SpbTestTool` **[MS-PL: own .sys]** work. Intel Serial IO (LPSS I2C/GPIO) vendor Win10 drivers load and enumerate I2C children.
3. **hidi2c.sys**.
   *Accept:* touchpad pointer + buttons and the I2C keyboard work on 2 laptops; device survives S3.
4. **Wi-Fi**: WDI host + WLAN service/API + supplicant.
   *Accept:* official Intel AX200/AX210 Win10 driver and one MediaTek or Realtek driver connect to WPA2-PSK and WPA3-SAE, and stay up through S3.
5. **Processor power**: rewrite processr; kernel PPM using `_PSS/_CST/_CPC`.
   *Accept:* CPU frequency changes under load (MSR or perf counter readout); idle reaches C-states deeper than C1; battery drain at idle measured vs before.
6. **UMDF 2 host**.
   *Accept:* MS `usb/umdf2_fx2` or `gnss/gnssUmdf` sample **[MS-PL: own .sys]** loads in WUDFHost.
7. **Further laptop devices**: USB Audio Class 1/2, UVC webcam (AVStream), USB-C UCSI, bthport/bthusb.
   *Accept:*
   - USB headset plays and records;
   - webcam shows a preview in a capture app;
   - USB-C role switch is logged;
   - a Bluetooth mouse pairs (Bluetooth may slip past stage 4).

### Stage 5 — WDDM GPUs

1. **dxgkrnl display-only path**: `DxgkInitialize`, miniport callbacks, VidPN, present to win32k/CDD.
   *Accept:* MS `video/KMDOD` sample **[MS-PL: own .sys]** and virtio `viogpu` (display-only) drive the screen on QEMU/OVMF and on one UEFI PC; mode change works.
2. **Complete the WDDM headers** (`d3dkmddi.h`, UMD DDIs `d3dumddi.h`, `d3d10umddi.h`, `d3d12umddi.h`, `dxgiddi.h`) from public docs and libdxg (MIT).
   *Accept:* an Intel or AMD Win10 driver package's import and export tables resolve against our dxgkrnl/gdi32 export lists (tool check).
3. **Render path**: GPU scheduler, video memory manager, D3DKMT syscalls, UMD loading.
   *Accept:* the official Intel UHD (Gen9+) Win10 driver loads; DXGI enumerates the adapter; a D3D11 triangle sample renders. Then AMD, then NVIDIA.
4. **TDR via watchdog + HDMI/DP audio** through hdaudbus with the GPU audio function.
   *Accept:* an injected GPU hang recovers without a bugcheck; HDMI audio plays.

---

## Sources

- In-tree evidence: all paths and line numbers above come from ReactOS master `e46f4bb1`. `media/doc/3rd Party Files.txt` gives third-party versions.
- WDF versions: `git clone https://github.com/microsoft/Windows-Driver-Frameworks` (log: d9c6040 = win-10.0.10586.0 2015-12-11; 3b9780e = win-10.0.22621.1 2022-11-10; HEAD b6191d9 2024-09-10; `src/publicinc/wdf/kmdf/1.15…1.33`, `umdf/2.15…2.33`; LICENSE MIT).
- Windows-driver-samples tree (HEAD f4c1ff8, 2026-10-28; LICENSE MS-PL): https://github.com/microsoft/Windows-driver-samples. Has storage/miniports/{storahci,lsi_u3}, storage/class/{classpnp,disk}, network/ndis/*, network/wlan/{WDI,wificx}, video/KMDOD, audio/sysvad, spb, gpio, usb/Ucm*.
- StorAHCI sample page: https://learn.microsoft.com/en-us/samples/microsoft/windows-driver-samples/storahci-storport-miniport-driver
- ACPICA 20260408 / 20251212: https://lkml.iu.edu/2605.3/06288.html, https://lkml.iu.edu/2601.1/11617.html, https://www.intel.com/content/www/us/en/download/776307/acpi-component-architecture-downloads-unix-format-source-code-and-build-environment-with-a-dual-license.html
- uACPI (NT-compatible AML claims, MIT; tags via `git ls-remote`, latest 7.0.0): https://github.com/uACPI/uACPI
- WinBtrfs 1.10: https://phoronix.com/news/WinBtrfs-1.10
- lwIP 2.2.1 tag `STABLE-2_2_1_RELEASE` (git ls-remote https://github.com/lwip-tcpip/lwip); release notes summary: https://software-dl.ti.com/mcu-plus-sdk/esd/AM62X/latest/exports/docs/api_guide_am62x/NETWORKING_LWIP.html
- OFA NVMe Windows driver 1.5 (BSD-style, SVN): https://lists.openfabrics.org/pipermail/nvmewin/2016-December/001420.html, https://lists.openfabrics.org/pipermail/nvmewin/2017-March/001439.html, https://lists.openfabrics.org/pipermail/nvmewin/2016-September/001396.html
- NDIS 6.50 = Windows 10 1507: https://learn.microsoft.com/en-us/windows-hardware/drivers/network/introduction-to-ndis-6-50
- WDI (Windows 10 Wi-Fi model, maintenance mode) / WiFiCx (Windows 11): https://learn.microsoft.com/en-au/WINDOWS-HARDWARE/DRIVERS/network/wdi-miniport-driver-design-guide, https://learn.microsoft.com/en-gb/windows-hardware/drivers/netcx/wifi-wdf-class-extension-wificx
- wpa_supplicant 2.11 (2024-07-20, BSD-3): https://lists.launchpad.net/debcrafters-packages/msg04936.html
- Haiku xHCI (MIT): https://cgit.haiku-os.org/haiku.git/tree/src/add-ons/kernel/busses/usb/xhci.cpp
- HID over I2C / SpbCx architecture: https://learn.microsoft.com/en-us/windows-hardware/drivers/hid/architecture-and-overview. GPL-3.0 touchpad driver (not usable): https://www.github.com/jxleyo/MouseLikeTouchPad_I2C
- ReactOS WDDM investigation (out-of-tree work; master has no dxgkrnl): https://reactos.org/blogs/investigating-wddm/, https://www.phoronix.com/news/ReactOS-WDDM-Effort
- virtio-win upstream (HEAD bd196cda 2026-10-23; dirs viostor, vioscsi, viogpu, NetKVM/wlh): https://github.com/virtio-win/kvm-guest-drivers-windows
- CoolStar sklhdaudbus (HEAD 5477b93 2026-04-27): https://github.com/coolstar/sklhdaudbus
- Ext4Fsd fork (tag v0.71, last commit 2026-04-27): https://github.com/bobranten/Ext4Fsd
- FreeType tags (VER-2-15-0): https://gitlab.freedesktop.org/freetype/freetype. SymCrypt tags (v103.13.0): https://github.com/microsoft/SymCrypt
