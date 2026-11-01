cmake_minimum_required(VERSION 3.13)
project(afrig2p VERSION 0.1.0 LANGUAGES C)

option(AFRIG2P_BUILD_SHARED "Build the shared library (libafrig2p.so/.dylib)" ON)
option(AFRIG2P_BUILD_STATIC "Build the static library (libafrig2p.a)" ON)
option(AFRIG2P_BUILD_CLI "Build the afrig2p command-line tool" ON)

if(NOT CMAKE_BUILD_TYPE AND NOT CMAKE_CONFIGURATION_TYPES)
  set(CMAKE_BUILD_TYPE Release)
endif()

set(CMAKE_C_STANDARD 99)
set(CMAKE_C_STANDARD_REQUIRED ON)
set(CMAKE_C_VISIBILITY_PRESET hidden)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

# utf8proc is compiled into the library (vendored, MIT licence).
set(AFRIG2P_SOURCES
  src/afrig2p.c
  third_party/utf8proc/utf8proc.c)

function(afrig2p_configure tgt)
  target_include_directories(${tgt}
    PUBLIC $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include> $<INSTALL_INTERFACE:include>
    PRIVATE third_party/utf8proc)
  target_compile_definitions(${tgt} PRIVATE UTF8PROC_STATIC)
  if(CMAKE_C_COMPILER_ID MATCHES "GNU|Clang")
    target_compile_options(${tgt} PRIVATE
      $<$<COMPILE_LANGUAGE:C>:-Wall -Wextra>)
    set_source_files_properties(third_party/utf8proc/utf8proc.c
      PROPERTIES COMPILE_OPTIONS "-w")
  endif()
endfunction()

set(AFRIG2P_TARGETS)
if(AFRIG2P_BUILD_SHARED)
  add_library(afrig2p_shared SHARED ${AFRIG2P_SOURCES})
  afrig2p_configure(afrig2p_shared)
  target_compile_definitions(afrig2p_shared PUBLIC AFRIG2P_SHARED)
  set_target_properties(afrig2p_shared PROPERTIES OUTPUT_NAME afrig2p
    VERSION ${PROJECT_VERSION} SOVERSION ${PROJECT_VERSION_MAJOR})
  list(APPEND AFRIG2P_TARGETS afrig2p_shared)
endif()
if(AFRIG2P_BUILD_STATIC)
  add_library(afrig2p_static STATIC ${AFRIG2P_SOURCES})
  afrig2p_configure(afrig2p_static)
  set_target_properties(afrig2p_static PROPERTIES OUTPUT_NAME afrig2p)
  list(APPEND AFRIG2P_TARGETS afrig2p_static)
endif()

if(AFRIG2P_BUILD_CLI AND AFRIG2P_BUILD_STATIC)
  add_executable(afrig2p_cli tools/afrig2p_cli.c)
  target_link_libraries(afrig2p_cli PRIVATE afrig2p_static)
  set_target_properties(afrig2p_cli PROPERTIES OUTPUT_NAME afrig2p)
  list(APPEND AFRIG2P_TARGETS afrig2p_cli)
endif()

include(GNUInstallDirs)
install(TARGETS ${AFRIG2P_TARGETS}
  RUNTIME DESTINATION ${CMAKE_INSTALL_BINDIR}
  LIBRARY DESTINATION ${CMAKE_INSTALL_LIBDIR}
  ARCHIVE DESTINATION ${CMAKE_INSTALL_LIBDIR})
install(FILES include/afrig2p.h DESTINATION ${CMAKE_INSTALL_INCLUDEDIR})
