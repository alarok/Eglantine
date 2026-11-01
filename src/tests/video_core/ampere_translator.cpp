// SPDX-License-Identifier: GPL-3.0-or-later

#include <array>
#include <bit>
#include <ios>
#include <map>
#include <span>
#include <utility>
#include <vector>
#include <catch2/catch_test_macros.hpp>

#include "shader_recompiler/frontend/ampere/lower_to_maxwell.h"

// These tests run the lowered Maxwell words and check the result that the native instruction asks
// for. The evaluator reads each field where the Maxwell translator reads it
// (frontend/maxwell/translate/impl). The expected values are hand-computed from the meaning of the
// native instruction, not from the lowering.
namespace {
using Shader::Ampere::Instruction;
using Shader::Ampere::LowerToMaxwell;

constexpr Instruction EXIT{{0x0000794d, 0, 0x03800000, 0}};
constexpr u32 RZ = 255;

u32 Field(u64 word, u32 offset, u32 count) {
    return static_cast<u32>((word >> offset) & ((u64{1} << count) - 1));
}

// F2F keeps the low 16 bits of its source: a register here holds an opaque half.
struct Evaluator {
    std::array<u32, 256> regs{};
    std::array<bool, 8> preds{};
    std::map<u32, u32> cbuf;

    u32 Read(u32 reg) const {
        return reg == RZ ? 0 : regs[reg];
    }

    void Write(u32 reg, u32 value) {
        if (reg != RZ) regs[reg] = value;
    }

    void Add(u64 word, u32 operand_b) {
        const bool neg_b = Field(word, 48, 1) != 0;
        const bool neg_a = Field(word, 49, 1) != 0;
        const bool po = neg_a && neg_b; // integer_add.cpp: both bits together mean .PO.
        u32 a = Read(Field(word, 8, 8));
        u32 b = operand_b;
        if (neg_a && !po) a = 0U - a;
        if (neg_b && !po) b = 0U - b;
        Write(Field(word, 0, 8), a + b + (po ? 1U : 0U));
    }

    void Run(const std::vector<u64>& words) {
        for (const u64 word : words) {
            const u32 high = static_cast<u32>(word >> 51);
            const u32 dest = Field(word, 0, 8);
            const u32 reg_a = Field(word, 8, 8);
            const u32 reg_b = Field(word, 20, 8);
            if (Field(word, 60, 4) == 0 && Field(word, 52, 8) == 0x10) { // MOV32I
                Write(dest, Field(word, 20, 32));
            } else if (high == (0x5c10000000000000ULL >> 51)) { // IADD
                Add(word, Read(reg_b));
            } else if (high == (0x5c18000000000000ULL >> 51)) { // ISCADD
                REQUIRE(Field(word, 48, 2) == 0);
                Write(dest, (Read(reg_a) << Field(word, 39, 5)) + Read(reg_b));
            } else if (high == (0x5c28000000000000ULL >> 51)) { // SHR
                const u32 shift = Read(reg_b);
                const bool wrapped = Field(word, 39, 1) != 0;
                if (wrapped) {
                    Write(dest, Read(reg_a) >> (shift & 31));
                } else {
                    Write(dest, shift < 32 ? Read(reg_a) >> shift : 0);
                }
            } else if (high == (0x5c98000000000000ULL >> 51)) { // MOV
                Write(dest, Read(reg_b));
            } else if (high == (0x4c98000000000000ULL >> 51)) { // MOV from a constant buffer
                Write(dest, cbuf.at(Field(word, 20, 14) * 4));
            } else if (high == (0x5ca8000000000000ULL >> 51)) { // F2F
                Write(dest, Read(reg_b) & 0xffff);
            } else if (high == (0x5cb8000000000000ULL >> 51)) { // I2F
                const u32 int_format = Field(word, 10, 2);
                REQUIRE(int_format <= 1);
                const u32 width = int_format == 0 ? 8 : 16;
                const u32 selector = Field(word, 41, 2);
                const u32 raw = (Read(reg_b) >> (selector * 8)) & ((u32{1} << width) - 1);
                const bool is_signed = Field(word, 13, 1) != 0;
                const s32 integer = is_signed && (raw & (u32{1} << (width - 1)))
                                        ? static_cast<s32>(raw) - (s32{1} << width)
                                        : static_cast<s32>(raw);
                const float value = is_signed ? static_cast<float>(integer)
                                              : static_cast<float>(raw);
                Write(dest, std::bit_cast<u32>(value));
            } else if (high == (0x5ca0000000000000ULL >> 51)) { // SEL
                const u32 pred = Field(word, 39, 3);
                const bool taken = (pred == 7 || preds[pred]) != (Field(word, 42, 1) != 0);
                Write(dest, taken ? Read(reg_a) : Read(reg_b));
            } else if (high == (0x5b60000000000000ULL >> 51)) { // ISETP
                REQUIRE(Field(word, 49, 3) == 1); // less than
                REQUIRE(Field(word, 48, 1) == 0); // unsigned
                preds[Field(word, 3, 3)] = Read(reg_a) < Read(reg_b);
            } else if (high == (0x5bb0000000000000ULL >> 51)) { // FSETP
                REQUIRE(Field(word, 48, 4) == 1); // less than
                REQUIRE(Field(word, 45, 2) == 0); // and
                REQUIRE(Field(word, 39, 4) == 7); // PT
                REQUIRE(Field(word, 6, 2) == 0);
                REQUIRE(Field(word, 43, 2) == 0);
                const bool result = std::bit_cast<float>(Read(reg_a)) < std::bit_cast<float>(Read(reg_b));
                preds[Field(word, 3, 3)] = result;
                preds[Field(word, 0, 3)] = !result;
            } else if (word >> 52 == 0xe30) { // EXIT
                return;
            } else {
                FAIL("the evaluator does not know the word " << std::hex << word);
            }
        }
    }
};

std::vector<u64> Lower(std::span<const Instruction> code) {
    const auto lowered = LowerToMaxwell(code);
    INFO(lowered.error);
    REQUIRE(static_cast<bool>(lowered));
    return lowered.instructions;
}

TEST_CASE("Ampere I2F U16 rejects invalid source selectors", "[video_core][ampere]") {
    const std::array<Instruction, 2> low{
        {{{0x00007306, 0x00000001, 0x00101000, 0x000fe200}}, EXIT}};
    const std::array<Instruction, 2> high{
        {{{0x00007306, 0x10000001, 0x00101000, 0x000fe200}}, EXIT}};
    const std::array<Instruction, 2> invalid2{
        {{{0x00007306, 0x20000001, 0x00101000, 0x000fe200}}, EXIT}};
    const std::array<Instruction, 2> invalid3{
        {{{0x00007306, 0x30000001, 0x00101000, 0x000fe200}}, EXIT}};

    CHECK(static_cast<bool>(LowerToMaxwell(low)));
    CHECK(static_cast<bool>(LowerToMaxwell(high)));
    CHECK_FALSE(static_cast<bool>(LowerToMaxwell(invalid2)));
    CHECK_FALSE(static_cast<bool>(LowerToMaxwell(invalid3)));
}

TEST_CASE("Ampere signed I2F S16 converts the selected integer exactly",
          "[video_core][ampere]") {
    // ptxas 12.6 / nvdisasm 12.6: I2F.S16 R5, R0 (PTX cvt.rn.f32.s16).
    const std::array<Instruction, 2> code{{
        {{0x00057306, 0x00000000, 0x00101400, 0x004e3000}},
        EXIT,
    }};
    Evaluator run;
    run.regs[0] = 0x7f80ff01;
    run.Run(Lower(code));
    CHECK(std::bit_cast<float>(run.regs[5]) == -255.0f);
}

TEST_CASE("Ampere I2F U8 selects each source byte", "[video_core][ampere]") {
    // ptxas 12.6 / nvdisasm 12.6 emits I2F.U8 R7, R0.B0; B1-B3 set native bits 60-61.
    constexpr std::array<f32, 4> expected{1.0f, 255.0f, 128.0f, 127.0f};
    for (u32 selector = 0; selector < expected.size(); ++selector) {
        const std::array<Instruction, 2> code{{
            {{0x00077306, selector << 28, 0x00001000, 0x000e6200}},
            EXIT,
        }};
        Evaluator run;
        run.regs[0] = 0x7f80ff01;
        run.Run(Lower(code));
        CHECK(std::bit_cast<float>(run.regs[7]) == expected[selector]);
    }
}

TEST_CASE("Ampere uniform I2F U8 selects each source byte", "[video_core][ampere]") {
    // ptxas 12.6 / nvdisasm 12.6: I2F.U8 R5, UR4 (PTX cvt.rn.f32.u8).
    for (u32 selector = 0; selector < 4; ++selector) {
        const std::array<Instruction, 2> code{{
            {{0x00057d06, 0x00000004 | (selector << 28), 0x08001000, 0x000e2200}},
            EXIT,
        }};
        Evaluator run;
        run.regs[220] = 1;
        run.Run(Lower(code));
        CHECK(std::bit_cast<float>(run.regs[5]) == (selector == 0 ? 1.0f : 0.0f));
    }
}

TEST_CASE("Ampere FSETP compares a register with a uniform register", "[video_core][ampere]") {
    // FSETP.LT.AND P1, P2, R1, UR5, PT.
    const std::array<Instruction, 2> code{{{{0x01007c0b, 5, 0x0ba21000, 0}}, EXIT}};
    const auto compare = [&](float a, float b) {
        Evaluator run;
        run.regs[1] = std::bit_cast<u32>(a);
        run.regs[221] = std::bit_cast<u32>(b); // UR5
        run.Run(Lower(code));
        return std::pair{run.preds[1], run.preds[2]};
    };
    REQUIRE((compare(1.0f, 2.0f) == std::pair{true, false}));
    REQUIRE((compare(3.0f, 2.0f) == std::pair{false, true}));
}

TEST_CASE("Ampere uniform FSETP reserves the uniform register bank", "[video_core][ampere]") {
    // R216 aliases UR0 when the program uses the uniform register bank.
    const std::array<Instruction, 2> code{{{{0xd8007c0b, 5, 0x0ba21000, 0}}, EXIT}};
    const auto lowered = LowerToMaxwell(code);
    REQUIRE_FALSE(static_cast<bool>(lowered));
    REQUIRE(lowered.error == "native program uses lowering scratch registers");
}

TEST_CASE("A disabled uniform instruction does not reserve registers", "[video_core][ampere]") {
    const std::array<Instruction, 3> code{{
        {{0xd8007210, 2, 0x07ffe003, 0}}, // IADD3 R0, R216, R2, R3
        {{0x0100fc0b, 5, 0x0ba21000, 0}}, // @!PT FSETP.LT.AND P1, P2, R1, UR5, PT
        EXIT,
    }};
    Evaluator run;
    run.regs[216] = 5;
    run.regs[2] = 1;
    run.Run(Lower(code));
    REQUIRE(run.regs[0] == 6);
}

TEST_CASE("Ampere IADD3 reads bit 63 of an immediate as its sign", "[video_core][ampere]") {
    const std::array<Instruction, 2> code{{
        {{0x01007810, 0xfffffff0, 0x07ffe002, 0}}, // IADD3 R0, R1, -16, R2
        EXIT,
    }};
    Evaluator run;
    run.regs[1] = 100;
    run.regs[2] = 1;
    run.Run(Lower(code));
    REQUIRE(run.regs[0] == 85);
}

TEST_CASE("Ampere IADD3 negates two sources without a plus-one", "[video_core][ampere]") {
    const auto lowered = [](u32 word1, u32 word2) {
        const std::array<Instruction, 2> code{{{{0x01007210, word1, word2, 0}}, EXIT}};
        Evaluator run;
        run.regs[1] = 1;
        run.regs[2] = 2;
        run.regs[3] = 10;
        run.Run(Lower(code));
        return run.regs[0];
    };
    // IADD3 R0, -R1, -R2, R3
    REQUIRE(lowered(0x80000002, 0x07ffe103) == 7);
    // IADD3 R0, -R1, -R2, -R3
    REQUIRE(lowered(0x80000002, 0x07ffe903) == 0U - 13U);
    // IADD3 R0, -R1, -R2, RZ
    REQUIRE(lowered(0x80000002, 0x07ffe1ff) == 0U - 3U);
    // One negation stays one negation: IADD3 R0, -R1, R2, R3
    REQUIRE(lowered(0x00000002, 0x07ffe103) == 11);
}

TEST_CASE("Ampere IADD3 with a constant writes its carry when the sum goes to RZ",
          "[video_core][ampere]") {
    // IADD3 RZ, P1, R1, c[0][0x10], RZ
    const std::array<Instruction, 2> code{{{{0x01ff7a10, 0x10U << 6, 0x07f3e0ff, 0}}, EXIT}};
    const auto carry = [&](u32 a, u32 b) {
        Evaluator run;
        run.regs[1] = a;
        run.cbuf[0x10] = b;
        run.Run(Lower(code));
        return run.preds[1];
    };
    REQUIRE(carry(0xffffffffU, 2));
    REQUIRE(!carry(1, 2));
}

TEST_CASE("Ampere LEA with a constant writes its carry when the sum goes to RZ",
          "[video_core][ampere]") {
    // LEA RZ, P1, R1, c[0][0x10], 2
    const std::array<Instruction, 2> code{{{{0x01ff7a11, 0x10U << 6, 0x07f210ff, 0}}, EXIT}};
    const auto carry = [&](u32 a, u32 b) {
        Evaluator run;
        run.regs[1] = a;
        run.cbuf[0x10] = b;
        run.Run(Lower(code));
        return run.preds[1];
    };
    // (0x3fffffff << 2) + 8 = 0x1'00000004
    REQUIRE(carry(0x3fffffffU, 8));
    // (1 << 2) + 8 = 12
    REQUIRE(!carry(1, 8));
}

TEST_CASE("Ampere LEA with a constant still writes a real destination", "[video_core][ampere]") {
    // LEA R0, P1, R1, c[0][0x10], 2
    const std::array<Instruction, 2> code{{{{0x01007a11, 0x10U << 6, 0x07f210ff, 0}}, EXIT}};
    Evaluator run;
    run.regs[1] = 1;
    run.cbuf[0x10] = 8;
    run.Run(Lower(code));
    REQUIRE(run.regs[0] == 12);
    REQUIRE(!run.preds[1]);
}

TEST_CASE("Ampere IADD3.X applies the negation of a constant", "[video_core][ampere]") {
    // IADD3.X R0, RZ, -c[0][0x10], RZ, with the carry in P0
    const std::array<Instruction, 2> code{{{{0xff007a10, 0x80000000U | (0x10U << 6), 0x007fe4ff, 0}}, EXIT}};
    const auto run_with = [&](bool carry) {
        Evaluator run;
        run.cbuf[0x10] = 5;
        run.preds[0] = carry;
        run.Run(Lower(code));
        return run.regs[0];
    };
    REQUIRE(run_with(false) == 0U - 5U);
    REQUIRE(run_with(true) == 0U - 4U);
}

TEST_CASE("Ampere IADD3 uses only the sign of an immediate with a third source",
          "[video_core][ampere]") {
    // UIADD3 UR0, UR1, -16, UR2 takes the same path as IADD3 once its registers are mapped.
    const std::array<Instruction, 2> code{{{{0x01007890, 0xfffffff0, 0x07ffe002, 0}}, EXIT}};
    Evaluator run;
    run.regs[217] = 100;
    run.regs[218] = 1;
    run.Run(Lower(code));
    REQUIRE(run.regs[216] == 85);
}

TEST_CASE("Ampere SHF.R.W keeps the wrap of a register shift", "[video_core][ampere]") {
    const std::array<Instruction, 2> code{{
        {{0x01007219, 0x00000002, 0x00001eff, 0}}, // SHF.R.W.U32 R0, R1, R2, RZ
        EXIT,
    }};
    Evaluator run;
    run.regs[1] = 0x10;
    run.regs[2] = 33;
    run.Run(Lower(code));
    REQUIRE(run.regs[0] == 0x08);
}

TEST_CASE("Ampere SHF.R without wrap keeps the clamp of a register shift", "[video_core][ampere]") {
    const std::array<Instruction, 2> code{{
        {{0x01007219, 0x00000002, 0x000016ff, 0}}, // SHF.R.U32 R0, R1, R2, RZ
        EXIT,
    }};
    Evaluator run;
    run.regs[1] = 0x10;
    run.regs[2] = 33;
    run.Run(Lower(code));
    REQUIRE(run.regs[0] == 0);
}

TEST_CASE("Ampere FP16 TEX packs the first component into the low half", "[video_core][ampere]") {
    // TEX.F16 with mask RG. texture_fetch_swizzled.cpp Pack() puts component 0 in the low half.
    const std::array<Instruction, 2> code{{
        {{0x02007b60, 0x20801004, 0x001e83ff, 0}},
        EXIT,
    }};
    // The sample writes R250 and R251. Run only the words after it, with those two results set.
    std::vector<u64> after_sample;
    bool sampled = false;
    for (const u64 word : Lower(code)) {
        if (sampled) after_sample.push_back(word);
        if (word >> 58 == 0xc000000000000000ULL >> 58) sampled = true;
    }
    REQUIRE(sampled);
    Evaluator run;
    run.regs[250] = 0x1111;
    run.regs[251] = 0x2222;
    run.Run(after_sample);
    REQUIRE(run.regs[0] == 0x22221111);
}

struct HalfCompare {
    u32 pred_q;
    u32 pred_p;
    u32 ftz;
    u32 reg_a;
    u32 reg_b;
    u32 swizzle_b;
    u32 abs_b;
    u32 neg_b;
    u32 compare;
    u32 input;
    u32 neg_input;
    u32 neg_a;
    u32 abs_a;
    u32 combine;
    u32 swizzle_a;
    u32 h_and;
};

// Reads the fields where half_floating_point_set_predicate.cpp and GetReg20 read them.
HalfCompare DecodeHsetp2(u64 word) {
    REQUIRE(word >> 51 == (0x5d20000000000000ULL >> 51));
    return {
        .pred_q = Field(word, 0, 3),
        .pred_p = Field(word, 3, 3),
        .ftz = Field(word, 6, 1),
        .reg_a = Field(word, 8, 8),
        .reg_b = Field(word, 20, 8),
        .swizzle_b = Field(word, 28, 2),
        .abs_b = Field(word, 30, 1),
        .neg_b = Field(word, 31, 1),
        .compare = Field(word, 35, 4),
        .input = Field(word, 39, 3),
        .neg_input = Field(word, 42, 1),
        .neg_a = Field(word, 43, 1),
        .abs_a = Field(word, 44, 1),
        .combine = Field(word, 45, 2),
        .swizzle_a = Field(word, 47, 2),
        .h_and = Field(word, 49, 1),
    };
}

constexpr u32 H1_H0 = 0;
constexpr u32 H0_H0 = 2;
constexpr u32 H1_H1 = 3;
constexpr u32 COMPARE_LESS = 1;
constexpr u32 COMPARE_EQUAL = 2;
constexpr u32 COMPARE_GREATER_EQUAL = 6;
constexpr u32 COMBINE_AND = 0;
constexpr u32 COMBINE_XOR = 2;

TEST_CASE("Ampere register HSETP2 matches the disassembly of a Bananza instruction",
          "[video_core][ampere]") {
    // nvdisasm: HSETP2.EQ.AND P0, PT, R52.H0_H0, R52.H1_H1, P0
    const std::array<Instruction, 2> code{{{{0x34007234, 0x30000034, 0x00702800, 0x000fe400}}, EXIT}};
    const auto words = Lower(code);
    const HalfCompare insn = DecodeHsetp2(words.front());
    REQUIRE(Field(words.front(), 16, 4) == 7);
    REQUIRE(insn.pred_p == 0);
    REQUIRE(insn.pred_q == 7);
    REQUIRE(insn.reg_a == 52);
    REQUIRE(insn.swizzle_a == H0_H0);
    REQUIRE(insn.reg_b == 52);
    REQUIRE(insn.swizzle_b == H1_H1);
    REQUIRE(insn.compare == COMPARE_EQUAL);
    REQUIRE(insn.combine == COMBINE_AND);
    REQUIRE(insn.input == 0);
    REQUIRE(insn.neg_input == 0);
    REQUIRE(insn.neg_a + insn.abs_a + insn.neg_b + insn.abs_b + insn.ftz + insn.h_and == 0);
}

TEST_CASE("Ampere register HSETP2 keeps each modifier on its own field", "[video_core][ampere]") {
    // The native fields: A 24-31, B 32-39, B swizzle 60-61, B abs 62, B neg 63, combine 69-70,
    // H_AND 71, A neg 72, A abs 73, A swizzle 74-75, compare 76-79, FTZ 80, P 81-83, Q 84-86,
    // input 87-89, input neg 90. Each value differs, so a swapped field fails.
    const auto native = [](u32 reg_a, u32 reg_b, u32 swizzle_b, u32 abs_b, u32 neg_b, u32 combine,
                           u32 h_and, u32 neg_a, u32 abs_a, u32 swizzle_a, u32 compare, u32 ftz,
                           u32 pred_p, u32 pred_q, u32 input, u32 neg_input) {
        return Instruction{{0x00007234U | (reg_a << 24),
                            reg_b | (swizzle_b << 28) | (abs_b << 30) | (neg_b << 31),
                            (combine << 5) | (h_and << 7) | (neg_a << 8) | (abs_a << 9) |
                                (swizzle_a << 10) | (compare << 12) | (ftz << 16) | (pred_p << 17) |
                                (pred_q << 20) | (input << 23) | (neg_input << 26),
                            0}};
    };
    SECTION("modifiers on A") {
        const std::array<Instruction, 2> code{
            {native(10, 20, H1_H0, 0, 0, COMBINE_XOR, 1, 1, 0, H1_H1, COMPARE_LESS, 0, 1, 2, 3, 1),
             EXIT}};
        const HalfCompare insn = DecodeHsetp2(Lower(code).front());
        REQUIRE(insn.reg_a == 10);
        REQUIRE(insn.reg_b == 20);
        REQUIRE(insn.swizzle_a == H1_H1);
        REQUIRE(insn.swizzle_b == H1_H0);
        REQUIRE(insn.neg_a == 1);
        REQUIRE(insn.abs_a == 0);
        REQUIRE(insn.neg_b == 0);
        REQUIRE(insn.abs_b == 0);
        REQUIRE(insn.combine == COMBINE_XOR);
        REQUIRE(insn.h_and == 1);
        REQUIRE(insn.compare == COMPARE_LESS);
        REQUIRE(insn.ftz == 0);
        REQUIRE(insn.pred_p == 1);
        REQUIRE(insn.pred_q == 2);
        REQUIRE(insn.input == 3);
        REQUIRE(insn.neg_input == 1);
    }
    SECTION("modifiers on B") {
        const std::array<Instruction, 2> code{
            {native(11, 21, H0_H0, 1, 0, COMBINE_AND, 0, 0, 1, H1_H0, COMPARE_GREATER_EQUAL, 1, 4, 5,
                    6, 0),
             EXIT}};
        const HalfCompare insn = DecodeHsetp2(Lower(code).front());
        REQUIRE(insn.reg_a == 11);
        REQUIRE(insn.reg_b == 21);
        REQUIRE(insn.swizzle_a == H1_H0);
        REQUIRE(insn.swizzle_b == H0_H0);
        REQUIRE(insn.neg_a == 0);
        REQUIRE(insn.abs_a == 1);
        REQUIRE(insn.neg_b == 0);
        REQUIRE(insn.abs_b == 1);
        REQUIRE(insn.compare == COMPARE_GREATER_EQUAL);
        REQUIRE(insn.ftz == 1);
        REQUIRE(insn.pred_p == 4);
        REQUIRE(insn.pred_q == 5);
        REQUIRE(insn.input == 6);
    }
    SECTION("negation on B") {
        const std::array<Instruction, 2> code{
            {native(12, 22, H1_H1, 0, 1, COMBINE_AND, 0, 0, 0, H1_H0, COMPARE_LESS, 0, 0, 7, 0, 0),
             EXIT}};
        const HalfCompare insn = DecodeHsetp2(Lower(code).front());
        REQUIRE(insn.neg_b == 1);
        REQUIRE(insn.abs_b == 0);
        REQUIRE(insn.swizzle_b == H1_H1);
    }
}

TEST_CASE("Ampere immediate HSETP2 compares against the half pair", "[video_core][ampere]") {
    // HSETP2.LT.AND P1, PT, R5.H1_H0, 0x40003f80, PT. Word 1 holds the pair.
    const std::array<Instruction, 2> code{
        {{{0x05007434, 0x40003f80, 0x00721000 | (7U << 23), 0}}, EXIT}};
    const auto words = Lower(code);
    Evaluator run;
    run.Run({words.front()});
    REQUIRE(run.regs[DecodeHsetp2(words[1]).reg_b] == 0x40003f80);
    const HalfCompare insn = DecodeHsetp2(words[1]);
    REQUIRE(insn.reg_a == 5);
    REQUIRE(insn.swizzle_b == H1_H0);
    REQUIRE(insn.compare == COMPARE_LESS);
    REQUIRE(insn.pred_p == 1);
    REQUIRE(insn.pred_q == 7);
    REQUIRE(insn.input == 7);
}
} // namespace
