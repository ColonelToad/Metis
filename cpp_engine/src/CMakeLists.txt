# Main Metis C++ library: order book + fusion + execution algos

add_library(metis-core STATIC)

target_sources(metis-core PRIVATE
    orderbook/orderbook.cpp
    fusion/fusion.cpp
    execution_algos/execution_algos.cpp
    networking/dpdk_ingest.cpp
    networking/sbe_parser.cpp
    decision/decision_layer.cpp
    lib.cpp
)

target_include_directories(metis-core PUBLIC
    ${CMAKE_CURRENT_SOURCE_DIR}/../include
)

target_compile_options(metis-core PRIVATE
    -Wall -Wextra -Wpedantic
    -Wcast-align -Wconversion -Wsign-conversion
)

# Allow anonymous structs in unions (Clang-specific, silently ignored by GCC)
target_compile_options(metis-core PRIVATE $<$<CXX_COMPILER_ID:Clang>:-Wno-gnu-anonymous-struct>)

# Ensure Release mode gets aggressive optimization
target_compile_options(metis-core PRIVATE
    $<$<CONFIG:Release>:-O3 -march=native -flto>
    $<$<CONFIG:Debug>:-g -O0>
)

# Position-independent code for linking flexibility
set_target_properties(metis-core PROPERTIES
    POSITION_INDEPENDENT_CODE ON
)
