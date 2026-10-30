#!/usr/bin/bash
# RosBE (GCC 8.4 + mingw-w64 v6) for CI, from ReactOS's CI (gist zefklop/b2d6a0b4...).
# Vendored so the build does not run a script fetched from someone's gist; mirrors added.
set -e

ROSBE_BUILD_DIR=$1
ROSBE_GIT_DIR=./RosBE-git
THIS_SCRIPT=`basename "$0"`

git clone --depth=1 --branch=unix_amd64 https://github.com/zefklop/RosBE.git $ROSBE_GIT_DIR

# Check if we have our toolchain ready
if [ -d $ROSBE_BUILD_DIR ]; then
    if [ -f $ROSBE_BUILD_DIR/git-commit ] && [ -f $ROSBE_BUILD_DIR/$THIS_SCRIPT.sha1 ]; then
        # Compare ourself with what we already have. Return if this is the same
        if (sha1sum -c --status $ROSBE_BUILD_DIR/$THIS_SCRIPT.sha1); then
            if (git --git-dir=$ROSBE_GIT_DIR/.git rev-parse HEAD | cmp -s $ROSBE_BUILD_DIR/git-commit); then
                echo "Nothing to do. Using precompiled RosBE"
                exit 0
            else
                echo "Rebuilding RosBE because of different commit hash"
            fi
        else
            echo "Rebuilding RosBE because build script differs"
        fi
    fi
fi

mkdir -p $ROSBE_BUILD_DIR

# binutils
wget https://ftp.gnu.org/gnu/binutils/binutils-2.36.tar.xz
tar -xf binutils-2.36.tar.xz
rm binutils-2.36.tar.xz
mv binutils-2.36 binutils
patch -d ./binutils -p1 < $ROSBE_GIT_DIR/Patches/binutils-seh_pushframe-jgardou.patch
tar -cjf $ROSBE_GIT_DIR/RosBE-Unix/Base-i386/sources/binutils.tar.bz2 ./binutils
rm -rf binutils

# GCC
wget https://ftpmirror.gnu.org/gcc/gcc-8.4.0/gcc-8.4.0.tar.xz || wget -L https://web.archive.org/web/2025if_/https://ftpmirror.gnu.org/gcc/gcc-8.4.0/gcc-8.4.0.tar.xz
tar -xf gcc-8.4.0.tar.xz
rm gcc-8.4.0.tar.xz
mv gcc-8.4.0 gcc
tar -cjf $ROSBE_GIT_DIR/RosBE-Unix/Base-i386/sources/gcc.tar.bz2 ./gcc
rm -rf gcc

# Bison
wget https://ftp.gnu.org/gnu/bison/bison-3.5.4.tar.xz
tar -xf bison-3.5.4.tar.xz
rm bison-3.5.4.tar.xz
mv bison-3.5.4 bison
tar -cjf $ROSBE_GIT_DIR/RosBE-Unix/Base-i386/sources/bison.tar.bz2 ./bison
rm -rf bison

# cmake
git clone --depth=1 --branch=cmake-3.17.2-reactos https://github.com/reactos/CMake.git cmake
rm -rf ./cmake/.git
tar -cjf $ROSBE_GIT_DIR/RosBE-Unix/Base-i386/sources/cmake.tar.bz2 ./cmake
rm -rf cmake

# Flex
wget https://github.com/westes/flex/releases/download/v2.6.4/flex-2.6.4.tar.gz
tar -xf flex-2.6.4.tar.gz
rm flex-2.6.4.tar.gz
mv flex-2.6.4 flex
tar -cjf $ROSBE_GIT_DIR/RosBE-Unix/Base-i386/sources/flex.tar.bz2 ./flex
rm -rf flex

# GMP
wget https://ftp.gnu.org/gnu/gmp/gmp-6.2.0.tar.xz
tar -xf gmp-6.2.0.tar.xz
rm gmp-6.2.0.tar.xz
mv gmp-6.2.0 gmp
patch -d ./gmp -p2 < $ROSBE_GIT_DIR/Patches/GMP-6.2.0-C89-fixes.patch
tar -cjf $ROSBE_GIT_DIR/RosBE-Unix/Base-i386/sources/gmp.tar.bz2 ./gmp
rm -rf gmp

# Mingw-w64
wget -O - https://github.com/mingw-w64/mingw-w64/archive/refs/tags/v6.0.0.tar.gz | tar -xz && mv mingw-w64-6.0.0 mingw-w64-v6.0.0 && tar -cjf mingw-w64-v6.0.0.tar.bz2 mingw-w64-v6.0.0 && rm -rf mingw-w64-v6.0.0
tar -xf mingw-w64-v6.0.0.tar.bz2
rm mingw-w64-v6.0.0.tar.bz2
mv mingw-w64-v6.0.0 mingw_w64
tar -cjf $ROSBE_GIT_DIR/RosBE-Unix/Base-i386/sources/mingw_w64.tar.bz2 ./mingw_w64
rm -rf mingw_w64

# MPC
wget https://ftp.gnu.org/gnu/mpc/mpc-1.1.0.tar.gz
tar -xf mpc-1.1.0.tar.gz
rm mpc-1.1.0.tar.gz
mv mpc-1.1.0 mpc
tar -cjf $ROSBE_GIT_DIR/RosBE-Unix/Base-i386/sources/mpc.tar.bz2 ./mpc
rm -rf mpc

# MPFR
wget https://ftp.gnu.org/gnu/mpfr/mpfr-4.0.2.tar.xz
tar -xf mpfr-4.0.2.tar.xz
rm mpfr-4.0.2.tar.xz
mv mpfr-4.0.2 mpfr
tar -cjf $ROSBE_GIT_DIR/RosBE-Unix/Base-i386/sources/mpfr.tar.bz2 ./mpfr
rm -rf mpfr

# ninja
wget -O ninja-1.10.0.tar.gz https://github.com/ninja-build/ninja/archive/refs/tags/v1.10.0.tar.gz
tar -xf ninja-1.10.0.tar.gz
rm ninja-1.10.0.tar.gz
mv ninja-1.10.0 ninja
tar -cjf $ROSBE_GIT_DIR/RosBE-Unix/Base-i386/sources/ninja.tar.bz2 ./ninja
rm -rf ninja

# ROSBE tools
cp -R $ROSBE_GIT_DIR/Tools $ROSBE_GIT_DIR/RosBE-Unix/Base-i386/tools

# Call builder
rm -rf $ROSBE_BUILD_DIR
echo yes | $ROSBE_GIT_DIR/RosBE-Unix/Base-i386/RosBE-Builder.sh $ROSBE_BUILD_DIR

# Remember how we built all of this
sha1sum $0 > $ROSBE_BUILD_DIR/$THIS_SCRIPT.sha1
git --git-dir=$ROSBE_GIT_DIR/.git rev-parse HEAD > $ROSBE_BUILD_DIR/git-commit

# cleanup 
rm -rf $ROSBE_GIT_DIR
