cmake_minimum_required(VERSION 3.18)
project(ai_navigation_assistant VERSION 1.0.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

# ---- Dependencies ----
# ONNX Runtime
if(NOT DEFINED ONNXRUNTIME_ROOT)
    set(ONNXRUNTIME_ROOT "/usr/local" CACHE PATH "ONNX Runtime install prefix")
endif()
find_library(ONNX_LIB onnxruntime PATHS ${ONNXRUNTIME_ROOT}/lib NO_DEFAULT_PATH)
if(NOT ONNX_LIB)
    find_library(ONNX_LIB onnxruntime)
endif()
find_path(ONNX_INCLUDE_DIR onnxruntime_cxx_api.h
    PATHS ${ONNXRUNTIME_ROOT}/include
    ${ONNXRUNTIME_ROOT}/include/onnxruntime
    /usr/include/onnxruntime
    /usr/local/include/onnxruntime
    NO_DEFAULT_PATH
)
if(NOT ONNX_INCLUDE_DIR)
    find_path(ONNX_INCLUDE_DIR onnxruntime_cxx_api.h)
endif()

# OpenCV
find_package(OpenCV REQUIRED COMPONENTS core imgproc highgui imgcodecs videoio)

# yaml-cpp
find_package(yaml-cpp QUIET)
if(NOT yaml-cpp_FOUND)
    # Fetch yaml-cpp if not installed
    include(FetchContent)
    FetchContent_Declare(yaml-cpp
        GIT_REPOSITORY https://github.com/jbeder/yaml-cpp.git
        GIT_TAG yaml-cpp-0.7.0
    )
    FetchContent_MakeAvailable(yaml-cpp)
endif()

# ---- Sources ----
set(SOURCES
    src/main.cpp
    src/pipeline.cpp
    src/detector.cpp
    src/depth_estimator.cpp
    src/tracker.cpp
    src/decision_engine.cpp
    src/direction.cpp
    src/frame_utils.cpp
    src/camera.cpp
)

set(HEADERS
    include/types.hpp
    include/pipeline.hpp
    include/detector.hpp
    include/depth_estimator.hpp
    include/tracker.hpp
    include/decision_engine.hpp
    include/direction.hpp
    include/frame_utils.hpp
    include/camera.hpp
)

# ---- Executable ----
add_executable(${PROJECT_NAME} ${SOURCES} ${HEADERS})
target_include_directories(${PROJECT_NAME} PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/include
    ${OpenCV_INCLUDE_DIRS}
    ${ONNX_INCLUDE_DIR}
)

target_link_libraries(${PROJECT_NAME} PRIVATE
    ${OpenCV_LIBS}
    ${ONNX_LIB}
    yaml-cpp::yaml-cpp
)

# Platform-specific: pthread, rt
if(UNIX)
    target_link_libraries(${PROJECT_NAME} PRIVATE pthread rt)
endif()

# ---- Install ----
install(TARGETS ${PROJECT_NAME} DESTINATION bin)

# ---- Copy models to build directory ----
file(COPY ${CMAKE_CURRENT_SOURCE_DIR}/models/ DESTINATION ${CMAKE_BINARY_DIR}/models/)

message(STATUS "AI Navigation Assistant (Mobile C++ Port)")
message(STATUS "  ONNX Runtime: ${ONNX_INCLUDE_DIR} / ${ONNX_LIB}")
message(STATUS "  OpenCV:       ${OpenCV_DIR}")
message(STATUS "  Models:       ${CMAKE_SOURCE_DIR}/models/")
