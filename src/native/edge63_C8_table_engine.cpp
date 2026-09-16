// Native C8.LevelB.v1 local-table compiler.
//
// This ports only the finite two-run geometry generator.  The Python
// implementation remains the reference for semantic queries, certificates,
// bilateral joins, and final verification.

#include "edge63_C8_bitset.hpp"

#include <algorithm>
#include <chrono>
#include <cstdint>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <functional>
#include <iostream>
#include <map>
#include <set>
#include <stdexcept>
#include <string>
#include <tuple>
#include <utility>
#include <vector>

namespace fs = std::filesystem;
using Vec = std::vector<int>;
using Clock = std::chrono::steady_clock;

constexpr int kFormatVersion = 2;
constexpr char kMagic[] = "GTC8TAB1";
constexpr char kLanguage[] = "C8.LevelB.v1";
constexpr char kOwnership[] = "ownership.v2";
constexpr char kTerminalCache[] = "corrected.v2";

struct Record {
    int id{};
    Vec offsets;
    Vec private_offsets;
    Vec difference_order;
    Vec signs;
    int min_value{};
    int max_value{};
    int span{};
    std::string order_mode;
};

static Vec negate_vec(const Vec& input) {
    Vec result(input.size());
    for (std::size_t i = 0; i < input.size(); ++i) result[i] = -input[i];
    return result;
}

static int value_span(const Vec& input) {
    auto limits = std::minmax_element(input.begin(), input.end());
    return *limits.second - *limits.first;
}

static bool unique_values(const Vec& input) {
    std::set<int> values(input.begin(), input.end());
    return values.size() == input.size();
}

static Vec add_prefix(const Vec& order, const Vec& signs) {
    Vec result{0};
    for (std::size_t i = 0; i < order.size(); ++i) {
        result.push_back(result.back() + order[i] * signs[i]);
    }
    return result;
}

static void sign_words_recursive(int n, int first, int turns, int at,
                                 int last, std::vector<int>& cuts,
                                 std::set<Vec>& output) {
    if (at == turns) {
        Vec word(n);
        int current = first;
        int cut_index = 0;
        for (int i = 0; i < n; ++i) {
            if (cut_index < turns && cuts[cut_index] == i) {
                current = -current;
                ++cut_index;
            }
            word[i] = current;
        }
        output.insert(std::move(word));
        return;
    }
    for (int value = last; value < n; ++value) {
        cuts[at] = value;
        sign_words_recursive(n, first, turns, at + 1, value + 1, cuts, output);
    }
}

static std::vector<Vec> sign_words(int n) {
    std::set<Vec> words;
    if (n <= 8) {
        const int count = 1 << n;
        for (int mask = 0; mask < count; ++mask) {
            Vec word(n);
            for (int i = 0; i < n; ++i) word[i] = (mask & (1 << i)) ? 1 : -1;
            words.insert(std::move(word));
        }
    } else {
        for (int first : {-1, 1}) {
            for (int turns = 0; turns <= 2; ++turns) {
                std::vector<int> cuts(turns);
                sign_words_recursive(n, first, turns, 0, 1, cuts, words);
            }
        }
        for (int first : {-1, 1}) {
            Vec word(n);
            for (int i = 0; i < n; ++i) word[i] = (i % 2 == 0) ? first : -first;
            words.insert(std::move(word));
        }
        if (n >= 2) {
            Vec repair(n, 1);
            for (int i = 2; i < n; ++i) repair[i] = (i % 2 == 1) ? 1 : -1;
            words.insert(repair);
            for (int& value : repair) value = -value;
            words.insert(std::move(repair));
        }
    }
    return std::vector<Vec>(words.begin(), words.end());
}

static std::vector<Vec> run_orders(int start, int length) {
    Vec values(length);
    for (int i = 0; i < length; ++i) values[i] = start + i;
    if (length <= 6) {
        std::sort(values.begin(), values.end());
        std::vector<Vec> result;
        do { result.push_back(values); } while (std::next_permutation(values.begin(), values.end()));
        return result;
    }
    std::set<Vec> orders;
    orders.insert(values);
    orders.insert(Vec(values.rbegin(), values.rend()));
    if (length > 0) {
        Vec rotation(values.begin() + 1, values.end());
        rotation.push_back(values.front());
        orders.insert(rotation);
        rotation.clear();
        rotation.push_back(values.back());
        rotation.insert(rotation.end(), values.begin(), values.end() - 1);
        orders.insert(rotation);
    }
    Vec high_low;
    Vec low_high;
    int lo = 0;
    int hi = length - 1;
    while (lo <= hi) {
        high_low.push_back(values[hi--]);
        if (lo <= hi) high_low.push_back(values[lo++]);
    }
    lo = 0;
    hi = length - 1;
    while (lo <= hi) {
        low_high.push_back(values[lo++]);
        if (lo <= hi) low_high.push_back(values[hi--]);
    }
    orders.insert(high_low);
    orders.insert(low_high);
    for (const Vec& base : {values, Vec(values.rbegin(), values.rend())}) {
        Vec first = base;
        std::swap(first[0], first[1]);
        orders.insert(std::move(first));
        Vec last = base;
        std::swap(last[length - 1], last[length - 2]);
        orders.insert(std::move(last));
    }
    return std::vector<Vec>(orders.begin(), orders.end());
}

static Vec alternating_merge(const Vec& first, const Vec& second, bool first_turn) {
    Vec result;
    std::size_t left = 0;
    std::size_t right = 0;
    bool take_first = first_turn;
    while (left < first.size() || right < second.size()) {
        if (take_first && left < first.size()) result.push_back(first[left++]);
        else if (!take_first && right < second.size()) result.push_back(second[right++]);
        else if (left < first.size()) result.push_back(first[left++]);
        else result.push_back(second[right++]);
        take_first = !take_first;
    }
    return result;
}

static std::vector<std::pair<Vec, std::string>> two_run_orders(
    int start_a, int length_a, int start_b, int length_b) {
    std::map<Vec, std::string> selected;
    const auto orders_a = run_orders(start_a, length_a);
    const auto orders_b = run_orders(start_b, length_b);
    auto add_first = [&](const Vec& order, const std::string& mode) {
        if (selected.find(order) == selected.end()) selected.emplace(order, mode);
    };
    for (const Vec& order_a : orders_a) {
        for (const Vec& order_b : orders_b) {
            Vec block_a = order_a;
            block_a.insert(block_a.end(), order_b.begin(), order_b.end());
            add_first(block_a, "block_a_then_b");
            Vec block_b = order_b;
            block_b.insert(block_b.end(), order_a.begin(), order_a.end());
            add_first(block_b, "block_b_then_a");
            Vec alt_a = alternating_merge(order_a, order_b, true);
            add_first(alt_a, "alternating_a_first");
            Vec alt_b = alternating_merge(order_a, order_b, false);
            add_first(alt_b, "alternating_b_first");
        }
    }
    std::vector<std::pair<Vec, std::string>> result;
    for (const auto& item : selected) result.push_back(item);
    std::sort(result.begin(), result.end(), [](const auto& left, const auto& right) {
        return std::tie(left.second, left.first) < std::tie(right.second, right.first);
    });
    return result;
}

static std::vector<Record> compile_table(int start_a, int end_a,
                                          int start_b, int end_b) {
    const int length_a = end_a - start_a + 1;
    const int length_b = end_b - start_b + 1;
    const auto orders = two_run_orders(start_a, length_a, start_b, length_b);
    const auto signs = sign_words(length_a + length_b);
    std::map<Vec, std::tuple<Vec, std::string, Vec>> canonical;
    for (const auto& order_data : orders) {
        const Vec& order = order_data.first;
        for (const Vec& sign : signs) {
            Vec offsets = add_prefix(order, sign);
            if (!unique_values(offsets) || value_span(offsets) > graceful_tree::kEdgeCount) continue;
            Vec negative = negate_vec(offsets);
            Vec key = std::min(offsets, negative);
            Vec stored_signs = (key == offsets) ? sign : negate_vec(sign);
            canonical.emplace(key, std::make_tuple(order, order_data.second, stored_signs));
        }
    }
    std::vector<Vec> keys;
    for (const auto& item : canonical) keys.push_back(item.first);
    std::sort(keys.begin(), keys.end(), [](const Vec& left, const Vec& right) {
        const int left_span = value_span(left);
        const int right_span = value_span(right);
        return left_span != right_span ? left_span < right_span : left < right;
    });

    std::vector<Record> records;
    std::set<Vec> seen_private;
    for (const Vec& key : keys) {
        const auto& data = canonical.at(key);
        const Vec& order = std::get<0>(data);
        const std::string& mode = std::get<1>(data);
        const Vec& stored_signs = std::get<2>(data);
        std::vector<Vec> orientations{key, negate_vec(key)};
        if (orientations[0] == orientations[1]) orientations.pop_back();
        for (const Vec& offsets : orientations) {
            if (value_span(offsets) > graceful_tree::kEdgeCount) continue;
            Vec private_offsets(offsets.begin() + 1, offsets.end());
            std::sort(private_offsets.begin(), private_offsets.end());
            if (!seen_private.insert(private_offsets).second) continue;
            const auto limits = std::minmax_element(private_offsets.begin(), private_offsets.end());
            Record record;
            record.id = static_cast<int>(records.size());
            record.offsets = offsets;
            record.private_offsets = private_offsets;
            record.difference_order = order;
            record.signs = stored_signs;
            record.min_value = std::min(0, *limits.first);
            record.max_value = std::max(0, *limits.second);
            record.span = record.max_value - record.min_value;
            record.order_mode = mode;
            records.push_back(std::move(record));
        }
    }
    return records;
}

static void write_u32(std::ofstream& out, std::uint32_t value) { out.write(reinterpret_cast<const char*>(&value), sizeof(value)); }
static void write_u64(std::ofstream& out, std::uint64_t value) { out.write(reinterpret_cast<const char*>(&value), sizeof(value)); }
static void write_i32(std::ofstream& out, std::int32_t value) { out.write(reinterpret_cast<const char*>(&value), sizeof(value)); }
static void write_string(std::ofstream& out, const std::string& value) {
    write_u32(out, static_cast<std::uint32_t>(value.size()));
    out.write(value.data(), static_cast<std::streamsize>(value.size()));
}
static void write_vec(std::ofstream& out, const Vec& values) {
    write_u32(out, static_cast<std::uint32_t>(values.size()));
    for (int value : values) write_i32(out, value);
}

static std::uint64_t fnv1a(const std::vector<std::uint8_t>& bytes) {
    std::uint64_t hash = 1469598103934665603ULL;
    for (std::uint8_t byte : bytes) {
        hash ^= byte;
        hash *= 1099511628211ULL;
    }
    return hash;
}

static void write_table(const fs::path& output, int start_a, int end_a,
                        int start_b, int end_b, const std::vector<Record>& records) {
    std::vector<std::uint8_t> payload;
    for (const Record& record : records) {
        for (int value : record.private_offsets) {
            for (int i = 0; i < 4; ++i) payload.push_back(static_cast<std::uint8_t>((value >> (8 * i)) & 0xff));
        }
    }
    const std::uint64_t payload_checksum = fnv1a(payload);
    std::ofstream out(output, std::ios::binary | std::ios::trunc);
    if (!out) throw std::runtime_error("cannot open native output");
    out.write(kMagic, 8);
    write_u32(out, kFormatVersion);
    write_u32(out, graceful_tree::kEdgeCount);
    write_u32(out, graceful_tree::kOffsetShift);
    write_i32(out, start_a); write_i32(out, end_a);
    write_i32(out, start_b); write_i32(out, end_b);
    write_string(out, kLanguage);
    write_string(out, kOwnership);
    write_string(out, kTerminalCache);
    write_u64(out, payload_checksum);
    write_u32(out, static_cast<std::uint32_t>(records.size()));
    for (const Record& record : records) {
        write_u32(out, static_cast<std::uint32_t>(record.id));
        write_i32(out, record.min_value); write_i32(out, record.max_value); write_i32(out, record.span);
        write_vec(out, record.private_offsets);
        write_vec(out, record.offsets);
        write_vec(out, record.difference_order);
        write_vec(out, record.signs);
        write_string(out, record.order_mode);
    }
    write_u32(out, static_cast<std::uint32_t>(payload_checksum & 0xffffffffULL));
    if (!out) throw std::runtime_error("native output write failed");
}

int main(int argc, char** argv) {
    try {
        fs::path output;
        int start_a = 0, end_a = 0, start_b = 0, end_b = 0;
        for (int i = 1; i < argc; ++i) {
            const std::string arg(argv[i]);
            auto next_int = [&](int& target) {
                if (++i >= argc) throw std::runtime_error("missing integer argument");
                target = std::stoi(argv[i]);
            };
            if (arg == "--output") {
                if (++i >= argc) throw std::runtime_error("missing output path");
                output = argv[i];
            } else if (arg == "--a-start") next_int(start_a);
            else if (arg == "--a-end") next_int(end_a);
            else if (arg == "--b-start") next_int(start_b);
            else if (arg == "--b-end") next_int(end_b);
            else if (arg == "--help") { return 0; }
            else throw std::runtime_error("unknown argument: " + arg);
        }
        if (output.empty() || start_a <= 0 || end_a < start_a || start_b <= 0 || end_b < start_b) {
            throw std::runtime_error("expected --a-start --a-end --b-start --b-end --output");
        }
        const auto started = Clock::now();
        const auto records = compile_table(start_a, end_a, start_b, end_b);
        fs::create_directories(output.parent_path());
        write_table(output, start_a, end_a, start_b, end_b, records);
        const auto elapsed = std::chrono::duration<double>(Clock::now() - started).count();
        std::ofstream meta(output.string() + ".meta", std::ios::trunc);
        meta << "behavior_count=" << records.size() << "\n";
        meta << "compile_seconds=" << elapsed << "\n";
        meta << "two_run_language=" << kLanguage << "\n";
        meta << "allocation_dedup_version=" << kOwnership << "\n";
        meta << "terminal_pair_cache_version=" << kTerminalCache << "\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << error.what() << "\n";
        return 2;
    }
}
