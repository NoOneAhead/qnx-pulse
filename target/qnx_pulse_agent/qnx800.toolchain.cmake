# QNX SDP 8.0 CMake Cross-Compilation Toolchain File
#
# Usage (after sourcing qnxsdp-env.sh or qnxsdp-env.bat):
#   x86_64 (QEMU):
#     cmake -B build-qnx-x86_64 -DCMAKE_TOOLCHAIN_FILE=qnx800.toolchain.cmake -DARCH=x86_64
#   aarch64le (Raspberry Pi 5 / ARM64):
#     cmake -B build-qnx-aarch64le -DCMAKE_TOOLCHAIN_FILE=qnx800.toolchain.cmake -DARCH=aarch64le

set(CMAKE_SYSTEM_NAME QNX)
set(CMAKE_SYSTEM_VERSION 8.0.0)

set(QNX_HOST "$ENV{QNX_HOST}")
set(QNX_TARGET "$ENV{QNX_TARGET}")

if(NOT QNX_HOST OR NOT QNX_TARGET)
    message(FATAL_ERROR
        "QNX_HOST and QNX_TARGET environment variables must be set. "
        "Source your QNX SDP 8.0 environment script (qnxsdp-env.sh or qnxsdp-env.bat) first.")
endif()

# Normalize Windows backslashes when building on Windows hosts
file(TO_CMAKE_PATH "${QNX_HOST}" QNX_HOST)
file(TO_CMAKE_PATH "${QNX_TARGET}" QNX_TARGET)

# Target architecture selection: x86_64 (default) or aarch64le
if(NOT DEFINED ARCH OR "${ARCH}" STREQUAL "")
    if(DEFINED QNX_ARCH AND NOT "${QNX_ARCH}" STREQUAL "")
        set(ARCH "${QNX_ARCH}")
    else()
        set(ARCH "x86_64")
    endif()
endif()
set(ARCH "${ARCH}" CACHE STRING "QNX 8.0 target architecture (x86_64 or aarch64le)")

if(ARCH STREQUAL "x86_64")
    set(CMAKE_SYSTEM_PROCESSOR "x86_64")
    set(QCC_TARGET_VARIANT "gcc_ntox86_64")
    set(QNX_BINUTILS_PREFIX "ntox86_64")
    set(QNX_TARGET_ARCH_DIR "x86_64")
elseif(ARCH STREQUAL "aarch64le")
    set(CMAKE_SYSTEM_PROCESSOR "aarch64")
    set(QCC_TARGET_VARIANT "gcc_ntoaarch64le")
    set(QNX_BINUTILS_PREFIX "ntoaarch64")
    set(QNX_TARGET_ARCH_DIR "aarch64le")
else()
    message(FATAL_ERROR "Unsupported QNX ARCH='${ARCH}'. Expected 'x86_64' or 'aarch64le'.")
endif()

if(CMAKE_HOST_WIN32)
    set(QNX_HOST_EXE_SUFFIX ".exe")
else()
    set(QNX_HOST_EXE_SUFFIX "")
endif()

set(CMAKE_C_COMPILER   "${QNX_HOST}/usr/bin/qcc${QNX_HOST_EXE_SUFFIX}")
set(CMAKE_CXX_COMPILER "${QNX_HOST}/usr/bin/q++${QNX_HOST_EXE_SUFFIX}")
set(CMAKE_ASM_COMPILER "${QNX_HOST}/usr/bin/qcc${QNX_HOST_EXE_SUFFIX}")

set(CMAKE_C_COMPILER_TARGET   "${QCC_TARGET_VARIANT}")
set(CMAKE_CXX_COMPILER_TARGET "${QCC_TARGET_VARIANT}")
set(CMAKE_ASM_COMPILER_TARGET "${QCC_TARGET_VARIANT}")

set(CMAKE_AR     "${QNX_HOST}/usr/bin/${QNX_BINUTILS_PREFIX}-ar${QNX_HOST_EXE_SUFFIX}"     CACHE FILEPATH "QNX ar")
set(CMAKE_RANLIB "${QNX_HOST}/usr/bin/${QNX_BINUTILS_PREFIX}-ranlib${QNX_HOST_EXE_SUFFIX}" CACHE FILEPATH "QNX ranlib")
set(CMAKE_STRIP  "${QNX_HOST}/usr/bin/${QNX_BINUTILS_PREFIX}-strip${QNX_HOST_EXE_SUFFIX}"  CACHE FILEPATH "QNX strip")

set(CMAKE_SYSROOT "${QNX_TARGET}")
set(CMAKE_FIND_ROOT_PATH
    "${QNX_TARGET}"
    "${QNX_TARGET}/${QNX_TARGET_ARCH_DIR}"
)

set(CMAKE_FIND_ROOT_PATH_MODE_PROGRAM NEVER)
set(CMAKE_FIND_ROOT_PATH_MODE_LIBRARY ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_INCLUDE ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_PACKAGE ONLY)
