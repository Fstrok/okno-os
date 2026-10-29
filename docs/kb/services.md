# Службы и системные компоненты Windows 10: что есть у нас и что писать

Состояние на 29.10.2026 (master ReactOS `e46f4bb`). «Есть» — каталог есть в дереве; насколько он рабочий,
решают автотест и `reactos-usermode.md`. Приоритет — номер этапа плана, на котором без этого не обойтись.

## Службы (`services.exe` → `svchost.exe`)

| Служба Windows 10 | Зачем она программам | У нас | Этап | Что делаем |
|---|---|---|---|---|
| RpcSs, RpcEptMapper, DcomLaunch | COM и RPC — всё межпроцессное в ОС | `base/services/rpcss`, `dcomlaunch` | 1 | проверить на COM-серверах установщиков |
| PlugPlay | устройства, установка драйверов | `base/services/umpnpmgr` | 3 | доводить вместе с PnP |
| EventLog (Vista: wevtsvc + wevtapi) | журналы; `EvtQuery`/`EvtSubscribe` в программах | XP-шный `eventlog`, `wevtapi` есть, `wevtsvc` нет | 1 | новый журнал событий с API Vista+ |
| Schedule (Планировщик 2.0) | установщики и обновлятели регистрируют задачи через `ITaskService` (Chrome, Edge, WebView2, Firefox) | `schedsvc` (только XP AT), `taskschd.dll` нет | 1 | **написать** `taskschd.dll` + служба 2.0 |
| BITS | фоновые загрузки обновлятелей (WebView2, Edge) | `qmgr` (Wine) | 1 | проверить, регистрируется ли как служба |
| NlaSvc + netprofm (`INetworkListManager`) | «есть ли интернет» — его спрашивают браузеры, мессенджеры, Teams | нет | 1 | **написать** `netprofm.dll` + `nlasvc` |
| nsi / nsiproxy | под `iphlpapi` с Vista: адаптеры, маршруты | `iphlpapi` есть, `nsi` нет | 1 | **написать** `nsi.dll` |
| Dhcp, Dnscache | сеть | `dhcpcsvc`, `dnsrslvr` | 3 | IPv6 (`dhcpcsvc6` нет) |
| WinHttpAutoProxySvc | прокси | `winhttp` | 1 | — |
| Audiosrv + AudioEndpointBuilder (WASAPI) | звук всех современных программ и браузеров (`IAudioClient`) | XP-шный `audiosrv`, `mmdevapi` есть, `audioses` нет | 1 | **WASAPI поверх KS**: mmdevapi + audioses + служба конечных точек |
| CryptSvc | каталоги подписей, обновление корневых сертификатов | нет | 1 | **написать** (корни — свой набор) |
| KeyIso (CNG Key Isolation) | ключи `NCrypt*`, сертификаты с закрытым ключом | нет | 1 | **написать** |
| VaultSvc (Диспетчер учётных данных) | `CredWrite`/`CredRead`, пароли Git, браузеров | нет | 1 | **написать** `vaultcli` + служба |
| ProfSvc | профили пользователей, загрузка `NTUSER.DAT` | в `userenv`, службы нет | 2 | по необходимости |
| LSM, TermService | сессии, `WTS*` API | `wtsapi32`, `winsta`; LSM нет | 2 | **написать** LSM (сессии нужны и для быстрой смены пользователя) |
| Power (umpo) | схемы питания, `PowerRegisterSuspendResumeNotification` | `powrprof`, службы нет | 4 | **написать** вместе с ноутбуками |
| Appinfo (UAC) | «Запуск от имени администратора», манифесты `requireAdministrator` | нет | 2 | **написать** вместе с разделённым токеном |
| SamSs/lsass, Netlogon | учётные записи, вход | `base/system/lsass`, `samsrv`, `netlogon` | 1 | проверка |
| Spooler | печать | есть | 3 | — |
| Winmgmt (WMI) | `Win32_*` запросы в программах и установщиках | `wmisvc` + `wbemprox` (Wine) | 1 | дополнять классы по замерам |
| Themes | оформление | есть | 6 | вид — последним |
| W32Time, Seclogon, LanmanServer/Workstation | время, `runas`, общие папки | есть | 3 | — |
| wuauserv | Windows Update | есть (заглушка) | — | заменим своей системой обновлений |
| BFE/MpsSvc (брандмауэр) | `INetFwPolicy2` — установщики игр и серверов добавляют правила | `hnetcfg` (Wine, заглушки) | 1 | заглушки не должны ронять установщики |
| AppXSvc, StateRepository, ClipSVC | программы из Store (UWP/MSIX) | нет | после 1.0 | — |

## Системные DLL, которых нет и которые нужны современным программам

| DLL | Что это | Кто требует | Этап |
|---|---|---|---|
| `mfplat`, `mf`, `mfreadwrite`, `evr` | Media Foundation | плееры, мессенджеры, браузеры (аппаратное видео), Teams | 1 |
| `xinput1_4` | геймпады (Windows 8+) | игры | 5 |
| `windows.storage` | оболочка Windows 10 (`shell32` на ней) | программы с `IFileDialog`, установщики | 1 |
| `taskschd`, `netprofm`, `nsi`, `audioses`, `vaultcli`, `wevtsvc` | см. службы выше | — | 1 |
| `wer` | отчёты об ошибках (`WerRegister*`) | Chromium, Electron, .NET | 1 |

Точный список недостающих функций по программам даёт `tools/compat` (`apigap-baseline.md`), этот файл — карта служб.
