# ReactOS user mode: audit for Okno OS (Windows 10/11 replacement)

Snapshot: ReactOS master `e46f4bb1a1ea` (2026-10-25), shallow clone. Audit date: 2026-10-29.
Scope: ntdll, kernel32/kernelbase/apisets, advapi32, user32/gdi32/win32ss, dll/win32/*, DirectX, OpenGL,
dll/3rdparty, CRT (msvcrt/ucrtbase), COM/RPC/WinRT, crypto/TLS, shell, services, Unicode/ICU, DWrite/D2D/WIC.

Evidence conventions in this file:
- `path:line` = file in the ReactOS tree (paths relative to the source root).
- "spec stats" = counted by parsing `.spec` files (script `specstat.py`, see section 4.9), x86, at export level
  0x502 (release default) and 0xA00 (everything). Format `exports/stubs`.
- "import check" = real import tables of real Windows binaries checked against ReactOS `.spec` files and the
  ReactOS apiset table (script `impcheck2.py`, section 4.9). Binaries used: Python 3.13.17 embeddable x86
  (python.org), Firefox 115.44.0esr x86 and Firefox 159.0 x86 (archive.mozilla.org). Raw outputs:
  `/tmp/claude-0/-home-user-okno/2af4bb7a-4411-572a-bbe7-dcffd3c4fc82/scratchpad/out/`.
- Upstream versions were checked on 2026-10-29 with `git ls-remote` against the upstream repos and with web
  sources listed in section 6.

---

## 1. Summary

- **The measured "Python 3.13 / Firefox exit silently" is a load-time failure, and the first blocker is in the
  loader, not a missing DLL.** `ucrtbase.dll` exists (`dll/win32/ucrtbase`, Microsoft UCRT subset, MIT) and an
  apiset table exists (`sdk/lib/apisets`), but apisets are only switched on per process from the manifest's
  `supportedOS` GUIDs, and ReactOS takes the **lowest** GUID (`dll/ntdll/ldr/ldrinit.c:1601-1716`). Vista lowest
  means "apisets off" (`dll/ntdll/rtl/libsupp.c:1026-1029`). `python.exe` lists Vista..10, so
  `api-ms-win-crt-*.dll` is never resolved and Python ships no copies of them. Firefox lists Win7..10, so Win7
  mode applies, and in that mode no `api-ms-win-crt-*` entry is active (they are `APISET_WIN10` only).
- **The apiset implementation has three structural bugs:** (a) exact match on the full name including the last
  version digit, while Windows 10 matches up to the last hyphen (Wine does the same: `dlls/ntdll/loader.c`
  `get_apiset_entry`); (b) per-OS flag sets copied from apisets.info, so Win10 mode does not resolve
  `api-ms-win-core-synch-l1-1-0`, `-memory-l1-1-0`, `-processthreads-l1-1-0` and similar; (c) host remapping
  `kernelbase→kernel32`, `combase→ole32` and `shcore→shell32` (`sdk/lib/apisets/update.py:14-22`) sends calls to
  DLLs that do not export them. Example: `api-ms-win-core-path-l1-1-0` goes to kernel32, but `PathCch*` live only
  in `kernelbase_ros.dll`. `api-ms-win-security-base-l1-1-0` goes to kernel32, but `GetTokenInformation` and
  similar live in advapi32. Of the roughly 1062 active entries, 346 point to 190 host DLLs that ReactOS does not
  build at all.
- **After the loader, missing exports are the next blocker: about 70 kernel32 functions plus a few dozen in other
  DLLs.** At the fork's new level 0x600, Python 3.13 still fails to load because of 9 kernel32 functions
  (`AddDllDirectory`, `RemoveDllDirectory`, `Pss*Snapshot` ×3, `SetWaitableTimerEx`, `CopyFile2`,
  `GetActiveProcessorCount`, `GetSystemTimePreciseAsFileTime`) and 2 `PathCch*` functions through the apiset bug.
  Firefox 115 fails on 0x601-level exports (`K32*`, `TryAcquireSRWLock*`, `GetThreadGroupAffinity`) and on
  `RtlQueryPerformanceCounter`, `QueryUnbiasedInterruptTime`, `Wer*RuntimeExceptionModule`, ETW `Event*`,
  `ktmw32.dll` and `PowerCreateRequest`. The union over the three test apps is 69 missing kernel32 functions,
  12 ntdll, 8 advapi32, 8 user32 and 8 Ro* functions (`out/` aggregate, section 2).
- **Many exports are only stubs that crash the app when called.** `@ stub X` raises the non-continuable
  exception 0x80000100 (`sdk/include/reactos/stubs.h:53-63`); `-stub` only prints a warning and returns 0.
  kernel32 has 110 crashing stubs at 0x600+, among them `CreateWaitableTimerExW` (Python's `time.sleep`) and
  `SetFileInformationByHandle` (msvcp140 `std::filesystem`). ucrtbase has 191 stubs, including C99 math such as
  `acosh`, `cbrt`, `erf`, `log1p`, `lround` and `nan`, and `fe*` functions. Python, sqlite, NSS and xul all
  import them.
- **Kernel features are the real long pole behind the user-mode gaps.** The x86 syscall table is NT 5.2 (296
  calls) plus 3 NT6 calls (`ntoskrnl/include/sysfuncs.h`). There is no `NtCreateUserProcess`, `NtCreateThreadEx`,
  ALPC, `NtCancelIoFileEx`, `NtRemoveIoCompletionEx`, wait-completion packets, `NtAlertThreadByThreadId`, KTM or
  WNF. The loader also lacks dynamic TLS for `LoadLibrary`'d DLLs (`ldrinit.c:1277-1335` handles only
  process-init modules). Process-thread attribute lists, `CancelIoEx` and IOCP-Ex can be implemented properly only
  after these exist in the kernel.
- **Core DLLs should stay ReactOS-own, but kernelbase should become real Wine code.** ReactOS kernel32, ntdll and
  win32k are tied to CSRSS, the NT5 kernel and win32k syscalls. Wine's `kernelbase` is pure PE: 22 files, no
  `unix/` directory (Wine 11.20 tree). Wine's ntdll is split into 48 PE files and 24 Unix files. Wine's
  user32/gdi32 sit on `win32u`, a 54-file Unix-side implementation. Plan: ship a real `kernelbase.dll` built
  from Wine 11.x and forward kernel32 to it function by function. Port the PE parts of Wine ntdll (apiset V6
  lookup, dynamic TLS, `LdrAddDllDirectory`, threadpool). Keep win32k and ReactOS user32/gdi32, and cherry-pick
  Wine's PE-side user32 code (DPI, pointer).
- **The graphics/DirectX stack is Wine 10.1-dev and modern, but built only when DLL_EXPORT_VERSION ≥ 0x600, and
  it has no backend.** Gated modules: `dxgi`, `d3d10/11`, `d2d1`, `dwrite`, `dxva2`; `d3d12` and `dxcore` need
  0xA00 (`dll/directx/wine/CMakeLists.txt:80-108`). wined3d needs a GL ≥3.2 ICD or `vulkan-1.dll`
  (`adapter_vk.c:101`). In-box OpenGL is Mesa 2.6 (GL 1.1 software), and there is no Vulkan loader.
- **TLS/crypto:** `schannel` is a WineStaging-3.3 frontend on mbedTLS 2.16.11, TLS ≤1.2, no TLS 1.3. 2.16 is EOL.
  Current upstream: 3.6 LTS until 2027-03, 4.1 LTS until 2029-03, latest tag v4.2.0. mbedTLS files are dual
  `Apache-2.0 OR GPL-2.0-or-later` (`dll/3rdparty/mbedtls/aes.c` header), so the license is fine; `3rd Party
  Files.txt` wrongly lists Apache-2.0 only. `bcrypt`, `ncrypt` and `rsaenh` are already at Wine 11.19 with
  SymCrypt 103.11 (MIT).
- **Missing modern subsystems.** There are no WinRT classes (`windows.*.dll`, `wintypes`), even though Wine 11.20
  has 29 `windows.*` DLLs. ICU, Media Foundation, XAudio2, sechost, ktmw32 and a Vulkan loader are also missing.
  WASAPI has no backend: `mmdevapi` looks for `winepulse/alsa/oss.drv`
  (`dll/win32/mmdevapi/main.c:110-111`). Most of `dll/win32` is Wine 10.0. Sync targets: Wine stable 11.0
  (2026-01-13), Wine dev 11.20 (2026-10-16).
- **Export-level roadmap: flip to 0x601 almost immediately.** Only 4 of 83 Win7-gated exports are stubs, and
  Firefox 115 needs them. Go to 0x602/0x603 after real kernelbase, CreateFile2/CopyFile2, WaitOnAddress, Pss* and
  process mitigation. Go to 0xA00 only after per-thread DPI, the apiset V6 rewrite and a complete ucrtbase
  (section 5.0).

---

## 2. Top-30 gaps for modern apps (ordered by "unblocks the most apps first")

Legend: **L** = loader blocks process start (app exits silently), **R** = runtime failure or crash, **K** = needs
new kernel work. Evidence comes from the import check unless a source line is given.

| # | Gap | Type | Evidence | Fix (and owner area) |
|---|---|---|---|---|
| 1 | Apisets disabled for Vista-lowest manifests; Win7 mode has no `api-ms-win-crt-*` | L | `ldrinit.c:1601-1716` (lowest GUID wins), `libsupp.c:1026-1029` (Vista → 0); Python manifest includes Vista GUID; 99 unresolved imports for Python in that mode | Always enable the apiset map (as Windows does), independent of manifest |
| 2 | Apiset lookup: exact last-digit match, per-OS flag sets | L | `apisets.c:60-90` exact `RtlCompareUnicodeString`; FF159 in Win10 mode: 190 unresolved imports (`out/ff159_600_win10.txt`), e.g. `api-ms-win-core-synch-l1-2-0` (flags WIN8\|WIN81 only) | Port Wine `apisetschema.spec` + V6 hashed lookup up to the last `-` (Wine `dlls/ntdll/loader.c:683-720`, LGPL) |
| 3 | Apiset host remapping to wrong DLLs | L | `update.py:14-22`; `api-ms-win-core-path-l1-1-0`→kernel32 lacks `PathCchSkipRoot/CombineEx` (python313.dll); `api-ms-win-security-base-l1-1-0`→kernel32 lacks `GetTokenInformation`, `InitializeAcl`… (mozglue); winrt sets→ole32 lacks `Ro*` (firefox.exe) | Real `kernelbase.dll` (gap 4); map winrt/com to `combase`, scaling to `shcore`, crt to `ucrtbase`; fix stale `ucrtbase→msvcrt` entry in `update.py` |
| 4 | No real `kernelbase.dll` | L | `dll/win32/kernelbase/CMakeLists.txt` builds `kernelbase_ros.dll` with 200 exports (path/string only); 1217 commented `#@` lines | Build Wine 11.x kernelbase (pure PE) as `kernelbase.dll`; kernel32 forwards |
| 5 | Win7 exports gated off at 0x600 | L | Firefox 115 at 0x600 lacks `K32EnumProcessModules`, `K32GetModuleInformation`, `TryAcquireSRWLock*`, `GetThreadGroupAffinity` (all `-version=0x601+`, implemented) | Raise to 0x601 (section 5.0) |
| 6 | DLL search-path API missing: `AddDllDirectory`, `RemoveDllDirectory`, `SetDefaultDllDirectories`; `LOAD_LIBRARY_SEARCH_*` flags ignored | L/R | MISSING in kernel32 and ntdll (`LdrAddDllDirectory` absent); `client/loader.c:300-352` ignores the flags; python313.dll, firefox.exe, plugin-container.exe import them | Implement in ntdll loader (Wine `LdrAddDllDirectory` logic) + kernelbase |
| 7 | ucrtbase C99 math / fenv / complex are stubs | R | `ucrtbase.spec`: 191 stubs (e.g. lines 2233 `acosh`, 2284 `cbrt`, 2345 `erf`); used by python313.dll (9), xul (20), nss3, sqlite3 | Compile Wine `dll/win32/msvcrt/math.c` (already in tree, implements them under `_MSVCR_VER>=120`) for ucrtbase, or musl libm (MIT) |
| 8 | Crashing `@ stub` kernel32 NT6 entries | R | 110 `@ stub` in kernel32.spec (e.g. `CreateWaitableTimerExW`, `SetFileInformationByHandle`, `FlushProcessWriteBuffers`, `FreeLibraryWhenCallbackReturns`, `*Transacted*`, calendar APIs); `stubs.h:53-63` raises 0x80000100 | Implement the ~25 used by real apps first (list in `out/` aggregate) |
| 9 | Process-thread attribute lists are `-stub` (return 0) | R | `InitializeProcThreadAttributeList`/`UpdateProcThreadAttribute`/`DeleteProcThreadAttributeList`; used by Python `subprocess`, firefox.exe and plugin-container (sandbox launch) | User-mode list handling now; `PROC_THREAD_ATTRIBUTE_HANDLE_LIST`/parent need `NtCreateUserProcess` (K) |
| 10 | No dynamic TLS for DLLs loaded after process start | R | `ldrinit.c:1277-1335` only walks modules present at init; no TLS setup in `ldrutils.c` load path | Port Vista-style dynamic TLS (Wine `alloc_tls_slot` in `dlls/ntdll/loader.c`) |
| 11 | I/O cancel and IOCP-Ex: `CancelIoEx`, `CancelSynchronousIo`, `GetQueuedCompletionStatusEx`, `NtCancelIoFileEx`, `NtRemoveIoCompletionEx` | R, K | stubs in kernel32.spec/ntdll.spec; not in `ntoskrnl/include/sysfuncs.h` | Kernel syscalls + kernelbase wrappers (asyncio, Chromium/Firefox IPC need them) |
| 12 | ETW provider API missing in advapi32 (`EventRegister`, `EventWrite`, `EventUnregister`, `EventSetInformation`, `EventWriteTransfer`, `EventActivityIdControl`) | L | MISSING in advapi32.spec; ntdll has `EtwEvent*` as `-stub` 0x600+ | Forward to ntdll and implement ntdll Etw* as "no consumer": success plus a dummy handle |
| 13 | High-resolution timers: `CreateWaitableTimerExW` (`@ stub`), `SetWaitableTimerEx` missing, `SetThreadpoolTimerEx` missing | R | kernel32.spec; python313.dll, mozglue | Implement on NtCreateTimer/NtSetTimer (later NtSetTimerEx) |
| 14 | Time APIs: `RtlQueryPerformanceCounter`, `QueryUnbiasedInterruptTime`, `GetDynamicTimeZoneInformation` (`-stub`), `GetTimeZoneInformationForYear` (`-stub`), `GetSystemTimePreciseAsFileTime` only 0x602+ | L/R | firefox.exe, xul.dll, crashreporter | Straightforward ntdll/kernelbase work (Wine kernelbase has all) |
| 15 | `Pss*` snapshot API, `CopyFile2`, `CreateFile2`, `GetOverlappedResultEx` (Win8 kernelbase set) | L | python313.dll (Pss*, CopyFile2), msvcp140 (CreateFile2, CopyFile2), crashhelper | Comes with Wine kernelbase |
| 16 | Process mitigation / thread info: `SetProcessMitigationPolicy`, `GetProcessMitigationPolicy`, `SetThreadInformation`, `GetProcessInformation` | L, K | firefox.exe, plugin-container | Kernel `NtSet/QueryInformationProcess` classes; accept-and-ignore first |
| 17 | AppModel/packaging APIs absent (`GetCurrentPackageFullName`, `GetCurrentPackageFamilyName`, `GetPackageInfo`, `AppPolicyGetWindowingModel`, …) | L | firefox.exe, xul.dll, Windows App SDK DLLs | Return `APPMODEL_ERROR_NO_PACKAGE` (15700) stubs (kernel.appcore equivalent) |
| 18 | WinRT activation reachable only through combase, but apisets route to ole32; no runtime classes | L/R | firefox.exe imports `RoGetActivationFactory` via `api-ms-win-core-winrt-l1-1-0` → ole32 MISSING; combase.spec: `RoGetActivationFactory` implemented, 164/345 stubs | Fix host map; import `wintypes`, `windows.globalization`, `windows.ui`, `windows.media.*` from Wine 11.x as needed |
| 19 | Per-thread / per-monitor DPI v2 in user32 | L | MISSING: `SetThreadDpiAwarenessContext`, `GetThreadDpiAwarenessContext`, `GetWindowDpiAwarenessContext`, `GetAwarenessFromDpiAwarenessContext`, `AdjustWindowRectExForDpi`, `GetSystemMetricsForDpi`, `SystemParametersInfoForDpi`, `EnableNonClientDpiScaling` | Port the PE-side logic from Wine 11 user32 into `win32ss/user/user32_vista`; win32k stores per-window awareness |
| 20 | TLS 1.3 / modern cipher suites in Schannel | R | `schannel_mbedtls.c:172-178` (TLS1.0-1.2 only); mbedTLS 2.16.11 | Rebase backend on mbedTLS 3.6 LTS (TLS 1.3 on by default) or 4.1 LTS; keep schannel API from Wine 11 |
| 21 | IP Helper NT6 tables: `GetIfTable2(Ex)`, `FreeMibTable`, `ConvertInterfaceLuidToNameW`, `if_nametoindex`, `GetIfEntry2Ex` stubs; `WSASendMsg`, `WSCGetProviderInfo` stubs | R | iphlpapi 85 stubs at 0xA00; Python `_socket.pyd`, xul | Implement on ReactOS tcpip IOCTLs (Wine's version needs `nsiproxy.sys`, which is Unix-backed) |
| 22 | WASAPI has no endpoint backend | R | `mmdevapi/main.c:68-111` loads `wine<name>.drv` from list `pulse,alsa,oss,coreaudio,android`; none exist | Write `winemm-ks`-style driver over KS/portcls (`wdmaud`); then sync dsound (forked at Wine 1.3.29) and add XAudio2 (Wine + FAudio, zlib) |
| 23 | Vulkan loader and ICD absent; in-box GL is Mesa 2.6 (GL 1.1) | R | no `vulkan-1` in tree; `dll/opengl/Mesa_for_ReactOS.txt`; wined3d tries `winevulkan.dll`/`vulkan-1.dll` (`adapter_vk.c:101-102`) | Ship Khronos loader (Apache-2.0, flagged, as separate unmodified binary) + Mesa 26.x lavapipe/llvmpipe (MIT) as fallback ICD |
| 24 | Wait-completion packets, `NtAlertThreadByThreadId`, `NtWaitForAlertByThreadId`, `NtSetIoCompletionEx` | L, K | ntdll MISSING (Chromium-era threadpool; Wine 11 SRW/condvar use them) | Kernel syscalls; ntdll threadpool (synced to Wine 9.7) can then be re-synced |
| 25 | KTM (`ktmw32.dll`, `RegCreateKeyTransactedW`, `*Transacted*` file APIs) | L | xul.dll imports `ktmw32!CreateTransaction/CommitTransaction`; kernel32 `*Transacted*` are `@ stub` | Add Wine `ktmw32` (returns failure), make `*Transacted*` return `ERROR_CALL_NOT_IMPLEMENTED` instead of crashing |
| 26 | `cfgmgr32!CM_Register_Notification` | L | xul.dll | Implement over umpnpmgr device-event channel |
| 27 | WNF / device family: `RtlSubscribeWnfStateChangeNotification`, `NtQueryWnfStateData`, `RtlGetDeviceFamilyInfoEnum`, `RtlIsMultiSessionSku` | L | ntdll MISSING (FF159 / WinAppSDK) | Stubs returning `STATUS_NOT_IMPLEMENTED` / "Desktop" family |
| 28 | Unicode: `NormalizeString`, `IsNormalizedString`, `IdnToUnicode/Ascii`, `ResolveLocaleName`, `GetStringScripts`/`VerifyScripts` stubs; no ICU | R | kernel32.spec (`-stub` / `@ stub` 0x600+); no `icu*.dll` in tree; NLS code from WineStaging-3.3 | Take Wine 11 kernelbase `locale.c` (NLS-file based) and Wine's PE ICU build (`dlls/icu`, `icuuc`) |
| 29 | `RaiseFailFastException`, `Wer*` (`WerRegisterRuntimeExceptionModule`) | L/R | mozglue MISSING; kernel32 `RaiseFailFastException` `-stub` 0x603+ | Simple: terminate process / accept registration |
| 30 | Power/energy APIs: `PowerCreateRequest/SetRequest/ClearRequest`, `PowerRegisterForEffectivePowerModeNotifications`; `GetSystemCpuSetInformation`, `IsWow64Process2` | L | xul.dll, FF159 | Thin kernelbase/powrprof implementations (map to `SetThreadExecutionState`) |

Also noted but outside the top 30: `GetLogicalProcessorInformationEx` is `-stub` (msvcp140 concurrency);
user32 `GetWindowCompositionAttribute`, `CalculatePopupWindowPosition` and `EnableMouseInPointer` are missing;
`propsys!VariantCompare` is a stub; `bcp47langs` has 71/71 stubs; DWM composition is absent (dwmapi Wine 8.14,
36/60 stubs).

**Missing DLLs vs exports vs kernel: the answer.**
1. **Loader/apiset policy first.** ucrtbase and combase exist, but apisets are off or misrouted. One focused
   ntdll change unblocks the CRT imports of every MSVC 2015+ binary.
2. **Missing exports next, mostly in the kernel32/kernelbase set.** About 70 functions across the three test
   apps; most are available as pure-PE code in Wine kernelbase.
3. **Missing DLLs third:** kernelbase (real), sechost, ktmw32, icu, WinRT `windows.*`, mf/mfplat, xaudio2,
   vulkan-1.
4. **Kernel features last but unavoidable:** about 15 NT6+ syscalls for I/O cancel, IOCP-Ex, process creation
   with attributes, ALPC and alert-by-thread-id, plus dynamic TLS in the loader.

---

## 3. Component table

Stats are `.spec` exports/stubs at 0x502 → 0xA00 (x86). FIXME/UNIMPLEMENTED are textual counts in the module
sources. "Stage" = Okno plan stage: 1 apps, 2 x64/WoW64/SMP, 3 PC hardware, 4 laptops, 5 WDDM GPUs, 6 polish.

### 3.1 Core (ntdll / kernel32 / kernelbase / apisets / advapi32 / CRT)

| Win10 counterpart | ReactOS path | Origin | Real state (evidence) | Best option 2026 | Stage |
|---|---|---|---|---|---|
| ntdll.dll | `dll/ntdll`, `sdk/lib/rtl` | ReactOS own; `rtl/actctx.c` Wine-10.0, `rtl/threadpool.c` Wine-9.7 | 1884 entries; 1401/24 → 1843/395; 483 NT6-only; 33 `@ stub`, 386 `-stub`; missing `LdrAddDllDirectory*`, `RtlQueryPerformanceCounter`, WNF, wait packets; ALPC/`NtCancelIoFileEx` stubs; no dynamic TLS; apiset gating | Keep own (bound to ReactOS kernel and CSRSS); port Wine 11 PE pieces: apiset V6, dynamic TLS, dll dirs, threadpool resync | 1 |
| ntdll_vista.dll (ReactOS-only) | `dll/ntdll/nt_0600` | own | holds SRW/condvar/WaitOnAddress/threadpool for 0x502 builds | Retire once default ≥0x600 everywhere (keep for compat until then) | 1 |
| kernel32.dll | `dll/win32/kernel32` | own; `wine/*.c` Wine 3.3 / WineStaging-3.3; `winnls` WineStaging-3.3 | 1284 entries; 980/0 → 1266/165 (110 `@ stub` crash, 55 `-stub`); UNIMPLEMENTED 38; 69 functions missing for test apps | Keep own for CreateProcess/console/CSR/BaseSrv; forward pure-user functions to real kernelbase | 1 |
| kernel32_vista.dll (ReactOS-only) | `dll/win32/kernel32/kernel32_vista` | own | NT6 functions for ReactOS apps in 0x502 builds | Keep while 0x502 builds exist, then fold | 1 |
| kernelbase.dll | `dll/win32/kernelbase` → **`kernelbase_ros.dll`** | Wine, untracked version (static lib `wine/{locale,path,string}.c`) | 200 exports (path/string/url only), 1217 `#@` commented; no `kernelbase.dll` file exists (`modules/rostests/unittests/pathcch/CMakeLists.txt:27` "Requires kernelbase.dll") | **Replace**: Wine 11.x kernelbase (pure PE, 22 files) as `kernelbase.dll`; LGPL | 1 |
| ApiSetSchema / api-ms-win-* | `sdk/lib/apisets` (linked into ntdll `rtl_um`) | own (2024), data from apisets.info | about 1062 active entries, 139 commented; 346 entries → 190 non-existent hosts; exact-version match; per-OS flags; host remap bugs | **Rewrite** with Wine `apisetschema.spec` semantics (V6, hash to last hyphen), always on | 1 |
| advapi32.dll | `dll/win32/advapi32` (+`advapi32_vista`) | own; `wine/crypt*.c` Wine-10.0, `wine/cred.c` WineStaging-3.3, `wine/security.c` out of sync | 686/120 → 699/128 (120 `@ stub`); ETW `Event*` missing; `RegCreateKeyTransactedW`, `AddMandatoryAce` missing; `RegRenameKey` stub | Keep; add ETW forwards; split service/security to `sechost` (Wine 11) | 1 |
| sechost.dll | — | — | 33 apiset entries target it | Add from Wine 11 (`dlls/sechost`) | 1 |
| msvcrt.dll | `dll/win32/msvcrt` (+`sdk/lib/crt`) | Wine-10.0 (built with `_MSVCR_VER=0`) | 860/13 → 1312/24 | Sync to Wine 11.x via winesync `crt.cfg` | 1 |
| ucrtbase.dll | `dll/win32/ucrtbase`, `sdk/lib/ucrt`, `sdk/lib/vcruntime` | Microsoft UCRT source subset (MIT; NuGet Microsoft.Windows.SDK.CRTSource 10.0.22621.3) + ReactOS glue (Timo Kreuzer, MIT) + Wine `msvcrt_shared` | 2614/191 (95 `@ stub` crash): C99 math, complex, `fe*`, `_dpcomp`, `_except1`, `__control87_2` | Keep MS UCRT core; fill math/fenv from Wine `msvcrt/math.c` (musl-derived, LGPL/MIT) | 1 |
| api-ms-win-crt-*.dll | (apiset table only) | — | resolved only in Win10 compat mode | Always-on apiset fix; optionally ship physical forwarder DLLs for robustness | 1 |
| vcruntime140 / msvcp140 | `sdk/lib/vcruntime` (static only) | — | not shipped (apps bring their own) | Keep app-local; optionally ship Wine 11 `msvcp140*`/`vcruntime140*` as fallback | 1 |
| crtdll/msvcrt20/msvcrt40 | `dll/win32/*` | own / out of sync | 520/9, 1126/441, 1162/449 | Keep (legacy) | – |

### 3.2 Win32 GUI subsystem (win32ss)

| Win10 counterpart | ReactOS path | Origin | Real state (evidence) | Best option 2026 | Stage |
|---|---|---|---|---|---|
| win32k.sys (win32kbase/full) | `win32ss/user/ntuser` (61 files, ~75k lines), `win32ss/gdi/ntgdi` (40 files, ~42k), `win32ss/gdi/eng` (DDI, 164 UNIMPLEMENTED), `dib`/`diblib` | own; `ntgdi/bezier.c` WineStaging-1.9.4 | 742 syscalls ordered as Server 2003 SP2 (`w32ksvc32.h`); FreeType font engine in `ntgdi/freetype.c`; D3DKMT entry points in `ntgdi/d3dkmt.c` (MIT, mostly stubs: no dxgkrnl) | Keep own (no realistic replacement); extend: per-window DPI, pointer input, DirectComposition hooks later | 1/5 |
| win32u.dll | `win32ss/win32u` | own | 662 syscall stubs exported | Keep | 1 |
| user32.dll | `win32ss/user/user32`, `user32_vista` | own; controls WineStaging-1.7.37/1.7.55; `user32_vista/{input,misc,win}.c` Wine-10.0 | 730/2 → 782/5; Win7 touch/gesture present (0x601+); DPI v2 per-thread missing (8 functions) | Keep; port DPI/pointer helpers from Wine 11 PE user32 | 1 |
| gdi32.dll | `win32ss/gdi/gdi32`, `gdi32_vista` | own | 613/0 → 673/0; `D3DKMT*` 0x600+ thunks to NtGdiDdDDI* | Keep | 1/5 |
| imm32.dll | `win32ss/user/imm32` | own | 132/0 | Keep | 1 |
| CSRSS user/console servers | `win32ss/user/winsrv` | own | 36 files | Keep (console moves to condrv model later, see 4.4) | 1 |
| DirectDraw kernel (dxg.sys, dxgthk, dxapi) | `win32ss/reactx/*` | own | DirectDraw-era kernel; `ntdxvista` only a header | Freeze; WDDM goes through new dxgkrnl | 5 |
| Display/font drivers, videoprt | `win32ss/drivers/*` | own | framebuf/vga displays; miniports bochs, vbe, vmx_svga…; `ftfd`/`bmfd` | Keep for XDDM; WDDM path is stage 5 | 3/5 |
| Spooler (printing) | `win32ss/printing` | own; localui WineStaging-4.18 | 218 FIXME / 61 UNIMPLEMENTED | Keep, low priority | 6 |

### 3.3 COM / RPC / WinRT / shell

| Win10 counterpart | ReactOS path | Origin | Real state (evidence) | Best option 2026 | Stage |
|---|---|---|---|---|---|
| combase.dll | `dll/win32/combase` | Wine-10.0 | 345/164; Ro* and HSTRING implemented; not reachable via apisets (mapped to ole32) | Sync Wine 11.x (winesync `com.cfg`), fix apiset hosts | 1 |
| ole32 / oleaut32 / coml2 | `dll/win32/ole32`, `oleaut32`, `coml2` | Wine-10.0 | 344/72 (136 forwards to combase); 418/27; 23/11 | Sync Wine 11.x | 1 |
| rpcrt4.dll | `dll/win32/rpcrt4` | Wine-10.0 | 543/227 stubs (`rpcrt4.cfg`) | Sync Wine 11.x | 1 |
| rpcss / DcomLaunch | `base/services/rpcss` (Wine-10.0), `base/services/dcomlaunch` (own) | mixed | — | Sync rpcss with combase | 1 |
| WinRT runtime classes (wintypes, windows.*.dll, twinapi.appcore, kernel.appcore) | — | — | absent; Wine 11.20 has 29 `windows.*` DLLs + `wintypes`, `twinapi.appcore` | Import from Wine on demand (Globalization, Storage, UI.ViewManagement, Media.*) | 1 |
| shell32.dll | `dll/win32/shell32` | forked at Wine-20071011, mostly own C++ | 466/17 → 629/154; 481 FIXME, 137 UNIMPLEMENTED | Keep own; fill Win7+ COM APIs that apps call (IFileDialog lives in comdlg32) | 1 |
| shlwapi.dll | `dll/win32/shlwapi` | WineStaging-3.3 | 858/58 | Sync to Wine 11 (most functions now forward to kernelbase there) | 1 |
| shcore.dll | `dll/win32/shcore` | Wine-derived, untracked | 185/115 | Sync Wine 11; becomes the apiset host for `shcore-*` | 1 |
| comctl32 v5/v6 | `dll/win32/comctl32` | Wine-5.0 (button Wine-3.3, datetime Wine-6.0) | 180/0 | Sync to Wine 11 (task dialogs, v6 controls) | 1 |
| comdlg32.dll | `dll/win32/comdlg32` | Wine-10.0 | 28/4 | Sync | 1 |
| propsys.dll | `dll/win32/propsys` | Wine-10.0 | 208/164 stubs; `VariantCompare` stub (xul) | Sync and implement used functions | 1 |
| uxtheme.dll | `dll/win32/uxtheme` | forked | 92/22 | Later (visual polish) | 6 |
| dwmapi.dll / DWM | `dll/win32/dwmapi` (0x600+ only) | Wine-8.14 | 60/36 stubs; no DWM | Sync Wine 11; report composition disabled until WDDM | 5 |
| dcomp.dll | `dll/win32/dcomp` (0x603+ only) | Wine-10.0 | 16/12 | Sync; real DirectComposition only with DWM | 5 |
| uiautomationcore | `dll/win32/uiautomationcore` | Wine-10.0 | 98/62 | Sync | 1 |
| explorer.exe | `base/shell/explorer` | own (C++) | 23 files | Keep; functional fixes only until stage 6 | 1/6 |
| rshell.dll | `base/shell/rshell` | own (quick launch band, shell bars/menus) | 14 exports | Keep | 6 |
| cmd.exe | `base/shell/cmd` | own | 58 files | Keep | 1 |
| Control Panel applets | `dll/cpl/*` | own, except `bthprops` (Wine-10.0) and `inetcpl` (WineStaging-4.18) | mostly complete for XP-era | Keep; Settings app is stage 6 | 6 |
| Shell extensions | `dll/shellext/*` | own (`shellbtrfs` = WinBtrfs 1.8.1, LGPL-3.0) | `netshell` 26/33 stubs | Keep | 6 |

### 3.4 Crypto, security, networking

| Win10 counterpart | ReactOS path | Origin | Real state (evidence) | Best option 2026 | Stage |
|---|---|---|---|---|---|
| bcrypt.dll (CNG) | `dll/win32/bcrypt` | Wine-11.19 + SymCrypt 103.11.0 (MIT) + mbedtls import | 62/23 | Keep synced; SymCrypt → 103.13.0 | 1 |
| bcryptprimitives.dll | `dll/win32/bcryptprimitives` (0x600+) | Wine-10.0 | 1/0 (`ProcessPrng`) | Keep | 1 |
| ncrypt.dll (KSP) | `dll/win32/ncrypt` (0x600+) | Wine-11.19 | 138/80 stubs | Implement KSP registration (CryptoPro CSP installs a KSP/CSP) | 1 |
| crypt32 / cryptnet / wintrust / cryptui | `dll/win32/*` | Wine-10.0 | crypt32 247/35; wintrust 127/38 | Sync Wine 11 | 1 |
| rsaenh/dssenh CSPs | `dll/win32/rsaenh` | Wine-11.19 + SymCrypt | 27/0 | Keep | 1 |
| schannel.dll / SSPI | `dll/win32/schannel` | WineStaging-3.3 frontend (`schannel_wine.c` Wine 1.7.17) + own mbedTLS backend | TLS 1.0-1.2 only (`schannel_mbedtls.c:172-178`) | **Rewrite backend** on mbedTLS 3.6 LTS or 4.1 LTS (TLS 1.3); frontend from Wine 11 secur32/schannel | 1 |
| secur32 / sspicli | `dll/win32/secur32` (forked), `sspicli` (Wine-10.0) | mixed | 76/18; 104/47 | Sync sspicli | 1 |
| mbedtls.dll | `dll/3rdparty/mbedtls` | mbedTLS 2.16.11 (Apache-2.0 OR GPL-2.0-or-later) | EOL branch | Upgrade to 3.6.x LTS (EOL 2027-03) now, 4.1 LTS (EOL 2029-03) next | 1 |
| winhttp / wininet / urlmon | `dll/win32/*` | Wine-10.0 | winhttp 49/0, wininet 248/42 | Sync Wine 11 | 1 |
| ws2_32.dll | `dll/win32/ws2_32` | own | 117/0 → 166/22; `inet_pton`/`inet_ntop` 0x600+; `WSASendMsg` stub | Keep; implement NT6 functions | 1 |
| iphlpapi.dll | `dll/win32/iphlpapi` | "Out of sync" Wine | 157/59 → 183/85 stubs | Rewrite NT6 table APIs on ReactOS tcpip | 1 |
| dhcpcsvc / dnsapi / dnsrslvr | `base/services/dhcpcsvc`, `dll/win32/dnsapi`, `base/services/dnsrslvr` | own | dhcpcsvc 38/21 stubs; dnsapi 191/58, 105 UNIMPLEMENTED; no DHCPv6 | Keep, extend (DHCPv6, DoH later) | 3 |
| wlanapi / wlansvc | `dll/win32/wlanapi`, `base/services/wlansvc` | own | wlansvc `rpcserver.c` 40 UNIMPLEMENTED | Rewrite with NDIS 6 WLAN (stage 4) | 4 |
| netapi32 | `dll/win32/netapi32` | forked Wine-1.3.34 | 340/142 | Keep | 1 |

### 3.5 Graphics, media, text

| Win10 counterpart | ReactOS path | Origin | Real state (evidence) | Best option 2026 | Stage |
|---|---|---|---|---|---|
| d3d8/d3d9/ddraw + wined3d | `dll/directx/wine/{d3d8,d3d9,ddraw,wined3d}` (wined3d built as `d3dwine.dll`) | Wine 10.1-dev `b00c7619f1b` | wined3d 354/0; GL backend or Vulkan backend (`adapter_vk.c`) | Sync Wine 11.x; DXVK 3.1.1 (zlib license) as optional D3D9-11 path when Vulkan exists | 1/5 |
| dxgi / d3d10 / d3d10_1 / d3d11 | `dll/directx/wine/*` (**0x600+ only**) | Wine 10.1-dev | `D3D11CreateDevice`, `CreateDXGIFactory2` implemented; d3d11 33/38 stubs are D3DKMT/forwards | Same | 1/5 |
| d3d12 / d3d12core / dxcore | `dll/directx/wine/*` (**0xA00 only**), `sdk/lib/vkd3d` (vkd3d 1.14) | Wine 10.1-dev | needs Vulkan | Wine vkd3d 2.1 (LGPL) or VKD3D-Proton 3.1 (LGPL-2.1) | 5 |
| d3dcompiler_47 etc. | `dll/directx/wine/d3dcompiler_*` | Wine (vkd3d-shader) | — | Sync | 1 |
| Direct2D (d2d1) | `dll/directx/wine/d2d1` (0x600+) | Wine 10.1-dev | `D2D1CreateFactory/Device` implemented | Sync Wine 11 | 1 |
| DirectWrite (dwrite) | `dll/directx/wine/dwrite` (0x600+) | Wine 10.1-dev + in-tree FreeType static lib | `DWriteCreateFactory` implemented; `reactos.c` shim | Sync Wine 11; FreeType 2.10.4 → 2.15.0 | 1 |
| WIC (windowscodecs) | `dll/win32/windowscodecs` (+ext) | Wine-10.0 (+ libpng 1.6.54, libjpeg 10, libtiff 4.7.1) | 118/5 | Sync Wine 11 (adds JPEG-XR/HEIF via codecs in Wine) | 1 |
| gdiplus | `dll/win32/gdiplus` | Wine-10.0 | 630/13 | Sync | 1 |
| opengl32.dll | `dll/opengl/opengl32` | own (ICD loader + `swimpl.c`) | 368/6 | Keep loader | 5 |
| Software GL | `dll/opengl/mesa` | **Mesa 2.6** (GL 1.1, by design: CORE-7499) | GPL-2.0-or-later | Optional Mesa 26.2.x llvmpipe/lavapipe build (MIT) as installable fallback ICD | 5 |
| glu32 | `dll/opengl/glu32` | Mesa GLU 9.0.1 (SGI-B-2.0) | — | Keep | – |
| vulkan-1.dll | — | — | absent | Khronos Vulkan-Loader (Apache-2.0, flagged: ship unmodified, separate) | 5 |
| DirectSound | `dll/directx/wine/dsound` | forked Wine-1.3.29 | own mixer over winmm | Re-sync after WASAPI backend exists | 1/3 |
| MMDevAPI / WASAPI | `dll/win32/mmdevapi` | WineStaging-4.18 | 18/14; no backend driver | Write KS backend | 1/3 |
| winmm | `dll/win32/winmm` | forked Wine-20050628 | 194/8 | Keep | 1 |
| XAudio2 / X3DAudio | — | — | absent | Wine 11 xaudio2_* (FAudio, zlib) | 1 |
| DirectShow (quartz, qcap, qedit, amstream) | `dll/directx/wine/*` | Wine 10.1-dev | — | Sync | 1 |
| Media Foundation (mf, mfplat, mfreadwrite) | — | — | absent (FF159 WinAppSDK imports `mf.dll`, `mfplat.dll`) | Wine 11 mf* PE parts + own PE codec backend (Wine's `winedmo`/`winegstreamer` are Unix-backed) | 1 |
| dxva2 | `dll/directx/wine/dxva2` (0x600+) | Wine 10.1-dev | 38/1 | Sync | 5 |
| dinput / dinput8 / xinput | `dll/directx/wine/dinput*`, `dll/win32/xinput*` | WineStaging-4.18 / 2.9 | — | Sync Wine 11 (HID-based) | 3 |
| usp10 (Uniscribe) / lpk | `dll/win32/usp10`, `dll/win32/lpk` | Wine-11.17 / own with Wine-4.9 bidi | 44/5 | Keep synced | 1 |
| ICU (icu.dll, icuuc, icuin) | — | — | absent | Wine 11 `dlls/icu*` PE build of ICU (Unicode-3.0 license); upstream ICU 79.1 | 1 |
| NLS (sorting, normalization, IDN) | kernel32 `winnls/*` (WineStaging-3.3), `dll/nls/{idndl,normaliz}`, `sdk/tools/unicode` (WineStaging-4.18) | mixed | normalization/IDN stubs | Wine 11 kernelbase `locale.c` + `.nls` data | 1 |
| FreeType | `sdk/lib/3rdparty/freetype` | 2.10.4 (header; the 3rd-party doc says 2.10.0) | FTL/GPLv2 dual | 2.15.0 | 1 |

### 3.6 Services and applications

| Win10 counterpart | ReactOS path | Origin | State | Best option | Stage |
|---|---|---|---|---|---|
| Audio service (AudioSrv, AudioEndpointBuilder) | `base/services/audiosrv` | own | 5 files, PnP list only | Extend with WASAPI endpoint registry | 1/3 |
| Event log | `base/services/eventlog` | own | 11 FIXME | Keep; add ETW channel stubs | 1 |
| Plug and Play | `base/services/umpnpmgr` | own | 20 UNIMPLEMENTED | Extend (`CM_Register_Notification`) | 1/3 |
| svchost / services / lsass / winlogon | `base/services/svchost`, `base/system/*` | own | — | Keep | – |
| DHCP / DNS / WLAN / time / server / workstation | `base/services/{dhcpcsvc,dnsrslvr,wlansvc,w32time,srvsvc,wkssvc}` | own | srvsvc 50, wkssvc 16, wlansvc 40 UNIMPLEMENTED | Keep, extend per stage | 3/4 |
| Task scheduler | `base/services/schedsvc` + `dll/win32/mstask` (WineStaging-3.3) | mixed | — | Keep | 1 |
| Windows Update / BITS | `base/services/wuauserv`, `dll/win32/qmgr` (Wine-10.0) | own / Wine | stubs | Low priority | – |
| Programs | `base/applications/*` | own, except Wine: `cmdutils/{cscript,reg,schtasks,taskkill,wmic,wscript,xcopy}`, `extrac32`, `iexplore`, `notepad` (forked 2004), `winhlp32`, `wordpad`, `write`, `games/winmine`, `regedit` (partial Wine-7.17) | — | Keep; `rapps` is the package manager | 6 |

The full per-DLL classification (all 279 `dll/win32/*` modules, plus `dll/directx/wine`, `dll/cpl`,
`dll/shellext`, `base/services`, `base/shell` and `win32ss`) is in Appendix A.

### 3.7 Third-party libraries (versions in tree vs upstream 2026-10-29)

| Library | Path | In tree | Upstream latest | License | Action |
|---|---|---|---|---|---|
| mbedTLS | `dll/3rdparty/mbedtls` | 2.16.11 (EOL) | 3.6.7 (LTS until 2027-03), 4.1.x (LTS until 2029-03), 4.2.0 | Apache-2.0 OR GPL-2.0-or-later | Upgrade (schannel rewrite) |
| SymCrypt | `sdk/lib/3rdparty/symcrypt` | 103.11.0 (+Wine 11.16 patches) | 103.13.0 | MIT | Bump with next bcrypt sync |
| FreeType | `sdk/lib/3rdparty/freetype` | 2.10.4 | 2.15.0 | FTL or GPL-2.0 | Upgrade (win32k + dwrite) |
| zlib | `sdk/lib/3rdparty/zlib` | 1.2.13 | 1.3.2 | Zlib | Upgrade |
| libpng | `dll/3rdparty/libpng` | 1.6.54 (header; doc says 1.6.51) | 1.6.59 | libpng-2.0 | Upgrade |
| libjpeg (IJG) | `dll/3rdparty/libjpeg` | 10 (2026-01-25) | 10 | IJG (BSD-like) | Keep |
| libtiff | `dll/3rdparty/libtiff` | 4.7.1 | — | libtiff | Keep |
| libxml2 / libxslt | `sdk/lib/3rdparty/libxml2`, `dll/3rdparty/libxslt` | 2.10.3 / 1.1.37 | 2.15.4 / – | MIT | Upgrade libxml2 (msxml3 uses it) |
| Mesa (SW GL) | `dll/opengl/mesa` | 2.6 | 26.2.6 (mesa-dist-win 26.2.4) | MIT (modern) | Optional fallback ICD |
| vkd3d (Wine) | `sdk/lib/vkd3d` | 1.14 | 2.1 | LGPL-2.1+ | Sync with d3d12 |
| DXVK | — | — | 3.1.1 | zlib | Optional (stage 5) |
| VKD3D-Proton | — | — | 3.1 | LGPL-2.1 | Optional alternative to vkd3d (stage 5) |
| Vulkan-Loader | — | — | SDK 1.4.363.0 | **Apache-2.0** (flag: not GPLv2-compatible; ship only as separate unmodified binary or avoid) | Decide in stage 5 |
| ICU | — | — | 79.1 | Unicode-3.0 (MIT-like) | Add |
| STLport | `sdk/lib/3rdparty/stlport` | 5.2.1 | dead upstream | BSD | Retire (clang/libc++ or MS STL, Apache-2.0 WITH LLVM-exception → flag) |
| lwIP | `drivers/network/tcpip/lwip` | 2.2.0 | (kernel area) | BSD | – |

License flags in the user-mode area:
- `base/applications/mstsc` (rdesktop 1.8.3) is **GPL-3.0-or-later**, so that binary is GPLv3. It is fine as a
  separate program, but its code must not be copied into GPLv2 modules.
- `dll/shellext/shellbtrfs` is **LGPL-3.0-or-later**, so it can only combine with GPLv3. It is a separate DLL.
- `media/fonts/trebuc*.ttf` (Open Sans) is Apache-2.0 font data.
- No Apache-2.0-only code is linked into user-mode DLLs; mbedTLS is dual-licensed.

---

## 4. Remember-once knowledge

### 4.1 `.spec` files and spec2def

- Tool: `sdk/tools/spec2def/spec2def.c`; CMake wrapper `spec2def(<dll> <spec> [ADD_IMPORTLIB] [VERSION <hex
  without 0x>] [WITH_RELAY] [WITH_DBG|NO_DBG] [NO_PRIVATE_WARNINGS])` in `sdk/cmake/gcc.cmake:505-538` (MSVC
  equivalent in `msvc.cmake`). Output: `<name>.def` + `<name>_stubs.c`. `ADD_IMPORTLIB` creates `lib<name>` and
  `lib<name>_delayed`.
- Line syntax: `@ <cc> [flags] Name(args) [target]`, where `<cc>` is one of
  `stdcall|cdecl|fastcall|thiscall|extern|stub`, and `[target]` is either `dll.Func` (forward) or a local symbol.
  Flags:
  - `-version=0x600+`: from 0x600 up.
  - `-version=0x502`: exactly 0x502.
  - `-version=0x400-0x502`: a range.
  - Comma lists are allowed.
  - `-arch=i386,x86_64` or `-arch=!i386`
  - `-stub`, `-private`, `-noname`, `-ordinal`, `-norelay`, `-ret64`, `-register`, `-impsym`, `-dbg`.
  - Parsing is in `spec2def.c:1106-1162`. Hex is assumed, and the open end is 0xFFF.
- **Stub semantics (important):**
  - `@ stub Foo` (calling convention `stub`) raises a non-continuable `EXCEPTION_WINE_STUB` 0x80000100 when
    called (`sdk/include/reactos/stubs.h:53-63`), so the app crashes.
  - `@ stdcall -stub Foo(ptr)` prints `WARNING: calling stub` and returns 0, so the app sees a failure value.
  - When adding an NT6 export you cannot implement yet, prefer `-stub` with a correct prototype, or better a
    real function returning `ERROR_CALL_NOT_IMPLEMENTED`.
- Global level: `DLL_EXPORT_VERSION` cache variable, default `0x502` (`sdk/cmake/config.cmake:117`; the fork now
  uses 0x600). It is passed as `-DDLL_EXPORT_VERSION=` to compilers and `--version=` to spec2def
  (`CMakeLists.txt:246`).
- `DLL_EXPORT_VERSION` is independent of:
  - `_WIN32_WINNT`/`WINVER`, defined globally as 0x502 (`CMakeLists.txt:238-246`); modules override them with
    `remove_definitions()`/`add_definitions()`.
  - The reported OS version (5.2 from `sdk/include/psdk/ntverp.h:25`), which is changed only by apphelp version-lie
    shims (`dll/appcompat/shims/layer/versionlie.c:37-55`).
- `DLL_EXPORT_VERSION` also gates whole modules:
  - ≥0x600: `avrt`, `bcryptprimitives`, `dwmapi`, `ncrypt`, `tbs` and `wevtapi` (`dll/win32/CMakeLists.txt:277-284`),
    plus `dxgi`, `d3d10*`, `d3d11`, `d2d1`, `dwrite`, `dxva2` and `d3dx10/11`
    (`dll/directx/wine/CMakeLists.txt:80-102`).
  - ≥0x603: `bcp47langs`, `dcomp` and `rtworkq`.
  - ≥0xA00: `d3d12`, `d3d12core` and `dxcore`.
  - It also changes the build of `ntdll`, `advapi32`, `ws2_32`, `shell32`, `comdlg32`, `uxtheme`, `shlwapi`,
    `ws2help` and `kernel32_vista` (grep `DLL_EXPORT_VERSION` in their CMakeLists).
- Distribution of version tags in this snapshot (all `.spec` under `dll`, `win32ss`, `base`): 1791 `0x600+`,
  83 `0x601+`, 24 `0x602+`, 1 `0x603+`, 16 `0xA00+`, 101 `0x502`-only. Most `0x502`-only lines have a `0x600+`
  twin that forwards in the other direction (e.g. `advapi32.spec:2-3` `A_SHAFinal`), so raising the level does
  not lose them. The coordinator's count on the fork tree: 1792 / 85 / 36 / 1 / 16 / 101.
- `*_vista` side DLLs (`ntdll_vista`, `kernel32_vista`, `advapi32_vista`, `user32_vista`, `gdi32_vista`,
  `uxtheme_vista`) exist so that ReactOS's own NT6-needing code works in 0x502 builds. Imports must list them
  explicitly (`add_importlibs(x ... kernel32_vista kernel32 ntdll)`).

### 4.2 Apiset machinery

- Code: `sdk/lib/apisets/apisets.c` (binary search, exact name match after stripping `.dll`),
  `apisets.table.c` (generated table `{name, host, APISET_WIN7|WIN8|WIN81|WIN10}`) and `update.py` (generator from
  apisets.info JSON). `update.py:14-22` `REDIRECT_HOSTS` maps missing hosts:
  - `kernelbase→kernel32`
  - `kernel.appcore→kernel32`
  - `combase→ole32`
  - `ucrtbase→msvcrt` (stale: the committed table already says `ucrtbase.dll`, so re-running the script would
    regress)
  - `shcore→shell32`
  - `winmmbase→winmm`
  - `gdi32full→gdi32`
- Linked into ntdll (`dll/ntdll/CMakeLists.txt:24`). The hook is `LdrpApplyFileNameRedirection`
  (`dll/ntdll/rtl/libsupp.c:1060-1150`), which runs before SxS redirection.
- Activation: `LdrpApisetVersion()` (`libsupp.c:1015-1050`) reads `RosGetProcessCompatVersion()`
  (`sdk/include/reactos/compat_undoc.h:24-38`). That value is set by:
  - apphelp shims (`dll/appcompat/apphelp/hsdb.c:732-763`), or
  - `LdrpInitializeProcessCompat` from manifest `supportedOS` GUIDs, picking the **lowest**
    (`ldrinit.c:1601-1716`). It can be disabled by policy (`LdrpDisableProcessCompatGuidDetection`).
- Results:
  - no manifest → apisets off;
  - Vista → off;
  - Win7..Win10 → that flag set only.
- Windows semantics to copy (Wine `dlls/ntdll/loader.c:683-720`): the schema is always present, and the lookup
  hashes the name up to the last `-`, so any minor version of `-lX-Y-*` matches.

### 4.3 How a Wine DLL is synced

- Status file: `media/doc/WINESYNC.txt`. Update it in the same commit.
- Automated tool: `sdk/tools/winesync/winesync.py <module> <wine_tag|commit> [<staging_tag>]`. It needs `pygit2`
  and `pyyaml`, plus local clones of reactos, wine and wine-staging (paths are stored in `winesync.cfg`).
- `<module>.cfg` maps Wine paths to ReactOS paths (`directories:`, `files:`) and stores the last synced tag. The
  tool replays **each Wine commit** between tags as one ReactOS commit `[WINESYNC] <msg>` with
  `git apply --reject`.
- On failure it stops so you can fix the code, amend and rerun. Staging patches are saved under
  `<module>_staging/NNNN-*.diff`.
- Configs exist for: com (combase, coml2, mscoree, rpcss), comctl32, crt, d3dx9, dbghelp, kernel32, msi,
  propsys, reg, riched20, rpcrt4, rtl, windowscodecs, winhttp, wininet, wintrust (`sdk/tools/winesync/*.cfg`).
  Everything else is synced by hand: copy the files, re-apply the `#ifdef __REACTOS__` blocks, update the spec
  and CMakeLists.
- Wine modules build with `set_wine_module(<target>)` / `set_wine_module_FIXME` (`sdk/cmake/set_wine_module.cmake`,
  adds `sdk/include/wine` and `__WINESRC__`). They link the `wine` static lib (`sdk/lib/3rdparty/libwine`:
  debug channels and helpers). ReactOS deltas inside Wine code are marked `#ifdef __REACTOS__`.
- Unix-backed Wine parts cannot be taken:
  - `dlls/ntdll/unix`, `win32u`, `winevulkan`, `winepulse.drv`/`winealsa.drv`, `nsiproxy.sys`, `winedmo`,
    `winegstreamer`;
  - `dwrite`'s unixlib (ReactOS wraps it with `dll/directx/wine/dwrite/reactos.c`).

  Wine `kernelbase`, `combase`, `ucrtbase`, `msvcp140`, `icu*`, `windows.*`, `sechost`, `ktmw32`,
  `apisetschema` and `xaudio2_*` are pure PE (verified in the Wine 11.20 tree).

### 4.4 Core-DLL strategy: own vs Wine

- **ntdll: stay own.** Wine ntdll's syscall layer is Unix (24 files in `dlls/ntdll/unix`). The PE half (48 files:
  loader, heap, actctx, threadpool, rtl*) is portable function by function, and ReactOS already does that for
  `actctx.c` and `threadpool.c`. Next ports: apiset V6, dynamic TLS, `LdrAddDllDirectory`,
  `RtlQueryPerformanceCounter`, WNF stubs.
- **kernelbase: adopt Wine.** It is pure PE on top of documented Nt*/Rtl* calls. Caveats:
  - Wine `CreateProcessInternalW` uses `NtCreateUserProcess`, which ReactOS x86 lacks, so keep ReactOS
    kernel32's CreateProcess path until the kernel has it.
  - Wine console uses `\Device\ConDrv`, but ReactOS console is the CSRSS ConSrv. Keep ReactOS console APIs.
- **kernel32: stay own,** progressively becoming a forwarder shell like Windows 7+.
- **user32/gdi32: stay own.** Wine's are thin wrappers over its Unix `win32u` (Wine-private `NtUserCall*`
  codes), so they are not drop-in over ReactOS win32k. Cherry-pick PE logic only; ReactOS already does this in
  `user32_vista`.
- **win32k: stay own;** it is the only viable implementation.

### 4.5 win32k structure (where to look)

- `win32ss/user/ntuser`: windows, messages, input, hooks, desktop/winsta, clipboard, DPI-less metrics
  (`sysparams.c`, `metric.c`), monitors (`monitor.c`) and display settings (`display.c`).
- `win32ss/gdi/ntgdi`:
  - GDI objects, DCs, regions, paths and bitmaps;
  - text via FreeType (`freetype.c`, `font.c`, `text.c`);
  - WGL to ICD bridge (`wingl.c`);
  - WDDM thunks (`d3dkmt.c`, needs a future dxgkrnl; see `sdk/include/reactos/rddm/rxgkinterface.h`).
- `win32ss/gdi/eng`: DDI engine for XDDM display drivers. `dib/`, `diblib/`: software blitters.
- `win32ss/reactx`: DirectDraw/D3D7 kernel pieces (`dxg`, `dxgthk`, `dxapi`).
- `win32ss/user/winsrv`: CSRSS servers (`usersrv`, `consrv`). `win32ss/user/user32`, `win32ss/gdi/gdi32`: client
  DLLs. `win32ss/win32u`: syscall stub DLL.
- Syscall tables: `win32ss/w32ksvc32.h` (742 entries, 2003 SP2 order) and `w32ksvc64.h`. Native NT syscalls:
  `ntoskrnl/sysfuncs.lst` + `ntoskrnl/include/sysfuncs.h` (x86: 296 NT5.2 + `GetCurrentProcessorNumberEx`,
  `GetNextProcess`, `GetNextThread`) and `sysfuncs64.h` (x64 table in Windows order, many unimplemented).

### 4.6 CRT layout

- `sdk/lib/crt`: static CRT pieces and `crtmath`.
- `dll/win32/msvcrt`: Wine-10.0 msvcrt. `msvcrt_shared`, compiled with `__UCRTSUPPORT__`, is reused by ucrtbase.
- `sdk/lib/ucrt` + `sdk/include/ucrt`: Microsoft UCRT sources (MIT subset, no libm).
- `sdk/lib/vcruntime`: vcruntime static pieces.
- `dll/win32/ucrtbase`: spec, `printf.c`, `stubs.c` (naive `fma`, `log2` and similar).
- Wine `dll/win32/msvcrt/math.c` already implements C99 math under `#if _MSVCR_VER>=120`
  (e.g. `fegetenv` at line 1439, `acosh` at line 2812). That is the fastest path to complete ucrtbase math.

### 4.7 Gotchas

- `kernelbase_ros.dll` is not `kernelbase.dll`. Anything importing `kernelbase.dll` directly fails, as do the
  pathcch unit tests (`modules/rostests/unittests/pathcch/CMakeLists.txt:27`).
- The release default 0x502 does not build dxgi/d3d11/d2d1/dwrite. Comparing with official ReactOS ISOs
  understates what the tree can do.
- `3rd Party Files.txt` is partly stale:
  - FreeType is 2.10.4 in headers;
  - libpng is 1.6.54 in headers;
  - mbedTLS is dual-licensed, not Apache-only.

  Read the headers, not the doc.
- `dll/directx/d3d9`, `d3d8` and `ddraw` (ReactOS's own) are not built (`dll/directx/CMakeLists.txt`). The
  live ones are under `dll/directx/wine/`. Tools that index specs by name must prefer the `wine/` copy.
- `GetSystemTimePreciseAsFileTime` is a forward to `GetSystemTimeAsFileTime` (`kernel32_vista.spec`), so it is
  not precise.
- `mmdevapi` silently has zero audio endpoints; `dsound` is forked from Wine 1.3.29 for that reason
  (WINESYNC note).
- `LoadLibraryExW` ignores `LOAD_LIBRARY_SEARCH_*` flags; it does not reject them
  (`dll/win32/kernel32/client/loader.c:300-352`).
- Manifest GUID handling deliberately picks the lowest OS (`ldrinit.c:1665-1672` comment). Windows picks the
  highest supported OS. Changing this affects `RosGetProcessEffectiveVersion` users in shell32.

### 4.8 Upstream versions (checked 2026-10-29)

Wine stable 11.0 (2026-01-13); Wine development 11.20 (tag dated 2026-10-16). ReactOS has 10.0, 10.1-dev and
11.x mixed. Mesa 26.2.6. mbedTLS 3.6.7 / 4.1.x LTS / 4.2.0. FreeType 2.15.0. zlib 1.3.2. libpng 1.6.59.
libxml2 2.15.4. DXVK 3.1.1. VKD3D-Proton 3.1. Wine vkd3d 2.1. SymCrypt 103.13.0. ICU 79.1. Vulkan SDK
1.4.363.0. CPython 3.13.17 (3.13.18 directory exists, no embed zip yet). Firefox 159.0, ESR 153.6.0 and
115.44.0esr.

### 4.9 Analyzer scripts (reuse for every new app)

Scripts are in `/tmp/claude-0/-home-user-okno/2af4bb7a-4411-572a-bbe7-dcffd3c4fc82/scratchpad/scripts/`. Copy
them into the repo under `tools/apigap/`.
- `specstat.py <spec...>`: totals, stubs and NT6-only counts per spec at 0x502/0xA00.
- `lookup.py <spec,spec> <Func...>`: presence, stub status and version range of functions.
- `impcheck2.py <ros_src> <app_dir> <0x600> <APISET_WIN7|APISET_WIN10|NONE> [files]`:
  - parses PE imports with `x86_64-w64-mingw32-objdump -p`;
  - resolves apisets the way ReactOS does;
  - follows app-local `api-ms-*` forwarders;
  - prints MISSING / STUB / UNRESOLVED / DLL NOT IN REACTOS.
- `dlltable.py <ros_src> <dir>`: per-module origin (from WINESYNC), stubs and FIXME/UNIMPLEMENTED counts
  (Appendix A).

---

## 5. Ordered task list

### 5.0 Export-level roadmap (DLL_EXPORT_VERSION)

The fork is at 0x600, raised so that clang 18 + mingw-w64 libstdc++ can use condition variables. Raising the
level only exposes exports that already have spec lines. Each step must first make the newly exposed lines
non-crashing, because a `@ stub` that becomes visible turns a load error into a runtime crash.

| Step | Level | Must be done before flipping | What it unlocks | Acceptance |
|---|---|---|---|---|
| A | **0x600 (now)** | Already flipped. Fix in place the crashing `@ stub` lines that real apps call: `CreateWaitableTimerExW/A`, `SetFileInformationByHandle`, `FlushProcessWriteBuffers`, `FreeLibraryWhenCallbackReturns` (+ other `*WhenCallbackReturns`), `GetNamedPipeServerProcessId`, `QueryProcessCycleTime`/`QueryThreadCycleTime`, `UnregisterApplicationRestart`, `GetApplicationRestartSettings`. Turn every `*Transacted*` and calendar `@ stub` into `-stub` or `ERROR_CALL_NOT_IMPLEMENTED`. Implement `CreateEventExW`, `CreateMutexExW`, `GetDynamicTimeZoneInformation`, `GetTimeZoneInformationForYear`, `SetThreadErrorMode`, ETW `Event*` in advapi32 | Vista exports (SRW, condvars, InitOnce, threadpool, locale-name APIs, `inet_pton`), dxgi/d3d11/d2d1/dwrite/ncrypt builds | `impcheck2.py` on Python 3.13 / FF115 / FF159 shows no `@ stub` hits; winetests kernel32/advapi32 no new failures; boot test in QEMU |
| B | **0x601 (Win7), recommended next** | Implement the 4 `-stub` 0x601 lines: `GetLogicalProcessorInformationEx`, `GetNumaNodeProcessorMaskEx`, `GetProcessGroupAffinity`, `K32EnumProcessModulesEx`/`K32GetWsChangesEx`. Add the Win7 functions with no spec line yet: `AddDllDirectory`, `RemoveDllDirectory`, `SetDefaultDllDirectories` (KB2533623, Win7-era), `QueryUnbiasedInterruptTime`, `PowerCreateRequest/SetRequest/ClearRequest`, `CreateRemoteThreadEx`, `SetWaitableTimerEx`, `RtlQueryPerformanceCounter/Frequency`, `Wer*RuntimeExceptionModule`, `ktmw32.dll` (failing stubs), x64 XState APIs (`InitializeContext`, `CopyContext`, `GetEnabledXStateFeatures`, `LocateXStateFeature`). `NtQuerySystemInformationEx` needs the kernel (K) | `K32*` psapi-in-kernel32, `TryAcquireSRWLock*`, group affinity, Win7 touch/gesture user32 set, Win7 shell32 AppUserModelID | Firefox 115 ESR `impcheck2.py` = 0 MISSING; FF115 starts and renders about:blank in QEMU |
| C | **0x602/0x603 (Win8/8.1)** | Real `kernelbase.dll` (Wine 11) with apiset hosts fixed. Then: `CreateFile2`, `CopyFile2`, `GetOverlappedResultEx`, `WaitOnAddress`/`WakeByAddress*` (export the existing `RtlWaitOnAddress`), `Pss*` snapshot API, `GetSystemTimePreciseAsFileTime` (real), `SetThreadInformation`, `Get/SetProcessMitigationPolicy` (accept-and-ignore, later K), `PrefetchVirtualMemory`/`OfferVirtualMemory`/`DiscardVirtualMemory` (K: `NtSetInformationVirtualMemory`), AppModel package APIs returning `APPMODEL_ERROR_NO_PACKAGE`, `RaiseFailFastException` (real), `LogicalToPhysicalPointForPerMonitorDPI`. Also combase/WinRT string+activation through apisets, and `bcp47langs`/`dcomp`/`rtworkq` stubs (built at 0x603) must not crash | Win8 kernelbase set, `GetCurrentPackageId`, firmware APIs, pointer input | Python 3.13 `impcheck2.py` = 0 MISSING and `python -c "import ssl, sqlite3, asyncio, ctypes; print('ok')"` passes in QEMU |
| D | **0xA00 (Win10)** | Per-thread DPI v2 user32 set (8 functions in gap 19) and `IsValidDpiAwarenessContext` (`-stub` today). `GetSystemCpuSetInformation`, `IsWow64Process2`, `GetCurrentThreadStackLimits`, `VirtualAlloc2`/`MapViewOfFile3` (K: `NtAllocateVirtualMemoryEx`, `NtMapViewOfSectionEx`), WNF/device-family stubs, apiset V6 rewrite, complete ucrtbase math, `GetIfEntry2Ex` (`-stub` today). Also d3d12/dxcore built (needs Vulkan story) | `SetThreadDescription`, `GetDpiForWindow`, `RtlFlsGetValue2`, Win10 FLS, d3d12 | Firefox 159 and Telegram Desktop pass `impcheck2.py` with 0 MISSING; FF159 loads a TLS 1.3 site in QEMU |

Separate decision: the version the system reports (`PEB->OSMajorVersion`, today 5.2) should move to 10.0 only
after step D. Until then, use the existing manifest/shim mechanism (Windows itself reports 6.2 to unmanifested
apps). Installers such as Python's and Firefox's check the reported version, not the exports.

### 5.1 Stage 1: modern apps (user mode), in order

1. **Make API-gap analysis a CI gate.**
   - Commit `tools/apigap/` (scripts from 4.9) and a pinned app corpus manifest: Python 3.13 embed x86/x64,
     Firefox ESR + release, Telegram Desktop, 7-Zip, LibreOffice, 1C thin client, CryptoPro CSP.
   - Acceptance: CI job prints per-app MISSING/STUB/UNRESOLVED counts and fails on regressions.
2. **Apisets always on + V6 lookup.**
   - Port Wine `apisetschema.spec` (LGPL) into a generated table.
   - Lookup up to the last hyphen.
   - Ignore manifest GUIDs for enabling.
   - Host map: kernelbase stays kernel32 until task 4, then real kernelbase; combase → `combase`; shcore →
     `shcore`; crt → `ucrtbase`.
   - Acceptance: `impcheck2.py` in default mode shows 0 UNRESOLVED for Python and FF159; apiset rostest
     (`modules/rostests/apitests/apisets`) passes.
3. **Stop crashing stubs (step A of 5.0).** Acceptance: grep shows no `@ stub` among functions imported by the
   corpus.
4. **Real `kernelbase.dll` from Wine 11.x.**
   - New module next to `kernelbase_ros`.
   - kernel32 forwards for everything Wine implements purely; keep ReactOS CreateProcess/console/CSR paths.
   - Acceptance: winetests `kernelbase`, `kernel32` (path, locale, file, sync) have no new failures;
     `pathcch_dyn1_unittest` enabled.
5. **Flip to 0x601 (step B).** Acceptance: as in 5.0.
6. **Loader:**
   - dynamic TLS for late-loaded DLLs;
   - `LdrAddDllDirectory` / `LdrSetDefaultDllDirectories` + `LOAD_LIBRARY_SEARCH_*` handling;
   - `RtlQueryPerformanceCounter`.

   Acceptance: new rostests; Python loads `.pyd` with `os.add_dll_directory`; a test DLL with
   `__declspec(thread)` loaded via `LoadLibrary` works.
7. **ucrtbase completion.**
   - Build Wine `msvcrt/math.c` with `_MSVCR_VER=140` into ucrtbase.
   - Implement `fe*`, `__control87_2`, `_except1` and complex functions.

   Acceptance: winetests `ucrtbase` math/misc pass; ucrtbase stubs fall from 191 to fewer than 20 (only
   arch-specific EH helpers).
8. **Kernel-dependent I/O** (coordinate with the core audit):
   - `NtCancelIoFileEx`, `NtCancelSynchronousIoFile`, `NtRemoveIoCompletionEx`;
   - wait-completion packets;
   - `NtAlertThreadByThreadId`.

   Then kernelbase `CancelIoEx`, `GetQueuedCompletionStatusEx` and threadpool resync to Wine 11.
   Acceptance: Python `asyncio` test subset and winetests `kernel32:sync`/`file` pass.
9. **Process creation with attributes** (needs `NtCreateUserProcess`, K): `ProcThreadAttributeList`
   (handle list, parent, mitigation policy as no-op). Acceptance: Python `subprocess` tests; Firefox content
   processes start.
10. **advapi32/sechost:** ETW `Event*`, `RegCreateKeyTransactedW` (fail cleanly), `AddMandatoryAce`, `sechost`
    from Wine. Acceptance: FF115 `impcheck2.py` clean for advapi32.
11. **TLS:** mbedTLS 3.6 LTS backend (TLS 1.3), schannel/secur32 frontend from Wine 11; winhttp/wininet sync.
    Acceptance: `Invoke-WebRequest`-equivalent test (winhttp) to a TLS 1.3-only host; winetests `secur32`
    schannel part passes.
12. **CNG/KSP for CryptoPro:**
    - ncrypt KSP registration;
    - bcrypt sync to latest Wine;
    - crypt32/cryptnet/wintrust to Wine 11.

    Acceptance: CryptoPro CSP installer completes; `csptest -keyset -enum` lists containers.
13. **Networking user mode:** iphlpapi NT6 table APIs on tcpip IOCTLs; `WSASendMsg`;
    `if_nametoindex`/`if_indextoname`. Acceptance: Python `socket` test subset; `ipconfig` unchanged.
14. **COM/WinRT:**
    - winesync `com.cfg` to Wine 11;
    - add `wintypes`, `windows.globalization`, `windows.storage` and `windows.ui` (viewmanagement) from Wine;
    - `RoGetActivationFactory` reachable via apisets.

    Acceptance: winetests `combase`, `wintypes` pass at Wine's rate; FF159 starts.
15. **user32 DPI v2 + pointer** (step D prerequisites). Acceptance: winetests `user32:dpi`-style tests; Qt 6 app
    (Telegram) creates windows.
16. **Text stack:** FreeType 2.15 (win32k + dwrite), Wine 11 dwrite/d2d1/usp10/windowscodecs sync, ICU from Wine
    `dlls/icu*`, kernelbase NLS (normalization, IDN, `ResolveLocaleName`). Acceptance: winetests `dwrite`,
    `d2d1`, `kernel32:locale`; Chromium/Electron app renders text.
17. **Audio:** WASAPI backend over KS (`wdmaud`/portcls), audiosrv endpoint registry, dsound re-sync, XAudio2
    from Wine + FAudio. Acceptance: winetests `mmdevapi:render` passes on AC97/HDA in QEMU; Firefox plays audio.
18. **Media:** Wine 11 mf/mfplat/mfreadwrite PE parts + PE FFmpeg-based decoders (LGPL build, no GPL-only
    codecs). Acceptance: winetests `mfplat`; H.264 playback in a test app.
19. **Library refresh:** zlib 1.3.2, libpng 1.6.59, libxml2 2.15.x, SymCrypt 103.13. Fix `3rd Party Files.txt`.
    Acceptance: build + winetests `msxml3`, `windowscodecs`.
20. **Flip to 0x602/0x603, then 0xA00** per 5.0 steps C and D, each gated by the corpus `impcheck2.py` +
    QEMU smoke tests.

### 5.2 User-mode parts of stage 2 (x64 by default + WoW64 + SMP)

1. **x64 corpus parity.** Run `impcheck2.py` on x64 builds of the corpus (x64 specs differ via `-arch`).
   Acceptance: same 0-MISSING targets as x86.
2. **XState/AVX context APIs** (`InitializeContext`, `CopyContext`, `LocateXStateFeature`) and
   `RtlAddGrowableFunctionTable`/`RtlDeleteGrowableFunctionTable` (both MISSING; JITs need them: V8,
   SpiderMonkey, .NET). Acceptance: Firefox x64 JIT runs; .NET 8 hello world runs.
3. **WoW64 user mode.**
   - `wow64.dll`, `wow64win.dll`, `wow64cpu.dll` equivalents. Wine 11's new WoW64 thunks live in Unix-side
     ntdll, so only the design is reusable.
   - Write a native NT design: 32-bit ntdll + x64 thunk layer.
   - `IsWow64Process2`, `Wow64GetThreadContext`/`Wow64SetThreadContext` (`@ stub` today).

   Acceptance: 32-bit Python and 7-Zip run on x64.
4. **SMP-safe user mode.** Group affinity APIs real (`GetLogicalProcessorInformationEx`,
   `GetSystemCpuSetInformation`). Acceptance: Python `os.cpu_count()` and Chromium thread pools correct on
   8-vCPU QEMU.

### 5.3 User-mode parts of stage 5 (WDDM GPUs)

1. **Vulkan loader decision:** Khronos loader (Apache-2.0, separate unmodified binary) or own minimal LGPL loader.
   Add Mesa 26.x lavapipe as fallback ICD. Acceptance: `vulkaninfo` lists lavapipe.
2. **wined3d Vulkan renderer by default when a Vulkan ICD exists;** optional DXVK 3.1.x for D3D9-11. Acceptance:
   D3D11 sample renders via lavapipe; feature level ≥ 11_0 reported.
3. **d3d12/dxcore at 0xA00** via Wine vkd3d 2.x (or VKD3D-Proton 3.1). Acceptance: D3D12 sample.
4. **gdi32 `D3DKMT*` and win32k `d3dkmt.c`** wired to the new dxgkrnl (kernel task). Acceptance: `D3DKMTOpenAdapterFromHdc`
   + `D3DKMTQueryAdapterInfo` return vendor data on real hardware.
5. **DWM.** dwmapi/dcomp real implementations once a compositor exists. Before that, report composition off
   consistently. Acceptance: `DwmIsCompositionEnabled` matches the actual behaviour; Chromium falls back
   without errors.

---

## 6. Sources

Code: the ReactOS tree at the commit above, with paths as cited. Wine tree: `wine-11.20` tag (fetched with a
blobless clone; structure via `git ls-tree`), `dlls/ntdll/loader.c` (master, `get_apiset_entry`). Test
binaries:
- `https://www.python.org/ftp/python/3.13.17/python-3.13.17-embed-win32.zip`
- `https://archive.mozilla.org/pub/firefox/releases/115.44.0esr/win32/en-US/`
- `https://archive.mozilla.org/pub/firefox/releases/159.0/win32/en-US/`

Upstream versions: `git ls-remote --tags` on gitlab.winehq.org/wine/wine, gitlab.winehq.org/wine/vkd3d,
github.com/Mbed-TLS/mbedtls, gitlab.freedesktop.org/freetype/freetype, gitlab.freedesktop.org/mesa/mesa,
github.com/doitsujin/dxvk, github.com/HansKristian-Work/vkd3d-proton, github.com/madler/zlib,
github.com/pnggroup/libpng, github.com/unicode-org/icu, github.com/microsoft/SymCrypt,
github.com/pal1000/mesa-dist-win, gitlab.gnome.org/GNOME/libxml2 and github.com/KhronosGroup/Vulkan-Loader. Also
`https://product-details.mozilla.org/1.0/firefox_versions.json`.

Web:
- [Wine 11.0 released (Phoronix)](https://phoronix.com/news/wine-11.0-released)
- [Wine 11.0 ANNOUNCE](https://raw.githubusercontent.com/wine-mirror/wine/wine-11.0/ANNOUNCE.md)
- [Mbed TLS BRANCHES.md (LTS 3.6 until 2027-03, 4.1 until 2029-03)](https://raw.githubusercontent.com/Mbed-TLS/mbedtls/development/BRANCHES.md)
- [Mbed TLS 3.6.0 LTS (TLS 1.3 on by default)](https://trustedfirmware.org/blog/mbed-tls-3-6-0-lts)
- [Mbed TLS license (dual Apache-2.0 OR GPL-2.0-or-later)](https://raw.githubusercontent.com/Mbed-TLS/mbedtls/v4.2.0/LICENSE)
- [Mesa 26.0.8 end of series / 26.1 stable (Phoronix)](https://www.phoronix.com/news/Mesa-26.0.8-Released)
- [Mesa 26.0.0 release notes](https://docs.mesa3d.org/relnotes/26.0.0.html)
- [UCRT source subset under MIT (NuGet WindowsSDK profile)](https://www.nuget.org/profiles/WindowsSDK)
- [Quarkslab: ApiSetSchema internals](https://blog.quarkslab.com/runtime-dll-name-resolution-apisetschema-part-ii.html)
- [Khronos Vulkan-Loader license (Apache-2.0)](https://raw.githubusercontent.com/KhronosGroup/Vulkan-Loader/main/LICENSE.txt)
- [DXVK license (zlib)](https://raw.githubusercontent.com/doitsujin/dxvk/master/LICENSE)
- [VKD3D-Proton license (LGPL-2.1)](https://raw.githubusercontent.com/HansKristian-Work/vkd3d-proton/master/LICENSE)

---

## Appendix A. Per-module classification (generated by `dlltable.py`)

Columns: module | origin (from `media/doc/WINESYNC.txt`; "own-tree, Wine-derived (untracked)" means at least
half of the sources include `wine/debug.h` but the module has no WINESYNC line; "ReactOS own" otherwise) | spec
exports/stubs at 0x502 | at 0xA00 | source files | FIXME | UNIMPLEMENTED.

### A.1 `dll/win32` (279 modules)

| Module | Origin | 0x502 exp/stub | 0xA00 exp/stub | Src files | FIXME | UNIMPL |
|---|---|---|---|---|---|---|
| acledit | ReactOS own | 8/0 | 8/0 | 2 | 0 | 9 |
| aclui | ReactOS own | 3/0 | 3/0 | 5 | 4 | 0 |
| activeds | Wine-10.0 | 30/0 | 31/0 | 3 | 26 | 0 |
| activeds.tlb | Wine-10.0 | 0/0 | 0/0 | 0 | 0 | 0 |
| actxprxy | Wine-10.0 | 5/0 | 5/0 | 1 | 0 | 0 |
| advapi32 | ReactOS own | 686/120 | 699/128 | 29 | 95 | 11 |
| advapi32_vista | ReactOS own | 6/0 | 6/0 | 1 | 0 | 0 |
| advpack | Wine-10.0 | 83/1 | 84/2 | 4 | 19 | 0 |
| atl | Wine-10.0 | 52/3 | 52/3 | 4 | 68 | 0 |
| atl100 | Wine-10.0 | 52/7 | 52/7 | 0 | 0 | 0 |
| atl80 | Wine-10.0 | 53/8 | 53/8 | 1 | 0 | 0 |
| authz | ReactOS own | 41/19 | 41/19 | 3 | 3 | 17 |
| avicap32 | own-tree, Wine-derived (untracked) | 6/0 | 6/0 | 1 | 2 | 2 |
| avifil32 | Wine-10.0 | 79/0 | 79/0 | 11 | 29 | 0 |
| avrt | Wine-10.0 | 14/7 | 14/7 | 1 | 5 | 0 |
| batt | ReactOS own | 2/0 | 2/0 | 1 | 0 | 0 |
| bcp47langs | Wine-10.0 | 71/71 | 71/71 | 0 | 0 | 0 |
| bcrypt | Wine-11.19 | 62/23 | 62/23 | 1 | 92 | 0 |
| bcryptprimitives | Wine-10.0 | 1/0 | 1/0 | 1 | 0 | 0 |
| beepmidi | ReactOS own | 2/0 | 2/0 | 1 | 0 | 0 |
| bluetoothapis | Wine-10.0 | 96/82 | 96/82 | 2 | 6 | 0 |
| browseui | ReactOS own | 31/0 | 31/0 | 34 | 48 | 46 |
| bthci | ReactOS own | 1/0 | 1/0 | 1 | 0 | 0 |
| cabinet | Wine-10.0 | 14/0 | 14/0 | 4 | 7 | 1 |
| cards | ReactOS own | 6/0 | 6/0 | 1 | 0 | 0 |
| cfgmgr32 | ReactOS own | 200/25 | 200/25 | 0 | 0 | 0 |
| clusapi | Wine-10.0 | 115/108 | 115/108 | 1 | 7 | 0 |
| combase | Wine-10.0 | 345/164 | 345/164 | 11 | 115 | 0 |
| comcat | Wine-10.0 | 4/0 | 4/0 | 0 | 0 | 0 |
| comctl32 | own-tree, Wine-derived (untracked) | 180/0 | 182/0 | 39 | 188 | 4 |
| comdlg32 | Wine-10.0 | 28/4 | 28/4 | 10 | 112 | 0 |
| coml2 | Wine-10.0 | 23/11 | 23/11 | 3 | 2 | 0 |
| compstui | Wine-10.0 | 4/0 | 4/0 | 1 | 9 | 0 |
| credui | Wine-10.0 | 21/6 | 21/6 | 1 | 13 | 0 |
| crtdll | ReactOS own | 520/9 | 520/9 | 1 | 0 | 0 |
| crypt32 | Wine-10.0 | 245/35 | 247/35 | 28 | 167 | 4 |
| cryptdlg | Wine-10.0 | 21/10 | 21/10 | 1 | 4 | 0 |
| cryptdll | Wine-10.0 | 14/11 | 14/11 | 0 | 0 | 0 |
| cryptnet | Wine-10.0 | 18/12 | 18/12 | 1 | 15 | 0 |
| cryptui | Wine-10.0 | 48/33 | 48/33 | 1 | 18 | 0 |
| dbgeng | Wine-10.0 | 5/1 | 5/1 | 1 | 432 | 0 |
| dbghelp | WineStaging-5.16 | 192/3 | 192/3 | 25 | 414 | 68 |
| dciman32 | Wine-10.1-dev (b00c7619f1b) | 21/17 | 21/17 | 1 | 1 | 0 |
| dcomp | Wine-10.0 | 16/12 | 16/12 | 1 | 3 | 0 |
| devmgr | ReactOS own | 24/0 | 24/0 | 15 | 44 | 4 |
| dnsapi | ReactOS own | 191/58 | 191/58 | 8 | 5 | 105 |
| dwmapi | Wine-8.14 | 60/36 | 60/36 | 1 | 23 | 0 |
| esent | ReactOS own | 156/156 | 156/156 | 0 | 0 | 0 |
| faultrep | Wine-10.0 | 14/11 | 14/11 | 1 | 1 | 0 |
| feclient | Wine-10.0 | 50/50 | 50/50 | 0 | 0 | 0 |
| fltlib | ReactOS own | 28/0 | 28/0 | 3 | 0 | 0 |
| fmifs | ReactOS own | 16/6 | 16/6 | 8 | 6 | 1 |
| fontsub | Wine-10.0 | 2/1 | 2/1 | 1 | 1 | 0 |
| framedyn | ReactOS own | 80/0 | 80/0 | 3 | 0 | 2 |
| fusion | Wine-10.0 | 17/8 | 17/8 | 5 | 33 | 0 |
| gdiplus | Wine-10.0 | 630/13 | 630/13 | 15 | 163 | 0 |
| getuname | ReactOS own | 1/0 | 1/0 | 1 | 0 | 0 |
| hhctrl.ocx | Wine-10.0 | 6/0 | 6/0 | 9 | 30 | 0 |
| hid | ReactOS own | 44/0 | 44/0 | 1 | 1 | 0 |
| hlink | Wine-10.0 | 32/12 | 32/12 | 4 | 33 | 0 |
| hnetcfg | Wine-10.0 | 4/0 | 4/0 | 7 | 158 | 0 |
| httpapi | ReactOS own | 45/45 | 45/45 | 0 | 0 | 0 |
| iccvid | Wine-10.0 | 1/0 | 1/0 | 1 | 4 | 0 |
| icmp | ReactOS own | 8/3 | 8/3 | 0 | 0 | 0 |
| ieframe | Wine-10.0 | 9/0 | 9/0 | 19 | 425 | 0 |
| ieproxy | Wine-10.0 | 5/0 | 5/0 | 0 | 0 | 0 |
| iernonce | ReactOS own | 2/0 | 2/0 | 3 | 1 | 0 |
| ifmon | ReactOS own | 1/0 | 1/0 | 5 | 0 | 0 |
| imaadp32.acm | Wine-10.0 | 1/0 | 1/0 | 1 | 6 | 0 |
| imagehlp | Wine-10.0 | 109/10 | 109/10 | 4 | 23 | 0 |
| inetcomm | Wine-10.0 | 106/87 | 106/87 | 9 | 252 | 0 |
| inetmib1 | WineStaging-4.18 | 4/2 | 4/2 | 1 | 10 | 0 |
| initpki | Wine-10.0 | 4/2 | 4/2 | 0 | 0 | 0 |
| inseng | WineStaging-4.18 | 12/4 | 12/4 | 4 | 60 | 0 |
| iologmsg | ReactOS own | 0/0 | 0/0 | 0 | 0 | 0 |
| iphlpapi | Out of sync | 157/59 | 183/85 | 14 | 68 | 20 |
| iprtprio | ReactOS own | 0/0 | 0/0 | 1 | 0 | 3 |
| itircl | Wine-10.0 | 4/1 | 4/1 | 0 | 0 | 0 |
| itss | Wine-10.0 | 6/1 | 6/1 | 7 | 58 | 0 |
| jscript | Wine-10.0 | 4/0 | 4/0 | 28 | 180 | 0 |
| jsproxy | Wine-10.0 | 6/3 | 6/3 | 1 | 1 | 0 |
| kernel32 | ReactOS own | 980/0 | 1266/165 | 112 | 117 | 38 |
| kernelbase | own-tree, Wine-derived (untracked) | 200/0 | 200/0 | 17 | 222 | 0 |
| l3codeca.acm | Wine-10.0 | 1/0 | 1/0 | 1 | 4 | 0 |
| loadperf | Wine-10.0 | 14/0 | 14/0 | 2 | 3 | 8 |
| lpk | ReactOS own | 10/0 | 10/0 | 4 | 3 | 21 |
| lsasrv | ReactOS own | 147/88 | 147/88 | 16 | 31 | 33 |
| lz32 | Wine-10.0 | 12/0 | 12/0 | 0 | 0 | 0 |
| mapi32 | Wine-10.0 | 191/78 | 191/78 | 7 | 28 | 9 |
| mciavi32 | Wine-11.11 | 1/0 | 1/0 | 4 | 42 | 0 |
| mcicda | Wine-10.0 | 1/0 | 1/0 | 1 | 7 | 0 |
| mciqtz32 | Wine-10.0 | 1/0 | 1/0 | 1 | 35 | 0 |
| mciseq | Wine-10.0 | 1/0 | 1/0 | 1 | 29 | 0 |
| mciwave | Wine-10.0 | 1/0 | 1/0 | 1 | 20 | 0 |
| mgmtapi | Wine-10.0 | 9/7 | 9/7 | 1 | 2 | 0 |
| mlang | Wine-10.0 | 14/1 | 14/1 | 1 | 26 | 0 |
| mmdevapi | WineStaging-4.18 | 18/14 | 18/14 | 4 | 18 | 0 |
| mmdrv | ReactOS own | 2/0 | 2/0 | 10 | 1 | 0 |
| modemui | ReactOS own | 14/12 | 14/12 | 1 | 0 | 0 |
| mpr | WineStaging-4.18 | 131/52 | 131/52 | 6 | 57 | 0 |
| mprapi | Wine-10.0 | 132/129 | 132/129 | 1 | 3 | 0 |
| msacm32 | WineStaging-4.18 | 44/1 | 44/1 | 7 | 34 | 0 |
| msacm32.drv | Wine-10.0 | 3/0 | 3/0 | 1 | 21 | 0 |
| msadp32.acm | Wine-10.0 | 1/0 | 1/0 | 1 | 7 | 0 |
| msafd | ReactOS own | 15/0 | 15/0 | 5 | 17 | 6 |
| mscat32 | Wine-10.0 | 36/0 | 36/0 | 0 | 0 | 0 |
| mscms | WineStaging-4.18 | 103/44 | 103/44 | 6 | 44 | 0 |
| mscoree | Wine-10.0 | 118/70 | 118/70 | 9 | 110 | 0 |
| msftedit | Wine-10.0 | 14/4 | 14/4 | 1 | 1 | 0 |
| msg711.acm | Wine-10.0 | 1/0 | 1/0 | 1 | 2 | 0 |
| msgina | ReactOS own | 50/26 | 50/26 | 8 | 9 | 7 |
| msgsm32.acm | WineStaging-4.0 | 1/0 | 1/0 | 1 | 6 | 0 |
| mshtml | WineStaging-1.7.55 | 15/5 | 15/5 | 73 | 1776 | 0 |
| mshtml.tlb | WineStaging-1.7.55 | 0/0 | 0/0 | 0 | 0 | 0 |
| msi | Wine-10.0 | 296/29 | 296/29 | 39 | 177 | 1 |
| msimg32 | Wine-10.0 | 5/0 | 5/0 | 1 | 1 | 0 |
| msimtf | Wine-10.0 | 6/2 | 6/2 | 2 | 17 | 0 |
| msisip | Wine-10.0 | 8/4 | 8/4 | 1 | 0 | 0 |
| msisys.ocx | Wine-10.0 | 4/0 | 4/0 | 1 | 1 | 0 |
| msnet32 | Wine-10.0 | 96/95 | 96/95 | 1 | 1 | 0 |
| mspatcha | Forked at WineStaging-3.3 | 12/3 | 12/3 | 2 | 4 | 0 |
| msports | ReactOS own | 12/1 | 12/1 | 5 | 6 | 0 |
| msrle32 | Wine-10.0 | 1/0 | 1/0 | 1 | 15 | 0 |
| mssign32 | Wine-10.0 | 30/22 | 30/22 | 1 | 5 | 0 |
| mssip32 | Wine-10.0 | 9/7 | 9/7 | 0 | 0 | 0 |
| mstask | WineStaging-3.3 | 15/0 | 15/0 | 6 | 48 | 11 |
| msv1_0 | own-tree, Wine-derived (untracked) | 16/6 | 16/6 | 7 | 13 | 0 |
| msvcrt | Wine-10.0 | 860/13 | 1312/24 | 44 | 134 | 0 |
| msvcrt20 | Out of sync | 1126/441 | 1126/441 | 1 | 0 | 0 |
| msvcrt40 | Out of sync | 1162/449 | 1162/449 | 1 | 0 | 0 |
| msvfw32 | Wine-10.0 | 67/41 | 67/41 | 3 | 40 | 0 |
| msvidc32 | Wine-10.0 | 1/0 | 1/0 | 1 | 9 | 0 |
| mswsock | ReactOS own | 32/0 | 32/0 | 4 | 0 | 0 |
| msxml | Wine-10.0 | 4/0 | 4/0 | 1 | 0 | 0 |
| msxml2 | Wine-10.0 | 4/0 | 4/0 | 1 | 0 | 0 |
| msxml3 | Wine-10.0 | 11/7 | 11/7 | 33 | 403 | 0 |
| msxml3r | ReactOS own | 0/0 | 0/0 | 0 | 0 | 0 |
| msxml4 | Wine-10.0 | 4/0 | 4/0 | 1 | 0 | 0 |
| msxml6 | Wine-10.0 | 4/0 | 4/0 | 1 | 0 | 0 |
| mycomput | ReactOS own | 0/0 | 0/0 | 0 | 0 | 0 |
| ncrypt | Wine-11.19 | 138/80 | 138/80 | 1 | 25 | 0 |
| nddeapi | Wine-10.0 | 28/2 | 28/2 | 1 | 1 | 0 |
| netapi32 | Forked at Wine-1.3.34 | 340/142 | 340/142 | 21 | 47 | 23 |
| netcfgx | ReactOS own | 16/9 | 16/9 | 11 | 9 | 0 |
| netevent | ReactOS own | 0/0 | 0/0 | 0 | 0 | 0 |
| netid | ReactOS own | 1/0 | 1/0 | 1 | 1 | 0 |
| netmsg | ReactOS own | 0/0 | 0/0 | 0 | 0 | 0 |
| netutils | Wine-10.0 | 22/17 | 22/17 | 1 | 0 | 0 |
| newdev | ReactOS own | 12/3 | 12/3 | 3 | 2 | 3 |
| npptools | Wine-10.0 | 60/60 | 60/60 | 0 | 0 | 0 |
| ntdsapi | Wine-10.0 | 96/86 | 96/86 | 1 | 8 | 0 |
| ntlanman | own-tree, Wine-derived (untracked) | 43/26 | 43/26 | 1 | 0 | 16 |
| ntmarta | ReactOS own | 9/0 | 9/0 | 1 | 19 | 5 |
| objsel | Wine-10.0 | 4/0 | 4/0 | 1 | 4 | 0 |
| odbc32 | WineStaging-4.18. Depends on port of Linux ODBC. | 174/57 | 174/57 | 1 | 3 | 0 |
| odbccp32 | Wine-10.0 | 57/5 | 57/5 | 1 | 19 | 0 |
| ole32 | Wine-10.0 | 344/72 | 344/72 | 29 | 164 | 0 |
| oleacc | Wine-10.0 | 22/2 | 22/2 | 5 | 68 | 0 |
| oleaut32 | Wine-10.0 | 418/27 | 418/27 | 15 | 248 | 0 |
| olecli32 | Wine-10.0 | 56/41 | 56/41 | 1 | 10 | 0 |
| oledlg | Wine-10.0 | 23/0 | 23/0 | 3 | 22 | 0 |
| olepro32 | Wine-10.0 | 11/0 | 11/0 | 1 | 1 | 0 |
| olesvr32 | Wine-10.0 | 12/3 | 12/3 | 1 | 9 | 0 |
| olethk32 | Wine-10.0 | 14/14 | 14/14 | 0 | 0 | 0 |
| pdh | Wine-10.0 | 163/119 | 163/119 | 1 | 21 | 0 |
| pidgen | Wine-10.0 | 7/5 | 7/5 | 1 | 2 | 0 |
| powrprof | Forked at Wine-1.0rc5 | 37/0 | 37/0 | 1 | 19 | 0 |
| profmap | ReactOS own | 6/3 | 6/3 | 1 | 0 | 2 |
| propsys | Wine-10.0 | 208/164 | 208/164 | 3 | 33 | 0 |
| psapi | ReactOS own | 25/0 | 25/0 | 2 | 0 | 3 |
| pstorec | Wine-10.0 | 7/2 | 7/2 | 1 | 20 | 0 |
| qmgr | Wine-10.0 | 3/0 | 3/0 | 7 | 46 | 0 |
| qmgrprxy | Wine-10.0 | 5/0 | 5/0 | 0 | 0 | 0 |
| query | Wine-10.0 | 46/38 | 46/38 | 1 | 5 | 0 |
| rasadhlp | ReactOS own | 6/1 | 6/1 | 3 | 0 | 0 |
| rasapi32 | Wine-10.0 | 128/68 | 128/68 | 1 | 65 | 0 |
| rasdlg | own-tree, Wine-derived (untracked) | 36/28 | 36/28 | 1 | 8 | 0 |
| rasman | own-tree, Wine-derived (untracked) | 164/159 | 164/159 | 1 | 6 | 0 |
| regapi | Wine-10.0 | 69/69 | 69/69 | 0 | 0 | 0 |
| resutils | Wine-10.0 | 71/71 | 71/71 | 0 | 0 | 0 |
| riched20 | Wine-10.0 | 9/0 | 9/0 | 19 | 284 | 0 |
| riched32 | Wine-10.0 | 1/0 | 1/0 | 1 | 0 | 0 |
| rpcrt4 | Wine-10.0 | 542/227 | 543/227 | 22 | 243 | 0 |
| rsabase | Wine-10.0 | 27/0 | 27/0 | 0 | 0 | 0 |
| rsaenh | Wine-11.19 | 27/0 | 27/0 | 3 | 23 | 0 |
| rtworkq | Wine-10.0 | 37/3 | 37/3 | 1 | 18 | 0 |
| samlib | own-tree, Wine-derived (untracked) | 65/12 | 65/12 | 2 | 1 | 3 |
| samsrv | ReactOS own | 158/92 | 158/92 | 12 | 33 | 12 |
| sccbase | Wine-10.0 | 26/24 | 26/24 | 0 | 0 | 0 |
| schannel | WineStaging-3.3 | 37/9 | 37/9 | 7 | 18 | 0 |
| scrrun | Wine-10.0 | 6/1 | 6/1 | 4 | 59 | 0 |
| secur32 | Forked | 76/18 | 76/18 | 13 | 43 | 5 |
| security | Forked (different .spec) | 36/0 | 36/0 | 0 | 0 | 0 |
| sensapi | Wine-10.0 | 3/0 | 3/0 | 1 | 2 | 0 |
| serialui | ReactOS own | 6/0 | 6/0 | 1 | 1 | 4 |
| setupapi | Forked at Wine-20050524 | 605/93 | 678/167 | 17 | 160 | 1 |
| sfc | ReactOS own | 17/7 | 17/7 | 1 | 0 | 0 |
| sfc_os | ReactOS own | 12/6 | 12/6 | 1 | 0 | 4 |
| sfcfiles | ReactOS own | 1/0 | 1/0 | 1 | 0 | 0 |
| shcore | own-tree, Wine-derived (untracked) | 185/115 | 185/115 | 1 | 24 | 0 |
| shdoclc | Wine-10.0 | 0/0 | 0/0 | 0 | 0 | 0 |
| shdocvw | WineStaging-4.18 | 128/92 | 128/92 | 9 | 23 | 15 |
| shell32 | Forked at Wine-20071011 | 466/17 | 629/154 | 103 | 481 | 137 |
| shfolder | Wine-10.0 | 2/0 | 2/0 | 0 | 0 | 0 |
| shimgvw | ReactOS own | 14/3 | 14/3 | 5 | 2 | 0 |
| shlwapi | WineStaging-3.3 | 858/58 | 862/58 | 23 | 91 | 0 |
| slbcsp | Wine-10.0 | 27/25 | 27/25 | 0 | 0 | 0 |
| sndblst | ReactOS own | 7/0 | 7/0 | 1 | 0 | 0 |
| snmpapi | Wine-10.0 | 45/21 | 45/21 | 1 | 1 | 0 |
| softpub | Wine-10.0 | 24/0 | 24/0 | 0 | 0 | 0 |
| srclient | ReactOS own | 10/7 | 10/7 | 1 | 0 | 0 |
| sspicli | Wine-10.0 | 104/47 | 104/47 | 1 | 3 | 0 |
| stdole2.tlb | WineStaging-3.3 | 0/0 | 0/0 | 0 | 0 | 0 |
| stdole32.tlb | WineStaging-3.3 | 0/0 | 0/0 | 0 | 0 | 0 |
| sti | Wine-10.0 | 7/0 | 7/0 | 3 | 18 | 0 |
| storprop | ReactOS own | 11/0 | 11/0 | 4 | 0 | 0 |
| streamci | ReactOS own | 1/0 | 1/0 | 1 | 1 | 0 |
| sxs | Wine-10.0 | 3/0 | 3/0 | 4 | 14 | 0 |
| syssetup | ReactOS own | 86/58 | 86/58 | 9 | 4 | 1 |
| t2embed | Wine-10.0 | 25/0 | 25/0 | 2 | 3 | 8 |
| tapi32 | Wine-10.0 | 278/97 | 278/97 | 3 | 135 | 0 |
| tapiui | ReactOS own | 0/0 | 0/0 | 0 | 0 | 0 |
| tbs | Wine-10.0 | 21/18 | 21/18 | 1 | 3 | 0 |
| themeui | ReactOS own | 0/0 | 0/0 | 0 | 0 | 0 |
| traffic | Wine-10.0 | 21/19 | 21/19 | 1 | 2 | 0 |
| twain_32 | Wine-10.0 | 1/0 | 1/0 | 2 | 7 | 0 |
| ubtrfs | ReactOS own | 5/0 | 5/0 | 1 | 0 | 0 |
| ucdfs | ReactOS own | 2/0 | 2/0 | 1 | 0 | 0 |
| ucrtbase | ReactOS own | 2614/191 | 2614/191 | 2 | 0 | 0 |
| uext2 | ReactOS own | 2/0 | 2/0 | 1 | 0 | 0 |
| ufat | ReactOS own | 2/0 | 2/0 | 1 | 0 | 0 |
| ufatx | ReactOS own | 2/0 | 2/0 | 1 | 0 | 0 |
| uiautomationcore | Wine-10.0 | 98/62 | 98/62 | 8 | 227 | 0 |
| untfs | ReactOS own | 2/0 | 2/0 | 1 | 0 | 0 |
| updspapi | Wine-10.0 | 78/4 | 78/4 | 1 | 1 | 0 |
| url | Wine-10.0 | 21/13 | 21/13 | 1 | 4 | 0 |
| urlmon | Wine-10.0 | 110/23 | 110/23 | 21 | 199 | 0 |
| userenv | ReactOS own | 122/73 | 122/73 | 10 | 19 | 2 |
| usp10 | Wine-11.17 | 44/5 | 44/5 | 12 | 45 | 0 |
| uxtheme | Forked | 92/22 | 92/22 | 14 | 33 | 1 |
| vbscript | Wine-10.0 | 4/0 | 4/0 | 11 | 189 | 0 |
| verifier | ReactOS own | 17/17 | 17/17 | 1 | 0 | 0 |
| version | WineStaging-4.18 (Requires kernelbase) | 16/0 | 16/0 | 1 | 7 | 0 |
| vssapi | WineStaging-4.18 | 84/77 | 84/77 | 1 | 7 | 0 |
| wbemdisp | WineStaging-4.18 | 4/0 | 4/0 | 3 | 93 | 0 |
| wbemprox | WineStaging-4.18 | 4/0 | 4/0 | 13 | 76 | 0 |
| wdmaud.drv | ReactOS own | 6/0 | 6/0 | 4 | 7 | 0 |
| wevtapi | Wine-10.0 | 46/30 | 46/30 | 1 | 16 | 0 |
| windowscodecs | Wine-10.0 | 118/5 | 118/5 | 35 | 210 | 0 |
| windowscodecsext | Wine-10.0 | 3/0 | 3/0 | 1 | 1 | 0 |
| winfax | ReactOS own | 55/0 | 55/0 | 1 | 0 | 55 |
| wing32 | Wine-10.0 | 10/0 | 10/0 | 1 | 0 | 0 |
| winhttp | Wine-10.0 | 49/0 | 49/0 | 8 | 66 | 0 |
| wininet | Wine-10.0 | 248/42 | 248/42 | 11 | 179 | 0 |
| winmm | Forked at Wine-20050628 | 194/8 | 194/8 | 10 | 106 | 0 |
| winscard | WineStaging-4.18 (Newer versions require pcsclite) | 63/4 | 63/4 | 2 | 12 | 43 |
| winsta | ReactOS own | 123/0 | 123/0 | 7 | 1 | 124 |
| wintrust | Wine-10.0 | 127/38 | 127/38 | 5 | 57 | 0 |
| winusb | Wine-10.0 | 22/21 | 22/21 | 1 | 1 | 0 |
| wlanapi | own-tree, Wine-derived (untracked) | 36/12 | 36/12 | 2 | 0 | 13 |
| wldap32 | WineStaging-4.18 | 245/2 | 245/2 | 20 | 22 | 0 |
| wlnotify | ReactOS own | 28/0 | 28/0 | 6 | 0 | 0 |
| wmi | Wine-10.0 | 45/0 | 45/0 | 0 | 0 | 0 |
| wmiutils | Wine-10.0 | 4/0 | 4/0 | 3 | 29 | 0 |
| wmvcore | WineStaging-4.18 | 20/7 | 20/7 | 3 | 246 | 0 |
| ws2_32 | ReactOS own | 117/0 | 166/22 | 37 | 7 | 21 |
| ws2help | ReactOS own | 23/0 | 23/0 | 5 | 0 | 0 |
| wshirda | ReactOS own | 11/0 | 11/0 | 1 | 0 | 11 |
| wshom.ocx | Wine-10.0 | 4/0 | 4/0 | 4 | 43 | 0 |
| wshtcpip | ReactOS own | 16/0 | 16/0 | 2 | 2 | 8 |
| wsock32 | ReactOS own | 75/0 | 75/0 | 1 | 0 | 0 |
| wtsapi32 | WineStaging-4.18 | 52/2 | 52/2 | 1 | 52 | 0 |
| wuapi | Wine-10.0 | 4/0 | 4/0 | 7 | 95 | 0 |
| xinput1_1 | WineStaging-2.9 | 5/0 | 5/0 | 1 | 0 | 0 |
| xinput1_2 | WineStaging-2.9 | 5/0 | 5/0 | 1 | 0 | 0 |
| xinput1_3 | WineStaging-2.9 | 9/0 | 9/0 | 1 | 8 | 0 |
| xinput9_1_0 | WineStaging-2.9 | 4/0 | 4/0 | 1 | 0 | 0 |
| xmllite | Wine-10.0 | 6/0 | 6/0 | 3 | 21 | 0 |
| xolehlp | Wine-10.0 | 6/3 | 6/3 | 1 | 19 | 0 |

### A.2 `dll/directx/wine` (94 modules)

| Module | Origin | 0x502 exp/stub | 0xA00 exp/stub | Src files | FIXME | UNIMPL |
|---|---|---|---|---|---|---|
| amstream | wine-10.1-dev (b00c7619f1b) | 4/0 | 4/0 | 6 | 43 | 0 |
| d2d1 | wine-10.1-dev (b00c7619f1b) | 11/1 | 11/1 | 15 | 197 | 0 |
| d3d10 | wine-10.1-dev (b00c7619f1b) | 29/4 | 29/4 | 4 | 61 | 0 |
| d3d10_1 | wine-10.1-dev (b00c7619f1b) | 30/5 | 30/5 | 1 | 5 | 0 |
| d3d10core | wine-10.1-dev (b00c7619f1b) | 2/0 | 2/0 | 1 | 0 | 0 |
| d3d11 | wine-10.1-dev (b00c7619f1b) | 38/33 | 45/33 | 11 | 191 | 0 |
| d3d12 | wine-10.1-dev (b00c7619f1b) | 11/4 | 11/4 | 1 | 3 | 0 |
| d3d12core | wine-10.1-dev (b00c7619f1b) | 2/2 | 2/2 | 0 | 0 | 0 |
| d3d8 | wine-10.1-dev (b00c7619f1b) | 5/0 | 5/0 | 10 | 24 | 0 |
| d3d9 | wine-10.1-dev (b00c7619f1b) | 15/3 | 15/3 | 12 | 55 | 0 |
| d3dcompiler_33 | ReactOS own | 10/2 | 10/2 | 0 | 0 | 0 |
| d3dcompiler_34 | ReactOS own | 10/2 | 10/2 | 0 | 0 | 0 |
| d3dcompiler_35 | ReactOS own | 10/2 | 10/2 | 0 | 0 | 0 |
| d3dcompiler_36 | ReactOS own | 10/2 | 10/2 | 0 | 0 | 0 |
| d3dcompiler_37 | ReactOS own | 10/2 | 10/2 | 0 | 0 | 0 |
| d3dcompiler_38 | ReactOS own | 11/3 | 11/3 | 0 | 0 | 0 |
| d3dcompiler_39 | ReactOS own | 11/3 | 11/3 | 0 | 0 | 0 |
| d3dcompiler_40 | ReactOS own | 12/3 | 12/3 | 0 | 0 | 0 |
| d3dcompiler_41 | ReactOS own | 13/3 | 13/3 | 0 | 0 | 0 |
| d3dcompiler_42 | ReactOS own | 13/3 | 13/3 | 0 | 0 | 0 |
| d3dcompiler_43 | wine-10.1-dev (b00c7619f1b) | 17/5 | 17/5 | 6 | 54 | 0 |
| d3dcompiler_46 | ReactOS own | 25/9 | 25/9 | 0 | 0 | 0 |
| d3dcompiler_47 | ReactOS own | 29/11 | 29/11 | 0 | 0 | 0 |
| d3drm | wine-10.1-dev (b00c7619f1b) | 23/0 | 23/0 | 11 | 409 | 0 |
| d3dx10_33 | ReactOS own | 177/0 | 177/0 | 1 | 0 | 0 |
| d3dx10_34 | ReactOS own | 177/0 | 177/0 | 1 | 0 | 0 |
| d3dx10_35 | ReactOS own | 180/0 | 180/0 | 1 | 0 | 0 |
| d3dx10_36 | ReactOS own | 180/0 | 180/0 | 1 | 0 | 0 |
| d3dx10_37 | ReactOS own | 181/2 | 181/2 | 1 | 0 | 0 |
| d3dx10_38 | ReactOS own | 180/1 | 180/1 | 1 | 0 | 0 |
| d3dx10_39 | ReactOS own | 180/4 | 180/4 | 1 | 0 | 0 |
| d3dx10_40 | ReactOS own | 176/0 | 176/0 | 1 | 0 | 0 |
| d3dx10_41 | ReactOS own | 176/0 | 176/0 | 1 | 0 | 0 |
| d3dx10_42 | ReactOS own | 176/0 | 176/0 | 1 | 0 | 0 |
| d3dx10_43 | own-tree, Wine-derived (untracked) | 176/26 | 176/26 | 8 | 67 | 0 |
| d3dx11_42 | ReactOS own | 44/23 | 44/23 | 0 | 0 | 0 |
| d3dx11_43 | own-tree, Wine-derived (untracked) | 44/23 | 44/23 | 3 | 14 | 0 |
| d3dx9_24 | ReactOS own | 320/65 | 320/65 | 0 | 0 | 0 |
| d3dx9_25 | ReactOS own | 323/68 | 323/68 | 0 | 0 | 0 |
| d3dx9_26 | ReactOS own | 327/72 | 327/72 | 0 | 0 | 0 |
| d3dx9_27 | ReactOS own | 327/72 | 327/72 | 0 | 0 | 0 |
| d3dx9_28 | ReactOS own | 332/72 | 332/72 | 0 | 0 | 0 |
| d3dx9_29 | ReactOS own | 332/72 | 332/72 | 0 | 0 | 0 |
| d3dx9_30 | ReactOS own | 332/72 | 332/72 | 0 | 0 | 0 |
| d3dx9_31 | ReactOS own | 329/70 | 329/70 | 0 | 0 | 0 |
| d3dx9_32 | ReactOS own | 334/72 | 334/72 | 0 | 0 | 0 |
| d3dx9_33 | ReactOS own | 334/72 | 334/72 | 0 | 0 | 0 |
| d3dx9_34 | ReactOS own | 334/72 | 334/72 | 0 | 0 | 0 |
| d3dx9_35 | ReactOS own | 334/72 | 334/72 | 0 | 0 | 0 |
| d3dx9_36 | ReactOS own | 336/72 | 336/72 | 20 | 381 | 0 |
| d3dx9_37 | ReactOS own | 336/72 | 336/72 | 0 | 0 | 0 |
| d3dx9_38 | ReactOS own | 336/72 | 336/72 | 0 | 0 | 0 |
| d3dx9_39 | ReactOS own | 336/72 | 336/72 | 0 | 0 | 0 |
| d3dx9_40 | ReactOS own | 336/72 | 336/72 | 0 | 0 | 0 |
| d3dx9_41 | ReactOS own | 336/72 | 336/72 | 0 | 0 | 0 |
| d3dx9_42 | ReactOS own | 329/67 | 329/67 | 0 | 0 | 0 |
| d3dx9_43 | ReactOS own | 329/67 | 329/67 | 0 | 0 | 0 |
| d3dxof | wine-10.1-dev (b00c7619f1b) | 5/0 | 5/0 | 4 | 28 | 0 |
| ddraw | wine-10.1-dev (b00c7619f1b) | 28/16 | 28/16 | 12 | 69 | 0 |
| ddrawex | wine-10.1-dev (b00c7619f1b) | 4/0 | 4/0 | 3 | 16 | 0 |
| devenum | wine-10.1-dev (b00c7619f1b) | 4/0 | 4/0 | 4 | 22 | 0 |
| dinput | WineStaging-4.18 | 7/0 | 7/0 | 11 | 81 | 0 |
| dinput8 | WineStaging-4.18 | 5/0 | 5/0 | 0 | 0 | 0 |
| dmband | wine-10.1-dev (b00c7619f1b) | 4/0 | 4/0 | 2 | 18 | 0 |
| dmcompos | wine-10.1-dev (b00c7619f1b) | 4/0 | 4/0 | 5 | 34 | 0 |
| dmime | wine-10.1-dev (b00c7619f1b) | 4/0 | 4/0 | 16 | 153 | 0 |
| dmloader | wine-10.1-dev (b00c7619f1b) | 4/0 | 4/0 | 5 | 27 | 0 |
| dmscript | wine-10.1-dev (b00c7619f1b) | 4/0 | 4/0 | 3 | 23 | 0 |
| dmstyle | wine-10.1-dev (b00c7619f1b) | 4/0 | 4/0 | 9 | 109 | 0 |
| dmusic | wine-10.1-dev (b00c7619f1b) | 4/0 | 4/0 | 11 | 61 | 0 |
| dmusic32 | wine-10.1-dev (b00c7619f1b) | 2/0 | 2/0 | 1 | 2 | 0 |
| dplay | wine-10.1-dev (b00c7619f1b) | 2/0 | 2/0 | 0 | 0 | 0 |
| dplayx | wine-10.1-dev (b00c7619f1b) | 11/0 | 11/0 | 9 | 212 | 0 |
| dpnaddr | wine-10.1-dev (b00c7619f1b) | 1/0 | 1/0 | 0 | 0 | 0 |
| dpnet | wine-10.1-dev (b00c7619f1b) | 5/0 | 5/0 | 7 | 107 | 0 |
| dpnhpast | wine-10.1-dev (b00c7619f1b) | 5/0 | 5/0 | 1 | 1 | 0 |
| dpnhupnp | wine-10.1-dev (b00c7619f1b) | 5/0 | 5/0 | 1 | 2 | 0 |
| dpnlobby | wine-10.1-dev (b00c7619f1b) | 1/0 | 1/0 | 0 | 0 | 0 |
| dpvoice | wine-10.1-dev (b00c7619f1b) | 5/0 | 5/0 | 3 | 29 | 0 |
| dpwsockx | wine-10.1-dev (b00c7619f1b) | 3/2 | 3/2 | 1 | 9 | 0 |
| dsound | Forked at Wine-1.3.29 (newer needs NT6 mmdevapi) | 14/0 | 14/0 | 11 | 49 | 0 |
| dswave | wine-10.1-dev (b00c7619f1b) | 4/0 | 4/0 | 1 | 1 | 0 |
| dwrite | wine-10.1-dev (b00c7619f1b) | 1/0 | 1/0 | 18 | 145 | 0 |
| dx8vb | wine-10.1-dev (b00c7619f1b) | 139/135 | 139/135 | 1 | 2 | 0 |
| dxcore | wine-10.1-dev (b00c7619f1b) | 1/0 | 1/0 | 1 | 1 | 0 |
| dxdiagn | wine-10.1-dev (b00c7619f1b) | 4/0 | 4/0 | 3 | 6 | 0 |
| dxgi | wine-10.1-dev (b00c7619f1b) | 6/0 | 6/0 | 8 | 139 | 0 |
| dxtrans | wine-10.1-dev (b00c7619f1b) | 11/7 | 11/7 | 1 | 1 | 0 |
| dxva2 | wine-10.1-dev (b00c7619f1b) | 38/1 | 38/1 | 1 | 52 | 0 |
| msdmo | wine-10.1-dev (b00c7619f1b) | 15/4 | 15/4 | 2 | 0 | 0 |
| qcap | wine-10.1-dev (b00c7619f1b) | 4/0 | 4/0 | 9 | 90 | 0 |
| qedit | wine-10.1-dev (b00c7619f1b) | 4/0 | 4/0 | 5 | 91 | 0 |
| quartz | wine-10.1-dev (b00c7619f1b) | 9/0 | 9/0 | 17 | 218 | 0 |
| wined3d | wine-10.1-dev (b00c7619f1b). Built as d3dwine.dll. | 354/0 | 354/0 | 29 | 508 | 0 |

### A.3 `dll/opengl` (3 modules)

| Module | Origin | 0x502 exp/stub | 0xA00 exp/stub | Src files | FIXME | UNIMPL |
|---|---|---|---|---|---|---|
| glu32 | ReactOS own | 59/0 | 59/0 | 17 | 0 | 0 |
| mesa | ReactOS own | 0/0 | 0/0 | 52 | 0 | 0 |
| opengl32 | ReactOS own | 368/6 | 368/6 | 6 | 6 | 2 |

### A.4 `dll/3rdparty` (7 modules)

| Module | Origin | 0x502 exp/stub | 0xA00 exp/stub | Src files | FIXME | UNIMPL |
|---|---|---|---|---|---|---|
| dxtn | ReactOS own | 4/0 | 4/0 | 2 | 0 | 0 |
| libjpeg | ReactOS own | 24/0 | 24/0 | 71 | 0 | 0 |
| libpng | ReactOS own | 53/0 | 53/0 | 16 | 0 | 0 |
| libtiff | ReactOS own | 16/0 | 16/0 | 44 | 1 | 0 |
| libtirpc | ReactOS own | 0/0 | 0/0 | 74 | 1 | 0 |
| libxslt | ReactOS own | 242/0 | 242/0 | 19 | 0 | 0 |
| mbedtls | ReactOS own | 119/0 | 119/0 | 81 | 0 | 0 |

### A.5 `win32ss/user` (6 modules)

| Module | Origin | 0x502 exp/stub | 0xA00 exp/stub | Src files | FIXME | UNIMPL |
|---|---|---|---|---|---|---|
| imm32 | ReactOS own | 132/0 | 132/0 | 15 | 6 | 0 |
| ntuser | ReactOS own | 0/0 | 0/0 | 61 | 224 | 6 |
| rtl | own-tree, Wine-derived (untracked) | 0/0 | 0/0 | 2 | 1 | 0 |
| user32 | ReactOS own | 730/2 | 782/5 | 54 | 164 | 32 |
| user32_vista | own-tree, Wine-derived (untracked) | 2/0 | 2/0 | 5 | 76 | 7 |
| winsrv | ReactOS own | 3/0 | 3/0 | 36 | 59 | 5 |

### A.6 `win32ss/gdi` (6 modules)

| Module | Origin | 0x502 exp/stub | 0xA00 exp/stub | Src files | FIXME | UNIMPL |
|---|---|---|---|---|---|---|
| dib | ReactOS own | 0/0 | 0/0 | 13 | 4 | 0 |
| diblib | ReactOS own | 0/0 | 0/0 | 29 | 1 | 0 |
| eng | ReactOS own | 0/0 | 0/0 | 40 | 42 | 166 |
| gdi32 | ReactOS own | 613/0 | 673/0 | 47 | 85 | 47 |
| gdi32_vista | ReactOS own | 9/0 | 9/0 | 2 | 0 | 0 |
| ntgdi | ReactOS own | 0/0 | 0/0 | 40 | 85 | 29 |

### A.7 `base/services` (23 modules)

| Module | Origin | 0x502 exp/stub | 0xA00 exp/stub | Src files | FIXME | UNIMPL |
|---|---|---|---|---|---|---|
| audiosrv | ReactOS own | 0/0 | 0/0 | 5 | 2 | 0 |
| browser | ReactOS own | 3/1 | 3/1 | 2 | 1 | 12 |
| dcomlaunch | ReactOS own | 1/0 | 1/0 | 2 | 1 | 1 |
| dhcpcsvc | ReactOS own | 38/21 | 38/21 | 13 | 4 | 3 |
| dnsrslvr | ReactOS own | 1/0 | 1/0 | 4 | 0 | 0 |
| eventlog | ReactOS own | 0/0 | 0/0 | 5 | 11 | 4 |
| netlogon | ReactOS own | 29/24 | 29/24 | 2 | 0 | 47 |
| nfsd | ReactOS own | 0/0 | 0/0 | 36 | 0 | 0 |
| rpcss | Wine-10.0 | 0/0 | 0/0 | 4 | 5 | 0 |
| schedsvc | ReactOS own | 1/0 | 1/0 | 3 | 5 | 0 |
| seclogon | ReactOS own | 2/0 | 2/0 | 2 | 1 | 0 |
| shsvcs | own-tree, Wine-derived (untracked) | 16/8 | 16/8 | 3 | 0 | 0 |
| srvsvc | ReactOS own | 1/0 | 1/0 | 2 | 14 | 50 |
| svchost | ReactOS own | 0/0 | 0/0 | 5 | 0 | 0 |
| tcpsvcs | ReactOS own | 0/0 | 0/0 | 8 | 1 | 0 |
| telnetd | own-tree, Wine-derived (untracked) | 0/0 | 0/0 | 3 | 2 | 0 |
| tftpd | ReactOS own | 0/0 | 0/0 | 1 | 0 | 0 |
| umpnpmgr | ReactOS own | 9/3 | 9/3 | 4 | 12 | 20 |
| w32time | ReactOS own | 5/0 | 5/0 | 3 | 0 | 0 |
| wkssvc | ReactOS own | 1/0 | 1/0 | 4 | 10 | 16 |
| wlansvc | ReactOS own | 0/0 | 0/0 | 2 | 1 | 40 |
| wmisvc | ReactOS own | 1/0 | 1/0 | 1 | 0 | 0 |
| wuauserv | ReactOS own | 1/0 | 1/0 | 1 | 0 | 0 |

### A.8 `base/shell` (5 modules)

| Module | Origin | 0x502 exp/stub | 0xA00 exp/stub | Src files | FIXME | UNIMPL |
|---|---|---|---|---|---|---|
| cmd | ReactOS own | 0/0 | 0/0 | 58 | 18 | 0 |
| explorer | ReactOS own | 0/0 | 0/0 | 23 | 35 | 3 |
| filebrowser | ReactOS own | 0/0 | 0/0 | 1 | 0 | 0 |
| progman | ReactOS own | 0/0 | 0/0 | 6 | 15 | 0 |
| rshell | own-tree, Wine-derived (untracked) | 14/0 | 14/0 | 2 | 0 | 0 |

### A.9 `dll/cpl` (23 modules)

| Module | Origin | 0x502 exp/stub | 0xA00 exp/stub | Src files | FIXME | UNIMPL |
|---|---|---|---|---|---|---|
| access | ReactOS own | 1/0 | 1/0 | 6 | 1 | 0 |
| appwiz | ReactOS own | 5/0 | 5/0 | 4 | 0 | 0 |
| bthprops | Wine-10.0 | 64/50 | 64/50 | 0 | 0 | 0 |
| console | ReactOS own | 1/0 | 1/0 | 6 | 4 | 0 |
| desk | ReactOS own | 7/0 | 7/0 | 20 | 18 | 1 |
| hdwwiz | ReactOS own | 3/0 | 3/0 | 1 | 2 | 0 |
| hotplug | ReactOS own | 1/0 | 1/0 | 3 | 0 | 0 |
| inetcpl | WineStaging-4.18 | 25/19 | 25/19 | 5 | 8 | 0 |
| input | ReactOS own | 1/0 | 1/0 | 10 | 3 | 0 |
| intl | ReactOS own | 1/0 | 1/0 | 12 | 0 | 0 |
| joy | ReactOS own | 1/0 | 1/0 | 1 | 0 | 0 |
| liccpa | ReactOS own | 1/0 | 1/0 | 1 | 0 | 0 |
| main | ReactOS own | 1/0 | 1/0 | 3 | 0 | 0 |
| mmsys | ReactOS own | 14/0 | 14/0 | 6 | 1 | 0 |
| ncpa | ReactOS own | 1/0 | 1/0 | 1 | 0 | 0 |
| odbccp32 | ReactOS own | 1/0 | 1/0 | 1 | 0 | 0 |
| openglcfg | ReactOS own | 1/0 | 1/0 | 2 | 0 | 0 |
| powercfg | ReactOS own | 1/0 | 1/0 | 6 | 2 | 0 |
| sysdm | ReactOS own | 1/0 | 1/0 | 12 | 10 | 0 |
| telephon | ReactOS own | 1/0 | 1/0 | 1 | 0 | 0 |
| timedate | ReactOS own | 1/0 | 1/0 | 6 | 1 | 0 |
| usrmgr | ReactOS own | 1/0 | 1/0 | 7 | 1 | 0 |
| wined3dcfg | ReactOS own | 1/0 | 1/0 | 2 | 0 | 0 |

### A.10 `dll/shellext` (16 modules)

| Module | Origin | 0x502 exp/stub | 0xA00 exp/stub | Src files | FIXME | UNIMPL |
|---|---|---|---|---|---|---|
| acppage | ReactOS own | 5/0 | 5/0 | 3 | 0 | 0 |
| cabview | ReactOS own | 4/0 | 4/0 | 3 | 0 | 1 |
| cryptext | ReactOS own | 2/0 | 2/0 | 1 | 0 | 0 |
| deskadp | ReactOS own | 2/0 | 2/0 | 2 | 0 | 0 |
| deskmon | ReactOS own | 2/0 | 2/0 | 2 | 0 | 0 |
| devcpux | ReactOS own | 1/0 | 1/0 | 1 | 0 | 0 |
| fontext | ReactOS own | 4/0 | 4/0 | 8 | 0 | 8 |
| mmcshext | ReactOS own | 4/0 | 4/0 | 1 | 0 | 0 |
| mydocs | ReactOS own | 4/0 | 4/0 | 2 | 4 | 0 |
| netplwiz | own-tree, Wine-derived (untracked) | 15/6 | 14/6 | 2 | 1 | 0 |
| netshell | ReactOS own | 33/26 | 33/26 | 7 | 10 | 0 |
| ntobjshex | ReactOS own | 4/0 | 4/0 | 5 | 0 | 0 |
| sendmail | ReactOS own | 4/0 | 4/0 | 2 | 4 | 0 |
| shellbtrfs | ReactOS own | 24/0 | 24/0 | 14 | 3 | 0 |
| stobject | ReactOS own | 4/0 | 4/0 | 6 | 2 | 1 |
| zipfldr | ReactOS own | 5/0 | 5/0 | 13 | 2 | 2 |

### A.11 `dll/appcompat` (2 modules)

| Module | Origin | 0x502 exp/stub | 0xA00 exp/stub | Src files | FIXME | UNIMPL |
|---|---|---|---|---|---|---|
| apphelp | ReactOS own | 179/105 | 179/105 | 10 | 1 | 0 |
| shims | ReactOS own | 0/0 | 0/0 | 14 | 0 | 0 |

### A.12 `dll/nls` (2 modules)

| Module | Origin | 0x502 exp/stub | 0xA00 exp/stub | Src files | FIXME | UNIMPL |
|---|---|---|---|---|---|---|
| idndl | ReactOS own | 3/0 | 3/0 | 1 | 0 | 0 |
| normaliz | ReactOS own | 5/0 | 5/0 | 4 | 0 | 0 |

### A.13 `dll/np` (1 modules)

| Module | Origin | 0x502 exp/stub | 0xA00 exp/stub | Src files | FIXME | UNIMPL |
|---|---|---|---|---|---|---|
| nfs | ReactOS own | 13/0 | 13/0 | 3 | 0 | 0 |

Notes: `dll/directx/wine/d3dcompiler_*` show "ReactOS own" only because they are listed as a range in WINESYNC (`d3dcompiler_33 => 47`, Wine 10.1-dev). The same applies to the `d3dx9_*`, `d3dx10_*` and `d3dx11_*` ranges. `base/shell/rshell` is flagged "Wine-derived" only because it includes `wine/debug.h`; it is ReactOS code. `base/services/telnetd` is a public-domain telnet server (header: "Use freely, no copyrights"). `ucrtbase` shows "ReactOS own" because it has no WINESYNC line; its real origin is the Microsoft UCRT source subset (MIT) plus ReactOS glue (section 3.1). A spec with 0 exports means the module is an EXE/service or has no `.spec`.
