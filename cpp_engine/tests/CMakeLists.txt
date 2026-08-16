# Test suite configuration

# Link against gtest and the main library
add_executable(metis-tests
    orderbook_test.cpp
    fusion_test.cpp
    execution_algos_test.cpp
)

target_link_libraries(metis-tests PRIVATE
    metis-core
    GTest::gtest
    GTest::gtest_main
)

target_include_directories(metis-tests PRIVATE
    ${CMAKE_SOURCE_DIR}/include
)

# Register tests with CTest
add_test(NAME metis_unit_tests COMMAND metis-tests)
