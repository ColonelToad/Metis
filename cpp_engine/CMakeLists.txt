cmake_minimum_required(VERSION 3.24)
project(metis-cpp
    VERSION 0.1.0
    LANGUAGES CXX
    DESCRIPTION "Metis HFT engine core (C++ production port)"
)

# Require modern C++
set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

# Release build: aggressive optimization + LTO (GCC-compatible)
# Note: LTO disabled by default for faster CI builds; enable with -DENABLE_LTO=ON
set(CMAKE_CXX_FLAGS_RELEASE "-O3 -march=native -fstrict-aliasing")
option(ENABLE_LTO "Enable Link-Time Optimization" OFF)
if(ENABLE_LTO)
    set(CMAKE_CXX_FLAGS_RELEASE "${CMAKE_CXX_FLAGS_RELEASE} -flto")
endif()

# AddressSanitizer + UBSanitizer in Debug
set(CMAKE_CXX_FLAGS_DEBUG "-g -O0 -fsanitize=address,undefined -fno-omit-frame-pointer")

# Setup Ninja generator if available (faster than Unix Makefiles)
if(NOT DEFINED CMAKE_GENERATOR)
    if(COMMAND ninja_available OR CMAKE_MAKE_PROGRAM MATCHES "ninja")
        set(CMAKE_GENERATOR "Ninja")
    endif()
endif()

# Enforce out-of-source builds
if(CMAKE_SOURCE_DIR STREQUAL CMAKE_BINARY_DIR)
    message(FATAL_ERROR "In-source builds not allowed. Use: cmake -B build -S .")
endif()

# Export compile commands for tooling (clangd, etc)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

# Modern CMake: link as private by default
set(CMAKE_LINK_LIBRARY_USING_CXX_MODULES ON CACHE BOOL "")

# Find or build dependencies
include(FetchContent)

# Google Test (for unit tests) — try system first
find_package(GTest QUIET)
if(NOT GTest_FOUND)
    message(STATUS "GTest not found, fetching from source...")
    FetchContent_Declare(googletest
        GIT_REPOSITORY https://github.com/google/googletest.git
        GIT_TAG main
    )
    FetchContent_MakeAvailable(googletest)
endif()

# Google Benchmark (for latency microbenchmarks) — try system first
find_package(benchmark QUIET)
if(NOT benchmark_FOUND AND BUILD_BENCHMARKS)
    message(STATUS "benchmark not found, fetching from source...")
    set(BENCHMARK_ENABLE_GTEST_TESTS OFF CACHE BOOL "")
    FetchContent_Declare(benchmark
        GIT_REPOSITORY https://github.com/google/benchmark.git
        GIT_TAG main
    )
    FetchContent_MakeAvailable(benchmark)
endif()

# Optional: mimalloc or jemalloc for perf (try system first)
find_package(mimalloc QUIET)
if(NOT mimalloc_FOUND)
    # Fall back to system malloc for now; can add Conan/vcpkg integration later
    message(STATUS "mimalloc not found, using system allocator")
endif()

# Add main library
add_subdirectory(src)

# Add tests
enable_testing()
add_subdirectory(tests)

# Add benchmarks (optional, can be disabled with -DBUILD_BENCHMARKS=OFF)
option(BUILD_BENCHMARKS "Build benchmark suite" ON)
if(BUILD_BENCHMARKS)
    add_subdirectory(benchmarks)
endif()

# Summary
message(STATUS "Metis C++ Engine Configuration")
message(STATUS "  Compiler: ${CMAKE_CXX_COMPILER_ID}")
message(STATUS "  Generator: ${CMAKE_GENERATOR}")
message(STATUS "  C++ Standard: ${CMAKE_CXX_STANDARD}")
message(STATUS "  Release Flags: ${CMAKE_CXX_FLAGS_RELEASE}")
message(STATUS "  Debug Flags: ${CMAKE_CXX_FLAGS_DEBUG}")
