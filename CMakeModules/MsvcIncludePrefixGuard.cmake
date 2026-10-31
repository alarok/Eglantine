# SPDX-FileCopyrightText: Copyright 2026 Eden Emulator Project
# SPDX-License-Identifier: GPL-3.0-or-later

# Ninja finds the headers of an object in the /showIncludes output of MSVC.
# It compares the bytes of each line with the msvc_deps_prefix value in rules.ninja.
# A localized prefix can have letters outside ASCII, for example the Spanish "inclusión".
# MSVC writes these letters in the output code page of the console that runs the build.
# CMake writes them in the code page of the console that runs the configure step.
# If the bytes differ, Ninja records no headers, and a header change does not rebuild the object.
# Ninja gives no error, so this check stops the build before the first compile.

if (CMAKE_SCRIPT_MODE_FILE)
    file(READ "${RULES_FILE}" rules LIMIT 8192 HEX)
    string(HEX "msvc_deps_prefix = " marker)
    string(FIND "${rules}" "${marker}" start)
    if (start EQUAL -1)
        return()
    endif()
    string(LENGTH "${marker}" marker_length)
    math(EXPR start "${start} + ${marker_length}")
    string(SUBSTRING "${rules}" ${start} -1 rules)
    string(REGEX MATCHALL ".." rule_bytes "${rules}")
    list(FIND rule_bytes "0a" end)
    list(SUBLIST rule_bytes 0 ${end} prefix_bytes)
    list(JOIN prefix_bytes "" expected)
    # rules.ninja has Windows line ends.
    string(REGEX REPLACE "0d$" "" expected "${expected}")

    file(WRITE "${WORK_DIR}/probe.h" "")
    file(WRITE "${WORK_DIR}/probe.cpp" "#include \"probe.h\"\n")
    execute_process(COMMAND "${COMPILER}" /nologo /showIncludes /Zs probe.cpp
        WORKING_DIRECTORY "${WORK_DIR}"
        OUTPUT_VARIABLE output
        ERROR_VARIABLE output
        ENCODING NONE)
    string(HEX "${output}" actual)
    string(FIND "${actual}" "${expected}" found)
    if (found EQUAL -1)
        message(FATAL_ERROR
            "MSVC does not write the include prefix that rules.ninja expects (${expected}).\n"
            "Ninja would record no headers, and header changes would not rebuild the objects.\n"
            "The configure step and this build used different console code pages.\n"
            "Run 'chcp 65001' in this console and build again.\n"
            "If this error stays, run 'cmake --fresh' with your options after 'chcp 65001'.")
    endif()
    return()
endif()

function(add_prefix_guard_to_targets directory)
    get_property(targets DIRECTORY "${directory}" PROPERTY BUILDSYSTEM_TARGETS)
    foreach (target IN LISTS targets)
        get_target_property(type ${target} TYPE)
        if (type MATCHES "^(STATIC_LIBRARY|SHARED_LIBRARY|MODULE_LIBRARY|OBJECT_LIBRARY|EXECUTABLE)$")
            add_dependencies(${target} check_msvc_include_prefix)
        endif()
    endforeach()

    get_property(subdirectories DIRECTORY "${directory}" PROPERTY SUBDIRECTORIES)
    foreach (subdirectory IN LISTS subdirectories)
        add_prefix_guard_to_targets("${subdirectory}")
    endforeach()
endfunction()

# An ASCII prefix has the same bytes in each code page, so it needs no check.
string(REGEX MATCH "[^ -~]" non_ascii "${CMAKE_CXX_CL_SHOWINCLUDES_PREFIX}")
if (MSVC AND CMAKE_GENERATOR STREQUAL "Ninja" AND non_ascii)
    # This folder must not have the name of the target. Ninja reads the target's output file
    # CMakeFiles/check_msvc_include_prefix, and a folder at that path stops the check from running.
    set(work_dir "${CMAKE_BINARY_DIR}/CMakeFiles/check_msvc_include_prefix.dir")
    add_custom_target(check_msvc_include_prefix
        COMMAND "${CMAKE_COMMAND}"
            "-DRULES_FILE=${CMAKE_BINARY_DIR}/CMakeFiles/rules.ninja"
            "-DCOMPILER=${CMAKE_CXX_COMPILER}"
            "-DWORK_DIR=${work_dir}"
            -P "${CMAKE_CURRENT_LIST_FILE}"
        COMMENT "Checking the MSVC include prefix"
        VERBATIM)
    add_prefix_guard_to_targets("${CMAKE_SOURCE_DIR}")
endif()
