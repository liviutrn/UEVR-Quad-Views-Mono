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

# Extend the existing pinned v208d+B40/M1 fixture; still build and run the
# same production compositor, but validate M2.1 fine depth and left/right GPU pixels.
set(GENERATED_M21_WARP_SOURCE "${CMAKE_CURRENT_BINARY_DIR}/V208SharedEyeWarpM21.cpp")
add_custom_command(
  OUTPUT "${GENERATED_M21_WARP_SOURCE}"
  COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_LIST_DIR}/M21ProductionWarpOverlay.py"
          --source "${GENERATED_WARP_SOURCE}" --output "${GENERATED_M21_WARP_SOURCE}"
  DEPENDS "${GENERATED_WARP_SOURCE}" "${CMAKE_CURRENT_LIST_DIR}/M21ProductionWarpOverlay.py"
  VERBATIM)

# Extend M21's existing exact production WARP fixture with M2.5a content path.
set(GENERATED_M25_WARP_SOURCE "${CMAKE_CURRENT_BINARY_DIR}/V208SharedEyeWarpM25.cpp")
add_custom_command(
  OUTPUT "${GENERATED_M25_WARP_SOURCE}"
  COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_LIST_DIR}/M25ProductionWarpOverlay.py"
          --source "${GENERATED_M21_WARP_SOURCE}" --output "${GENERATED_M25_WARP_SOURCE}"
  DEPENDS "${GENERATED_M21_WARP_SOURCE}" "${CMAKE_CURRENT_LIST_DIR}/M25ProductionWarpOverlay.py"
  VERBATIM)

# M2.5a positive gate checks, M3a per-eye edges and contract C2 (lead build).
set(GENERATED_M3_WARP_SOURCE "${CMAKE_CURRENT_BINARY_DIR}/V208SharedEyeWarpM3.cpp")
add_custom_command(
  OUTPUT "${GENERATED_M3_WARP_SOURCE}"
  COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_LIST_DIR}/M3ProductionWarpOverlay.py"
          --source "${GENERATED_M25_WARP_SOURCE}" --output "${GENERATED_M3_WARP_SOURCE}"
  DEPENDS "${GENERATED_M25_WARP_SOURCE}" "${CMAKE_CURRENT_LIST_DIR}/M3ProductionWarpOverlay.py"
  VERBATIM)

if(WIN32)
  add_executable(DuoViewB40ProductionWarp "${GENERATED_M3_WARP_SOURCE}")
  target_compile_features(DuoViewB40ProductionWarp PRIVATE cxx_std_20)
  target_include_directories(DuoViewB40ProductionWarp PRIVATE "${JOYEY_BACKEND_DIR}/src/mods/vr")
  target_link_libraries(DuoViewB40ProductionWarp PRIVATE d3d12 dxgi d3dcompiler)
  add_test(NAME duoview-b40-production-warp COMMAND DuoViewB40ProductionWarp)
  set_tests_properties(duoview-b40-production-warp PROPERTIES TIMEOUT 60)
else()
  message(STATUS "B40 production WARP test requires Windows D3D12; overlay generation remains available")
endif()
