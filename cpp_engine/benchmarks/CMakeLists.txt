# Benchmark suite configuration

add_executable(orderbook_bench orderbook_bench.cpp)
target_link_libraries(orderbook_bench PRIVATE metis-core benchmark::benchmark)

add_executable(fusion_bench fusion_bench.cpp)
target_link_libraries(fusion_bench PRIVATE metis-core benchmark::benchmark)

# Benchmarks are registered with benchmark::Main
