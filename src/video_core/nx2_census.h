// SPDX-FileCopyrightText: Copyright 2026 Eden Emulator Project
// SPDX-License-Identifier: GPL-3.0-or-later

#pragma once

#include <algorithm>
#include <array>
#include <atomic>
#include <cstdlib>
#include <mutex>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <vector>

#include "common/common_types.h"
#include "common/logging.h"
#include "video_core/nx2_profile.h"

// EDEN_NX2_DRAW_CENSUS: every 10 s, log how many draws and dispatches the engines ran and how many
// did nothing. A draw with no vertices or no copies fails with no error, so only a count shows it.
// A macro that gets a record with 0 copies draws nothing at all, so the macros count too.
// Also log each shader program with stores the recompiler cannot map. See tools/nx2/debug/README.md.
namespace VideoCommon::Nx2Census {

// Read once, at first use and not at program start: main() reads nx2_switches.txt first.
inline bool Enabled() {
    static const bool enabled = std::getenv("EDEN_NX2_DRAW_CENSUS") != nullptr;
    return enabled;
}

enum class Count : u32 {
    Direct,
    Indexed,
    MacroIndirect, ///< Draws of a macro that got a draw record, or read guest memory first
    ApiIndirect,   ///< Host indirect draws. Their counts are in GPU memory and are not read here
    Failed,        ///< No pipeline, or its configuration failed
    PredicateOff,  ///< Of the draws above: the render condition dropped the draw
    ZeroDirect,
    ZeroIndexed,
    ZeroMacroIndirect,
    MacroRecordNoDraw, ///< Macros with a draw record that drew nothing: a record with 0 copies
    Dispatches,
    DispatchesFailed,
    DrawsSampling, ///< Draws with one or more images that have no memory or are only partly backed
    NullViews,
    Unbacked,  ///< Distinct images too big to back
    Unwritten, ///< Distinct images over sparse blocks nobody wrote
    ByLayer,   ///< Distinct images with memory for only the layers written
    Size,
};

inline std::array<std::atomic<u64>, static_cast<size_t>(Count::Size)> g_counts{};

inline void Add(Count count, u64 amount = 1) {
    g_counts[static_cast<size_t>(count)].fetch_add(amount, std::memory_order_relaxed);
}

/// Indexed by macro start position, as in the "Native MME" log lines (native_code holds 0x1000
/// instructions). The thread that reports is not always the thread that counts.
inline constexpr size_t MacroSlots = 0x1000;
inline std::array<std::atomic<u32>, MacroSlots> g_macro_zero_draws{};
inline std::array<std::atomic<u32>, MacroSlots> g_macro_no_draws{};

/// The macro in progress on the thread that runs its draws. With the split thread and macros on
/// the front, deferred calls set it on the back. See Maxwell3D::FrontRunMacro.
struct MacroTag {
    u32 start{};
    bool active{};
    bool from_record{};
    bool read_memory{};
    bool drew{};
};
inline thread_local MacroTag t_macro;
inline thread_local bool t_next_macro_from_record{};

/// The next macro's parameters continue in a command entry of their own. This is how a guest
/// gives a macro an indirect draw record: a small entry that points at the record itself.
inline void NextMacroFromRecord() {
    t_next_macro_from_record = true;
}

inline void MacroBegin(u32 start) {
    t_macro = {.start = static_cast<u32>(start % MacroSlots), .active = true,
               .from_record = t_next_macro_from_record};
    t_next_macro_from_record = false;
}

inline void MacroRead() {
    t_macro.read_memory = true;
}

inline void MacroEnd() {
    auto& macro = t_macro;
    if (macro.active && (macro.from_record || macro.read_memory) && !macro.drew) {
        Add(Count::MacroRecordNoDraw);
        g_macro_no_draws[macro.start].fetch_add(1, std::memory_order_relaxed);
    }
    macro = {};
}

/// `vertices` and `instances` are the values the rasterizer gives to the host draw call.
inline void CountDraw(bool indexed, u32 vertices, u32 instances, bool execute) {
    auto& macro = t_macro;
    macro.drew = true;
    const bool from_record = macro.active && (macro.from_record || macro.read_memory);
    Add(from_record ? Count::MacroIndirect : indexed ? Count::Indexed : Count::Direct);
    if (!execute) {
        Add(Count::PredicateOff);
    }
    if (vertices != 0 && instances != 0) {
        return;
    }
    Add(from_record ? Count::ZeroMacroIndirect : indexed ? Count::ZeroIndexed : Count::ZeroDirect);
    if (macro.active) {
        g_macro_zero_draws[macro.start].fetch_add(1, std::memory_order_relaxed);
    }
}

inline void CountApiIndirect(bool execute) {
    t_macro.drew = true;
    Add(Count::ApiIndirect);
    if (!execute) {
        Add(Count::PredicateOff);
    }
}

enum class ImageKind : u32 { TooBig, Unwritten, ByLayer };

/// Changes when a report starts a new window, so each image counts once per window.
inline std::atomic<u64> g_window_epoch{};

inline constexpr std::array<const char*, 3> image_kind_names{"too big to back", "unwritten sparse",
                                                             "backed by layer"};

/// One sampled image with no device memory, or memory for only some layers. Called for each such
/// image of each draw: the first time, it logs the image. The log has a limit of 256 images.
inline void CountImage(GPUVAddr address, ImageKind kind, u32 width, u32 height, u32 layers,
                       u32 format) {
    static std::mutex mutex;
    static std::unordered_set<u64> logged;
    static std::unordered_set<u64> window;
    static u64 window_epoch{};
    const u64 key = address ^ (u64{static_cast<u32>(kind)} << 56);
    std::scoped_lock lock{mutex};
    if (const u64 epoch = g_window_epoch.load(std::memory_order_relaxed); epoch != window_epoch) {
        window_epoch = epoch;
        window.clear();
    }
    if (window.insert(key).second) {
        Add(kind == ImageKind::TooBig      ? Count::Unbacked
            : kind == ImageKind::Unwritten ? Count::Unwritten
                                           : Count::ByLayer);
    }
    if (logged.size() < 256 && logged.insert(key).second) {
        LOG_INFO(HW_GPU, "Census image: {:#x} {}x{}x{} format={} {}", address, width, height, layers,
                 format, image_kind_names[static_cast<size_t>(kind)]);
    }
}

/// One line for each program with stores that can reach only the buffers the program already binds.
/// A store through an address loaded from memory is the usual case: it writes nothing and logs
/// nothing.
inline void LostStores(u64 program, size_t stage, u32 lost, u32 total, size_t buffers) {
    if (lost == 0) {
        return;
    }
    static std::mutex mutex;
    static std::unordered_set<u64> logged;
    std::scoped_lock lock{mutex};
    if (logged.insert(program).second) {
        LOG_INFO(HW_GPU,
                 "Lost shader stores: program {:016x} stage {}: {} of {} stores not mapped, {} "
                 "buffers bound",
                 program, stage, lost, total, buffers);
    }
}

/// Called by the GPU thread and the split's back thread between commands: the first to see the
/// window end logs and resets the totals.
inline void Report() {
    if (!Enabled()) {
        return;
    }
    static std::atomic<u64> window_start{};
    const u64 now = Nx2Profile::Now();
    u64 start = window_start.load(std::memory_order_relaxed);
    if (start == 0) {
        window_start.compare_exchange_strong(start, now, std::memory_order_relaxed);
        return;
    }
    // EDEN_NX2_DRAW_CENSUS_SECONDS: a shorter window finds a short event, such as a black scene.
    static const u64 window_ns = [] {
        const char* value = std::getenv("EDEN_NX2_DRAW_CENSUS_SECONDS");
        const u64 seconds = value != nullptr ? std::strtoull(value, nullptr, 10) : 0ULL;
        return (seconds != 0 ? seconds : 10ULL) * 1'000'000'000ULL;
    }();
    if (now - start < window_ns ||
        !window_start.compare_exchange_strong(start, now, std::memory_order_relaxed)) {
        return;
    }
    g_window_epoch.fetch_add(1, std::memory_order_relaxed);
    const auto take = [](Count count) {
        return g_counts[static_cast<size_t>(count)].exchange(0, std::memory_order_relaxed);
    };
    const u64 direct = take(Count::Direct);
    const u64 indexed = take(Count::Indexed);
    const u64 macro_indirect = take(Count::MacroIndirect);
    const u64 api_indirect = take(Count::ApiIndirect);
    LOG_INFO(HW_GPU, "Census window={:.1f} s", static_cast<double>(now - start) / 1e9);
    LOG_INFO(HW_GPU,
             "Census draws: total={} direct={} indexed={} macro_indirect={} api_indirect={} "
             "failed={} predicate_off={}",
             direct + indexed + macro_indirect + api_indirect, direct, indexed, macro_indirect,
             api_indirect, take(Count::Failed), take(Count::PredicateOff));
    LOG_INFO(HW_GPU, "Census zero draws: direct={} indexed={} macro_indirect={} macro_record_no_draw={}",
             take(Count::ZeroDirect), take(Count::ZeroIndexed), take(Count::ZeroMacroIndirect),
             take(Count::MacroRecordNoDraw));

    struct MacroRow {
        u32 start;
        u32 zero;
        u32 no_draw;
    };
    std::vector<MacroRow> macros;
    for (u32 slot = 0; slot < MacroSlots; ++slot) {
        const u32 zero = g_macro_zero_draws[slot].exchange(0, std::memory_order_relaxed);
        const u32 no_draw = g_macro_no_draws[slot].exchange(0, std::memory_order_relaxed);
        if (zero != 0 || no_draw != 0) {
            macros.push_back({slot, zero, no_draw});
        }
    }
    const size_t top = (std::min)(macros.size(), size_t{5});
    std::partial_sort(macros.begin(), macros.begin() + top, macros.end(),
                      [](const MacroRow& a, const MacroRow& b) {
                          return u64{a.zero} + a.no_draw > u64{b.zero} + b.no_draw;
                      });
    std::string top_line;
    for (size_t i = 0; i < top; ++i) {
        top_line += fmt::format("{}{:#x} zero={} no_draw={}", i != 0 ? "; " : "", macros[i].start,
                                macros[i].zero, macros[i].no_draw);
    }
    LOG_INFO(HW_GPU, "Census top macros: {}", top_line.empty() ? "none" : top_line);

    LOG_INFO(HW_GPU, "Census dispatches: total={} failed={}", take(Count::Dispatches),
             take(Count::DispatchesFailed));
    LOG_INFO(HW_GPU, "Census images: unbacked={} unwritten={} by_layer={} null_views={} draws_sampling={}",
             take(Count::Unbacked), take(Count::Unwritten), take(Count::ByLayer),
             take(Count::NullViews), take(Count::DrawsSampling));
}

} // namespace VideoCommon::Nx2Census
