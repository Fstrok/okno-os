# Okno OS

Открытая замена Windows 10/11 на ядре NT. Программы и драйверы Windows работают напрямую, без прослоек.

Основа — форк [ReactOS](https://reactos.org) (история проекта сохранена, исходный README — `README.reactos.md`).
Из ReactOS берём только то, что годно в 2026 году и лучше всех доступных вариантов; остальное заменяем или пишем сами.

- План и этапы — [docs/plan.md](docs/plan.md)
- Ход работ и замеры — [docs/progress.md](docs/progress.md)
- Как устроена Windows и что из этого есть у нас — [docs/kb/](docs/kb/)

## Сборка

```bash
sudo apt-get install -y clang lld llvm gcc-mingw-w64 g++-mingw-w64 binutils-mingw-w64 flex bison ninja-build
cmake -S . -B build -G Ninja -DCMAKE_TOOLCHAIN_FILE:FILEPATH=toolchain-clang.cmake -DARCH:STRING=i386 -DCMAKE_BUILD_TYPE=Debug
cmake --build build --target bootcd   # → build/bootcd.iso
```

`ARCH`: `i386` или `amd64`. Каждый пуш собирает обе версии в GitHub Actions (артефакты `okno-i386`, `okno-amd64`).

## Лицензия

GPL-2.0-or-later, как у ReactOS (`COPYING`); сторонние части — под своими лицензиями (`media/doc/3rd Party Files.txt`).
