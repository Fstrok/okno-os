# ReactOS build, toolchains, CI, tests, debugging (Okno knowledge base)

Audited 2026-10-29.

- **Upstream code:** ReactOS master `e46f4bb1a1e` (2026-10-25). Paths below are relative to the source root.
- **Fork:** `/home/user/okno-os` at `7fa32267b2d`.
  - `DLL_EXPORT_VERSION` default is 0x600.
  - It builds with clang 18 + Ubuntu mingw-w64 through `toolchain-clang.cmake` after three fixes: `xmmintrin.h`, mingw `dlltool`, and i386 C++ EH model auto-detection.
  - Debug 0x600 links everything except modules hit by two open issues: the i386 `_alloca` stack-probe symbol and out-of-line float math for UCRT modules.
  - CI is `.github/workflows/okno.yml`. The app tests are `tools/qemu/apptest.py` + `vm.py`.
- **Evidence tags:**
  - **[code]**: read in the source tree.
  - **[run]**: executed here, on Ubuntu 24.04 with 4 vCPU and QEMU TCG (no KVM in this sandbox).
  - **[web]**: external source, URL in the "Sources" section at the end.
  - **[hist]**: upstream git history (full clone).

---

## 1. Summary and decisions

### 1.1 Decisions

| # | Decision | Why (short) |
|---|---|---|
| D1 | **Primary toolchain: LLVM clang targeting `*-w64-mingw32`, with distro mingw-w64 binutils/GCC 13 for `as`/`ld`/`windres`/`windmc`/`dlltool`.** Build it on `ubuntu-24.04` runners. Keep `toolchain-clang.cmake`, which the fork already builds with. | It already works in the fork. On Linux runners the build is about 10× faster than MSVC jobs. It is ccache-friendly and produces KDBG builds with plain-text serial logs, which is what automated testing needs (§3). |
| D1a | **Before trusting any x64 result, fix x64 SEH for clang.** Today, clang+amd64 compiles all `_SEH2_TRY` blocks as plain blocks: no exception handling at all (§1.3). Fix: use native `__try` with `-fasync-exceptions`, which this audit verified compiles to real handlers. | The kernel's user-buffer probing depends on SEH. |
| D2 | **Secondary: an MSVC job (VS 2022 toolset `14`, or VS 2026 on `windows-2025`), x64 Debug, nightly or `workflow_dispatch`.** It does not run on every push. Upload `build/msvc_pdb`. | MSVC is the only toolchain upstream uses for official x64 nightlies. It gives PDBs + KD protocol, i.e. WinDbg. It also keeps the fork mergeable with upstream MSVC-only code paths. |
| D3 | **Not chosen:** RosBE GCC 8.4, and clang-cl + lld-link. | **RosBE GCC 8.4:** the Unix release is frozen since 2020. ReactOS CI builds it from a personal gist plus a personal fork branch, and amd64 SEH depends on a home-made GCC plugin. **clang-cl + lld-link:** upstream says "not compatible yet", and it still needs MASM, `rc` and `mc`. Revisit clang-cl + lld later as the way to get PDBs from Linux. |
| D4 | **`DLL_EXPORT_VERSION=0x600` stays the default** (fork). Add a **build-only, non-blocking `0xA00` job.** | `0xA00` is a real level: 16 exports and 3 extra DLLs depend on it. Upstream never tests it in CI. |
| D5 | **ISO targets:** use `bootcd` for humans (setup + live in one ISO) and `bootcdregtest` for automation. `hybridcd` no longer exists. The `livecd` target only builds a non-bootable `liveimg.iso`. **`okno.yml` uploads a non-existent `build/livecd.iso`: remove that path.** | §2.4 |
| D6 | **Test flow = `bootcdregtest.iso` unattended install → autologon (Administrator) → first-logon hook → `\okno\run.cmd` on a FAT32 test disk → `dbgprint OKNO:*` markers on COM1 → host stops the VM.** This is the design of the fork's `tools/qemu/apptest.py`. **Verified end-to-end here on the x86 nightly: 236 s (payload on CD) and 387 s (payload on a data disk), under TCG.** Test builds must be KDBG builds (non-MSVC Debug). §3.6 lists the improvements: bidirectional serial to answer `kdb:>` with `bt`/`cont` (sysreg2 logic); no ACPI power-off; no `/FIRSTCHANCE` false crashes. | §3 |
| D7 | **Headers:** keep the ReactOS SDK. Do targeted syncs of user-mode headers from **mingw-w64 v14** (public domain). Wine headers (LGPL) go only with Wine-synced DLLs. Write WDK-level headers by hand from Microsoft Learn (ReactOS already has WDDM up to 3.1, NDIS 6.20, StorPort, UCX 1.6 and KMDF 1.17). Never copy WDK/SDK headers. | §4 |
| D8 | **Debugging:** for CI, use KDBG text plus backtraces (`bt`) resolved with `raddr2line`/`log2lines`. Interactively, use `kdgdb` + GDB, or the QEMU gdbstub. Use WinDbg only on MSVC builds. There is no KDNET transport. | §5 |

### 1.2 Toolchain comparison, with evidence

| | MSVC (cl/link/ml) | clang-cl + MS link | **clang mingw-target + GNU binutils** (fork) | RosBE GCC 8.4 (upstream Linux CI) |
|---|---|---|---|---|
| Upstream status | Official x64 nightlies are **x64 MSVC Debug only**. x86 nightlies are both GCC and MSVC [web getbuilds]. The serial log shows buildbot path `Build_GCCLin_x86` for x86 [run]. | CI job uses LLVM 13 + VS link. `# FIXME: Does not boot on toolset 14.1, 14.3+ is untested` (`.github/workflows/build.yml`) [code] | CI job: LLVM 13, 0x502 only, RosBE's GNU ld [code] | CI primary on Linux, all matrix cells [code] |
| SEH x86 | Native | Native | PSEH3 (`sdk/lib/pseh/CMakeLists.txt`) [code] | PSEH3 [code] |
| SEH x64 | Native | Native (`[PSEH] Use native SEH on clang-cl x64`, 2025-01) [hist] | **Dummy: no SEH at all.** `pseh2.h` sends `__clang__ && _M_AMD64` to the `_USE_DUMMY_PSEH` branch, and `pseh/CMakeLists.txt` builds `dummy.c` for Clang+amd64 [code] | Home-made GCC plugin `sdk/tools/gcc_plugin_seh` (built against that GCC's plugin headers). `kmtests` are skipped: "FIXME build is broken with new x64 PSEH" [code] |
| Debug info | PDB (`/Zi`, Debug only) → `build/msvc_pdb` [code] | PDB | DWARF-2 embedded. i386 Debug also gets a `.rossym` section via `rsym`. `-DSEPARATE_DBG=TRUE` writes `build/symbols/` [code] | same as clang |
| Kernel debugger default | `_WINKD_=TRUE` (Debug) → KD protocol (WinDbg), `KDBG=FALSE` (`sdk/cmake/config.cmake`) [code] | same | `KDBG=TRUE` (Debug), `_WINKD_=FALSE` → built-in KDBG on serial [code] | same |
| Linux runner | No | No (needs link.exe, lib.exe, ml, rc, mc) | **Yes**: apt packages only (fork `okno.yml`) [code] | Yes, but RosBE is compiled from source on a cache miss [code] |
| Per-job time in ReactOS CI, run 40239066678 (warm caches) | 10m47s – 23m30s [web] | 12m34s – 28m12s [web] | 2m43s – 3m14s [web] | 2m02s – 3m59s [web] |
| Cost to switch from fork state | Separate job only, no code change (upstream CI recipe works) | Medium (no Linux path) | 0 (current); x64 SEH fix needed | High (old GCC) |

### 1.3 x64 SEH under clang: the problem and the verified building block

- **The problem [code]:**
  - `sdk/lib/pseh/include/pseh/pseh2.h` uses native `__try` only for `_USE_NATIVE_SEH || _MSC_VER`.
  - GCC+amd64 → `pseh2_64.h` (plugin).
  - **Clang+amd64 → the dummy branch:** `_SEH2_TRY` becomes `{`, and `_SEH2_EXCEPT` compiles to `if (_SEH2_Volatile0 || ...)`, so the handler body is never entered on a fault.
  - `sdk/lib/pseh/CMakeLists.txt` builds `dummy.c` for `CMAKE_C_COMPILER_ID STREQUAL "Clang" AND ARCH STREQUAL "amd64"`.
  - Upstream commit `5ffc6ceb558` (2025-07) only guards macros "for Clang on Linux x64 builders".
- **Verified building block [run]** (clang 18):
  - `clang --target=x86_64-w64-mingw32 -fms-extensions -c` accepts `__try/__except/__finally` and emits `.pdata/.xdata` + `__C_specific_handler`. The same holds for `x86_64-pc-windows-msvc`.
  - Without `-fasync-exceptions`, a `__try` that contains only a memory load (no call) is **optimised away**: 0 handler references. With `-fasync-exceptions` the handler is kept.
  - `i686-w64-mingw32` **fails** (`assembler label 'L__ehtable$f' can not be undefined`). That is why i386 must stay on PSEH3.
  - `__C_specific_handler` already exists in the tree (`sdk/lib/crt/except/amd64/ehandler.c`, exported by `ntdll.spec`, `ntoskrnl.spec`, `msvcrt.spec`).
- **Minimal patch to try:** for Clang+amd64,
  1. define `_USE_NATIVE_SEH` in `pseh2.h`;
  2. build `dummy.c` only (as for MSVC);
  3. add `-fasync-exceptions` in `sdk/cmake/gcc.cmake` under `CMAKE_C_COMPILER_ID STREQUAL "Clang" AND ARCH STREQUAL "amd64"`.

  Then re-enable `kmtests` for that combination and run `kmtest` plus the `ntdll`/`kernel32` apitests (§3). This patch is **not built yet**.

### 1.4 Versions as of 2026-10-29 [web]

| Component | Version | Note |
|---|---|---|
| LLVM | 23.1.0 (2026-08-25); 22.1.0 (2026-02-24); 21.1.8 last of 21.x | The fork uses distro clang 18. Upstream CI pins 13. |
| mingw-w64 | **v14.0.0** (2026-03-27); v13.0.0 (2025-06-04) | Ubuntu 24.04 ships mingw-w64 11.0.1, GCC 13.2 (win32 threads) and binutils 2.41.90 [run, dpkg]. |
| RosBE | **RosBE-Windows 2.3.0 is a test build only** (SourceForge "Test Builds", 2026-01-23). Its `README.pdf` says GCC 13.2.0, Binutils 2.42, CMake 3.31.10, Ninja 1.13.2, ccache 4.12.2, GDB 13.1 [hist, RosBE repo]. **RosBE-Unix latest = 2.2.1 (2020-05-31)**, i.e. GCC 8.4.0, binutils 2.34, mingw-w64 6.0.0 [web]. | |
| Upstream code vs newer GCC | Upstream code is kept compatible with GCC 13/15. | Commits such as "[CTF][SHDOCVW] fix gcc 15 -Werror=overloaded-virtual" (2026-03-28), several "Disable GCC 13 ... warning" commits (2026-03), and the dlltool change for binutils 2.40+ bug #31614 in `sdk/cmake/gcc.cmake` [hist, code]. |
| Visual Studio on GitHub | The `windows-latest`/`windows-2025` label moves to the "Windows Server 2025 with Visual Studio 2026" image (announced for June 2026; VS 18.x builds). | ReactOS `configure.cmd` maps `cl 19.5x` → VS 18 and `build.yml` already switches its MSBuild generator to "Visual Studio 18 2026" when `VisualStudioVersion >= 18` [code]. |

---

## 2. CI recipe

### 2.1 What upstream CI does (`.github/workflows/build.yml`) [code]

| Job | Matrix | What it builds |
|---|---|---|
| `build-linux` | gcc/clang × i386/amd64 × Debug/Release × 0x502/0x600. The 0x600 rows are gcc Debug only (`exclude:`). | Uses RosBE built by `build_rosbe_ci.sh` (gist), cached by `actions/cache` with key = CPU `-march` hash + `zefklop/RosBE` `unix_amd64` HEAD + script hash. Builds with ccache (`CCACHE_SLOPPINESS=time_macros`, 1 GB). |
| `build-msvc` | windows-latest × toolsets `14`/`14.2` × i386/amd64. | `ilammy/msvc-dev-cmd@v1`, Ninja. Flex/bison from `flexbison.7z`. Uploads `bootcd.iso` + `msvc_pdb`. |
| `build-msvc-arm`, `build-clang-cl`, `build-msbuild-i386` | | Secondary jobs. |

**Every job runs:**
1. `cmake --build build -- -k0`
2. `cmake --build build --target bootcd`
3. Upload `build/bootcd.iso`.

### 2.2 Things that must be vendored, never fetched per run

| Item | Upstream fetches it from | Evidence of flakiness |
|---|---|---|
| `build_rosbe_ci.sh` | `gist.githubusercontent.com/zefklop/...` (a personal gist) | |
| RosBE scripts | `github.com/zefklop/RosBE` branch `unix_amd64` (a personal fork) | |
| GCC 8.4 / binutils 2.36 (+ `binutils-seh_pushframe-jgardou.patch`) / gmp / mpc / mpfr / bison / flex / ninja 1.10 | ftp.gnu.org, sourceforge, GitHub | Fallbacks to web.archive.org were added in 2026-09/10 because GNU and SourceForge mirrors failed: commits `bf7cd909dd1` and `214e8665a39` ("SourceForge randomly fails to serve mingw-w64-v6.0.0.tar.bz2") [hist] |
| CMake 3.17.2-reactos | `github.com/reactos/CMake` | Top-level `CMakeLists.txt` warns when the CMake is not RosBE's; MSVC CI uses stock CMake anyway. |
| `flexbison.7z` (Windows jobs) | `svn.reactos.org/storage/vperevertkin/` | Fallback to web.archive.org [code] |
| `llvm.sh` | apt.llvm.org | |
| Test payloads (apps, installers) | (ours) | Put them in a GitHub Release asset or an `actions/cache` keyed by a manifest hash, never vendor URLs at test time. |

**The fork's Linux job needs only Ubuntu apt packages**, so nothing above is required for D1. For D2, vendor `flexbison.7z` as a release asset of our repo.

### 2.3 Build commands and targets [code]

```bash
# Linux (D1). Packages as in okno.yml.
cmake -S . -B build -G Ninja -DCMAKE_TOOLCHAIN_FILE:FILEPATH=toolchain-clang.cmake \
  -DARCH:STRING=i386 -DCMAKE_BUILD_TYPE=Debug -DDLL_EXPORT_VERSION=0x600 \
  -DENABLE_CCACHE=1 -DENABLE_ROSTESTS=1 [-DENABLE_ROSAPPS=1] [-DSEPARATE_DBG=TRUE]
cmake --build build -- -k0
cmake --build build --target bootcd bootcdregtest     # -> build/bootcd.iso, build/bootcdregtest.iso
```

**Options [code]:**
- `ARCH`: `i386`, `amd64`, `arm`, `arm64`.
- `CMAKE_BUILD_TYPE`: `Debug` is the default if unset; `Release` sets `DBG=0` and `KDBG=0`.
- `OPTIMIZE`: 1..7; Debug default = 4 = `-O1`.
- `GDB`: kdgdb becomes `kdcom.dll`.
- `_WINKD_`, `KDBG`, `SEPARATE_DBG`, `NO_ROSSYM`, `LTCG`, `PCH`: PCH is OFF when ccache is used or with GCC.
- `NO_REACTOS_BUILDNO`: freezes `version.h`; otherwise it carries the date and commit (`sdk/include/reactos/version.cmake`).
- `ISAPNP_ENABLE`.
- `I18N_LANG`.
- `USE_DUMMY_PSEH`.

**ISO targets (`boot/boot_images.cmake`):**

| Target | Output | Boot sector / freeldr.ini | Use |
|---|---|---|---|
| `bootcd` | `bootcd.iso`: BIOS El Torito `loader/isoboot.bin`, UEFI `loader/efisys.bin`, made isohybrid (USB-bootable) | `boot/bootdata/bootcd.ini`: `DefaultOS=LiveImg_Debug`, `TimeOut=10`; entries Setup, LiveImg, `*_Debug`, `*_Screen`, `LiveImg_VBoxDebug`, `LiveImg_RamDisk_Debug` | Since `b2e33f26eb3` ("Merge our bootcd and livecd into an all-in-one ReactOS BootCD (#7313)", committed 2026-04-28) **the bootcd *is* the live CD**: files for `livecd` are merged into it. |
| `bootcdregtest` | `bootcdregtest.iso`: El Torito `loader/isobtrt.bin` (= `isoboot.S` with `ROS_REGTEST`, which boots the HDD **immediately** if it has a valid MBR) | `bootcd_regtest.ini`: `DefaultOS=Setup`, `TimeOut=0` | Unattended install + `regtest.cmd` → `rosautotest` (§3.1). |
| `livecd` | `liveimg.iso`: **no El Torito options, not bootable** | – | Intermediate. The RAMDISK variant is `if(FALSE)` in `CMakeMacros.cmake`. |
| `hybridcd` | – | – | Removed (`8fa6679b9f7` "[BOOT] Remove last instances of hybridcd", 2026-05-07) [hist]. |

**`DLL_EXPORT_VERSION` [code]:**
- Cache var in `sdk/cmake/config.cmake`; passed as `-DDLL_EXPORT_VERSION=` to all C code and as `--version=` to `spec2def`.
- `_WIN32_WINNT`/`WINVER` stay **0x502 globally** (top-level `CMakeLists.txt`), so the export level and the header level are independent.
- `spec2def` grammar: `-version=0x600+` (to 0xFFF), `-version=0x502` (exact), `-version=0x400-0x502` (range).
- Counts in `.spec` files: `0x600+` ×1799, `0x601+` ×85, `0x602+` ×36, **`0xA00+` ×16** (ntdll: `RtlFlsAllocEx`/`RtlFlsGetValue2` "Windows 11", `NtGetCurrentProcessorNumberEx`, `RtlIsProcessorFeaturePresent`; kernel32 `SetThreadDescription`; user32 DPI APIs `GetDpiForWindow`, `SetProcessDpiAwarenessContext`...; iphlpapi `GetIfEntry2Ex`).
- **Modules gated by level:**
  - **≥0x600:** avrt, bcryptprimitives, dwmapi, ncrypt, tbs, wevtapi, d2d1, d3d10*, d3d11, d3dx10/11, dwrite, dxgi, dxva2 (`dll/win32/CMakeLists.txt`, `dll/directx/wine/CMakeLists.txt`).
  - **≥0x603:** bcp47langs, dcomp, rtworkq.
  - **≥0xA00:** d3d12, d3d12core, dxcore.
  - **<0x600 only:** ws2help, shlwapi bits.
  - **Clang and <0x601:** `sdk/lib/llvm-compat`.
- Upstream CI never builds 0x603 or 0xA00 (**untested**).

### 2.4 YAML: build job (improved `okno.yml`)

```yaml
name: Okno OS
on: { push: {}, pull_request: {}, workflow_dispatch: {} }
jobs:
  build:
    strategy:
      fail-fast: false
      matrix:
        arch: [i386, amd64]
        dllver: ['0x600']
        include:
          - { arch: amd64, dllver: '0xA00', experimental: true }   # build-only, non-blocking
    continue-on-error: ${{ matrix.experimental == true }}
    runs-on: ubuntu-24.04
    timeout-minutes: 150
    env:
      CCACHE_DIR: ${{ github.workspace }}/.ccache
      CCACHE_BASEDIR: ${{ github.workspace }}
      CCACHE_MAXSIZE: 2G
      CCACHE_SLOPPINESS: time_macros        # same as upstream CI
    steps:
      - uses: actions/checkout@v4
      - name: Toolchain
        run: |
          sudo apt-get update -q
          sudo apt-get install -y -q clang lld llvm gcc-mingw-w64 g++-mingw-w64 binutils-mingw-w64 \
               flex bison ninja-build ccache
          clang --version | head -1 > .toolchain-id; x86_64-w64-mingw32-gcc --version | head -1 >> .toolchain-id
      - uses: actions/cache@v4
        with:
          path: .ccache
          key: ccache-${{ matrix.arch }}-${{ matrix.dllver }}-${{ hashFiles('.toolchain-id') }}-${{ github.sha }}
          restore-keys: ccache-${{ matrix.arch }}-${{ matrix.dllver }}-${{ hashFiles('.toolchain-id') }}-
      - name: Configure
        run: >
          cmake -S . -B build -G Ninja -DCMAKE_TOOLCHAIN_FILE:FILEPATH=toolchain-clang.cmake
          -DARCH:STRING=${{ matrix.arch }} -DCMAKE_BUILD_TYPE=Debug
          -DDLL_EXPORT_VERSION=${{ matrix.dllver }} -DENABLE_CCACHE=1 -DENABLE_ROSTESTS=1
      - name: Build
        run: cmake --build build -- -k0
      - name: ISOs
        run: cmake --build build --target bootcd bootcdregtest
      - run: ccache -s
      - uses: actions/upload-artifact@v4
        with:
          name: okno-${{ matrix.arch }}-${{ matrix.dllver }}
          path: |
            build/bootcd.iso
            build/bootcdregtest.iso
            build/host-tools/bin/raddr2line
            build/host-tools/bin/mkisofs
          compression-level: 0
```

**Notes:**
- **Durations.** Upstream Linux jobs with warm RosBE and ccache caches take **2–4 min** [web]. A cold build here took tens of minutes. Expect roughly 30–60 min cold on a 4-vCPU `ubuntu-24.04` runner and a few minutes warm. **This is an estimate, not measured on GitHub.**
- **What `ENABLE_ROSTESTS=1` adds.** 142 winetest dirs, 69 apitest dirs and kmtests (kmtests are skipped on non-MSVC amd64). They go to `reactos/bin` on every ISO via `add_rostests_file(... FOR all)`.
- **Keep release ISOs separate.** For a lean ISO, build release ISOs in a separate job without `ENABLE_ROSTESTS`.

### 2.5 YAML: MSVC secondary (D2), copy of the upstream recipe with vendored flex/bison

```yaml
  msvc-x64:
    if: github.event_name == 'schedule' || github.event_name == 'workflow_dispatch'
    runs-on: windows-latest
    steps:
      - run: choco install -y ninja
      - name: Flex & Bison (vendored copy of svn.reactos.org flexbison.7z)
        run: |
          gh release download toolchain-assets -p flexbison.7z -R ${{ github.repository }}
          7z x flexbison.7z -O${{github.workspace}}\bin
          echo "${{github.workspace}}\bin" | Out-File -FilePath $env:GITHUB_PATH -Encoding utf8 -Append
          echo "BISON_PKGDATADIR=${{github.workspace}}\bin\share\bison" | Out-File -FilePath $env:GITHUB_ENV -Encoding utf8 -Append
          echo "M4=${{github.workspace}}\bin\m4.exe" | Out-File -FilePath $env:GITHUB_ENV -Encoding utf8 -Append
        env: { GH_TOKEN: '${{ github.token }}' }
      - uses: ilammy/msvc-dev-cmd@v1
        with: { arch: amd64, toolset: '14' }
      - uses: actions/checkout@v4
        with: { path: src }
      - run: cmake -S src -B build -G Ninja -DCMAKE_TOOLCHAIN_FILE:FILEPATH=toolchain-msvc.cmake -DARCH:STRING=amd64 -DCMAKE_BUILD_TYPE=Debug -DDLL_EXPORT_VERSION=0x600
      - run: cmake --build build -- -k0
      - run: cmake --build build --target bootcd
      - uses: actions/upload-artifact@v4
        with: { name: okno-msvc-amd64, path: "build/bootcd.iso\nbuild/msvc_pdb" }
```

**Notes:**
- **No ccache for MSVC.** MSVC Debug uses `/Zi` (shared PDB), which ccache and sccache cannot cache. They would need `/Z7`. Ninja links are serialised (`JOB_POOL link_pool=1`, `sdk/cmake/msvc.cmake`).
- **Duration.** Upstream MSVC jobs take 10–24 min [web].

### 2.6 YAML: test job (uses §3)

```yaml
  qemu-test:
    needs: build
    runs-on: ubuntu-24.04
    strategy: { fail-fast: false, matrix: { arch: [i386] } }   # add amd64 after D1a
    steps:
      - uses: actions/checkout@v4
      - name: Enable KVM            # GitHub changelog 2024-04-02
        run: |
          echo 'KERNEL=="kvm", GROUP="kvm", MODE="0666", OPTIONS+="static_node=kvm"' | sudo tee /etc/udev/rules.d/99-kvm4all.rules
          sudo udevadm control --reload-rules
          sudo udevadm trigger --name-match=kvm
      - run: sudo apt-get update -q && sudo apt-get install -y -q qemu-system-x86 qemu-utils mtools dosfstools
      - uses: actions/download-artifact@v4
        with: { name: 'okno-${{ matrix.arch }}-0x600', path: iso }
      - uses: actions/cache@v4                    # downloaded apps: fetched once, never per run
        with: { path: appcache, key: 'apps-${{ hashFiles(''tools/qemu/apps.tsv'') }}' }
      - name: App test                            # fork's tools/qemu/apptest.py (builds the FAT32 test disk itself)
        run: >
          python3 tools/qemu/apptest.py --arch ${{ matrix.arch == 'amd64' && 'x64' || 'x86' }} --kvm
          --iso iso/bootcdregtest.iso --apps tools/qemu/apps.tsv --cache appcache --out out --timeout 5400
      - if: always()
        run: cat out/results.md >> $GITHUB_STEP_SUMMARY || true
      - uses: actions/upload-artifact@v4
        if: always()
        with: { name: 'test-${{ matrix.arch }}', path: out }
```

**Notes:**
- **Duration.** Install + first logon took **236–387 s under TCG** in this sandbox [run]. With KVM, expect less. The rest of the job is the app runs.
- **Mirror the app downloads.** `apptest.py` fetches app URLs on a cache miss. Mirror them as release assets so a vendor URL change cannot break CI (§2.2).
- **Sharding.** To keep runs short, shard the app list across matrix entries. Each shard is a separate VM from the same ISO.

---

## 3. Headless QEMU test recipe

### 3.1 How ReactOS tests itself [code]

1. **ISO.** `bootcdregtest.iso` boots `Setup` (`bootcd_regtest.ini`, TimeOut 0). Text-mode setup reads **`<SourcePath>\unattend.inf`, i.e. `\i386\unattend.inf` or `\amd64\unattend.inf` on the CD**: NO_CAB files for the bootcd are placed under `${ARCH}/` (`add_cd_file` in `sdk/cmake/CMakeMacros.cmake`). The regtest `unattend.inf` (`boot/bootdata/bootcdregtest/unattend.inf`) does the following:
   - sets `UnattendSetupEnabled = yes`, `AutoPartition=1`, `FormatPartition=1`, `FsType=0` (FAT);
   - installs to `\Windows` "for taming unreliable Winetests (ROSTESTS-416)";
   - sets `[Display] 800x600x16`;
   - adds `[GuiRunOnce] %SystemRoot%\system32\cmd.exe /c "regtest.cmd"`.
2. **Boot entries after an unattended install.** Setup writes `freeldr.ini` with `ReactOS_KdSerial` as the default when `DBG && !_WINKD_ && IsUnattendedSetup`: `/DEBUG /DEBUGPORT=COM1 /BAUDRATE=115200 /SOS /KDSERIAL`, `Timeout=0`. Otherwise the default is `ReactOS_Debug` (DBG) or `ReactOS` (`base/setup/lib/bootsup.c`).
3. **Autologon.** `AutoAdminLogon=1` is the default in `boot/bootdata/hivesft.inf`. `SetAutoAdminLogon()` (`dll/win32/syssetup/security.c`) copies the Administrator name and password (from `AdminPassword`, empty if unset) into `DefaultUserName`/`DefaultPassword`.
4. **`[GuiRunOnce]`.** Lines are written to `HKLM\...\RunOnce` (`dll/win32/syssetup/wizard.c`) and run at the first logon.
5. **`regtest.cmd` (`boot/bootdata/bootcdregtest/regtest.cmd`):**
   - sets `WINETEST_PLATFORM=reactos`;
   - adds itself to the `Run` key, so it also runs after a crash and reboot;
   - prepares the kernel32 versioned test DLLs;
   - optionally copies `AHK-Tests`;
   - runs `dbgprint --process "ipconfig"`, then `start rosautotest /r /s /n`.
6. **`rosautotest` (`modules/rostests/rosautotest`).** For every `%WINDIR%\bin\*test.exe` (override with `ROSAUTOTEST_DIR`; select with `rosautotest <module> [test]`) it does the following:
   - runs `--list`, then each test in its own process;
   - prints `Running Wine Test, Module: M, Test: T` and the test output via `DbgPrint` in 512-byte chunks → **COM1**;
   - kills a test after **170 s without output** ("must be lower than sysreg's 180 s").
   
   **Flags:**
   - `/r`: journal in `%APPDATA%\rosautotest\rosautotest.journal`, so the run resumes after a crash and reboot.
   - `/s`: shutdown at the end.
   - `/n`: no console output.
   - `/w`: submit to the testman web service at `https://<host>/testman/webservice/` with `rosautotest.ini [Login] SourceID/Password`.
   - `/t N`: repeat.
   - `/l`: list.

   At the end it prints **`SYSREG_CHECKPOINT:THIRDBOOT_COMPLETE`**. If rosautotest itself failed, it prints **`SYSREG_ROSAUTOTEST_FAILURE`**. Each winetest/apitest ends with `\n<test>: N tests executed (T marked as todo, F failures), S skipped.` (`sdk/include/wine/test.h`).
7. **sysreg2 (`github.com/reactos/sysreg2`, last push 2019-01-22)** controls a libvirt/KVM VM and reads the serial pty line by line. Its defaults in `sysreg.xml`:
   - 20 s idle timeout;
   - 3600 s global timeout;
   - `breakontimeout`;
   - 3 stages, all booting from cdrom;
   - success on `SYSREG_CHECKPOINT:THIRDBOOT_COMPLETE`;
   - `maxconts=5`;
   - `maxcachehits=50` (the same line repeated = endless loop).

   Logic in `console.c`:
   - on the first `kdb:>`, send `bt\r`;
   - on the next `kdb:>`, send `cont\r` (up to maxconts), else abort;
   - after `Break repea...` (an `RtlAssert` `DbgPrompt`), answer `o\r` ("break Once") instead;
   - on `--- Press q` (KDBG pager), send `\r`;
   - on `SYSREG_ROSAUTOTEST_FAILURE`, stop.

   Addresses in `bt` output are resolved with `raddr2line`. The VM in `reactos.xml` is IDE disk + CD, pcnet NIC, `virbr0`, 256 MB, 1 vCPU.

   **This design only works with KDBG builds** (non-MSVC Debug): MSVC builds use the KD protocol (§5).

### 3.2 What was verified here, end-to-end [run]

- **Input:** nightly `reactos-bootcd-0.4.17-dev-1268-gbba112f-x86-gcc-lin-dbg` (GCC 8.4 build, KDBG). Nightlies contain **no rostests** (0 `*_winetest.exe`/`*_apitest.exe`).
- **Remaster:** the ISO was rebuilt with the build's own `host-tools/bin/mkisofs` and the exact options from `boot/boot_images.cmake`:
  - `freeldr.ini`: `DefaultOS=Setup`, `TimeOut=0`;
  - `\i386\unattend.inf`: the file in §3.4;
  - a payload `run.cmd` (on the CD in run 1, on a FAT32 data disk in run 2).
- **QEMU:** `q35`, AHCI `ide-hd`/`ide-cd`, `-vga std`, e1000, TCG, `-smp 2` (the kernel reports "1 System Processor"), serial = unix socket.

**Sequence on COM1, with markers and timing.** Run 1 total: **236 s**, harness verdict `0`.

| Stage | Serial evidence |
|---|---|
| Setup kernel boots | `Command Line: DEBUG KDSERIAL DEBUGPORT=COM1 FIRSTCHANCE FASTDETECT NOGUIBOOT`. These are the `[SetupData] SetupDebugOptions` from `txtsetup.sif`, because the build is DBG. |
| 1st stage copy | `(base/setup/usetup/usetup.c:3241) CHECKPOINT:HALF_COPIED`. Harmless: `kdvbox.dll` missing → skipped. |
| Reboot | `isoboot.bin` saw a valid MBR on disk 0, waited 5 s and booted the HDD (no key pressed). |
| 2nd stage (GUI setup) | `Command Line: DEBUG DEBUGPORT=COM1 BAUDRATE=115200 SOS KDSERIAL` (= `ReactOS_KdSerial`, confirms §3.1-2); `syssetup` echoes each unattend key; **`OKNO:SETUP2:END`** from `[SetupParams] UserExecute`. |
| 3rd boot, autologon | `OKNO:RUNONCE:BEGIN drive=D: user=Administrator` (from `[GuiRunOnce]`). |
| App check | `dbgprint --process "ver"` → `Version 0.4.17-x86-dev ...`; **`OKNO:APP:notepad:PASS`**; **`OKNO:RUNONCE:END`**. |
| Screen | Desktop at 1024×768 (the `[Display]` section worked) with the cmd window. **A "New Hardware Wizard" button was in the taskbar**, which can steal focus during GUI tests. |

**Run 2** (data disk + `isobtrt.bin` + result write-back + power-off check): see §3.7.

### 3.3 Two ways to get a test ISO

1. **In the build (preferred for CI; this is what the fork does).** Build `bootcdregtest`. The fork's hook lives in `boot/bootdata/bootcdregtest/regtest.cmd`: it loops `for %%d in (D E F G H I)` and calls `\okno\run.cmd`, then `exit /b`. That is equivalent to my `[GuiRunOnce]` probe line in §3.4, which was verified.

   **Timing of the hook.** `regtest.cmd` first adds itself to `HKLM\...\Run` and exits; the hook therefore runs on the *second* invocation, from `Run`, in the same first logon. Because the `Run` value stays, **`run.cmd` runs again after every reboot** (a crash or an installer that reboots). It has no journal, so make it idempotent: write `D:\okno\done.<app>` and skip apps already done. Alternatively, delete the `Run` value at the start of the suite.

   There are also no-code hooks that are re-globbed at configure time, all in `modules/CMakeLists.txt`:
   - `modules/bootcd_extras/**` → ISO `\extras` (bootcd + regtest);
   - `modules/livecd_extras/**` → live image `\extras`;
   - `modules/3rdparty/**` → installed `%SystemRoot%\3rdParty`;
   - `modules/AHK_Tests/` → `add_subdirectory` if present;
   - `modules/optional/DroidSansFallback.ttf`.
2. **Remaster a prebuilt ISO (for nightlies or upstream comparison).** Extract with `7z x`, replace files, then rebuild:
   ```bash
   mkisofs -quiet -o out.iso -iso-level 4 -publisher "ReactOS Project" -preparer "ReactOS Project" \
     -volid ReactOS -volset ReactOS \
     -eltorito-platform x86 -eltorito-boot loader/isobtrt.bin -no-emul-boot -boot-load-size 4 \
     -eltorito-alt-boot -eltorito-platform efi -eltorito-boot loader/efisys.bin -no-emul-boot \
     -hide boot.catalog -duplicates-once -no-cache-inodes -graft-points TREE/
   ```
   `mkisofs` here is ReactOS's own host tool (`build/host-tools/bin/mkisofs`). Use `isoboot.bin` instead of `isobtrt.bin` for a 5 s HDD-boot wait. Upstream's `boot/remaster.sh` does the same thing interactively.

**Alternative with no ISO change:** setup also accepts an `unattend.inf` in the root of **any** removable drive, then any fixed drive, when the one on the CD does not enable unattended setup. It must contain both `UnattendSetupEnabled = yes` **and** `UnattendForDetached = yes` (`base/setup/lib/setuplib.c: GetUnattendInfPath / IsInfUnattendSetupEnabled`). However, the stock `bootcd.iso` boots `LiveImg_Debug` by default, so you still need `bootcdregtest.iso` or a freeldr.ini change.

### 3.4 Files (exactly what ran in §3.2, CRLF line endings)

**`\<arch>\unattend.inf`.** The keys are documented in `boot/bootdata/bootcd/unattend.inf`:
```ini
[Unattend]
Signature = "$ReactOS$"
UnattendSetupEnabled = yes
DestinationDiskNumber = 0
DestinationPartitionNumber = 1
InstallationDirectory=ReactOS
BootLoaderLocation=2
FullName="Okno"
ComputerName="OKNOTEST"
TimeZoneIndex=85
FormatPartition=1
AutoPartition = 1
FsType = 0
RappsDownload = no
LocaleID = 409

[SetupParams]
UserExecute="cmd.exe /C dbgprint OKNO:SETUP2:END"

[GuiRunOnce]
%SystemRoot%\system32\cmd.exe /c "for %i in (D E F G H I J K L M) do @if exist %i:\okno\run.cmd call %i:\okno\run.cmd %i:"

[Display]
BitsPerPel = 32
XResolution = 1024
YResolution = 768
```

**Other keys in the templates:**
- `AdminPassword`, `OrgName`, `DisableAutoDaylightTimeSet`.
- `InstallationType` (0 Server, 1 Workstation, 2 Server Core).
- `[GuiUnattended] DetachedProgram/Arguments`: runs early in the 2nd stage.
- `[Env]`: e.g. `WINETEST_PLATFORM=reactos`.
- `[Shell] DefaultThemesOff/CustomDefaultThemeFile`.

**Payload `\okno\run.cmd` on the data disk** (run 2). Tools present in ReactOS: `dbgprint` (`--process "<cmd>"` pipes command output to the debug log, `--winetest`), `timeout /t N /nobreak`, `tasklist` (only `/nh`, **no `/fi`**), `taskkill /f /im`, `find`, `shutdown -s -t 0`, `reg`.
```bat
@echo off
set R=%1\results
mkdir %R% 2>nul
dbgprint OKNO:RUNONCE:BEGIN drive=%1
ver > %R%\ver.txt
start "" notepad.exe
timeout /t 10 /nobreak >nul
tasklist /nh > %R%\tasklist.txt
find /i "notepad.exe" %R%\tasklist.txt >nul && (echo notepad PASS>> %R%\result.txt & dbgprint OKNO:APP:notepad:PASS) || (echo notepad FAIL>> %R%\result.txt & dbgprint OKNO:APP:notepad:FAIL)
taskkill /f /im notepad.exe >nul 2>&1
dbgprint OKNO:RUNONCE:END
shutdown -s -t 0
```

**Data disk.** A raw image with an MBR, one FAT32 partition (type 0x0C) at sector 2048, and `mkfs.fat -F 32 --offset 2048`. Copy files in and out with `mcopy -i data.img@@1M`. No root and no loop devices are needed. The earlier `apps.img` used by the fork's `vm.py` has the same layout.

### 3.5 Serial-log markers (COM1)

| Marker | Source | Meaning |
|---|---|---|
| `(ntoskrnl/kd64/kdinit.c:95) ReactOS <ver> (Build ...) (Commit <sha>)` | `KdpPrintBanner` | Kernel started; one per boot (count = boot number) |
| `Command Line: ...` | same | Which freeldr entry booted (setup vs installed) |
| `CHECKPOINT:HALF_COPIED` | `base/setup/usetup/usetup.c` | 1st-stage file copy in progress |
| `OKNO:SETUP2:END` | our `[SetupParams] UserExecute` | 2nd stage finished |
| `OKNO:RUNONCE:BEGIN` / `OKNO:APP:<name>:PASS/FAIL` / `OKNO:RUNONCE:END` | our `run.cmd` | Test session |
| `Running Wine Test, Module: M, Test: T` … `T: N tests executed (x marked as todo, F failures), S skipped.` | rosautotest + `wine/test.h` | Per-test results |
| `SYSREG_CHECKPOINT:THIRDBOOT_COMPLETE` / `SYSREG_ROSAUTOTEST_FAILURE` | rosautotest | Whole suite done / rosautotest broken |
| `kdb:> ` | `ntoskrnl/kdbg/kdb_cli.c` | **KDBG prompt: the system stopped** (crash, assert, breakpoint) |
| `Entered debugger on <first/last>-chance exception (Exception Code: 0x...)` / `Entered debugger on embedded INT3` | `ntoskrnl/kdbg/kdb.c` | Why it stopped |
| `*** Fatal System Error: 0x%08lx` | `ntoskrnl/ke/bug.c` (DbgPrint) | **Bugcheck (BSOD)** |
| `Break repeatedly, break Once, Ignore, terminate Process or terminate Thread (boipt)?` | `sdk/lib/rtl/assert.c` | `ASSERT` hit; answer `o` |
| `--- Press q to abort, any other key to continue ---` | KDBG pager | Send `\r` |

The BSOD screen text `*** STOP: 0x...` is drawn on screen only (`ke/bug.c` via Inbv), not on serial.

### 3.6 Harness: the fork's `tools/qemu/apptest.py`, checked against this research

**Current design (fork, uncommitted):**
- `apptest.py` builds a FAT32 test disk (MBR, partition at 1 MiB, `mkfs.vfat --offset 2048`, `mcopy -i img@@1M`) holding `\okno\run.cmd` and the apps from `apps.tsv`.
- It starts `vm.py start --install` with options `q35`, AHCI, `-serial file:`, and `-boot order=c,once=d` without `bootindex` on the CD.
- It polls the serial file every 2 s for `OKNO:BEGIN`, `OKNO:SHOT:<app>` (→ screendump), `OKNO:PASS|FAIL:<app>` and `OKNO:END`.
- Its crash regex is `\*\*\* Fatal System Error|KeBugCheckEx|kdb:>|Entered debugger|\*\*\* STOP`. It stops the VM through the monitor and writes `results.json` / `results.md`.

**Confirmed by this research [run/code]:**
- **Disk layout works.** The FAT32 partition test disk is mounted as `D:` (run 2).
- **Autologon is Administrator** (`hivesft.inf` `AutoAdminLogon=1` + `SetAutoAdminLogon`).
- **Stopping on the end marker is right.** The guest's `shutdown -s -t 0` did **not** power QEMU off within 180 s (run 2).
- **`tasklist | find` and `timeout /t N /nobreak` work.** `tasklist` has no `/fi` filter (`base/applications/cmdutils/tasklist`).

**Corrections and improvements:**

1. **Boot order: `-boot order=c,once=d` works, but it is not needed.** `bootcdregtest.iso` boots with `isobtrt.bin`, which jumps straight to the HDD once disk 0 has a valid MBR, and boots the CD otherwise (`boot/freeldr/bootsect/isoboot.S` with `ROS_REGTEST`; run 2 used CD-first and went through all three boots). The plain `bootcd.iso` (`isoboot.bin`) does the same after a 5 s "Press any key" wait (run 1).
   - Keeping `bootindex=0` on the CD makes a reinstall onto an empty disk automatic.
   - On SeaBIOS, `-boot order=` is ignored once any device has `bootindex`, so keep the two mutually exclusive, as the patch already does.
2. **KDBG stops are not always crashes, and with `-serial file:` they freeze the VM.** Both the setup kernel and the installed system run KDBG with **`/KDSERIAL`**:
   - setup uses `txtsetup.sif` `SetupDebugOptions = /DEBUG /KDSERIAL /DEBUGPORT=COM1 /FIRSTCHANCE`;
   - the installed system uses `ReactOS_KdSerial`, which is the default entry after an unattended DBG non-WinKD install (`base/setup/lib/bootsup.c`);
   - so the prompt `kdb:>` waits for input **on COM1**.

   With a write-only `file:` serial, any `ASSERT` (`Break repeatedly, break Once...`), any first-chance kernel exception under `/FIRSTCHANCE` (setup only), or any `DbgBreakPoint` hangs the VM forever. You also get no backtrace.

   **Use a bidirectional serial** (`-chardev socket,id=s0,path=...,server=on,wait=on -serial chardev:s0`; `wait=on` holds the VM until the harness connects, so no early bytes are lost) and **answer like sysreg2** (`console.c`):
   - first `kdb:>` → `bt\r`;
   - next `kdb:>` → `cont\r`, up to 5 times;
   - `Break repea...` → answer `o\r` at the next prompt;
   - `--- Press q` → `\r`.

   Classify the run as a crash only on `*** Fatal System Error`, or when conts are exhausted. This keeps the backtrace in the log, and benign breaks no longer fail the run.

   A working prototype of this socket loop ran here: it exchanged nothing in two clean runs, so the `bt`/`cont` path is **code-derived from sysreg2, not exercised**. The prototype is `/tmp/claude-0/-home-user-okno/2af4bb7a-4411-572a-bbe7-dcffd3c4fc82/scratchpad/qt/scripts/qrun.py`; port its loop into `vm.py`/`apptest.py` rather than adding a second tool.
3. **Crash regex hygiene.**
   - `\*\*\* STOP` never reaches serial: it is drawn on screen by Inbv (`ntoskrnl/ke/bug.c`). Drop it, or keep it as harmless.
   - `KeBugCheckEx` also appears inside ordinary `bt` frames.
   - The reliable bugcheck marker is `*** Fatal System Error: 0x........` (DbgPrint in `KeBugCheckWithTf`). It is followed by `kdb:>` on KDBG builds.
   - Add `SYSREG_ROSAUTOTEST_FAILURE` if rosautotest is used.
4. **Idle timeout.** Besides the global timeout, fail when nothing has arrived on serial for N minutes (sysreg2 used 20 s idle with KVM). Take a screenshot then too. A GUI deadlock prints nothing.
5. **Repeated-line loop detection.** Abort after the same line appears 50 times in a row (sysreg2 `maxcachehits`).
6. **Backtrace symbolisation.**
   - i386 Debug builds print `file:line` in `bt` thanks to `.rossym`.
   - amd64 builds (`NO_ROSSYM`) print raw addresses. Post-process them with `build/host-tools/bin/raddr2line` or `log2lines`, so upload those tools and the build's binaries with the ISO.
7. **Result channel.** Serial markers are primary. The FAT32 test disk is a reliable second channel for bulk output (logs, `tasklist`, app stderr), because files written by the guest survived a hard stop in run 2. Add `timeout /t 5` after the last write, before `OKNO:END`: there is no `sync`.
8. **Run on every boot.** See §3.3: the `Run` key re-runs `run.cmd` after reboots. Mark finished apps on the test disk.
9. **Focus.** On first logon a **"New Hardware Wizard"** was open (taskbar, run 1). Screenshots may show it, and GUI-automation tests need it closed. Wait for it, or disable it.
10. **Display.** `bootcdregtest/unattend.inf` sets `[Display] 800x600x16`. For screenshots, `1024x768x32` works (run 1).

### 3.7 Run 2 result [run]

Run 2 used the same nightly with these changes:
- BIOS El Torito image = `loader/isobtrt.bin`;
- no payload on the CD;
- payload on a 128 MB data disk (`-device ide-hd,bus=ide.1`, raw, MBR + FAT32).

Result: verdict OK in **387 s** (TCG). The serial log has `OKNO:SETUP2:END` → `OKNO:RUNONCE:BEGIN drive=D:` → `OKNO:APP:notepad:PASS` → `OKNO:RUNONCE:END`.

**Findings:**
- **The data disk became `D:`.** The CD comes after it.
- **`isobtrt.bin` boots the HDD right away** after stage 1, with CD as the first boot device.
- **Guest-written results survived a hard stop.** `D:\results\result.txt` (`notepad PASS`), `ver.txt` and `tasklist.txt` were readable on the host with `mtype`/`mcopy -i data.img@@1M` after QEMU was killed. They had been written about 1 min earlier.
- **No ACPI power-off.** `shutdown -s -t 0` did not power off QEMU within 180 s.

### 3.8 Gotchas

- **Setup reads `\<arch>\unattend.inf`, not `\reactos\unattend.inf`.** The latter belongs to the live image. In the live image, `UnattendSetupEnabled=yes` means "start the GUI installer immediately" (`base/system/userinit/livecd.c`).
- **The bootcd boots Live by default** (`DefaultOS=LiveImg_Debug`, 10 s). Automation needs `bootcdregtest` or a changed freeldr.ini.
- **WinKD (MSVC) builds are bad for log-driven tests.** Without a KD client on COM1:
  - every `DbgPrint` is sent as a KD packet and **retried 20 times** (`KdpDefaultRetries = 20`, `ntoskrnl/kd64/kdinit.c`; `drivers/base/kdcom/kddll.c`). The x64 MSVC nightly log here had the banner line ×40 for 2 boots;
  - a crash waits for a debugger instead of printing a backtrace.

  Use KDBG builds for CI.
- **Machine type.** x64 nightly + i440FX IDE → STOP 0x1E in `pciidex.sys`; q35/AHCI works (fork `CLAUDE.md`, `docs/plan.md`). With q35, `PCI\CC_0106` maps to `pciide` in `txtsetup.sif` (the `storahci` mapping is commented out).
- **Single processor.** `-smp 2` still gives "1 System Processor": the default kernel is UP.
- **Setup kernel debug options.** In DBG builds the plain `Setup` entry already uses `/DEBUG /KDSERIAL /DEBUGPORT=COM1 /FIRSTCHANCE` (`txtsetup.sif [SetupData] SetupDebugOptions`). `/FIRSTCHANCE` breaks into KDBG on first-chance kernel exceptions, so the harness must answer `cont`.
- **New Hardware Wizard.** It appeared on first logon (taskbar). For GUI app tests, dismiss or disable it, or wait for it.
- **`rosautotest /r`** adds a `Run` key, so after a crash it runs again on the next boot. Do not pass `-no-reboot` to QEMU in suite runs.
- **No rostests in upstream nightlies.** Build them with `-DENABLE_ROSTESTS=1`.
- **Payload files need CRLF.** `cmd`'s `for %i` works inside a RunOnce value because `ExpandEnvironmentStringsW` leaves unknown `%...%` alone [run].
- **Live-CD autorun (not verified).** Add a `Run` value to `boot/bootdata/livecd.inf`, which is merged only into the live hives (`create_registry_hives()`), or `add_cd_file(... DESTINATION "ProgramData/Microsoft/Windows/Start Menu/Programs/Startup" FOR livecd)`. The install flow is preferred because `C:` is writable.

---

## 4. SDK headers state [code]

| Dir | Files | Content and level |
|---|---|---|
| `sdk/include/psdk` | 772 (208 `.idl`) | Win32 user-mode SDK. About 455 files carry Wine's LGPL notice and about 12 the mingw-w64 public-domain notice; the rest are ReactOS-original. `sdkddkver.h` defines `_WIN32_WINNT_WIN10 0x0A00` and **NTDDI up to `NTDDI_WIN11_SE` (0x0A000011, 25H2)**. IDLs exist for d3d11–d3d12, dxgi1_6, d2d1_3, dwrite_3, uiautomation; headers are generated by widl at build time. **Missing:** `dcomp.h`, `webservices.h`, `usbspec.h`. |
| `sdk/include/xdk` | 55 | Templates that generate `wdm.h`, `ntddk.h`, `ntifs.h`, `ntdef.h` and `winnt.h` at build time (`xdk` target). They contain `NTDDI_WIN10/11` blocks. |
| `sdk/include/ddk` | 128 | WDK-style kernel headers: `ndis.h` (6228 lines, `NDIS_SUPPORT_NDIS6/61/620`), `storport.h`, **`d3dkmddi.h` + `dispmprt.h`** (ReactOS-written, MIT, 2024, WDDM DDI), `hidport.h`, `ata.h`, `scsi.h`, `fltkernel.h`, `classpnp.h`, `acpiioct.h`. `psdk/d3dukmdt.h` defines `DXGKDDI_INTERFACE_VERSION` up to **WDDM 3.1**, but the build pins `DXGKDDI_INTERFACE_VERSION=0x1052` (Vista) and `D3D_UMD_INTERFACE_VERSION=0x000C` globally. **Missing:** `nvme.h`, `dxgkrnl`, `fwpsk.h`/WFP, `netadaptercx.h`, `d3dumddi.h`, `wdfldr.h`. |
| `sdk/include/ucx/1.6` | 9 | **UCX 1.6** headers (`ucxclass.h`, `ucxcontroller.h`, `ucxendpoint.h`, `ucxroothub.h`...). |
| `sdk/include/wdf/kmdf/1.17` | 42 | KMDF 1.17 (used by `set_module_type(... kmdfdriver)`, `FxDriverEntry`). |
| `sdk/include/ndk` | 73 | Native API (undocumented NT) headers. |
| `sdk/include/crt` | 76 | msvcrt-era CRT headers, mostly mingw-w64 public domain (73 files carry the notice). |
| `sdk/include/ucrt` | 66 | Microsoft UCRT headers ("Copyright (c) Microsoft"). They come from the MIT-licensed `Microsoft.Windows.SDK.CRTSource` 10.0.22621.3 import that also provides `sdk/lib/ucrt` [web]. Used only by ucrt code (`sdk/lib/ucrt/CMakeLists.txt` swaps the include dir). |
| `sdk/include/vcruntime` | 47 | ReactOS (MIT) + mingw-w64 bits: `vcruntime.h`, intrinsics (`xmmintrin.h` fixed in the fork for clang 18). |
| `sdk/include/reactos`, `wine`, `dxsdk`, `winrt`, `host`, `asm`, `c++` | | Internal headers, Wine compat, DirectX 9-era SDK, a minimal WinRT stub (2 files), host-tool headers, GAS/MASM macro layer (`asm.inc`), C++ STL. |

**Header options for 2026:**
- **Keep the ReactOS SDK as the base.** Kernel, NDK and generated `xdk` headers are ReactOS-specific and cannot be replaced wholesale.
- **mingw-w64 v14.0.0 (2026-03-27):**
  - `mingw-w64-headers/include/*`, `crt/*` and many `ddk/*` (`ndis*.h`, `ntddk.h`, `ntifs.h`, `storport.h`, `wdm*.h`...) are **public domain**; the CRT runtime is ZPL-2.1 (Debian `copyright` for mingw-w64-common) [run]. Both are GPL-compatible.
  - Changelog v14: Wine 11.5 sync, C23 additions, arm64ec [web].
  - **Use it to fill missing user-mode API declarations** (Win8–11 functions) one header at a time.
  - Its `ddk/` is older than ReactOS's for WDDM, UCX and KMDF, so don't take it for those.
- **Wine headers (LGPL-2.1+).** These are already the majority of psdk and suit Wine-synced DLLs. Sync them through `sdk/tools/winesync` (media/doc/WINESYNC.txt: widl synced to Wine-10.0, d3d* to wine-10.1-dev).
- **Never** copy the Windows SDK/WDK headers (Microsoft license, and the clean-room rule in `CLAUDE.md`).
- **For StorPort, NDIS 6.x and WDDM,** extend ReactOS's own headers from Microsoft Learn docs. WDDM is already MIT here.

---

## 5. Debugging

**KD transports available [code]:**

| Transport | Where | Notes |
|---|---|---|
| `kdcom.dll` | `drivers/base/kdcom` (when `_WINKD_`) | KD protocol over serial (WinDbg). |
| `kdgdb.dll` | i386/amd64, when `_WINKD_` | GDB remote protocol over serial, with `qXfer:libraries:read` so GDB auto-loads module symbols. `-DGDB=TRUE` renames it to `kdcom.dll` and kdcom to `kdser.dll`. |
| `kdvbox.dll` | `drivers/base/kdvm` | **VirtualBox-only** VM channel ("kdVMvA" magic). **Not Hyper-V KDVM, and nothing for QEMU.** |
| `kdcom.dll` (built from `kdrosdbg`) | when **not** `_WINKD_` | KDBG builds. |
| `kdstub.dll` | `drivers/base/kdstub` | Stubs. |

- **There is no KDNET transport.** Only type headers exist ("[SDK] Implement type header for KDNET...", "[KDSTUB] Implement driver for KDNET extension stubs", 2026-06-15) [hist].
- **How freeldr picks the DLL:** `kd<DEBUGPORT>.dll`, e.g. `/DEBUGPORT=GDB` → `kdgdb.dll`, `/DEBUGPORT=VBOX` → `kdvbox.dll`, `COMn` → `kdcom.dll`; it falls back to kdcom (`boot/freeldr/freeldr/ntldr/winldr.c`).
- **KDBG builds (non-MSVC Debug):**
  - `/DEBUGPORT=COM1` prints plain text;
  - `/KDSERIAL` gives the interactive `kdb:>` on serial;
  - `/DEBUGPORT=SCREEN` and `FILE:\Device\HarddiskX\PartitionY\debug.log` are also supported (`ntoskrnl/kd/kdio.c`).

**WinDbg:**
- Needs MSVC (or clang-cl) builds: `_WINKD_` on, PDBs in `build/msvc_pdb`.
- Connect to QEMU's COM1 as a pipe or TCP on a Windows host: `-serial tcp::5555,server` + WinDbg `com:port=...` through a pipe bridge.
- GCC/clang builds have DWARF only, so WinDbg shows exports at best.

**GDB:**
- **Option A, inside-guest stub:** build with `-DGDB=TRUE -D_WINKD_=TRUE -DKDBG=FALSE -DSEPARATE_DBG=TRUE`. This is exactly the `.gitpod.yml` recipe. Connect `i686-w64-mingw32-gdb` (`gdb-mingw-w64` package) to the serial TCP port and `set sysroot build/symbols` (`.theia/launch.json` uses QEMU `-chardev socket,port=9091,...` on serial 1).
- **Option B, hypervisor stub:** QEMU `-s -S` (gdbserver on `tcp::1234`) works with any build, but module bases must be added by hand (`add-symbol-file`). The kernel's preferred base is `0x00400000` (`set_module_type ... kernel`), relocated by freeldr; read the real bases from the `bt`/module list in the serial log.

**Symbols:**
- i386 Debug GCC/clang builds embed `.rossym` (via `rsym`), so KDBG backtraces show `file:line` in the guest.
- amd64 and Release builds are `NO_ROSSYM`. For those, resolve `bt` addresses on the host with `build/host-tools/bin/raddr2line <module> <addr>` or `log2lines` (`sdk/tools/log2lines`), which is what sysreg2 did.
- MSVC: `build/msvc_pdb/*.pdb` (uploaded as a CI artifact upstream).

---

## 6. Remember-once: layout and how-tos

### 6.1 Layout (top two levels) [code]

| Path | Purpose |
|---|---|
| `base/applications` | User apps (calc, notepad, regedit, taskmgr, rapps, mspaint...), `cmdutils` (`reg`, `tasklist`, `timeout`, `dbgprint`, `where`, `xcopy`...) |
| `base/ctf` | Text Services Framework (msctf fork, synced to Wine-10.12) |
| `base/services` | Services: svchost, rpcss, umpnpmgr (PnP installs), eventlog, dhcpcsvc, dnsrslvr, audiosrv, wlansvc, schedsvc, wuauserv... |
| `base/setup` | `usetup` (text setup), `reactos` (GUI installer), `lib` (setuplib: partitioning, unattend, bootsup = freeldr.ini writer), `welcome` |
| `base/shell` | `explorer`, `cmd`, `rshell`, `progman`, `filebrowser` |
| `base/system` | `smss`, `winlogon`, `services`, `lsass`, `userinit`, `logonui`, `msiexec`, `rundll32`, `regsvr32`, `runonce`, `autochk`, `chkdsk`, `format`, `diskpart`... |
| `boot/freeldr` | FreeLoader (BIOS + UEFI), boot sectors (`isoboot`/`isobtrt`/`isombr`/fat/ntfs/btrfs...), NT loader `ntldr/` |
| `boot/bootdata` | Registry `.inf` hives, `txtsetup.sif`, `unattend.inf`s, freeldr.ini templates, `packages/reactos.dff.in` (cab), `regtest.cmd` |
| `boot/rtl`, `boot/armllb`, `boot/bcd`, `boot/bgfx` | Boot-time RTL; ARM low-level boot; empty placeholders |
| `dll/ntdll`, `dll/win32` (280 dirs) | Native API DLL; Win32 DLLs (kernel32 + `kernel32_vista`, advapi32, shell32, ucrtbase, ws2_32...), mostly Wine-synced |
| `dll/directx`, `dll/opengl`, `dll/cpl`, `dll/shellext`, `dll/keyboard`, `dll/nls`, `dll/appcompat`, `dll/np`, `dll/3rdparty`, `dll/branding` | DirectX (Wine d3d/dxgi/d3d12 + ReactX), OpenGL/Mesa, control panels, shell extensions, keyboard layouts, NLS, apphelp/shims, network providers, 3rd-party libs, branding |
| `drivers/*` | `acpi`, `base` (beep, bootvid, condrv, kd*, null), `battery`, `bluetooth`, `bus` (acpi/acpica/uACPI, pci, pcix, isapnp, pcmcia), `crypto`, `filesystems` (fastfat, ntfs, btrfs, ext2, cdfs, udfs, npfs, msfs, mup, nfs), `filters` (fltmgr), `hid`, `input`, `ksfilter`, `multimedia`, `network` (`dd/` e1000, rtl8139, pcnet, netkvm, ne2000, nvnet, dc21x4; ndis; tcpip; afd), `parallel`, `processor`, `sac`, `serial`, `setup`, `storage` (`class/` disk, cdrom, classpnp; `ide/` atapi, pciide, pciidex, uniata; `port/` scsiport, storport, storahci, buslogic), `usb`, `wdm/audio`, `wmi` |
| `hal/halx86`, `hal/halarm` | HALs (`hal.spec`) |
| `media/*` | `inf/` (device INFs, `syssetup.inf`), `fonts`, `themes`, `nls`, `sdb` (shim DB), `doc/` (WINESYNC.txt, 3rd Party Files.txt) |
| `modules/rostests`, `modules/rosapps`, `modules/wallpapers` | Tests (`apitests`, `winetests`, `kmtests`, `rosautotest`, `unittests`, `win32`, `drivers`, `testdata`); extra apps (`ENABLE_ROSAPPS`); wallpapers. Optional hook dirs: `bootcd_extras`, `livecd_extras`, `3rdparty`, `AHK_Tests`, `optional`. |
| `ntoskrnl/*` | Kernel: `ke`, `mm`, `io`, `ob`, `ps`, `se`, `ex`, `cm` (`config/`), `cc`, `fsrtl`, `po`, `kd`/`kd64`/`kdbg`, `kse`, `vf`, `wmi`, `inbv`, `lpc`, `vdm`, `rtl`; `ntoskrnl.spec`, `ntos.cmake` |
| `sdk/cmake` | Build logic: `CMakeMacros.cmake` (add_cd_file, set_module_type, add_importlibs, hives, ISO lists), `gcc.cmake`/`msvc.cmake` (toolchain specifics, spec2def, import libs), `config.cmake` (options), `baseaddress*.cmake`, `widl-support.cmake`, `host-tools.cmake` |
| `sdk/include/*` | See §4 |
| `sdk/lib/*` | Static libs: `rtl`, `crt`, `ucrt`, `vcruntime`, `pseh`, `cmlib` (hives), `inflib`, `drivers/*` (wdf, virtio, usbdex, ucxstub, ntoskrnl_vista...), `3rdparty` (zlib, freetype, libpng, mbedtls, symcrypt...), `apisets`, `llvm-compat`, `gcc-compat` |
| `sdk/tools/*` | Host tools: `spec2def`, `widl`, `mkhive`, `cabman`, `mkisofs`, `isohybrid`, `fatten`, `rsym`, `log2lines`, `raddr2line` (built in host-tools), `gcc_plugin_seh`, `winesync`, `gen_baseaddress.py`, `utf16le`, `asmpp`, `geninc` |
| `subsystems/csr`, `subsystems/win`, `subsystems/mvdm` | CSR server; basesrv; NTVDM (16-bit DOS / WOW16) |
| `win32ss/*` | `gdi` (gdi32 + `ntgdi`, eng, dib), `user` (user32, `ntuser`, winsrv, imm32), `drivers` (`displays`, `miniport/` vga, vbe, **bochs**, vmx_svga, `videoprt`, `font`), `printing`, `reactx`, `win32u`; `win32k.spec` |

### 6.2 Add a module [code]

**DLL** (`dll/win32/<name>/CMakeLists.txt`, then `add_subdirectory(<name>)` in `dll/win32/CMakeLists.txt`):
```cmake
spec2def(foo.dll foo.spec ADD_IMPORTLIB)          # -> foo.def, foo_stubs.c, import lib "libfoo"
list(APPEND SOURCE foo.c ${CMAKE_CURRENT_BINARY_DIR}/foo.def)
add_library(foo MODULE ${SOURCE} foo.rc)
set_module_type(foo win32dll UNICODE)             # ENTRYPOINT defaults to DllMainCRTStartup 12
target_link_libraries(foo wine uuid)              # static libs
add_importlibs(foo advapi32 msvcrt kernel32 ntdll)   # DLL imports (lib<name>); add_delay_importlibs for delay-load
add_cd_file(TARGET foo DESTINATION reactos/system32 FOR all)
```

- **`.spec` lines:**
  - format `@ stdcall [-stub] [-version=0x600+] [-arch=...] Name(args) [ForwardTo]`;
  - `-dbg` exports only for DBG builds;
  - `spec2def(... VERSION 600)` overrides the global level for one DLL.
- **Base address:** add `set(baseaddress_foo 0x...)` to `sdk/cmake/baseaddress.cmake` (x86), `baseaddress64.cmake` (x64) and `baseaddress_msvc.cmake`. These files are generated by `sdk/tools/gen_baseaddress.py`. If the entry is missing, the build only prints `foo has no base address`.
- **Self-registration (regsvr32 at install):** add `11,,foo.dll,1` under `[OleControlDlls]` in `media/inf/syssetup.inf`.
- **Wine code:** add `add_definitions(-D__WINESRC__)` or `set_wine_module(foo)`.

**Driver:**
```cmake
add_library(foo MODULE foo.c foo.rc)
set_module_type(foo kernelmodedriver)   # or wdmdriver (/DRIVER:WDM), kmdfdriver (KMDF 1.17, links wdfldr), kerneldll
add_importlibs(foo ntoskrnl hal)
add_cd_file(TARGET foo DESTINATION reactos/system32/drivers FOR all)
add_driver_inf(foo foo.inf)             # optional: INF -> reactos/inf (UTF-16 converted)
add_registry_inf(foo_reg.inf)           # optional: merged into hives (see 6.3)
```

- **Boot-start / PnP drivers:**
  - add the service key to `boot/bootdata/hivesys.inf` (e.g. `Services\Null`: `ImagePath`, `Start`, `Type`, `Group`);
  - for setup, add entries to `boot/bootdata/txtsetup.sif` (`[SourceDisksFiles]`, `[HardwareIdsDatabase]`, `[SCSI.Load]`/`[BusExtenders.Load]`);
  - PnP devices also need an INF in `media/inf`.
- **Signing:** `sign_driver_if_needed()` signs only on MSVC with `C:/ReactOSCerts/ReactOSDevCert.cer`.

**App:**
```cmake
add_executable(foo foo.c foo.rc)
set_module_type(foo win32gui UNICODE)   # win32cui, nativecui ...
add_importlibs(foo user32 gdi32 comctl32 msvcrt kernel32)
add_cd_file(TARGET foo DESTINATION reactos/system32 FOR all)
```

**Test:**
- Put a winetest/apitest exe under `modules/rostests/...`.
- Call `add_rostests_file(TARGET foo_apitest)`, which puts it in `reactos/bin`. rosautotest finds it by the `*test.exe` pattern.
- `start_module_group(rostests)` / `end_module_group()` give a `rostests` target.

**Module types** (`VALID_MODULE_TYPES`): kernel, kerneldll, kernelmodedriver, kmdfdriver, wdmdriver, nativecui, nativedll, win32cui, win32gui, win32dll, win32ocx, cpl, module.

**`add_cd_file` semantics:**
- `FOR bootcd|livecd|regtest|all`.
- Without `NO_CAB`, a bootcd file goes into `reactos.cab` and is installed by setup. `DESTINATION` must then be one of the numbered dirs in `dir_to_num` (`CMakeMacros.cmake`), which must stay in sync with `boot/bootdata/packages/reactos.dff.in`.
- `NO_CAB` puts the file on the CD, with `reactos/` rewritten to `<arch>/`.
- For livecd, any path works.

### 6.3 Registry hives [code]

- **Registry inf list.** `add_registry_inf()` collects the `.inf` files: `boot/bootdata/hivecls.inf`, `hivedef.inf`, `hivesft.inf`, `hivesys.inf`, `hivebcd.inf`, plus module ones such as `vga_reg.inf`, `bochsmp_reg.inf`, `afd_reg.inf`.
- **`create_registry_hives()`** converts them to UTF-16 and concatenates them into `build/boot/bootdata/registry.inf`, then builds with `native-mkhive`:
  - `SETUPREG.HIV` from `registry.inf` + `setupreg.inf`, for the bootcd setup;
  - live hives `system/software/default/sam/security` from `registry.inf` + `livecd.inf` + `caroots.inf` + `hiveinst.inf`, at `reactos/system32/config` for livecd;
  - `BCD` from `hivebcd.inf` (EFI).
- **Format:** INF `AddReg`, i.e. `HKLM,"Key","Value",flags,data`. Flags: `0x00000000` SZ, `0x00020000` EXPAND_SZ, `0x00010001` DWORD, `0x00010000` MULTI_SZ, `0x00000012` key only (NOCLOBBER).
- **Installed-system hives** are built by setup from `registry.inf` (`[HiveInfs.Install]` in `txtsetup.sif`).

### 6.4 Gotchas (build)

- **`ENABLE_CCACHE=1` turns PCH off.** GCC has PCH off by default anyway (CORE-17108).
- **`-Werror` on non-clang i386 Debug.** GCC i386 Debug builds use `-Werror`; clang builds don't (`gcc.cmake`).
- **Thin archives.** `ar crT` thin archives broke with binutils 2.40+ (bug #31614). Import libs are now IMPORTED libraries made by dlltool, which is why the fork sets `CMAKE_DLLTOOL` to the mingw dlltool.
- **CMake warning.** The top-level `CMakeLists.txt` warns when CMake is not RosBE's "ReactOS" CMake. This is harmless with stock CMake 3.28 [run, fork builds].
- **`version.h` changes daily.** It is regenerated on every configure (build date + `git describe`); about 20 files include `buildno.h`/`version.h`. Use `-DNO_REACTOS_BUILDNO=ON` for reproducible ISOs.
- **Shallow checkout.** `actions/checkout` is shallow, so `git describe` falls back to the abbreviated hash (`--always`).
- **Clang i386 Release cannot catch SEH** in code compiled without PSEH3 macros. i386 always uses PSEH3: native `__try` fails on `i686-w64-mingw32` [run].
- **Version reported to programs:** NT 5.2 (`ReactOS [Version 5.2.3790] Service Pack 2`) and `/VERSION:5.01` PE headers (`msvc.cmake`), independent of `DLL_EXPORT_VERSION` [run, code].

---

## Sources

**Code and history:**
- ReactOS tree (paths above).
- `git log` of the full upstream clone.
- `github.com/reactos/RosBE` (cloned: `RosBE-Windows/Root/ChangeLog.txt`, `README.pdf`, `RosBE.cmd`).
- `github.com/reactos/sysreg2` (cloned).
- The CI gist `build_rosbe_ci.sh` (downloaded).

**Web:**
- [ReactOS getbuilds](https://reactos.org/getbuilds/): nightly variants (x86 GCC dbg/rel, x86 MSVC dbg, x64 MSVC dbg); also iso.reactos.org/bootcd/ listing.
- [ReactOS CI runs](https://github.com/reactos/reactos/actions/workflows/build.yml) and [run 40239066678 usage](https://github.com/reactos/reactos/actions/runs/40239066678/usage): per-job durations.
- [RosBE-Windows Test Builds (RosBE-2.3.0.exe, 2026-01-23)](https://sourceforge.net/projects/reactos/files/RosBE-Windows/Test%20Builds/) and [RosBE-Unix releases (2.2.1, 2020-05-31)](https://sourceforge.net/projects/reactos/files/RosBE-Unix/).
- [LLVM 22.1.0 released](https://discourse.llvm.org/t/llvm-22-1-0-released/89950) and [LLVM 23.1.0 release notes](https://releases.llvm.org/23.1.0/docs/ReleaseNotes.html).
- [mingw-w64 changelog (v14.0.0, 2026-03-27)](https://www.mingw-w64.org/changelog/) and [Mingw-w64 (Wikipedia: v13.0.0, 2025-06-04)](https://en.wikipedia.org/wiki/Mingw-w64).
- [runner-images win25-vs2026 release notes](https://newreleases.io/project/github/actions/runner-images/release/win25-vs2026%2F20260803.193).
- [GitHub changelog: hardware-accelerated Android virtualization / KVM udev rule](https://github.blog/changelog/2024-04-02-github-actions-hardware-accelerated-android-virtualization-now-available/).
- [UCRT CRTSource MIT import (mirror listing)](https://tangled.org/huwcampbell.com/reactos/tree/listview/sdk/lib/ucrt/internal) and [huangqinjin/ucrt (MIT)](https://awesome.ecosyste.ms/projects/github.com%2Fhuangqinjin%2Fucrt).
- [ReactOS newsletter 101 (RosBE 2.3 amd64 plans)](https://reactos.org/blogs/newsletter-101/).
