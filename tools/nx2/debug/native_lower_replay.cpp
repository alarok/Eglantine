// SPDX-FileCopyrightText: Copyright 2026 Eden Emulator Project
// SPDX-License-Identifier: GPL-3.0-or-later

#include <cstddef>
#include <cstdint>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <vector>

#include "shader_recompiler/frontend/ampere/lower_to_maxwell.h"

namespace {
using Shader::Ampere::Instruction;

constexpr std::size_t MaxInstructions = 65536;
constexpr std::size_t MaxBytes = MaxInstructions * sizeof(Instruction);

int Replay(const char* path) {
    std::ifstream file(path, std::ios::binary | std::ios::ate);
    if (!file) {
        std::cerr << "Cannot open shader dump: " << path << '\n';
        return 2;
    }

    const std::streamoff size = file.tellg();
    if (size <= 0) {
        std::cerr << "Shader dump is empty or its size cannot be read.\n";
        return 2;
    }
    if (static_cast<std::uint64_t>(size) > MaxBytes) {
        std::cerr << "Shader dump exceeds " << MaxInstructions << " instructions.\n";
        return 2;
    }
    if (size % sizeof(Instruction) != 0) {
        std::cerr << "Shader dump size is not a multiple of 16 bytes.\n";
        return 2;
    }

    std::vector<Instruction> code(static_cast<std::size_t>(size) / sizeof(Instruction));
    file.seekg(0);
    if (!file.read(reinterpret_cast<char*>(code.data()), static_cast<std::streamsize>(size))) {
        std::cerr << "Cannot read the full shader dump.\n";
        return 2;
    }

    const auto lowered = Shader::Ampere::LowerToMaxwell(code);
    if (!lowered) {
        const std::size_t offset = lowered.error_offset;
        std::cerr << "Rejected at byte 0x" << std::hex << offset << ": " << lowered.error << '\n';
        if (offset % sizeof(Instruction) != 0 || offset / sizeof(Instruction) >= code.size()) {
            std::cerr << "The lowerer returned an invalid source offset.\n";
            return 2;
        }
        const auto& instruction = code[offset / sizeof(Instruction)];
        std::cerr << "Words:";
        for (const u32 word : instruction.words) {
            std::cerr << ' ' << std::setw(8) << std::setfill('0') << word;
        }
        std::cerr << '\n';
        return 1;
    }

    std::cout << "Lowering succeeded: " << code.size() << " native instructions became "
              << lowered.instructions.size() << " Maxwell instructions. No GPU work was run.\n";
    return 0;
}
} // namespace

int main(int argc, char* argv[]) {
    if (argc != 2) {
        std::cerr << "Usage: native_lower_replay <native-shader.bin>\n";
        return 2;
    }
    return Replay(argv[1]);
}
