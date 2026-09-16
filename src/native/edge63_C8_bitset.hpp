#pragma once

#include <cstdint>
#include <vector>

namespace graceful_tree {

// The signed offset universe is deliberately fixed to the same range used by
// the Python reference ([-256, 63+256]).  This is the native representation
// used by the table engine; it is not a new search language.
constexpr int kEdgeCount = 63;
constexpr int kOffsetShift = 256;
constexpr int kOffsetMin = -kOffsetShift;
constexpr int kOffsetMax = kEdgeCount + kOffsetShift;

struct FixedOffsetMask {
    static constexpr int kBits = kOffsetMax - kOffsetMin + 1;
    static constexpr int kWords = (kBits + 63) / 64;
    std::uint64_t words[kWords]{};

    void set(int value) {
        const int index = value - kOffsetMin;
        if (index < 0 || index >= kBits) return;
        words[index >> 6] |= (std::uint64_t(1) << (index & 63));
    }

    bool test(int value) const {
        const int index = value - kOffsetMin;
        if (index < 0 || index >= kBits) return false;
        return (words[index >> 6] >> (index & 63)) & 1U;
    }
};

}  // namespace graceful_tree
