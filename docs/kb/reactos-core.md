# ReactOS core audit for Okno OS: boot, kernel, HAL, RTL, system processes

Source audited: ReactOS master shallow clone, commit `e46f4bb1a1e` (2026-10-25). Where the Okno fork differs (build
settings), it is marked **[fork]**. Paths are relative to the source root.

How the numbers were measured. "Lines" is a raw `wc -l` over `*.c *.h *.S *.s *.asm *.cpp *.inc`. Marker counts come
from `grep` over the same files: `UNIMPLEMENTED` (whole word, so `_DBGBREAK`/`_ONCE` are counted separately), `TODO`,
`FIXME` and `STATUS_NOT_IMPLEMENTED`. They also count macro mentions in comments, so treat them as a heat map, not an
exact score. The counting script was `cnt.sh <paths>`, kept in the session scratchpad.

---

## 1. Summary: the biggest keep/replace decisions

- **Keep the NT kernel core and raise its level.** That means ke, mm, io, ob, se, ps, cm, ex, fsrtl and kd64. No
  GPL-compatible NT kernel can replace it, and it is ReactOS's real asset. But it is NT 5.2 throughout:
  - 299 syscalls: 296 from NT5 plus 3 from NT6 (`ntoskrnl/include/sysfuncs.h`). Windows 10/11 have roughly 450–500 (public j00ru/windows-syscalls tables).
  - Of 1659 `ntoskrnl.spec` exports, only 15 are gated ≥0x600.
  - The kernel builds with `NTDDI_VERSION=0x05020400` (`ntoskrnl/ntos.cmake`) and reports 5.2.3790
    (`sdk/include/psdk/ntverp.h`).
  - These NT6+ syscalls are missing: ALPC, `NtCreateUserProcess`, `NtCreateThreadEx`, `NtWaitForAlertByThreadId`,
    `Nt*VirtualMemoryEx`/`*SectionEx`, `NtQuerySystemInformationEx`, and all KTM syscalls.

  Stage 1 work = add the NT6–10 syscalls, info classes and token features, ordered by the import analyzer.
- **x64 runs on one CPU, sees at most 8 GB, and has no WoW64.**
  - `KeStartAllProcessors` on amd64 is `UNIMPLEMENTED` (`ntoskrnl/ke/amd64/mproc.c`).
  - `HalStartNextProcessor` on amd64 is `//TODO: return FALSE` (`hal/halx86/smp/amd64/spinup.c`).
  - The loader caps physical memory at `MM_MAX_PAGE 0x1FFFFF` (8 GB), "HACK … CORE-20265"
    (`boot/freeldr/freeldr/include/mm.h`).
  - `KiSystemCallEntry32` is `swapgs; int 3` (`ke/amd64/trap.S`).
  - `BUILD_WOW64_ENABLED` is never defined by the build.

  Stage 2: write AP startup and IPIs, lift the cap, and port Wine 11.x `wow64`/`wow64cpu`/`wow64win` (LGPL).
  `wow64win` must be re-targeted to ReactOS win32k syscalls.
- **HAL: keep the ACPI+APIC HAL and extend it; stop building the other HALs.**
  - MSI/MSI-X is missing. `IoConnectInterruptEx(CONNECT_MESSAGE_BASED)` prints a FIXME and returns
    `STATUS_SUCCESS` without connecting anything, which is a latent bug (`ntoskrnl/io/iomgr/irq.c`).
  - PCI config access is port CF8/CFC only: no MCFG/ECAM, so no extended config space.
  - x2APIC exists only as an unbuilt scaffold (`hal/halx86/x2apic`).
  - No HPET. The clock is the RTC periodic IRQ. Reboot is only via 8042 port 0x64.
  - Stop building the PIC, legacy, MPS, PC-98, Xbox and ARM HALs for Okno.
- **UEFI: keep and finish FreeLoader's `uefildr.efi`.** It is the only GPL-compatible loader that builds a
  `LOADER_PARAMETER_BLOCK`. Gaps:
  - Runtime services are not handed to the kernel. `ex/efi.c` has 15 `UNIMPLEMENTED`, and every
    `Nt*SystemEnvironmentValueEx` is too.
  - SMBIOS is only searched at physical 0xF0000 (`wmi/smbios.c`).
  - No command line comes from the load options.
  - Setup does not write an ESP or `Boot####` entry.

  `boot/bcd` and `boot/bgfx` are empty placeholders, so don't plan a BCD/bootmgr clone. Keep the BIOS path only as a
  CI fallback.
- **RTL: keep it (own code plus Wine actctx/threadpool) and fix the blockers.**
  - `RtlWaitOnAddress`, `RtlWakeAddressAll` and `RtlWakeAddressSingle` are `UNIMPLEMENTED`
    (`sdk/lib/rtl/waitaddress.c`). That breaks `WaitOnAddress`, which Wine `kernelbase` calls.
  - Resync `threadpool.c` (Wine-9.7) and `actctx.c` (Wine-10.0) to Wine 11.x.
  - The heap has no LFH. Wine has had LFH since 8.3 (LGPL), which is an option later.
- **Power, ETW/WMI and crash dumps are stubs. Rewrite them from WDK docs.**
  - Power only does shutdown. `NtSetSystemPowerState` logs "you may not have chosen a yet supported power option",
    and there is no S3, S4 or PoFx.
  - `EtwRegister` and `EtwWrite` return `STATUS_NOT_IMPLEMENTED` (`sdk/lib/drivers/ntoskrnl_vista/etw.c`).
  - 23 `IoWMI*`/`Wmi*` functions are `UNIMPLEMENTED`.
  - `IoInitializeCrashDump` is `UNIMPLEMENTED`, so no dumps are ever written.

  Order: ETW (minimal) in stage 1, crash dumps in stage 2, power in stage 4.
- **Registry (Cm + cmlib): keep it and fill the API gaps.**
  - `NtRenameKey`, `NtRestoreKey`, `NtReplaceKey`, `NtQueryMultipleValueKey`, `NtCompressKey`, `NtLockRegistryKey`,
    `NtSetInformationKey`, `NtUnloadKeyEx` and `NtQueryOpenSubKeysEx` are `UNIMPLEMENTED`.
  - Hives are written as v1.3 and read up to v1.5, with a single `.LOG` file.
  - There is no transactional registry and no `CmRegisterCallbackEx`.
- **System processes follow the NT 5.2 model: keep them and extend them where apps notice.**
  - The chain is smss → csrss + winlogon (GINA `msgina.dll`), and winlogon itself starts `services.exe` and
    `lsass.exe`.
  - The SCM accepts only config levels 1–2: no delayed-auto-start, no SID type, no triggers, and no
    `NotifyServiceStatusChange`. Extend it in stage 1.
  - Replace the csrss console (`consrv`, 21.5k lines) with OpenConsole/conhost (microsoft/terminal, MIT) plus a new
    `condrv.sys` for ConPTY.
  - Drop NTVDM (39k lines) from x64 builds.
- **Build levers. [fork]**
  - The fork builds with clang 18 + Ubuntu mingw-w64, and `DLL_EXPORT_VERSION` defaults to 0x600. Spec stats:
    1792 exports gated 0x600+, 85 at 0x601+, 36 at 0x602+, 1 at 0x603+, 16 at 0xA00+, and 101 that exist only up
    to 0x502.
  - However, `-D_WIN32_WINNT=0x502 -DWINVER=0x502` are still global (`CMakeLists.txt` lines 238–240), and
    ntoskrnl still uses NTDDI 0x05020400.
  - Raising the kernel NTDDI changes structure layouts that the loader, HAL and kernel share (e.g. the
    `FirmwareInformation` field of the loader block). Do it once, deliberately, in stage 2, rebuilding all three
    together.
- **Third-party updates in this area.**
  - ACPICA `20221020` → `20260930` (latest tag, 2026-09-30). Take it under the BSD-3 dual-license option, because
    the "GPL-2.0" listing in `3rd Party Files.txt` would make the combined work GPLv2-only.
  - EDK2 headers `sdk/include/reactos/edk2` (18 headers, Intel BSD, 2006–2012) → MdePkg from `edk2-stable202608`
    (BSD-2-Clause-Patent).
  - Wine-derived RTL parts → Wine 11.20 (dev, 2026-10-16) or 11.0 (stable).

---

## 2. Component table

Columns: Windows 10 counterpart | ReactOS path | approx. lines | origin | real state, with evidence |
best option in 2026 | plan stage. "Drop" = stop building and testing it in Okno. The files stay in the tree so
upstream merges stay clean.

### 2.1 Boot

| Component | Win10 counterpart | Path | Lines | Origin | State (evidence) | Best option 2026 | Stage |
|---|---|---|---|---|---|---|---|
| BIOS boot sectors | MBR/PBR + bootmgr (BIOS) | `boot/freeldr/bootsect` (fat, fat32, ntfs, ext, btrfs, iso*), `boot/freeldr/freeldr/arch/realmode` | 6.6k + 1.8k | own | Work in VMs. FAT/ISO paths described in `boot/freeldr/notes.txt`. | **Keep as CI fallback only** (QEMU SeaBIOS); freeze after stage 3. Target PCs are UEFI-only. | 0–2 |
| FreeLoader stage 1 (BIOS) | bootmgr | `boot/freeldr/freeldr/freeldr.c`, `arch/i386/pc`, `lib/*`, `disk/*`, `ui/*` | ~25k | own (FreeLoader, GPL-2.0+) | Two-stage: `BootMain` inits mach, UI, mm, FS and devices, then loads `rosload.exe`, registered under module name `scsiport.sys` because it exports `ScsiPort*` for `ntbootdd.sys`. FS readers: FAT, NTFS, ext, btrfs, ISO, PXE (`lib/fs`, 7.6k). GPT supported (`disk/part_gpt.c`). `disk/scsiport.c` has 19 `UNIMPLEMENTED` (x86 only). | **Keep** (shared library code for the UEFI path) | 0 |
| UEFI front-end `uefildr.efi` | bootmgfw.efi | `boot/freeldr/freeldr/arch/uefi`, `uefi.cmake` | 3.5k | own (2023+, J. Miller), EDK2 headers | Single stage: no rosload; NT loader linked in. Provides a GOP framebuffer (`uefivid.c`) published as ARC "UEFI GOP Framebuffer", the ACPI RSDP/XSDT from the config table (`uefihw.c`), BlockIo disks (`uefidisk.c`) and the memory map + `ExitBootServices` (`uefimem.c`). Gaps: (1) `CmdLine = ""; // FIXME: Determine a command-line from UEFI boot options`. (2) The SMBIOS config table is not passed. (3) Runtime services are not passed to the kernel: no `SetVirtualAddressMap`, `EfiInformation` empty. (4) On x64 only the first 1 GB is mapped (`MM_MAX_PAGE_LOADER 0x3FFFF`), and RAM is capped at 8 GB. (5) "FIXME: Detect more devices". (6) Not signed for Secure Boot. | **Keep + finish.** GRUB, Limine and similar can't build an NT loader block, so the alternatives are only chain loaders. Secure Boot later via `shim` (rhboot, BSD-style). | 2–3 |
| NT OS loader (winldr) | winload.efi | `boot/freeldr/freeldr/ntldr` (+ `ntoskrnl/config/cmboot.c`, `ke/config.c` compiled in) | 9.0k | own | Builds an **NT 5.2-layout** `LOADER_PARAMETER_BLOCK`: `FirmwareInformation` only exists if NTDDI ≥ LONGHORN, and EFI boot is flagged via `Extension->BootViaEFI`. Loads the kernel (`KERNEL=`), HAL (`HAL=`), KD DLL (`kd<port>.dll` registered as `kdcom.dll`), bootvid (`bootvid.dll`/`lfbbvid.dll`) and boot drivers from the SYSTEM hive. `3GB`, `SAFEBOOT` and `BOOTLOGO` are "not implemented" FIXMEs (`winldr.c` 766–785). | **Keep.** Extend the LPB to the NT6.x layout when the kernel NTDDI is raised. Pass SMBIOS, EFI runtime and ACPI pointers. | 2–3 |
| setupldr | WinPE boot | `ntldr/setupldr.c`, `boot/bootdata/txtsetup.sif` | 0.7k + data | own | NT5-style text-mode setup boot. `DETECTHAL` is honoured. | **Keep for now**, revisit with the installer | — |
| BCD | BCD store + bootmgr | `boot/bcd` (empty `.keep`), `boot/bootdata/hivebcd.inf` | 0 | own | Only a BCD-hive *template* pointing to `\reactos\system32\boot\rosload.efi`. No code reads it, and `boot/bgfx` is empty too. | **Drop BCD.** Keep `freeldr.ini`. Read-only BCD only if `bcdedit` compatibility is ever needed. | — |
| bootdata (hive INFs, ISO config) | default hives | `boot/bootdata/*.inf`, `bootcd.ini`, `livecd.inf` | 27.8k INF lines | own | Built into hives by `mkhive`. Holds Session Manager, `SubSystems` (csrss command line), `ServiceGroupOrder` and services. | **Keep**; prune the `*_pc98`/`*_xbox` variants from Okno images | 0 |
| Legacy targets | — | `arch/i386/pc98` (3.1k), `arch/i386/xbox` (1.5k), `boot/armllb` (3.3k), ARM UEFI bits, `hiveinst_{pc98,xbox}.inf`, `floppy_pc98.ini`, `bootsect/pc98` | ~9k | own | Only for PC-98, Xbox and ARM. | **Drop** (maintenance cost, no Okno target) | 0 |
| Chain/linux boot | — | `linuxboot.c`, `miscboot.c`, multiboot | 0.8k | own | Works; not needed. | **Keep, untested** (no cost) | — |
| Boot video | bootvid.dll, BGFX | `drivers/base/bootvid` (`framebuf/` → `lfbbvid.dll` for UEFI GOP), `ntoskrnl/inbv` (2.0k) | 4.3k + 2.0k | own | `NtLdrDetectBootVid` picks `lfbbvid.dll` on EFI. Inbv has 0 markers. | **Keep** | 3 |

### 2.2 Kernel (`ntoskrnl/`, 311.8k lines total, all own code, GPL-2.0+)

| Component | Win10 counterpart | Path | Lines | State (evidence) | Best option 2026 | Stage |
|---|---|---|---|---|---|---|
| Ke (scheduler, traps, IRQL, DPC/APC, IPI) | Ke | `ke/`, `ke/amd64` (6.8k), `ke/i386` (9.4k), `ke/x86x64` | 32.3k; UNIMPL 33, FIXME 86 | **amd64:** `KeStartAllProcessors` UNIMPLEMENTED. `KiSystemCallEntry32` = `int 3`. `KeRaiseUserException` and `KiNpxNotAvailableFaultHandler` UNIMPLEMENTED. Large pages, global pages, MTRR and PAT are "detected but not yet taken advantage of" (`kiinit.c` 50–75). SMEP/SMAP are detected (`cpu.c`) but never set in CR4; NX is on (`MSR_NXE`). XSAVE/AVX/AVX-512 state is supported (`xstate.c`). No KPTI or Spectre mitigations. **i386:** AP startup exists (`ke/i386/mproc.c`), but the generic IPI packet functions `ASSERT("Not yet implemented")` (`ke/ipi.c` 20–75). **Both:** NT5.2 single dispatcher lock, threaded DPC FIXME (`dpc.c` 800), "SMT support" FIXME, no processor-group APIs (`KeQueryActiveProcessorCountEx` etc. absent), `MAXIMUM_PROCESSORS` = 64 (x64) / 32 (x86). | **Keep + finish** SMP x64, IPIs and groups | 1–2 |
| Mm (ARM3 + legacy ROS Mm) | Mm | `mm/ARM3` (38.2k), `mm/` legacy (`section.c` 5.5k, `marea.c`, `rmap.c`, `pagefile.c`), `mm/amd64`, `mm/i386` | 52.1k; UNIMPL 40, DBGBRK 19 | Hybrid: ARM3 does pool, PFN, VAD, sysldr and anonymous memory. Legacy code (Rex Jolliff era, `MEMORY_AREA_SECTION_VIEW/CACHE`) still does file-backed sections and Cc. UNIMPLEMENTED: AWE (`NtAllocateUserPhysicalPages`, `NtMapUserPhysicalPages*`), `MmLockPageableDataSection`/`…ByHandle`, `MmSecureVirtualMemory`, `MmPrefetchPages`, `MmAdvanceMdl`, `MmForceSectionClosed`, `MmMarkPhysicalMemoryAsBad`/`Good`. No `NtAllocateVirtualMemoryEx`/`NtMapViewOfSectionEx`/`NtCreateSectionEx`. WoW64 address-space code is gated on the never-defined `BUILD_WOW64_ENABLED` (`ARM3/procsup.c`, `pagfault.c`). | **Keep**; add Ex APIs; lift the 8 GB cap; ARM3-ify sections only if stability requires | 1–2 |
| I/O manager | Io | `io/iomgr` | 26.7k; UNIMPL 21 | Message-based `IoConnectInterruptEx` is a silent no-op. `IoInitializeCrashDump` UNIMPLEMENTED (no dumps). `NtQueryEaFile`/`NtSetEaFile`, quota calls, `NtReadFileScatter`/`NtWriteFileGather`, `IoCheckQuerySetFileInformation` UNIMPLEMENTED. `IoGet/SetDevicePropertyData` are present. | **Keep + extend** (MSI, crash dump, EA) | 2–3 |
| PnP manager | PnP | `io/pnpmgr` (+`arb`) | 16.1k | Resource rebalance is faked (`PiFakeResourceRebalance`, "TODO: do resource rebalance"). `IoPnPDeliverServicePowerNotification` UNIMPLEMENTED. No container IDs (`IoRegisterContainerNotification` absent). | **Keep** | 3 |
| Power manager | Po + PoFx | `po/` | 2.4k; UNIMPL 14 | Shutdown only. `NtInitiatePowerAction`, `PoRegisterDeviceNotify`, `PoSetHiberRange`, `PoRegisterSystemState` and `PoStartNextPowerIrp` UNIMPLEMENTED. PoFx exists only as stubs in `sdk/lib/drivers/ntoskrnl_vista/pofx.c`. | **Rewrite** from WDK docs (system states, S3/S4, PoFx, power settings) | 4 |
| Object manager | Ob | `ob/` | 12.8k; UNIMPL 2 | Solid. Missing NT6: `ObRegisterCallbacks`, private namespaces. `ObShutdownSystem` and `ObGetObjectType` UNIMPLEMENTED. | **Keep** | 1/3 |
| Security ref. monitor | Se | `se/` | 21.0k; UNIMPL 19 (audit) | Token info classes stop at the NT5.2 set (`TokenUser`…`TokenSandBoxInert`, `TokenOrigin`). Anything else → `STATUS_INVALID_INFO_CLASS` (`se/tokencls.c`). No `TokenElevation*`, `TokenIntegrityLevel`, mandatory labels, `TokenLinkedToken` or AppContainer/LowBox. Auditing mostly UNIMPLEMENTED (`se/audit.c`). | **Keep + add NT6 integrity/elevation** | 1 |
| Process/thread | Ps | `ps/` | 16.2k; NOTIMPL 19 | No `NtCreateUserProcess` (which Wine `kernelbase/wine/process.c` uses) and no `NtCreateThreadEx`. No `PsSetCreateProcessNotifyRoutineEx(2)` or `PsSetLoadImageNotifyRoutineEx`. `NtCreateJobSet` UNIMPLEMENTED. `ProcessWow64Information` is a hack under `BUILD_WOW64_ENABLED`. | **Keep + add NT6 calls** | 1–2 |
| Registry (Cm) | Cm | `config/` + `sdk/lib/cmlib` | 18.8k + 10.3k | See summary. `HSYS_MINOR 3`, `HSYS_MINOR_SUPPORTED 5` (`cmlib/hivedata.h`). `cmapi.c` hits `UNIMPLEMENTED_DBGBREAK` on frozen/damaged hives. | **Keep + fill gaps.** Reference: public registry format specs (e.g. msuhanov "Windows registry file format specification"), docs only, no code copy | 1 |
| Cache manager | Cc | `cc/` (built) / `cache/` (NEWCC, not built: `NEWCC FALSE` in `ntos.cmake`) | 4.7k / 6.5k | `CcMdlRead`, `CcPrepareMdlWrite`, `CcMdlWriteComplete`/`Abort`, `CcSetLogHandleForFile`, `CcGetDirtyPages`, `CcGetLsnForFileObject` and `CcRemapBcb` UNIMPLEMENTED. | **Keep `cc/`; drop `cache/`** | 2–3 |
| Executive support | Ex | `ex/` | 23.0k; FIXME 108, NOTIMPL 60 | The `NtQuerySystemInformation` table lists 80 classes, ending at `SystemProcessorBrandString` (class 105). 26 of them have no handler (`SI_XX`); 10 of those are marked "FIXME: not implemented". There is no `NtQuerySystemInformationEx`. `ex/efi.c`: all `Nt*BootEntry*`/`Nt*DriverEntry*`/`NtTranslateFilePath` UNIMPLEMENTED. `NtQuery/SetSystemEnvironmentValueEx` and `NtEnumerateSystemEnvironmentValuesEx` UNIMPLEMENTED (`ex/sysinfo.c` 555–590). Keyed events, push locks and rundown are present. | **Keep + extend** | 1, 3 |
| FsRtl | FsRtl | `fsrtl/` | 11.8k; UNIMPL 0 | Complete for NT5.2. ECP helpers live in `ntoskrnl_vista`. | **Keep** | — |
| Fstub (partitions) | fstub | `fstub/` | 5.7k | MBR and GPT (`fstubex.c`, 51 GPT refs). | **Keep** | — |
| LPC | LPC/ALPC | `lpc/` | 4.4k | NT5 LPC works for csrss/smss/lsass. `NtReplyWaitReplyPort` and `NtQueryInformationPort` UNIMPLEMENTED. **No ALPC at all** (no `NtAlpc*` syscall, no `alpc/` dir). | **Keep LPC**; add an ALPC subset only if the import analyzer shows demand | 1+ |
| KD protocol (WinDbg) | kd64 | `kd64/` | 6.4k | x86/x64 complete. Only `KdpSysRead/WriteBusData` and `KdpSysCheckLowMemory` are UNIMPLEMENTED on amd64 (ARM: 14). Built when `_WINKD_=TRUE` (MSVC Debug default). | **Keep** | 0 |
| ReactOS debug log + KDBG | (none) | `kd/` (2.3k), `kdbg/` (13.1k) | 15.4k | Default for GCC/Clang Debug builds (`KDBG=TRUE`, `_WINKD_=FALSE`, `sdk/cmake/config.cmake`). Debug ports: SCREEN, COMn, FILE. KDBG is "broken" with x64 MP (comment in `base/setup/lib/settings.c`). | **Keep for x86 dev**; use kd64+WinDbg/GDB for x64 | 0 |
| KD transports | kdcom/kdnet/kdusb | `drivers/base/kdcom` (0.95k), `kdgdb` (3.0k), `kdvm` (0.8k), `kdrosdbg`, `kdstub` | — | Serial KD, a GDB stub and a VM-fast transport. **No network (KDNET) or USB3 debug transport.** | **Keep.** Add a network transport only for bare-metal debugging in stage 3. No open-source KDNET exists to reuse. | 0/3 |
| WMI / ETW | WMI, ETW | `wmi/` (1.8k), `sdk/lib/drivers/ntoskrnl_vista/etw.c`, `dll/ntdll/etw` | — | 23 `IoWMI*`/`Wmi*` and `NtTraceEvent` UNIMPLEMENTED. Kernel `EtwRegister`/`EtwWrite` return `STATUS_NOT_IMPLEMENTED`. | **Rewrite minimal ETW** (register/enable/write succeed; NtTraceControl). Real tracing later. | 1 |
| SMBIOS | SMBIOS provider | `wmi/smbios.c` | — | 2.1 and 3.0 entry points are parsed, but only physical **0xF0000–0xFFFFF** is searched, so it fails on UEFI-only PCs. | **Fix**: take the address from the loader (EFI config table) | 3 |
| Verifier | Driver Verifier | `vf/` | 75 | 4 stub functions | **Keep the stub**; real verifier much later | — |
| Kernel Shim Engine | KSE (NT6.2+) | `kse/` | 1.5k | Active (2020–2026 work). | **Keep** | 3 |
| Dbgk (user-mode debugging) | Dbgk | `dbgk/` | 2.7k; 0 markers | Complete for native processes. | **Keep** (needs WoW64 bits in stage 2) | 2 |
| VDM / V86 / ABIOS | (x86 only) | `vdm/`, `ke/i386/v86vdm.c`, `ke/i386/abios.c` (9 UNIMPL) | 1.5k | i386 only | **Drop** with NTVDM on x64. Keep on i386 while stage 1 runs on x86. | 2 |
| Syscall tables | KiServiceTable | `include/sysfuncs.h` (299), `include/internal/napi.h`, `ntdll.S`, `ntdll_nt6.S`, `ex/zw.S`; unused: `sysfuncs.lst`, `include/sysfuncs64.h` | — | Positional numbering, alphabetical NT5 list, then NT6 entries (`GetCurrentProcessorNumberEx`, `GetNextProcess`, `GetNextThread`). | **Keep the mechanism.** Delete or ignore the stale lists. | 1 |
| Kernel export surface | ntoskrnl.exe exports | `ntoskrnl.spec` (1659 exports), `hal/hal.spec` (110) + static `sdk/lib/drivers/ntoskrnl_vista` (811 lines) | — | Only 15 kernel exports are gated ≥0x600, and none in HAL. Absent: `ExAllocatePool2/3`, `KeQueryActiveProcessorCountEx`, `KeGetProcessorNumberFromIndex`, `KeQueryInterruptTimePrecise`, `KeQueryUnbiasedInterruptTime`, `ExAcquireSpinLockShared`, `ObRegisterCallbacks`, `CmRegisterCallbackEx`, `PsSetCreateProcessNotifyRoutineEx`, `MmAllocateContiguousNodeMemory`, `HalGetEnvironmentVariableEx`, `Ex{Get,Set}FirmwareEnvironmentVariable`. | **Extend** by driver-import analysis | 3 |

### 2.3 HAL (`hal/`, 30.8k lines, own code)

| Component | Win10 counterpart | Path | Lines | State (evidence) | Best option 2026 | Stage |
|---|---|---|---|---|---|---|
| Build variants | hal.dll (single, ACPI/APIC) | `hal/halx86/CMakeLists.txt` | — | **i386:** hal (PIC legacy), halacpi, halaacpi, halapic, halxbox, halpc98, halmacpi (SMP); `halmp` (MPS) is commented out. **amd64:** `hal` (generic+acpi+up+apic) and `halmp` (smp). | **Keep** amd64 hal/halmp, plus i386 halaacpi/halmacpi while stage 1 is x86. **Drop** hal (PIC), halapic, halacpi, xbox, pc98 and `mp/`. | 0–2 |
| generic | — | `halx86/generic` | 8.0k | Beep, CMOS, DMA, `x86bios.c` (VBE int10 via `fast486`). Reboot only through 8042 port 0x64 (`reboot.c`). "FIXME: Initialize DMA 64-bit support" (`acpi/halacpi.c` 1128). | **Keep**; add ACPI reset register and EFI `ResetSystem` | 3 |
| ACPI tables / MADT | HalAcpi | `halx86/acpi` | 2.8k | Own RSDT/XSDT/MADT parsing; ACPICA headers. MADT x2APIC entries are parsed, but "LapicId holds 8 bits … eventually want to support x2APIC" (`madt.c` 60). SRAT is read and then "NUMA/HotPlug are not supported" (`halacpi.c` 835). No MCFG or HPET table use. | **Keep + add** MCFG, HPET, FADT reset reg | 3 |
| APIC (LAPIC/IOAPIC, timers) | — | `halx86/apic` | 2.8k | Multi-IOAPIC supported (`apic.c` 601–645). Clock = RTC periodic interrupt (`rtctimer.c`). TSC is used for stall. `HalCalibratePerformanceCounter` is `UNIMPLEMENTED; ASSERT(FALSE)` (`tsc.c` 172), which SMP needs. | **Keep + add** HPET/invariant-TSC QPC, perf-counter sync | 2–3 |
| SMP | HalStartNextProcessor | `halx86/smp` (0.5k), `apic/apicsmp.c` | 0.5k | i386: `smp/i386/spinup.c` works (experimental). amd64: `HalStartNextProcessor` returns FALSE. | **Write the amd64 AP spin-up.** References: Intel SDM, ACPI spec, FreeBSD `sys/x86` (BSD-2) or Haiku (MIT). Not Linux (GPLv2-only). | 2 |
| x2APIC | — | `halx86/x2apic` | 163 | Detection/enable helpers only (2026, MIT header), **not referenced by any `.cmake`** | **Finish and wire in** | 2–3 |
| PCI config / bus | HAL bus handlers + pci.sys | `halx86/legacy/bus` (2.0k; `pci_*.ids` 2026.01.31) | 2.0k | Type1/Type2 port access only (`pcibus.c`). No ECAM, so no config space ≥ 0x100. | **Keep + add ECAM** via MCFG | 3 |
| MSI / MSI-X | HAL interrupt messages | (missing) | 0 | `APIC_MSI_VECTOR` placeholder in `apic.c`. Kernel side no-op (see Io). | **Write** from PCI spec and WDK docs | 3 |
| Legacy / PIC / MPS / PC-98 / Xbox / ARM | — | `legacy` (5.0k), `pic` (1.6k), `mp` (3.3k), `pc98` (1.1k), `xbox` (0.6k), `halarm` (2.3k, 49 UNIMPL) | ~14k | Old hardware only | **Drop** (keep `legacy/bus` PCI code used by the ACPI HAL) | 0 |
| ACPICA (used by HAL headers and `drivers/bus/acpi`) | acpi.sys AML interpreter | `drivers/bus/acpi/acpica` | — | Version **20221020** (`3rd Party Files.txt`) | **Update to 20260930.** Use the BSD-3 dual-license option. | 3 |

### 2.4 RTL (`sdk/lib/rtl`, 61.3k lines)

| Component | Win10 counterpart | Path | Lines | Origin | State (evidence) | Best option 2026 | Stage |
|---|---|---|---|---|---|---|---|
| Core RTL (strings, bitmaps, AVL, SD/ACL, paths, env, registry, time) | ntdll/ntoskrnl Rtl | `sdk/lib/rtl/*.c` | ~45k | own; some files carry Wine headers (`unicode.c`, `path.c`, `critical.c`, `exception.c`…) | Broadly complete. `compress.c`: the chunk APIs are UNIMPLEMENTED. | **Keep** | — |
| Heap | RtlHeap (+LFH, segment heap) | `heap.c`, `heappage.c`, `heapdbg.c` | 6.7k | own (2010 Bragin) | No LFH: `RtlSetHeapInformation` logs "needs to enable LFH". `RtlWalkHeap`, `RtlProtectHeap`, `RtlCompactHeap`, `RtlQueryProcessHeapInformation`, `RtlZeroHeap`, `RtlUsageHeap` and tag APIs UNIMPLEMENTED. | **Keep for now.** Option: port Wine heap with LFH (Wine ≥ 8.3, LGPL) if profiling demands. Add `RtlWalkHeap` early (Toolhelp/debuggers use it). | 1 |
| Sync primitives | SRW, CONDITION_VARIABLE, WaitOnAddress | `srw.c`, `condvar.c`, `waitaddress.c` | — | own (keyed-event based) | SRW and condvar work. **`RtlWaitOnAddress`/`RtlWake*` are UNIMPLEMENTED.** | **Add** `NtWaitForAlertByThreadId`/`NtAlertThreadByThreadId` to the kernel, then port Wine's wait-on-address (current Wine builds it on those syscalls; check `dlls/ntdll/sync.c` when porting) | 1 |
| Thread pool | TP API | `threadpool.c` | 3.5k | **Wine 9.7** | Works | **Resync to Wine 11.x** | 1 |
| Activation contexts | SxS | `actctx.c` | 6.5k | **Wine 10.0** | Works. `BaseSrvSxsCreateActivationContext` in csrss is not implemented (see 2.5). | **Resync to Wine 11.x** | 1 |
| WoW64 helpers | — | `wow64.c` | small | own | `RtlWow64GetProcessMachines` via `ProcessWow64Information` | **Keep** | 2 |
| Trace/ETW user | EtwEventWrite… | `trace.c` (8 UNIMPL), `dll/ntdll/etw` | — | own | Stubs | **Rewrite minimal** with kernel ETW | 1 |

### 2.5 System processes and subsystems (user mode)

| Component | Win10 counterpart | Path | Lines | Origin | State (evidence) | Best option 2026 | Stage |
|---|---|---|---|---|---|---|---|
| smss | smss.exe | `base/system/smss` | 6.9k | own (Alex Ionescu) | NT5.2 model. Starts csrss + `DEFAULT_INITIAL_COMMAND L"winlogon.exe"` (`smsubsys.c` 25). `SmpCreateForeignSession`, `SmpSessionComplete`, `SmpTerminateForeignSession` and `SmpStopCsr` → `STATUS_NOT_IMPLEMENTED` (`smloop.c`). "FIXME: Handle SFC-protected file renames". | **Keep.** The NT6 session-0 model (wininit, per-session csrss) only when services isolation is needed. | 3+ |
| csrss / csrsrv / csrlib | csrss.exe, csrsrv.dll | `subsystems/csr/{csrss,csrsrv,csrlib}` | 8.5k | own | Works. `CsrSbCreateProcess`, `CsrSbForeignSessionComplete` and `CsrSbTerminateSession` not implemented. | **Keep** | — |
| basesrv | basesrv.dll | `subsystems/win/basesrv` | 4.4k | own | `BaseSrvSxsCreateActivationContext`, the NLS user-info APIs, `BaseSrvRegisterThread`, `BaseSrvDebugProcess` and the TS APIs → NOT_IMPLEMENTED | **Keep + fill SxS/NLS** | 1 |
| Console server (csrss-hosted) | conhost.exe + condrv.sys (ConPTY) | `win32ss/user/winsrv/consrv` (21.5k), `drivers/base/condrv` (0.3k skeleton) | 21.8k | own | NT5-style console inside csrss. No ConPTY. | **Replace** with OpenConsole/conhost from `microsoft/terminal` (MIT) plus our own `condrv.sys`, using the interface the OpenConsole server code expects | 1–2 |
| winlogon | winlogon.exe + LogonUI + credential providers | `base/system/winlogon` | 7.9k | own | GINA model (`wlx.c`: 10 UNIMPLEMENTED Wlx callbacks). Itself starts `services.exe` and `lsass.exe` (`winlogon.c` 47–95). | **Keep GINA** until the visual stage; credential-provider LogonUI later | 6 |
| services (SCM) | services.exe | `base/system/services` | 12.5k | own | `RChangeServiceConfig2*`/`RQueryServiceConfig2*` accept only `SERVICE_CONFIG_DESCRIPTION..FAILURE_ACTIONS`. `RNotifyServiceStatusChange`, `RControlServiceEx*`, `RCreateServiceWOW64*` and `ROpenServiceStatusHandle` UNIMPLEMENTED. | **Keep + extend** (levels 3–8, notifications) | 1 |
| lsass + lsasrv/samsrv/msv1_0 | lsass, lsasrv, samsrv, msv1_0, kerberos, negotiate | `base/system/lsass` (87), `dll/win32/{lsasrv 15.5k, samsrv 17.2k, msv1_0 4.3k}` | ~37k | own | NTLM/local SAM only. lsasrv: 33 UNIMPL, 47 NOT_IMPL. No Kerberos/Negotiate package dirs. | **Keep** (local accounts). Domain/Kerberos out of scope. | 1 |
| userinit, logonui, autochk, bootok, runonce | same | `base/system/*` | 1.8k / 0.6k / 0.7k / … | own | Small, working | **Keep** | — |
| NTVDM / WOW16 | none on x64 Windows 10 | `subsystems/mvdm` | 39.4k | own (`vdmdbg` from Wine) | Software emulation (fast486), 64 UNIMPL | **Drop from x64 builds**; optional on x86 | 2 |

---

## 3. Remember-once knowledge

### 3.1 Boot flow end to end

**UEFI path (Okno target):**
1. Firmware loads `\EFI\BOOT\BOOTX64.EFI` = `uefildr.efi`. `boot/boot_images.cmake` builds `efisys.bin` for the ISO.
2. `EfiEntry` (`arch/uefi/uefildr.c`) runs `LoadSettings` → `DebugInit` → `MachInit` → `UiInitialize` →
   `MmInitializeMemoryManager` (EFI memory map) → `FsInit` → `PeLdrInitializeModuleList` → `MachInitializeBootDevices`.
3. It switches to its own stack, then `ExecuteLoaderCleanly` → `RunLoader` (`bootmgr.c`) reads `freeldr.ini` and
   shows the OS menu.

**BIOS path:**
1. Boot sector (`bootsect/*.S`) → `freeldr.sys` realmode entry → `BootMain` (`freeldr.c`, same init).
2. It loads **`rosload.exe`** (second stage; module name "scsiport.sys") → `RunLoader`.

**Both paths, from `LoadAndBootWindows` (`ntldr/winldr.c`):**
1. Parse `Options=`, `Hal=` and `Kernel=` from the ini, plus boot-time F8 options.
2. `AllocateAndInitLPB` → `WinLdrInitSystemHive` + `WinLdrScanSystemHive`. These read `SYSTEM`, pick the NLS files,
   and collect the boot drivers via `CmpFindDrivers`/`CmpSortDriverList`/`CmpResolveDriverDependencies`. Those
   functions come from `ntoskrnl/config/cmboot.c`, compiled into the loader.
3. `LoadAndBootWindowsCommon`:
   - `MachHwDetect` builds the ARC config tree (ACPI BIOS, PCI, disks, framebuffer).
   - `LoadWindowsCore` loads the kernel, HAL, `kd<port>.dll` (as "kdcom.dll") and the bootvid DLL, then resolves
     imports.
   - Then: `WinLdrLoadBootDrivers` → `WinLdrInitializePhase1` (ARC names, LoadOptions, NLS) →
     `MachPrepareForReactOS` (UEFI: `ExitBootServices`) → `WinLdrSetupMachineDependent` (GDT/IDT/TSS/PCR) →
     `WinLdrSetupMemoryLayout` (page tables + memory descriptors) → `WinLdrSetProcessorContext` → zero
     `KI_USER_SHARED_DATA` → `KiSystemStartup(LoaderBlockVA)`.

**Kernel, x64** (`ke/amd64/kiinit.c`, `krnlinit.c`):
1. `KiSystemStartup`:
   - Saves `KeLoaderBlock` and runs `KiInitializeP0BootStructures`, `KiInitializeCpu`, `KiInitModuleList` and
     `KeInitExceptions` (IDT).
   - Then `HalInitializeProcessor` → `KdInitSystem(0)` → `KiInitializeKernelMachineDependent` → XState config.
   - Finally `KiSwitchToBootStack` → `KiSystemStartupBootStack` → `KiInitializeKernel` → **`ExpInitializeExecutive`**
     (`ex/init.c`).
2. Phase 0 runs: `HalInitSystem(0)`, `ExInitSystem`, `MmInitSystem(0)`, `ExpInitNls`, `ObInitSystem`,
   `SeInitSystem` and `PsInitSystem`. `PsInitSystem` creates the **Phase1Initialization** system thread
   (`ps/psmgr.c` 516). Then `DbgkInitialize`, and the boot CPU becomes the idle loop.
3. Phase 1 (`Phase1InitializationDiscard`), in order:
   1. `HalInitSystem(1)`
   2. `InbvDriverInitialize` (boot logo/SOS)
   3. `PoInitSystem(0)`
   4. **`KeStartAllProcessors`** (no-op on x64)
   5. Ob, Ex and Ke phase 1
   6. `KdInitSystem(1)`
   7. `SeInitSystem`
   8. `ExpCreateSystemRootLink`
   9. `MmInitSystem(1)`
   10. `CcInitializeCacheManager`
   11. `CmInitSystem1` (hives)
   12. `FsRtlInitSystem`
   13. `LpcInitSystem`
   14. **`IoInitSystem`** (PnP enumeration, boot and system drivers)
   15. `PoInitSystem(1)`
   16. `PsInitSystem(1)`
   17. `MmFreeLoaderBlock`
   18. `SeRmInitPhase1`
   19. **`ExpLoadInitialProcess`** (`\SystemRoot\System32\smss.exe`)
4. The kernel waits 5 s. If smss has died by then → `SESSION5_INITIALIZATION_FAILED`.

**smss** (`base/system/smss`):
1. Reads `HKLM\SYSTEM\CurrentControlSet\Control\Session Manager` and runs, in order: `BootExecute` (autochk),
   `PendingFileRenameOperations`, `KnownDlls`, paging files, environment, DOS devices.
2. Starts `SubSystems\Required` = `Debug Windows`. `Windows` is the csrss command line:
   `ServerDll=basesrv,1 ServerDll=winsrv:UserServerDllInitialization,3 ServerDll=winsrv:ConServerDllInitialization,2`
   (`hivesys.inf` 1737).
3. Runs the initial command `winlogon.exe`.

**csrss:** `csrss.exe` → csrsrv → loads `basesrv.dll` and `winsrv.dll` (usersrv + consrv) → LPC `\Windows\ApiPort`.
Clients connect through csrlib (`CsrClientConnectToServer`, linked into ntdll).

**winlogon:** starts `services.exe` and `lsass.exe` → loads GINA `msgina.dll` → SAS/logon → `Userinit`
(`userinit.exe`) → `Shell` (`explorer.exe`). The values are in
`HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon` (`hivesft.inf` 1727–1728).

### 3.2 Where key structures and config live

| What | Where |
|---|---|
| `LOADER_PARAMETER_BLOCK`, ARC types | `sdk/include/reactos/arc/arc.h` (NT5.2 layout unless NTDDI ≥ LONGHORN) |
| `KPCR`/`KPRCB`/`KTRAP_FRAME` | `sdk/include/ndk/{i386,amd64}/ketypes.h`; `KUSER_SHARED_DATA` in `sdk/include/xdk/ketypes.h` |
| `EPROCESS`/`ETHREAD`/`PEB`/`TEB` | `sdk/include/ndk/pstypes.h` |
| Native API prototypes | `sdk/include/ndk/*fncs.h` (e.g. `psfuncs.h`) |
| Kernel-internal headers | `ntoskrnl/include/internal/*` (`ke_x.h`, `mm.h`, `amd64/mm.h` for the x64 VA layout) |
| x64 VA layout | `MI_USER_PROBE_ADDRESS 0x7FFFFFF0000`, paged pool at `0xFFFFF8A000000000` (128 GB), `MM_HIGHEST_USER_ADDRESS_WOW64 0x7FFEFFFF` |
| Loader memory limits | `boot/freeldr/freeldr/include/mm.h` (`MM_MAX_PAGE`, `MM_MAX_PAGE_LOADER`) |
| Boot menu/options | `freeldr.ini` on the system partition/ESP root. ISO: `boot/bootdata/bootcd.ini`. Template: `boot/freeldr/FREELDR.INI` |
| Default registry | `boot/bootdata/hive{sys,sft,def,cls,inst}.inf` → `mkhive` at build time |
| Boot drivers | `SYSTEM\CurrentControlSet\Services\*` with `Start=0`, ordered by `Control\ServiceGroupOrder` |
| HAL/kernel per machine type | `txtsetup.sif` `[Map.Computer]`, `[Map.Computer.NTamd64]` → `[Files.x64_mp]` copies `ntkrnlmp.exe`→`ntoskrnl.exe` and `halmp.dll`→`hal.dll` |
| NT version reported | `sdk/include/psdk/ntverp.h` (5.2, build 3790) → `ex/init.c` `NtMajorVersion/NtMinorVersion/NtBuildNumber` |
| Build NT levels | `CMakeLists.txt` 238–240 (`WINVER/_WIN32_WINNT 0x502`), `ntoskrnl/ntos.cmake` 12 (`NTDDI_VERSION 0x05020400`), `sdk/cmake/config.cmake` 117 (`DLL_EXPORT_VERSION`; 0x600 in the fork) |
| Third-party/Wine versions | `media/doc/3rd Party Files.txt`, `media/doc/WINESYNC.txt` |
| Kernel tests | `modules/rostests/kmtests/ntos_{cc,cm,ex,fsrtl,io,kd,ke,mm,ob,po,ps,se}`, `kmtests/hal`, `kmtests/rtl`; user mode in `apitests/ntdll`, `winetests/ntdll` |

### 3.3 How to add a syscall

1. Implement `NTSTATUS NTAPI NtFoo(...)` in the right component, e.g. `ntoskrnl/ps/…`.
   - Mark it `__kernel_entry`.
   - Check `ExGetPreviousMode()` and probe/capture user buffers inside `_SEH2_TRY` (`ProbeForRead`/`ProbeForWrite`).
2. Put the prototype in `sdk/include/ndk/<comp>fncs.h`, guarded by `NTDDI_VERSION`/`_WIN32_WINNT` if it is NT6+.
3. Append `SVC_(Foo, <argc>)` **at the end** of `ntoskrnl/include/sysfuncs.h`, inside the `#ifndef SYSFUNCS_NT5_ONLY`
   block.
   - Numbers are positional, so never insert in the middle.
   - `argc` = number of pointer-size arguments. `napi.h` builds `MainSSDT`/`MainSSPT` from it.
   - `ntoskrnl/sysfuncs.lst` and `include/sysfuncs64.h` are **not used by the build**: don't edit them, and expect
     them to be stale.
4. User stubs are generated automatically:
   - NT5 entries → `ntdllsys` (`ntoskrnl/ntdll.S`).
   - NT6 entries → `ntdllsys_nt6` (`ntdll_nt6.S`, which counts the NT5 entries first to get the IDs).
   - Both use the macros in `sdk/include/asm/syscalls.inc`.
   - Kernel `Zw*` stubs come from `ntoskrnl/ex/zw.S`.
5. Export it:
   - `dll/ntdll/def/ntdll.spec`: `@ stdcall -version=0x600+ NtFoo(...)` and `ZwFoo`. ntdll links
     `ntdllsys_nt6` when `DLL_EXPORT_VERSION >= 0x600`.
   - Add the `ZwFoo` export to `ntoskrnl/ntoskrnl.spec` only if drivers need it.
6. Test: an apitest in `modules/rostests/apitests/ntdll`, plus a kmtest if kernel callers matter.

Win32k syscalls are separate. They live in `win32ss/w32ksvc32.h`/`w32ksvc64.h` (742/744 entries), the user stubs are
generated from `win32ss/sys-stubs.S`, and the table is registered by `KeAddSystemServiceTable` in
`win32ss/user/ntuser/main.c`.

Our syscall numbers do **not** match Windows. That is fine while all user code goes through our ntdll and win32u.
It breaks only software that hard-codes syscall numbers.

### 3.4 How the HAL is selected

- The loader loads the kernel named by `/KERNEL=` (default `ntoskrnl.exe`) and the HAL named by `/HAL=` (default
  `hal.dll`) (`winldr.c` 836–869). It does no runtime auto-detection, except the `/DETECTHAL` handling in setupldr
  and the debug-only F8 "ACPI APIC/ACPI SMP" override for x86 (`advopts.c`).
- The real choice happens at **install time**:
  - Setup's `GetComputerIdentifier` (`base/setup/lib/settings.c`) returns "ACPI UP/MP" or "PC UP/MP" on x86.
  - On amd64 it always returns **"X64 MP"**, or "X64 UP" in KDBG builds.
  - `txtsetup.sif` then copies the matching files over `hal.dll`/`ntoskrnl.exe`.
- On x64, "MP" therefore means `halmp`+`ntkrnlmp` still running on one CPU (see 3.6).
- The HAL is a `kerneldll` with entry `HalInitSystem`. It is built from object libraries (`lib_hal_generic`, `_acpi`,
  `_apic`, `_up`/`_smp`) by `add_hal()` in `hal/halx86/CMakeLists.txt`.

### 3.5 Debugging

**Two incompatible kernel-debug builds:**
- **`KDBG=TRUE`, `_WINKD_=FALSE`.** This is the default for GCC/Clang Debug, so it is the fork's default.
  - The built-in KDBG plus the ReactOS debug log `ntoskrnl/kd/`.
  - `kdcom.dll` is really `kdrosdbg` (stubs).
  - Output port comes from `/DEBUGPORT=`: `SCREEN` (boot screen), `COM1..4` or `COM:<ioport>`, or `FILE[:name]`.
    Set the speed with `/BAUDRATE=115200`; `/KDSERIAL` runs the KDBG console on serial; `/KDNOECHO`.
  - KDBG runs an optional `KDBinit` script.
- **`_WINKD_=TRUE`** (MSVC Debug default). This is the real KD protocol (`kd64`) through `kdcom.dll` (serial),
  `kdgdb.dll` (GDB remote; `-DGDB=TRUE` makes it the default) or `kdvm.dll` (VirtualBox/VMware fast channel). Attach
  WinDbg to the VM's serial pipe.

**Boot switches:**
- `/DEBUG`, `/NODEBUG`, `/CRASHDEBUG`, `/SOS`, `/NOGUIBOOT`, `/BOOTLOG`, `/BOOTLOGO`.
- `/NUMPROC=`, `/BURNMEMORY=`, `/MININT`, `/SAFEBOOT:`, `/NOEXECUTE=…`.
- `/HAL=`, `/KERNEL=`, `/BOOTVID=`.
- The loader prints "You need to connect a debugger on port …" when `/DEBUG` is set.

**FreeLoader's own log:** `[FREELOADER] Debug=/DEBUG /DEBUGPORT=COM1 /BAUDRATE=115200`. It also accepts
`DEBUGPORT=SCREEN` and `BOCHS` (port 0xE9). Channel masks are parsed in `boot/freeldr/freeldr/lib/debug.c`. Use
`TRACE`/`WARN`/`ERR` with `DBG_DEFAULT_CHANNEL(x)`.

**Macros** (`sdk/include/reactos/debug.h`):
- `DPRINT1` always prints in DBG builds.
- `DPRINT` prints only if the file does not `#define NDEBUG`.
- `UNIMPLEMENTED` **only prints** (`is UNIMPLEMENTED!`) and lets the function continue, so stubs often return
  success.
- `UNIMPLEMENTED_DBGBREAK` breaks into the debugger.
- Release builds compile all of them out.

**CI:** read the COM1 log. Debug builds log the kernel there, and the fork's tests parse it. Bug check screens come
from `KiDisplayBlueScreen` (`ke/bug.c`).

**No crash dumps** (`IoInitializeCrashDump` UNIMPLEMENTED). To debug post-mortem, use serial KD or KDBG.

### 3.6 x64 gaps (exact)

| Gap | Evidence | Plan stage |
|---|---|---|
| Only one CPU used | `KeStartAllProcessors` UNIMPLEMENTED (amd64). `HalStartNextProcessor` returns FALSE. Setup still installs `halmp`/`ntkrnlmp`. | 2 |
| RAM ≤ 8 GB | `MM_MAX_PAGE 0x1FFFFF` "HACK: ReactOS AMD64 can't handle the full memory range yet CORE-20265"; the loader maps 1 GB | 2 |
| No WoW64 | `KiSystemCallEntry32: swapgs; int 3`. `BUILD_WOW64_ENABLED` is defined nowhere. No `wow64*.dll` in the tree. The plan's VM test showed 32-bit PuTTY does not start on x64. | 2 |
| KDBG unusable on x64 MP | setup comment "except when we use KDBG, which is broken" | 2 |
| No SMEP/SMAP/KPTI | CR4 only gets FXSR/XMMEXCPT/XSAVE (`kiinit.c` 199–217) | 2 |
| Large pages/PAT unused | `KiInitMachineDependent` FIXMEs | 2/5 |
| No processor groups | Group APIs absent from the spec | 2 |
| Boots only on q35/AHCI in QEMU | [fork] plan test: STOP 0x1E in `pciidex.sys` on i440FX IDE; this is in the drivers area | 2 |

### 3.7 Gotchas

- "Implemented" does not mean working. Several functions log a FIXME and return `STATUS_SUCCESS`:
  `IoConnectInterruptEx` (message- or line-based), `NtSetSystemPowerState` for sleep, and many heap info classes.
  Grep for `DPRINT1("FIXME` as well as `UNIMPLEMENTED`.
- `NtQuerySystemInformation`/token/process info classes that are not in the tables return
  `STATUS_INVALID_INFO_CLASS`. Modern runtimes probe these and may change code paths or fail.
- The loader and kernel share `ntoskrnl/config/cmboot.c` and `ntoskrnl/ke/config.c`. Changing them affects both.
- Layouts tied to NTDDI (`LOADER_PARAMETER_BLOCK`, `KPRCB`) must stay identical in the loader, HAL and kernel. Never
  raise NTDDI in one of them alone.
- `NEWCC` (`ntoskrnl/cache`) is dead code (not built). The live cache manager is `ntoskrnl/cc`, sitting on the legacy
  Mm sections.
- `sdk/lib/drivers/ntoskrnl_vista` is **statically linked into drivers** to give them some Vista APIs. Real Windows 10
  drivers can't use it. They need real exports from `ntoskrnl.exe`.
- License rules for reference code:
  - **Not Linux** `arch/x86` (GPLv2-only) and **not** Apache-2.0 code.
  - BSD/MIT sources are fine: FreeBSD `sys/x86`, Haiku `src/system/kernel/arch/x86`, EDK2 MdePkg.
  - MS-PL code only as a separate module, never mixed into GPL files (fork rule).
  - No leaked Windows source, ever.

---

## 4. Ordered task list (this area), stages 1–5

Each task ends with its acceptance check. "QEMU" means `tools/qemu/vm.py` on the fork's CI (q35 + AHCI; OVMF for UEFI
tasks).

### Stage 1: modern apps (x86 first, then x64 too)

1. **Version policy.**
   - Make the reported NT version configurable: a registry value read in `ex/init.c`, defaulting to 5.2 now and
     switching to 10.0.19045 once the stage-1 gate is met.
   - Keep kernel NTDDI at 5.2 for struct layouts. Add new APIs with `-version=0x600+`/`0xA00+` spec gating.
   - *Check:* `RtlGetVersion`/`ver` show the configured value. The Python 3.13 installer passes its OS check with 10.0.
2. **Thread-alert syscalls + WaitOnAddress.**
   - Add `NtWaitForAlertByThreadId` and `NtAlertThreadByThreadId` (ke/ps).
   - Port Wine 11.x `RtlWaitOnAddress`/`RtlWakeAddress*` into `sdk/lib/rtl/waitaddress.c`, and switch SRW/condvar to
     them later if they prove faster.
   - *Check:* Wine `ntdll` sync tests for wait-on-address pass. A C++20 `std::atomic::wait` test binary built with
     MSVC STL passes on x86 and x64.
3. **Process/thread creation used by Wine kernelbase.** Add `NtCreateUserProcess` (on top of the existing
   `PspCreateProcess` + image section + PEB/params) and `NtCreateThreadEx`.
   - *Check:* Wine `kernelbase` `CreateProcessInternalW` runs unmodified. winetests `kernel32:process` show no
     regressions against the baseline.
4. **NT6 VM/IO syscalls by demand.** Rank them with the import analyzer (`docs/kb/apigap-baseline.md`). Expected
   first: `NtCancelIoFileEx`, `NtCancelSynchronousIoFile`, `NtRemoveIoCompletionEx`, `NtFlushProcessWriteBuffers`,
   `NtAllocateVirtualMemoryEx`, `NtMapViewOfSectionEx`, `NtCreateSectionEx`, `NtSetInformationVirtualMemory`,
   `NtQueryInformationByName`, `NtQueryDirectoryFileEx`, `NtCompareObjects`, `NtCreateLowBoxToken`, `NtSetTimerEx`
   and `NtCreateIRTimer`.
   - *Check:* the analyzer reports 0 missing `Nt*` imports for the top-100 apps' ntdll/kernelbase paths, and each new
     syscall has an apitest.
5. **Info classes.** Add `SystemLogicalProcessorAndGroupInformation` and `NtQuerySystemInformationEx`. Add the process
   classes Chromium and Firefox use (mitigation policies, image file name Win32, …) and `ThreadNameInformation`.
   - *Check:* `GetLogicalProcessorInformationEx` works. Firefox/Chromium startup logs contain no
     `invalid information class`.
6. **Token integrity and elevation.** Add `TokenElevation`, `TokenElevationType`, `TokenLinkedToken`,
   `TokenIntegrityLevel`, `TokenMandatoryPolicy` and `TokenIsAppContainer`. Give default tokens a mandatory label
   (admin High, user Medium) and add the access-check integrity rule.
   - *Check:* advapi32 winetests `security` token tests pass. `whoami /groups` shows the mandatory label. Installers
     that check elevation proceed.
7. **Minimal ETW.** Implement `EtwRegister`, `EtwEventEnabled`, `EtwWrite` and `EtwUnregister` in ntoskrnl (exported,
   returning success). Implement `NtTraceControl`/`NtTraceEvent` as success no-ops, and fix the user-mode
   `EventRegister`/`EventWrite`.
   - *Check:* a driver calling `EtwRegister` loads, and the TraceLogging sample apps run.
8. **Registry APIs.** Add `NtRenameKey`, `NtQueryMultipleValueKey`, `NtSetInformationKey`, `NtRestoreKey`,
   `NtReplaceKey`, `NtUnloadKeyEx` and `NtQueryOpenSubKeysEx`.
   - *Check:* advapi32 `registry` winetests improve. regedit rename works. `reg save`/`reg restore` round-trip.
9. **SCM levels 3–8 + notifications.** Add `SERVICE_CONFIG_DELAYED_AUTO_START_INFO`, `SERVICE_SID_INFO`,
   `REQUIRED_PRIVILEGES_INFO`, `PRESHUTDOWN_INFO` and `TRIGGER_INFO`. Store and enforce these where cheap. Add
   `NotifyServiceStatusChange` and `ControlServiceEx`.
   - *Check:* `sc config X start= delayed-auto` succeeds and advapi32 `service` winetests improve.
10. **RTL Wine resync.** Bring `threadpool.c` and `actctx.c` to Wine 11.x. Add `RtlWalkHeap` and
    `RtlQueryProcessHeapInformation`.
    - *Check:* winetests `ntdll:threadpool`, `kernel32:actctx` and `kernel32:heap` show no regressions; Toolhelp heap
      walk works.
11. **basesrv SxS/NLS.** Add `BaseSrvSxsCreateActivationContext` and the NLS user-info APIs.
    - *Check:* manifest-dependent apps (comctl32 v6) behave the same when started from Explorer and from `cmd`.
12. **Console (ConPTY).** Add `condrv.sys` and port OpenConsole conhost (MIT). Keep consrv as a fallback until it is
    at parity.
    - *Check:* `CreatePseudoConsole` sample (EchoCon) works. cmd and PowerShell 7 run in the new conhost.

### Stage 2: x64 by default, WoW64, SMP

1. **Lift the 8 GB cap** (CORE-20265). Fix the x64 PFN database and loader mapping beyond 1 GB.
   - *Check:* x64 boots with 32 GB in QEMU, `GlobalMemoryStatusEx` reports it, and a stress test allocates and
     touches 24 GB without a bug check.
2. **x64 AP startup.**
   - HAL: `smp/amd64/spinup.c` (trampoline below 1 MB, INIT-SIPI-SIPI, `apentry.S`).
   - Kernel: amd64 `KeStartAllProcessors` (per-CPU PCR/PRCB/GDT/TSS/IDT/stacks; logic exists in i386 `mproc.c`).
   - Implement the generic IPI packet in `ke/ipi.c`, `HalCalibratePerformanceCounter`, and the "Add a time out" TODO.
   - *Check:* QEMU `-smp 8` (TCG and KVM) shows 8 CPUs. kmtests `ntos_ke` (DPC/IPI) pass. A 1-hour parallel workload
     runs without a bug check.
3. **Processor-group APIs** (single group ≤ 64 CPUs): `KeQueryActiveProcessorCountEx`,
   `KeGetCurrentProcessorNumberEx`, `KeGetProcessorNumberFromIndex`, `KeSetSystemGroupAffinityThread` and the user
   counterparts.
   - *Check:* the `GetActiveProcessorCount(ALL_PROCESSOR_GROUPS)` and `GetLogicalProcessorInformationEx` tests pass.
4. **x2APIC.** Wire `hal/halx86/x2apic` in and accept 32-bit APIC IDs from the MADT.
   - *Check:* boots on QEMU/KVM with `+x2apic` and firmware handing over in x2APIC mode.
5. **WoW64, kernel side.**
   - Define `BUILD_WOW64_ENABLED`.
   - Load i386 `SEC_IMAGE` on amd64, create the 32-bit PEB/TEB, add the compat code segment and context
     save/restore.
   - Make `ProcessWow64Information` real (remove the hack), handle `Dbgk` for WoW64, and keep the 4 GB address limit.
   - *Check:* a 32-bit process starts to `LdrInitializeThunk` of the 32-bit ntdll under a 64-bit debugger.
6. **WoW64, user side.**
   - Port Wine 11.x `wow64.dll`, `wow64cpu.dll` and `wow64win.dll` (LGPL).
   - Adapt `wow64win` thunks to ReactOS win32k syscalls (742 x86 entries).
   - Add the 64-bit ntdll WoW64 init path, and build the i386 DLLs into `SysWOW64` (multi-arch packaging).
   - *Check:* 32-bit PuTTY and 7-Zip x86 run on x64 Okno (the plan baseline is "does not start"). A selected set of
     i386 winetests passes under WoW64.
7. **Crash dumps.** Implement `IoInitializeCrashDump` plus a dump writer through the boot disk's dump stack, or a
   simpler pagefile-based kernel memory dump.
   - *Check:* a forced bug check produces `MEMORY.DMP` that WinDbg opens with a correct stack.
8. **WinDbg on x64 MP.** Make the `_WINKD_` + kdcom/kdgdb build a CI variant.
   - *Check:* WinDbg/GDB attach to the x64 `-smp 4` VM and run break, `k` and `!process 0 0`.
9. **Hardening.** Enable SMEP/SMAP/UMIP when supported.
   - *Check:* a kmtest that executes or reads a user page from kernel faults as expected, and rosautotest shows no
     regressions.
10. **Prune the x64 build.** No NTVDM/VDM, PC-98, Xbox or ARM.
    - *Check:* the x64 ISO has no `ntvdm.exe`, and CI time drops.

### Stage 3: modern desktop PC

1. **UEFI loader completion.**
   - Command line from `LoadOptions`.
   - Pass the SMBIOS3 and ACPI config-table pointers.
   - Handle EFI runtime services: `SetVirtualAddressMap` plus `EfiInformation` in the loader block.
   - Map all physical memory.
   - Handle every EFI memory type (no `ASSERT(FALSE)` for `LoaderBad`).
   - *Check:* boots on OVMF with 64 GB and on 3 real PCs from 2016–2024.
2. **Firmware variables and boot entries.**
   - `HalGet/SetEnvironmentVariableEx`.
   - `NtQuery/SetSystemEnvironmentValueEx`, `NtEnumerateSystemEnvironmentValuesEx`.
   - `NtEnumerateBootEntries`/`NtAddBootEntry`/`NtSetBootEntryOrder` (`ex/efi.c`).
   - Setup populates the ESP and creates `Boot####`.
   - *Check:* after install on OVMF, the firmware boot menu lists "Okno" and the system boots from it with no manual
     shell.
3. **SMBIOS from the loader** (`wmi/smbios.c`).
   - *Check:* `GetSystemFirmwareTable('RSMB')` and `wmic bios` return data on OVMF and on a real PC.
4. **PCIe ECAM** via MCFG in the HAL and `pci.sys`.
   - *Check:* extended capabilities (offset ≥ 0x100) are readable on q35. AER/PCIe capability lists appear in a dump
     tool.
5. **MSI/MSI-X.**
   - HAL: vector allocation, message address/data.
   - PnP resource requirements with message interrupts.
   - `IoConnectInterruptEx(CONNECT_MESSAGE_BASED)`; make it fail loudly until implemented.
   - *Check:* QEMU `nvme`, `e1000e` and `qemu-xhci` get MSI-X vectors (HAL log), and the NVMe driver completes I/O
     on MSI-X.
6. **Time sources.** HPET and invariant-TSC `KeQueryPerformanceCounter`; RTC only as a fallback.
   - *Check:* QPC frequency is stable, and `timeBeginPeriod(1)` sleep accuracy is within 1 ms on KVM and on real
     hardware.
7. **Reset/power-off without legacy hardware.** ACPI FADT reset register, 0xCF9, EFI `ResetSystem`.
   - *Check:* reboot works on a PC without an 8042 controller (or with the 8042 disabled in QEMU).
8. **64-bit DMA in the HAL** ("FIXME: Initialize DMA 64-bit support") and `MmAllocateContiguousNodeMemory`.
   - *Check:* the NVMe/xHCI DMA kmtest uses addresses above 4 GB on a 32 GB VM.
9. **Kernel/HAL export gap for Windows 10 vendor drivers.**
   - Run the import analyzer on Intel/Realtek Ethernet, Intel RST/Storport miniports and HDA drivers.
   - Add the missing exports to `ntoskrnl.spec`/`hal.spec`, real implementations, not `ntoskrnl_vista` static stubs.
   - *Check:* the target vendor `.sys` files load with no missing imports.
10. **ACPICA 20260930 + EDK2 stable202608 headers.**
    - *Check:* builds pass, and ACPI tables plus `_PRT` routing still work on OVMF and real PCs.
11. **Secure Boot path (optional).** shim (BSD-style) + Okno key enrollment (MOK).
    - *Check:* boots with Secure Boot on one test PC after MOK enrollment.

### Stage 4: laptops

1. **Power manager rewrite** (WDK docs): system power policy, `NtInitiatePowerAction`, S3 sleep/resume orchestration
   with `drivers/bus/acpi`, S4 hibernation (`PoSetHiberRange`, hiberfile writer), power-setting callbacks, a real
   `PoStartNextPowerIrp`/IRP sequencing, and PoFx moved into the kernel.
   - *Check:* lid close → S3 → resume on one ACPI S3 laptop with the network and display back. Hibernate and resume in
     QEMU. A PoFx-using driver (I2C HID) idles and wakes.
2. **CPU idle/perf states** (`_CST`/`_PSS`/`_CPC`) in the HAL/processor driver.
   - *Check:* idle package power drops measurably on a laptop, and frequency scales under load.
3. **Wake sources and timers** (`NtSetTimerEx` wake, `PoSetSystemWake`).
   - *Check:* wake-on-timer from S3 works.
4. **NUMA/SRAT basics** (single-node fallback stays).
   - *Check:* `GetNumaHighestNodeNumber` is correct on a 2-node QEMU config.

### Stage 5: WDDM GPUs (kernel prerequisites only)

1. **PAT/write-combining and large pages** on x64 (the `KiInitMachineDependent` FIXMEs). Add `MmMapIoSpaceEx`
   protections.
   - *Check:* a kmtest maps BAR memory WC and the PAT MSR is programmed. Write throughput to the framebuffer improves
     measurably compared with UC.
2. **Kernel APIs dxgkrnl and miniports need**, found by import analysis of a WDDM miniport (`KeQueryInterruptTimePrecise`,
   `ExAllocatePool2`, …), plus MSI-X (stage 3).
   - *Check:* the GPU vendor miniport's imports resolve.
3. **Session/desktop plumbing check for dxgkrnl** (per-session win32k state).
   - *Check:* the dxgkrnl skeleton loads Microsoft's KMDOD display-only sample (Windows-driver-samples `video/KMDOD`,
     MS-PL, built as a separate module) and reaches `DxgkDdiStartDevice` in QEMU.

---

## Sources

- ReactOS source (paths cited inline), commit `e46f4bb1a1e`, 2026-10-25.
- ACPICA tags (20260930 latest): https://github.com/acpica/acpica/tags. 20260408 release on LKML:
  https://lkml.iu.edu/2605.3/06288.html
- EDK2 tags (edk2-stable202608, 2026-08-12): https://github.com/tianocore/edk2/tags
- Wine tags (wine-11.20, 2026-10-16): https://github.com/wine-mirror/wine/tags. Wine 11.0 WoW64 status:
  https://linuxiac.com/wine-11-0-brings-fully-supported-wow64-mode/
- Wine LFH shipped in 8.3: https://www.phoronix.com/news/Wine-8.3-Released
- microsoft/terminal (MIT, contains conhost/OpenConsole and ConPTY): https://github.com/microsoft/terminal
- Fork build facts: `/home/user/okno-os` commits `64d8b769d3f` (clang 18 + mingw-w64), `sdk/cmake/config.cmake`
  (`DLL_EXPORT_VERSION 0x600`), and `docs/plan.md` (VM test results).
