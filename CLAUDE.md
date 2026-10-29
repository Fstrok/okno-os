# Okno OS — правила работы

Okno OS — замена Windows 10/11 на ядре NT. Это форк ReactOS (история ReactOS сохранена, `git remote upstream`).
Linux не используем — решение владельца. План и решения владельца — `docs/plan.md`.

## Сначала читай базу знаний, а не исходники ReactOS

| Файл | Что там |
|---|---|
| `docs/kb/windows-architecture.md` | как устроена Windows 10/11: слои, загрузка, модели драйверов, DLL, безопасность, реестр |
| `docs/kb/decisions.md` | по каждой части ReactOS: берём / обновляем / заменяем / пишем сами — и почему |
| `docs/kb/reactos-core.md` | загрузчик, ядро, HAL, системные процессы: состояние, как устроено, задачи |
| `docs/kb/reactos-drivers.md` | драйверы: состояние, модели драйверов, PnP и установка, задачи |
| `docs/kb/reactos-usermode.md` | DLL, win32k, синхронизация с Wine, пробелы для современных программ, задачи |
| `docs/kb/reactos-build.md` | сборка, компиляторы, CI, тесты, отладка, карта каталогов, как добавить модуль |
| `docs/kb/apigap-baseline.md` | каких функций Windows не хватает программам (замер анализатором) |

В исходники ReactOS лезь только за деталями конкретной правки. Узнал что-то важное и общее — допиши в нужный
файл `docs/kb/` в том же коммите, чтобы в следующий раз не искать заново.

## Жёсткие правила

- **Чистая комната.** Никогда не использовать утёкшие исходники Windows (NT4, 2000, XP, Windows Research Kernel)
  и дизассемблированный код Microsoft. Можно: документация Microsoft Learn, WDK и Windows SDK; открытый код
  совместимых лицензий; проверка поведения (запустить программу или тест и сравнить результат). У бинарников
  Microsoft разбирать только таблицы импорта и экспорта.
- **Лицензии.** Проект GPL-2.0-or-later. Свободно: MIT, BSD, ISC, zlib, LGPL, public domain.
  MS-PL с GPL несовместима — только отдельным модулем (свой .sys/.dll), не смешивая с GPL-файлами.
  Apache-2.0 и код ядра Linux (GPLv2-only) не берём.
- **Из ReactOS берём только то, что годно в 2026 году и лучше всех доступных вариантов.** Остальное заменяем
  или пишем сами по документации; решение записываем в `docs/kb/decisions.md`.
- **Внешний вид — последним этапом.** До этапа 6 оформление, темы и иконки не трогаем.
- **Изменения модульные.** Новое — отдельными файлами и каталогами, правки чужого кода — минимальные:
  так проще вливать обновления ReactOS (`git fetch upstream && git merge upstream/master`).
- **Готово = проверено запуском.** Сборка плюс загрузка в QEMU (`tools/qemu/vm.py`) и проверка результата
  (снимок экрана, журнал с последовательного порта, автотест). Одной успешной компиляции мало.

## Сборка (проверено на Ubuntu 24.04)

```bash
sudo apt-get install -y clang lld llvm gcc-mingw-w64 g++-mingw-w64 binutils-mingw-w64 flex bison ninja-build
cmake -S . -B build -G Ninja -DCMAKE_TOOLCHAIN_FILE:FILEPATH=toolchain-clang.cmake -DARCH:STRING=i386 -DCMAKE_BUILD_TYPE=Debug
cmake --build build                  # система
cmake --build build --target bootcd  # build/bootcd.iso (установщик + живая система)
```

`ARCH` — `i386` или `amd64`. Debug-сборка пишет журнал ядра в COM1 — его читают тесты.

## Проверка в QEMU

```bash
tools/qemu/vm.py start t1 --arch x86 --iso build/bootcd.iso [--data apps.img]
tools/qemu/vm.py shot t1 shot.png    # снимок экрана, потом посмотреть его
tools/qemu/vm.py stop t1
```

Машина q35 с дисками AHCI: на стандартном IDE (i440FX) 64-битная сборка падает в pciidex.sys.

## Ответы владельцу

Только на русском, коротко, без воды; английский — только в коде, командах и названиях.
Общие правила работы — `.claude/skills/work-style/SKILL.md`.
