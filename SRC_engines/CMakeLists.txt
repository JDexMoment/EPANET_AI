cmake_minimum_required(VERSION 3.14)
project(epanet2 VERSION 2.2.0 LANGUAGES C)

set(CMAKE_C_STANDARD 99)

set(EPANET_LIB_SOURCES
    epanet.c
    epanet2.c
    genmmd.c
    hash.c
    hydcoeffs.c
    hydraul.c
    hydsolver.c
    hydstatus.c
    inpfile.c
    input1.c
    input2.c
    input3.c
    mempool.c
    output.c
    project.c
    quality.c
    qualreact.c
    qualroute.c
    report.c
    rules.c
    smatrix.c
)

# Shared library (epanet2.dll on Windows / libepanet2.so on Linux)
add_library(epanet2 SHARED ${EPANET_LIB_SOURCES})
target_include_directories(epanet2 PUBLIC ${CMAKE_CURRENT_SOURCE_DIR})

if(WIN32)
    target_sources(epanet2 PRIVATE epanet2.def)
    target_compile_definitions(epanet2 PRIVATE _CRT_SECURE_NO_WARNINGS)
else()
    target_link_libraries(epanet2 PRIVATE m)
endif()

# Command-line executable (runepanet)
add_executable(runepanet main.c)
target_link_libraries(runepanet PRIVATE epanet2)
