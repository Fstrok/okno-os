# Как устроена Windows 10/11 (NT 10) — опорная модель Okno OS

Цель Okno OS — совместимость с Windows 10 22H2 (сборка 19045) как базовым уровнем, с добавками Windows 11 там,
где их требуют программы и драйверы. Этот документ — карта «что есть в Windows и через что программы и драйверы
с ней разговаривают». Состояние каждой части в ReactOS и решения — в `reactos-*.md` и `decisions.md`.

Источники: только публичная документация Microsoft (Learn/MSDN, WDK, Windows SDK) и открытые книги/статьи.
Утёкшие исходники Windows не используем никогда (см. `CLAUDE.md`).

## 1. Слои

```
 Прошивка UEFI (Secure Boot: db/dbx, TPM — измеренная загрузка)
   └─ bootmgfw.efi (Boot Manager) — читает хранилище BCD, меню, восстановление
       └─ winload.efi — грузит ntoskrnl.exe, hal.dll, куст SYSTEM, драйверы Start=0 (boot-start), ELAM,
          строит LOADER_PARAMETER_BLOCK, ExitBootServices() → KiSystemStartup
 ─────────────────────────── режим ядра ───────────────────────────
 ntoskrnl.exe = Kernel (Ke) + Executive:
   Ob объекты · Mm память · Ps процессы/потоки · Io ввод-вывод · Pnp/Pp · Po питание · Se безопасность
   Cm реестр · Cc кэш · Alpc · Ex (пулы, ресурсы, push lock, рабочие потоки, колбэки) · FsRtl
   Etw/Wmi · Kd отладчик · Vf Driver Verifier · Ksr/Kse (shim) · Ci (ci.dll — подписи кода)
 hal.dll — один HAL на x64 с Windows 8 (ACPI, APIC/x2APIC, таймеры HPET/TSC) + HAL extensions
 Модели драйверов: WDM · KMDF/UMDF (Wdf01000.sys, WUDFHost) · StorPort · NDIS 6.x (+NetAdapterCx/WiFiCx в 11)
   · KS/PortCls/AVStream (+ACX в 11) · WDDM (dxgkrnl.sys, dxgmms2.sys) · UCX (USB 3) · HID class · FltMgr (минифильтры)
 win32k: win32kbase.sys + win32kfull.sys (+ win32k.sys) — окна, сообщения, GDI, ввод
 ─────────────────────────── режим пользователя ───────────────────────────
 smss.exe → csrss.exe (сервер подсистемы Win32 на сессию)
          → wininit.exe (сессия 0) → services.exe (SCM) → svchost.exe (группы служб), lsass.exe (LSA, SAM, Kerberos/NTLM)
          → winlogon.exe (сессии 1+) → LogonUI, userinit.exe → explorer.exe
 dwm.exe — композитор, всегда включён с Windows 8; рисует всё через Direct3D
 DLL: ntdll → kernelbase (+ kernel32-переходники) · API-sets · user32/gdi32 → win32u (вызовы win32k)
      combase (COM + WinRT) · rpcrt4 · sechost · advapi32 · ucrtbase (Universal CRT — часть ОС с Windows 10)
      CNG: bcrypt/bcryptprimitives/ncrypt · crypt32 · schannel (TLS 1.3 с Windows 11/Server 2022)
      ws2_32/mswsock · winhttp/wininet · dwrite/d2d1/d3d11/d3d12/dxgi/dcomp · windowscodecs (WIC)
      Media Foundation · WASAPI (audioses → audiosrv → audiodg) · shell32/shcore · WebView2 (Chromium, отдельный runtime)
 WoW64 (x86 на x64): wow64.dll + wow64win.dll + wow64cpu.dll, отдельный SysWOW64
```

## 2. Загрузка — по шагам

1. UEFI проверяет подпись `bootmgfw.efi` (ключ Microsoft в `db`). Без подписи Microsoft — только с выключенным
   Secure Boot или через своё доверие (MOK/свой ключ в `db`).
2. Boot Manager читает BCD (это куст реестра на ESP), выбирает запись → `winload.efi`.
3. winload: проверяет подписи, читает куст SYSTEM, решает, какие драйверы boot-start (по `Start=0` и группам
   `ServiceGroupOrder`), грузит их и NLS-таблицы, при необходимости — гипервизор (VBS/HVCI), кладёт всё
   в `LOADER_PARAMETER_BLOCK` (карта памяти, список модулей, ARC-пути, ACPI-таблицы, кадровый буфер GOP),
   вызывает `ExitBootServices` и прыгает в `KiSystemStartup`.
4. Ядро: фаза 0 (Ke/Mm/Ob/Se/Ps — один процессор), фаза 1 (остальные процессоры, Io → PnP-перечисление шин,
   запуск boot- и system-start драйверов), затем первый процесс `smss.exe`.
5. smss: файлы подкачки, переменные среды, `KnownDLLs`, запуск `csrss` и `wininit`/`winlogon` для сессий.
6. Экран до драйвера видеокарты — `BasicDisplay.sys` на кадровом буфере GOP от UEFI. **Это и есть наш путь
   на этапе 3: изображение в родном разрешении на любой видеокарте без её драйвера.**

## 3. Executive — что за что отвечает и что важно для совместимости

| Часть | Отвечает за | Что ломает программы/драйверы, если не так |
|---|---|---|
| Ke | планировщик, IRQL, DPC/APC, прерывания, спинлоки, объекты ожидания, многоядерность | гонки и зависания; драйверы считают, что DPC идут на других ядрах |
| Mm | виртуальная память, секции, файлы подкачки, пулы, большие страницы, ASLR, CFG | браузеры/JIT: `VirtualAlloc2`, `MapViewOfFile3`, placeholder-регионы, CFG (`SetProcessValidCallTargets`) |
| Ps | процессы, потоки, задания (Job), PEB/TEB, `KUSER_SHARED_DATA` | песочница Chromium (Job + ограниченные токены), чтение полей PEB напрямую |
| Ob | пространство имён `\`, дескрипторы, `\BaseNamedObjects`, `\Sessions\N` | именованные объекты, AppContainer-пространства имён |
| Se | токены, SID, ACL, уровни целостности, привилегии, AppContainer (lowbox) | UAC, песочницы, `CreateRestrictedToken`, `CreateAppContainerProfile` |
| Io | IRP, драйверы, устройства, асинхронный ввод-вывод, IOCP, отмена | серверы/браузеры на IOCP, `CancelIoEx`, `SetFileCompletionNotificationModes` |
| Pnp | перечисление, дерево устройств, INF-установка, ресурсы | любой драйвер производителя |
| Po | S0ix/S3/S4, состояния устройств, процессорное питание | ноутбуки: сон, батарея |
| Cm | реестр, кусты, транзакции, уведомления | установщики, `RegNotifyChangeKeyValue`, виртуализация реестра UAC |
| Cc | кэш файлов, отложенная запись | скорость и целостность ФС |
| Alpc | быстрые сообщения между процессами (RPC, COM, CSR, LSA) | весь COM/RPC ОС |
| Etw | трассировка событий | не критично для программ, нужно для диагностики |

## 4. Модели драйверов — от них зависит, заработают ли драйверы производителей

| Модель | Файлы в Windows | Кто ею пользуется | Документация |
|---|---|---|---|
| WDM | ntoskrnl/hal экспорты, IRP | всё «старое» | WDK |
| KMDF/UMDF 2 | Wdf01000.sys, WUDFHost | большинство новых драйверов | **исходники открыты Microsoft (MIT)** |
| StorPort | storport.sys + минипорты (stornvme, storahci, RAID Intel RST) | диски NVMe/SATA | WDK |
| NDIS 6.x | ndis.sys + минипорты; Wi-Fi: WDI или WiFiCx (Win11); NetAdapterCx | Ethernet, Wi-Fi | WDK |
| WDDM 2.x | dxgkrnl.sys, dxgmms2.sys; драйвер производителя = KMD + UMD (d3d10umddi) + ICD Vulkan/OpenGL | видеокарты | WDK (`d3dkmddi.h`, `d3dumddi.h`) |
| UCX | ucx01000.sys + usbxhci.sys + usbhub3.sys | USB 3 | WDK |
| HID | hidclass, hidusb, hidi2c, kbdhid, mouhid | клавиатуры, мыши, тачпады (I2C HID) | WDK |
| PortCls/AVStream, ACX | portcls.sys, ks.sys, hdaudio.sys, HDAudBus; ACX в Win11 | звук | WDK |
| FltMgr | fltmgr.sys + минифильтры | антивирусы, облачные диски, шифрование | WDK |
| ACPI | acpi.sys (+ таблицы прошивки, AML) | питание, батарея, кнопки, ноутбуки | спецификация ACPI 6.x |

Драйверы x64 в Windows 10 требуют подписи Microsoft (attestation). Okno грузит драйверы производителей без
проверки подписи Microsoft — это наше право, но подпись Authenticode проверять стоит, чтобы не грузить подделки.

## 5. Пользовательский режим — порядок слоёв DLL

- **ntdll.dll** — заглушки `Nt*/Zw*` (номера системных вызовов **не стабильны** между сборками Windows:
  программы зовут функции ntdll, а не номера — значит, нумерацию держим свою), загрузчик `Ldr*`, куча `Rtl*Heap`,
  пул потоков `Tp*`, `Etw*`, клиент CSR.
- **kernelbase.dll** — с Windows 7/8 основная реализация Win32; **kernel32.dll** — во многом переходники в kernelbase.
- **API sets** (`api-ms-win-core-*.dll`, `ext-ms-*`) — виртуальные имена; загрузчик разрешает их по схеме
  `apisetschema.dll`, отображённой в PEB. Современные программы и ucrtbase импортируют именно их.
- **user32/gdi32** → **win32u.dll** (с Windows 10 — заглушки системных вызовов win32k); gdi32full.
- **combase.dll** — COM и активация WinRT (`RoActivateInstance`, `RoGetActivationFactory`).
- **ucrtbase.dll** + `api-ms-win-crt-*` — Universal CRT (часть ОС); `vcruntime140*.dll`, `msvcp140*.dll` идут с программами.
- **Версия ОС**: `GetVersionEx` врёт программам без манифеста с GUID Windows 10 (`supportedOS`) и возвращает 6.2;
  `RtlGetVersion` и `KUSER_SHARED_DATA` говорят правду. Программы также читают
  `HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion` (`CurrentBuild`, `DisplayVersion`, `ProductName`).
- **Side-by-side** (WinSxS, манифесты, контексты активации) — нужен для comctl32 v6 и VC-рантаймов старых программ.
- **WebView2** — отдельный Chromium-рантайм, на нём живут Teams, Outlook new, часть 1С-клиентов, установщики.
  Заработает WebView2 → заработает большой класс программ.

## 6. Безопасность (то, что нужно браузерам и установщикам)

- Токены: основной/олицетворения, ограниченные (`CreateRestrictedToken`), уровни целостности (Low/Medium/High/System).
- UAC: разделённый токен администратора, `consent.exe`, служба `appinfo`, `ShellExecute` с `runas`, манифест
  `requestedExecutionLevel`; виртуализация файлов и реестра для старых программ.
- AppContainer (lowbox-токен, capability SID) — песочница Chromium/Edge/WebView2 и UWP.
- Job objects с ограничениями UI и памяти — тоже песочница Chromium.
- LSA: SAM, NTLM, Kerberos, DPAPI (`CryptProtectData` — им шифруют пароли браузеры и мессенджеры).

## 7. Реестр — где что лежит

- `HKLM\SYSTEM\CurrentControlSet\Services\<имя>` — драйверы и службы (`Start`, `Type`, `ImagePath`, `Group`).
- `HKLM\SYSTEM\CurrentControlSet\Enum` — дерево устройств PnP; `Control\Class\{GUID}` — классы драйверов.
- `HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion` — версия ОС (её читают программы и установщики).
- `HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall` — установленные программы.
- Пользователь: `NTUSER.DAT` (HKCU), `UsrClass.dat` (HKCU\Software\Classes).
- BCD — отдельный куст на ESP.

## 8. Установка драйверов

INF + каталог `.cat` (подпись) → DriverStore (`FileRepository`) → PnP сопоставляет Hardware ID / Compatible ID →
ставит службу драйвера → запускает. Драйверы производителей распространяются именно так (часто внутри
установщика .exe). Okno должна уметь: (1) поставить INF-пакет; (2) достать INF-пакет из установщика производителя.

## 9. Что из этого нужно на каком этапе Okno

| Этап | Обязательные части Windows |
|---|---|
| 1. Современные программы | ntdll/kernelbase/API sets уровня 10, ucrtbase, combase/WinRT-минимум, CNG+TLS 1.3, Mm (VirtualAlloc2, CFG), Job/AppContainer/токены для браузеров, версия 10.0.19045, WebView2 |
| 2. x64 + WoW64 + SMP | WoW64-триада, SysWOW64, перенаправление файлов и реестра, многоядерный Ke и HAL |
| 3. Современный ПК | загрузка UEFI с кадровым буфером GOP («BasicDisplay»), ACPI 6, StorPort + NVMe, UCX + xHCI, NDIS 6 Ethernet, HDA |
| 4. Ноутбук | NDIS 6 + Wi-Fi (WDI/WiFiCx), Po: S0ix/S3, батарея (ACPI CMBatt), HID I2C (тачпад), яркость |
| 5. Видеокарты | WDDM 2.x: dxgkrnl/dxgmms, D3DKMT-вызовы, UMD-интерфейс; DWM-композиция; Vulkan ICD |
| Продукт (вид — в конце) | установщик, обновления, Проводник/Пуск, оформление |
