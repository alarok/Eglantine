// SPDX-FileCopyrightText: Copyright 2026 Eden Emulator Project
// SPDX-License-Identifier: GPL-3.0-or-later

// SPDX-FileCopyrightText: Copyright 2023 yuzu Emulator Project
// SPDX-License-Identifier: GPL-2.0-or-later

#include <cstdlib>

#include <renderdoc_app.h>

#include "common/assert.h"
#include "common/dynamic_library.h"
#include "core/tools/renderdoc.h"

#ifdef _WIN32
#include <windows.h>
#else
#include <dlfcn.h>
#endif

namespace Tools {

RenderdocAPI::RenderdocAPI() {
#ifdef WIN32
    // EDEN_RENDERDOC_DLL=<path>: load RenderDoc with no injection, before the Vulkan instance exists.
    if (const char* path = std::getenv("EDEN_RENDERDOC_DLL")) {
        LoadLibraryA(path);
    }
    if (HMODULE mod = GetModuleHandleA("renderdoc.dll")) {
        void* proc = reinterpret_cast<void*>(GetProcAddress(mod, "RENDERDOC_GetAPI"));
        if (proc) {
            const auto RENDERDOC_GetAPI = reinterpret_cast<pRENDERDOC_GetAPI>(proc);
            const s32 ret = RENDERDOC_GetAPI(eRENDERDOC_API_Version_1_6_0, (void**)&rdoc_api);
            ASSERT(ret == 1);
            // EDEN_RENDERDOC_PATH=<path template>: the default folder is on the system disk.
            if (const char* capture_path = std::getenv("EDEN_RENDERDOC_PATH")) {
                static_cast<RENDERDOC_API_1_6_0*>(rdoc_api)->SetCaptureFilePathTemplate(capture_path);
            }
        }
    }
#elif defined(__HAIKU__)
    // no rtld on haiku
#else
#ifdef __ANDROID__
    static constexpr const char RENDERDOC_LIB[] = "libVkLayer_GLES_RenderDoc.so";
#else
    static constexpr const char RENDERDOC_LIB[] = "librenderdoc.so";
#endif
    if (void* mod = dlopen(RENDERDOC_LIB, RTLD_NOW | RTLD_NOLOAD)) {
        const auto RENDERDOC_GetAPI =
            reinterpret_cast<pRENDERDOC_GetAPI>(dlsym(mod, "RENDERDOC_GetAPI"));
        const s32 ret = RENDERDOC_GetAPI(eRENDERDOC_API_Version_1_6_0, (void**)&rdoc_api);
        ASSERT(ret == 1);
    }
#endif
}

RenderdocAPI::~RenderdocAPI() = default;

void RenderdocAPI::ToggleCapture() {
    if (!rdoc_api) [[unlikely]] {
        return;
    }

    auto* api = static_cast<RENDERDOC_API_1_6_0*>(rdoc_api);
    if (!is_capturing) {
        api->StartFrameCapture(NULL, NULL);
    } else {
        api->EndFrameCapture(NULL, NULL);
    }
    is_capturing = !is_capturing;
}

} // namespace Tools
