cmake_minimum_required(VERSION 3.20)

project(qnx_pulse_agent
    VERSION 1.0.0
    DESCRIPTION "QNX-Pulse SDP 8.0 Target Companion Agent & Host Simulator"
    LANGUAGES C
)

set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)
set(CMAKE_C_EXTENSIONS OFF)

# Shared lock-free telemetry ring, traceprinter/NDJSON formatters, and watchdog
add_library(qnx_pulse_core STATIC
    src/telemetry_ring.c
)

target_include_directories(qnx_pulse_core
    PUBLIC
        "${CMAKE_CURRENT_SOURCE_DIR}/include"
        "${CMAKE_CURRENT_SOURCE_DIR}/src"
)

if(CMAKE_C_COMPILER_ID MATCHES "GNU|Clang|QCC")
    target_compile_options(qnx_pulse_core PRIVATE -Wall -Wextra -Werror)
endif()

if(CMAKE_SYSTEM_NAME STREQUAL "QNX")
    # Authentic QNX SDP 8.0 Resource Manager (/dev/qnxpulse)
    add_executable(qnx_pulse_agent
        src/qnx_pulse_agent.c
    )
    target_link_libraries(qnx_pulse_agent
        PRIVATE
            qnx_pulse_core
            slog2
            secpol
    )
    if(CMAKE_C_COMPILER_ID MATCHES "GNU|Clang|QCC")
        target_compile_options(qnx_pulse_agent PRIVATE -Wall -Wextra -Werror)
    endif()
    install(TARGETS qnx_pulse_agent RUNTIME DESTINATION bin)
else()
    # Host Simulation Mode (Windows MinGW / Linux / macOS)
    add_executable(qnx_pulse_agent_sim
        src/qnx_pulse_agent.c
    )
    target_link_libraries(qnx_pulse_agent_sim
        PRIVATE
            qnx_pulse_core
    )
    if(CMAKE_C_COMPILER_ID MATCHES "GNU|Clang")
        target_compile_options(qnx_pulse_agent_sim PRIVATE -Wall -Wextra -Werror)
    endif()

    include(CTest)
    if(BUILD_TESTING)
        add_executable(test_telemetry_ring
            tests/test_telemetry_ring.c
        )
        target_link_libraries(test_telemetry_ring
            PRIVATE
                qnx_pulse_core
        )
        if(CMAKE_C_COMPILER_ID MATCHES "GNU|Clang")
            target_compile_options(test_telemetry_ring PRIVATE -Wall -Wextra -Werror)
        endif()

        add_test(NAME telemetry_ring_unit_tests
            COMMAND test_telemetry_ring
        )
        add_test(NAME sim_inversion_traceprinter
            COMMAND qnx_pulse_agent_sim --scenario inversion --format traceprinter --stats
        )
        add_test(NAME sim_inversion_ndjson
            COMMAND qnx_pulse_agent_sim --scenario inversion --format ndjson --stats
        )
        add_test(NAME sim_healthy_traceprinter
            COMMAND qnx_pulse_agent_sim --scenario healthy --format traceprinter --stats
        )
    endif()
endif()
