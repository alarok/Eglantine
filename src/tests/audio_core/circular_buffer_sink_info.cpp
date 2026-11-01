// SPDX-FileCopyrightText: Copyright 2026 Eden Emulator Project
// SPDX-License-Identifier: GPL-3.0-or-later

#include <algorithm>
#include <span>

#include <catch2/catch_test_macros.hpp>

#include "audio_core/common/common.h"
#include "audio_core/renderer/memory/pool_mapper.h"
#include "audio_core/renderer/sink/circular_buffer_sink_info.h"

TEST_CASE("Circular buffer sink cleanup does not treat its state as a device sink",
          "[audio_core]") {
    using namespace AudioCore::Renderer;

    CircularBufferSinkInfo sink;
    SinkInfoBase::InParameter input{};
    input.in_use = true;
    input.circular_buffer.in_use = true;
    input.circular_buffer.cpu_address = 0x1000;
    input.circular_buffer.size = 0x20000;
    input.circular_buffer.input_count = 1;
    input.circular_buffer.sample_count = 1;
    input.circular_buffer.format = AudioCore::SampleFormat::PcmInt16;

    const PoolMapper pool_mapper{nullptr, false};
    BehaviorInfo::ErrorInfo error{};
    SinkInfoBase::OutStatus output{};
    sink.Update(error, output, input, pool_mapper);
    for (u32 sample = 0; sample < 32768; ++sample) {
        sink.UpdateForCommandGeneration();
    }

    const auto* state = reinterpret_cast<const SinkInfoBase::CircularBufferState*>(sink.GetState());
    REQUIRE(state->current_pos == 0x10000);

    sink.CleanUp();

    CHECK(sink.GetType() == SinkInfoBase::Type::Invalid);
    CHECK(std::ranges::all_of(std::span{sink.GetState(), sizeof(SinkInfoBase::CircularBufferState)},
                              [](u8 byte) { return byte == 0; }));
}
