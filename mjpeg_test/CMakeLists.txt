include(FetchContent)
cmake_minimum_required(VERSION 3.17)

# GLFW uses wayland-scanner to find out if the system uses wayland or not but I don't want to download it
find_program(WAYLAND_SCANNER_EXECUTABLE NAMES wayland-scanner)
if(NOT WAYLAND_SCANNER_EXECUTABLE)
  set(GLFW_BUILD_WAYLAND False)
endif()

project("stitcher preview")

set(CMAKE_CXX_STANDARD 23)

FetchContent_Declare(
        imgui-glfw-glad-glm
        GIT_REPOSITORY https://github.com/cmmw/imgui-glfw-glad-glm.git
)
FetchContent_MakeAvailable(imgui-glfw-glad-glm)

set(PYTHON_EXECUTABLE python3.14)
set(PYBIND11_FINDPYTHON ON)
find_package(pybind11 REQUIRED)
find_package(OpenCV REQUIRED)

add_executable(
    st
    "st.cc"
    "video_stitcher.cc"
    "video_stitcher.hpp"
    "MJPEGCapture.cc"
    "gl.h"
)
target_include_directories(st PUBLIC ${OpenCV_INCLUDE_DIRS} )
target_link_libraries(st glfw imgui glm glad ${OpenCV_LIBS} curl)
target_compile_definitions(st PUBLIC MEDIA_DIRECTORY="${CMAKE_SOURCE_DIR}/media/")

add_executable(
    test
    "test.cc"
    "MJPEGCapture.hpp"
    "MJPEGCapture.cc"
    "gl.h"
)

target_include_directories(test PUBLIC ${OpenCV_INCLUDE_DIRS} )
target_link_libraries(test ${OpenCV_LIBS} curl)

pybind11_add_module(video_stitcher python_bindings.cc video_stitcher.cc MJPEGCapture.cc)
target_include_directories(video_stitcher PRIVATE ${OpenCV_INCLUDE_DIRS})
target_link_libraries(video_stitcher PRIVATE ${OpenCV_LIBS} python3 curl)
set_target_properties(video_stitcher PROPERTIES PREFIX "" )
