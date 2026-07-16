cmake_minimum_required(VERSION 3.22)

project(XBJuceVst3Host VERSION 0.1.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

set(XB_JUCE_DIR "" CACHE PATH "Path to a local JUCE checkout")
set(XB_JUCE_FETCH OFF CACHE BOOL "Download JUCE with CMake FetchContent when no local JUCE is configured")
set(XB_JUCE_GIT_TAG "master" CACHE STRING "JUCE git tag/branch used when XB_JUCE_FETCH is ON")
set(
    XB_JUCE_HOST_OUTPUT_DIR
    "${CMAKE_CURRENT_LIST_DIR}/../../engines/juce-vst3-host"
    CACHE PATH
    "Directory where xb-juce-vst3-host is emitted"
)

if(NOT XB_JUCE_DIR AND DEFINED ENV{XB_JUCE_DIR})
    set(XB_JUCE_DIR "$ENV{XB_JUCE_DIR}")
endif()

if(NOT XB_JUCE_DIR AND DEFINED ENV{JUCE_DIR})
    set(XB_JUCE_DIR "$ENV{JUCE_DIR}")
endif()

if(XB_JUCE_DIR)
    file(TO_CMAKE_PATH "${XB_JUCE_DIR}" XB_JUCE_DIR)
    if(EXISTS "${XB_JUCE_DIR}/CMakeLists.txt")
        add_subdirectory("${XB_JUCE_DIR}" "${CMAKE_BINARY_DIR}/juce")
    else()
        list(APPEND CMAKE_PREFIX_PATH "${XB_JUCE_DIR}")
        find_package(JUCE CONFIG QUIET)
    endif()
else()
    find_package(JUCE CONFIG QUIET)
endif()

if(NOT TARGET juce::juce_audio_processors)
    if(XB_JUCE_FETCH)
        include(FetchContent)
        FetchContent_Declare(
            JUCE
            GIT_REPOSITORY https://github.com/juce-framework/JUCE.git
            GIT_TAG "${XB_JUCE_GIT_TAG}"
        )
        FetchContent_MakeAvailable(JUCE)
    else()
        message(FATAL_ERROR
            "JUCE was not found. Set XB_JUCE_DIR/JUCE_DIR to a local JUCE checkout, "
            "or configure with -DXB_JUCE_FETCH=ON.")
    endif()
endif()

juce_add_console_app(xb-juce-vst3-host
    PRODUCT_NAME "XB JUCE VST3 Host"
    VERSION "${PROJECT_VERSION}"
)

target_sources(xb-juce-vst3-host PRIVATE
    src/Main.cpp
)

target_compile_definitions(xb-juce-vst3-host PRIVATE
    JUCE_PLUGINHOST_VST3=1
    JUCE_USE_CURL=0
    JUCE_WEB_BROWSER=0
    JUCE_MODAL_LOOPS_PERMITTED=1
    JUCE_DISPLAY_SPLASH_SCREEN=0
)

target_link_libraries(xb-juce-vst3-host PRIVATE
    juce::juce_audio_basics
    juce::juce_audio_devices
    juce::juce_audio_formats
    juce::juce_audio_processors
    juce::juce_dsp
    juce::juce_events
    juce::juce_gui_extra
    juce::juce_recommended_config_flags
    juce::juce_recommended_warning_flags
)

set_target_properties(xb-juce-vst3-host PROPERTIES
    RUNTIME_OUTPUT_DIRECTORY "${XB_JUCE_HOST_OUTPUT_DIR}"
)

foreach(config DEBUG RELEASE RELWITHDEBINFO MINSIZEREL)
    set_target_properties(xb-juce-vst3-host PROPERTIES
        "RUNTIME_OUTPUT_DIRECTORY_${config}" "${XB_JUCE_HOST_OUTPUT_DIR}"
    )
endforeach()
