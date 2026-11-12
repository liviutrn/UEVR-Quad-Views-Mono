cmake_minimum_required(VERSION 3.20)
project(DuoViewB40ProductionWarp LANGUAGES CXX)

if(NOT JOYEY_BACKEND_DIR)
  message(FATAL_ERROR "Pass -DJOYEY_BACKEND_DIR=<exact patched backend checkout>")
endif()
find_package(Python3 REQUIRED COMPONENTS Interpreter)
include(CTest)

set(PINNED_WARP_SOURCE "${CMAKE_CURRENT_LIST_DIR}/../../duoview/joey_stage1/V208SharedEyeWarp.cpp")
set(GENERATED_WARP_SOURCE "${CMAKE_CURRENT_BINARY_DIR}/V208SharedEyeWarpB40.cpp")
add_custom_command(
  OUTPUT "${GENERATED_WARP_SOURCE}"
  COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_LIST_DIR}/B40ProductionWarpOverlay.py"
          --source "${PINNED_WARP_SOURCE}" --output "${GENERATED_WARP_SOURCE}"
  DEPENDS "${PINNED_WARP_SOURCE}" "${CMAKE_CURRENT_LIST_DIR}/B40ProductionWarpOverlay.py"
  VERBATIM)

if(WIN32)
  add_executable(DuoViewB40ProductionWarp "${GENERATED_WARP_SOURCE}")
  target_compile_features(DuoViewB40ProductionWarp PRIVATE cxx_std_20)
  target_include_directories(DuoViewB40ProductionWarp PRIVATE "${JOYEY_BACKEND_DIR}/src/mods/vr")
  target_link_libraries(DuoViewB40ProductionWarp PRIVATE d3d12 dxgi d3dcompiler)
  add_test(NAME duoview-b40-production-warp COMMAND DuoViewB40ProductionWarp)
  set_tests_properties(duoview-b40-production-warp PROPERTIES TIMEOUT 60)
else()
  message(STATUS "B40 production WARP test requires Windows D3D12; overlay generation remains available")
endif()
