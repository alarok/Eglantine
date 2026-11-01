// SPDX-FileCopyrightText: Copyright 2026 Eden Emulator Project
// SPDX-License-Identifier: GPL-3.0-or-later

#include <memory>

#include <catch2/catch_test_macros.hpp>

#include "audio_core/audio_in_manager.h"
#include "audio_core/audio_out_manager.h"
#include "audio_core/in/audio_in.h"
#include "audio_core/out/audio_out.h"
#include "core/core.h"
#include "core/hle/result.h"

namespace {

template <typename Manager, typename Session, typename State>
void CheckSessionLifetime(State stopped) {
    Core::System system;
    auto manager = std::make_shared<Manager>(system);
    size_t session_id{};
    REQUIRE(manager->AcquireSessionId(session_id).IsSuccess());
    auto session = std::make_shared<Session>(system, *manager, nullptr, session_id);
    manager->sessions[session_id] = session;
    const std::weak_ptr<Manager> weak_manager = manager;

    manager.reset();
    const bool retained = !weak_manager.expired();
    CHECK(retained);
    if (!retained) {
        return;
    }
    CHECK(session->GetState() == stopped);
    session->Free();
    session.reset();
    CHECK(weak_manager.expired());
}

} // Anonymous namespace

TEST_CASE("Stopped audio sessions survive their service manager", "[audio_core]") {
    SECTION("Output") {
        CheckSessionLifetime<AudioCore::AudioOut::Manager, AudioCore::AudioOut::Out>(
            AudioCore::AudioOut::State::Stopped);
    }
    SECTION("Input") {
        CheckSessionLifetime<AudioCore::AudioIn::Manager, AudioCore::AudioIn::In>(
            AudioCore::AudioIn::State::Stopped);
    }
}
