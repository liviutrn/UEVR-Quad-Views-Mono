cmake_minimum_required(VERSION 3.20)
project(DuoViewB40ProductionWarp LANGUAGES CXX)

if(NOT JOYEY_BACKEND_DIR)
  message(FATAL_ERROR "Pass -DJOYEY_BACKEND_DIR=<exact patched backend checkout>")
endif()
find_package(Python3 REQUIRED COMPONENTS Interpreter)
include(CTest)

# B318 independent source-camera projection/viewport contract. Kept out
# of the v208d pinned "duoview/" tree so #317 source identity remains intact.
add_executable(DuoViewB318SourceFit b318_source_fit_tests.cpp)
target_compile_features(DuoViewB318SourceFit PRIVATE cxx_std_20)
target_include_directories(DuoViewB318SourceFit PRIVATE "${CMAKE_CURRENT_LIST_DIR}/../../duoview")
if(MSVC)
  target_compile_options(DuoViewB318SourceFit PRIVATE /UNDEBUG)
else()
  target_compile_options(DuoViewB318SourceFit PRIVATE -UNDEBUG)
endif()
add_test(NAME duoview-b318-source-fit COMMAND DuoViewB318SourceFit)

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

# M4 full-resolution fovea depth (lead build).
set(GENERATED_M4_WARP_SOURCE "${CMAKE_CURRENT_BINARY_DIR}/V208SharedEyeWarpM4.cpp")
add_custom_command(
  OUTPUT "${GENERATED_M4_WARP_SOURCE}"
  COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_LIST_DIR}/M4ProductionWarpOverlay.py"
          --source "${GENERATED_M3_WARP_SOURCE}" --output "${GENERATED_M4_WARP_SOURCE}"
  DEPENDS "${GENERATED_M3_WARP_SOURCE}" "${CMAKE_CURRENT_LIST_DIR}/M4ProductionWarpOverlay.py"
  VERBATIM)

# Goal D switch 1 (2026-11-18): fovea depth grid 4096 activation on the real compositor.
set(GENERATED_GOALD_WARP_SOURCE "${CMAKE_CURRENT_BINARY_DIR}/V208SharedEyeWarpGoalD.cpp")
add_custom_command(
  OUTPUT "${GENERATED_GOALD_WARP_SOURCE}"
  COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_LIST_DIR}/GoalDWarpOverlay.py"
          --source "${GENERATED_M4_WARP_SOURCE}" --output "${GENERATED_GOALD_WARP_SOURCE}"
  DEPENDS "${GENERATED_M4_WARP_SOURCE}" "${CMAKE_CURRENT_LIST_DIR}/GoalDWarpOverlay.py"
  VERBATIM)

# Research-only: derive fixture from the EXACT generated production source.
# The augmentation executes only with DUOVIEW_RECON_REPLAY=1; it changes no UEVR shader.
set(GENERATED_RECON_WARP_SOURCE "${CMAKE_CURRENT_BINARY_DIR}/V208SharedEyeWarpRecon.cpp")
add_custom_command(
  OUTPUT "${GENERATED_RECON_WARP_SOURCE}"
  COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_LIST_DIR}/ReconProductionWarpOverlay.py"
          --source "${GENERATED_GOALD_WARP_SOURCE}" --output "${GENERATED_RECON_WARP_SOURCE}"
  DEPENDS "${GENERATED_GOALD_WARP_SOURCE}" "${CMAKE_CURRENT_LIST_DIR}/ReconProductionWarpOverlay.py"
  VERBATIM)

# Second gated replay extends the original 32x32 GPU fixture to 384x216
# without modifying the production shader or removing earlier M4 probes.
set(GENERATED_LARGE_WARP_SOURCE "${CMAKE_CURRENT_BINARY_DIR}/V208SharedEyeWarpReconLarge.cpp")
add_custom_command(
  OUTPUT "${GENERATED_LARGE_WARP_SOURCE}"
  COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_LIST_DIR}/ReconLargeWarpOverlay.py"
          --source "${GENERATED_RECON_WARP_SOURCE}" --output "${GENERATED_LARGE_WARP_SOURCE}"
  DEPENDS "${GENERATED_RECON_WARP_SOURCE}" "${CMAKE_CURRENT_LIST_DIR}/ReconLargeWarpOverlay.py"
  VERBATIM)

# Generated-source-only V3 independent corpus replay; shipping shaders untouched.
set(GENERATED_V3_WARP_SOURCE "${CMAKE_CURRENT_BINARY_DIR}/V208SharedEyeWarpReconV3.cpp")
add_custom_command(
  OUTPUT "${GENERATED_V3_WARP_SOURCE}"
  COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_LIST_DIR}/ReconV3CorpusWarpOverlay.py"
          --source "${GENERATED_LARGE_WARP_SOURCE}" --output "${GENERATED_V3_WARP_SOURCE}"
  DEPENDS "${GENERATED_LARGE_WARP_SOURCE}" "${CMAKE_CURRENT_LIST_DIR}/ReconV3CorpusWarpOverlay.py"
  VERBATIM)

if(WIN32)
  add_executable(DuoViewB40ProductionWarp "${GENERATED_V3_WARP_SOURCE}")
  target_compile_features(DuoViewB40ProductionWarp PRIVATE cxx_std_20)
  # Fixture-only probes are compiled out of shipping UEVR headers.
  target_compile_definitions(DuoViewB40ProductionWarp PRIVATE DUOVIEW_M4_WARP_PROBE=1)
  target_include_directories(DuoViewB40ProductionWarp PRIVATE "${JOYEY_BACKEND_DIR}/src/mods/vr")
  target_link_libraries(DuoViewB40ProductionWarp PRIVATE d3d12 dxgi d3dcompiler)
  if(EDGE_BASELINE_PROBE_DIR)
    # Separate executable and copied DXBC; shipping backend is not changed.
    add_executable(DuoViewEdgeReadback "${GENERATED_V3_WARP_SOURCE}")
    target_compile_features(DuoViewEdgeReadback PRIVATE cxx_std_20)
    target_compile_definitions(DuoViewEdgeReadback PRIVATE DUOVIEW_M4_WARP_PROBE=1)
    target_include_directories(DuoViewEdgeReadback PRIVATE "${EDGE_BASELINE_PROBE_DIR}/include")
    target_link_libraries(DuoViewEdgeReadback PRIVATE d3d12 dxgi d3dcompiler)
  endif()
  add_test(NAME duoview-b40-production-warp COMMAND DuoViewB40ProductionWarp)
  add_test(NAME duoview-reconstruction-production-warp COMMAND DuoViewB40ProductionWarp)
  set_tests_properties(duoview-reconstruction-production-warp PROPERTIES
      TIMEOUT 120 ENVIRONMENT "DUOVIEW_RECON_REPLAY=1")
  add_test(NAME duoview-reconstruction-large-production-warp COMMAND DuoViewB40ProductionWarp)
  set_tests_properties(duoview-reconstruction-large-production-warp PROPERTIES
      TIMEOUT 420 ENVIRONMENT "DUOVIEW_RECON_LARGE=1")
  add_test(NAME duoview-reconstruction-quality-jitter-warp COMMAND DuoViewB40ProductionWarp)
  set_tests_properties(duoview-reconstruction-quality-jitter-warp PROPERTIES
      TIMEOUT 600 ENVIRONMENT "DUOVIEW_RECON_LARGE=1;DUOVIEW_RECON_QUALITY=1")
  add_test(NAME duoview-reconstruction-v3-corpus-warp COMMAND DuoViewB40ProductionWarp)
  set_tests_properties(duoview-reconstruction-v3-corpus-warp PROPERTIES
      TIMEOUT 1200 ENVIRONMENT "DUOVIEW_RECON_V3=1;DUOVIEW_RECON_V3_DIR=${CMAKE_CURRENT_LIST_DIR}/recon_corpus_generated")
  set_tests_properties(duoview-b40-production-warp PROPERTIES TIMEOUT 60)
  add_test(NAME duoview-m4-condition-probe COMMAND DuoViewB40ProductionWarp)
  set_tests_properties(duoview-m4-condition-probe PROPERTIES TIMEOUT 60
      ENVIRONMENT "DUOVIEW_M4_DIAG=condition")
  add_test(NAME duoview-m4-vertical-probe COMMAND DuoViewB40ProductionWarp)
  set_tests_properties(duoview-m4-vertical-probe PROPERTIES TIMEOUT 60
      ENVIRONMENT "DUOVIEW_M4_DIAG=vertical")
  foreach(M4_PROBE skip constant fine barrier seed symmetric legacy noorigin-off noorigin-on originonly-off originonly-on)
    add_test(NAME duoview-m4-${M4_PROBE}-probe COMMAND DuoViewB40ProductionWarp)
    set_tests_properties(duoview-m4-${M4_PROBE}-probe PROPERTIES TIMEOUT 60)
  endforeach()
  set_tests_properties(duoview-m4-skip-probe PROPERTIES ENVIRONMENT "DUOVIEW_M4_DIAG=skip")
  set_tests_properties(duoview-m4-constant-probe PROPERTIES ENVIRONMENT "DUOVIEW_M4_DIAG=konstant")
  set_tests_properties(duoview-m4-fine-probe PROPERTIES ENVIRONMENT "DUOVIEW_M4_DIAG=fine")
  set_tests_properties(duoview-m4-barrier-probe PROPERTIES ENVIRONMENT "DUOVIEW_M4_DIAG=barrier")
  set_tests_properties(duoview-m4-seed-probe PROPERTIES ENVIRONMENT "DUOVIEW_M4_DIAG=edge-seed")
  set_tests_properties(duoview-m4-symmetric-probe PROPERTIES ENVIRONMENT "DUOVIEW_M4_DIAG=yield-symmetric")
  set_tests_properties(duoview-m4-legacy-probe PROPERTIES ENVIRONMENT "DUOVIEW_M4_DIAG=legacy")
  set_tests_properties(duoview-m4-noorigin-off-probe PROPERTIES ENVIRONMENT "DUOVIEW_M4_DIAG=nosym")
  set_tests_properties(duoview-m4-noorigin-on-probe PROPERTIES ENVIRONMENT "DUOVIEW_M4_DIAG=nAdaptive")
  set_tests_properties(duoview-m4-originonly-off-probe PROPERTIES ENVIRONMENT "DUOVIEW_M4_DIAG=origin")
  set_tests_properties(duoview-m4-originonly-on-probe PROPERTIES ENVIRONMENT "DUOVIEW_M4_DIAG=oAdaptive")
else()
  message(STATUS "B40 production WARP test requires Windows D3D12; overlay generation remains available")
endif()
