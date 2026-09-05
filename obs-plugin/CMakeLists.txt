cmake_minimum_required(VERSION 3.28...3.30)

include("${CMAKE_CURRENT_SOURCE_DIR}/cmake/common/bootstrap.cmake" NO_POLICY_SCOPE)

project(${_name} VERSION ${_version})

# Short git hash baked into the binary and logged on load, so a running
# instance can be matched back to a source tree with `git rev-parse
# --short=10 HEAD` instead of guessing from file dates.
execute_process(
  COMMAND git rev-parse --short=10 HEAD
  WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}"
  OUTPUT_VARIABLE RAKUSPACE_GIT_HASH
  OUTPUT_STRIP_TRAILING_WHITESPACE
  ERROR_QUIET
)
if(NOT RAKUSPACE_GIT_HASH)
  set(RAKUSPACE_GIT_HASH "unknown")
endif()

option(ENABLE_FRONTEND_API "Use obs-frontend-api for UI functionality" OFF)
option(ENABLE_QT "Use Qt functionality" OFF)

include(compilerconfig)
include(defaults)
include(helpers)

add_library(${CMAKE_PROJECT_NAME} MODULE)

find_package(libobs REQUIRED)
target_link_libraries(${CMAKE_PROJECT_NAME} PRIVATE OBS::libobs)

find_package(CURL REQUIRED)
target_link_libraries(${CMAKE_PROJECT_NAME} PRIVATE CURL::libcurl)

# The go-live glue needs the frontend streaming start/stop events, so the
# frontend API is a hard requirement for this plugin. ENABLE_FRONTEND_API is
# left on (see CMakePresets.json) so the legacy LibObs finder path in
# cmake/*/defaults.cmake also builds the OBS::obs-frontend-api target; the
# modern config package is tried here and the target is required either way.
if(NOT TARGET OBS::obs-frontend-api)
  find_package(obs-frontend-api REQUIRED)
endif()
target_link_libraries(${CMAKE_PROJECT_NAME} PRIVATE OBS::obs-frontend-api)

if(ENABLE_QT)
  find_package(Qt6 COMPONENTS Widgets Core REQUIRED)
  target_link_libraries(${CMAKE_PROJECT_NAME} PRIVATE Qt6::Core Qt6::Widgets)
  target_compile_options(
    ${CMAKE_PROJECT_NAME}
    PRIVATE $<$<C_COMPILER_ID:Clang,AppleClang>:-Wno-quoted-include-in-framework-header -Wno-comma>
  )
  set_target_properties(
    ${CMAKE_PROJECT_NAME}
    PROPERTIES AUTOMOC ON AUTOUIC ON AUTORCC ON
  )
endif()

target_sources(${CMAKE_PROJECT_NAME} PRIVATE src/plugin-main.cpp src/discord-rpc.cpp src/rakuspace-dock.cpp src/rakuspace-http.cpp src/rakuspace-config-store.cpp src/rakuspace-output.cpp)

target_compile_definitions(${CMAKE_PROJECT_NAME} PRIVATE RAKUSPACE_GIT_HASH="${RAKUSPACE_GIT_HASH}")

target_compile_features(${CMAKE_PROJECT_NAME} PRIVATE cxx_std_17)
set_target_properties(${CMAKE_PROJECT_NAME} PROPERTIES CXX_STANDARD 17 CXX_STANDARD_REQUIRED ON)
target_include_directories(${CMAKE_PROJECT_NAME} PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}/src")

set_target_properties_plugin(${CMAKE_PROJECT_NAME} PROPERTIES OUTPUT_NAME ${_name})

option(RAKUSPACE_BUILD_SMOKE "Build the standalone Discord RPC smoke test" OFF)
if(RAKUSPACE_BUILD_SMOKE)
  add_executable(rpc-smoke src/tools/rpc-smoke.cpp src/discord-rpc.cpp)
  target_include_directories(rpc-smoke PRIVATE src)
  target_compile_features(rpc-smoke PRIVATE cxx_std_17)
endif()
