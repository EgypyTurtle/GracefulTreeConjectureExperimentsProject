#include <atomic>
#include <algorithm>
#include <chrono>
#include <cstdint>
#include <cstdlib>
#include <iostream>
#include <mutex>
#include <string>
#include <thread>
#include <utility>
#include <vector>

// A correctness-preserving experimental searcher.
// It keeps the same extension rule as the reference implementation, but uses
// bit-set adjacency and splits only complete prefix states between workers.

class BitGraph {
public:
    explicit BitGraph(int kk = 0) : k(kk) {}

    int k = 0;
    std::vector<std::vector<std::uint64_t>> a;

    int n() const { return static_cast<int>(a.size()); }

    bool has(int u, int v) const {
        return (a[u][v >> 6] >> (v & 63)) & 1ULL;
    }

    void add_vertex() {
        const int old_n = n();
        const int new_words = (old_n + 1 + 63) >> 6;
        for (auto& row : a) row.resize(new_words, 0);
        a.emplace_back(new_words, 0);
    }

    void edge(int u, int v) {
        a[u][v >> 6] |= 1ULL << (v & 63);
        a[v][u >> 6] |= 1ULL << (u & 63);
    }

    void unedge(int u, int v) {
        a[u][v >> 6] &= ~(1ULL << (v & 63));
        a[v][u >> 6] &= ~(1ULL << (u & 63));
    }

    int degree(int v) const {
        int d = 0;
        for (std::uint64_t x : a[v]) d += __builtin_popcountll(x);
        return d;
    }

private:
    bool cycle_dfs(std::vector<std::uint64_t>& used, int left,
                   int v, int start) const {
        used[v >> 6] |= 1ULL << (v & 63);
        if (left == 0) {
            const bool found = has(v, start);
            used[v >> 6] &= ~(1ULL << (v & 63));
            return found;
        }

        for (int w = 0; w < n(); ++w) {
            if (has(v, w) && !(used[w >> 6] & (1ULL << (w & 63)))) {
                if (cycle_dfs(used, left - 1, w, start)) return true;
            }
        }
        used[v >> 6] &= ~(1ULL << (v & 63));
        return false;
    }

public:
    bool has_cycle(int length) const {
        if (length > n()) return false;
        std::vector<std::uint64_t> used((n() + 63) >> 6, 0);
        for (int s = 0; s < n(); ++s) {
            if (cycle_dfs(used, length - 1, s, s)) return true;
        }
        return false;
    }

    bool has_power_two_cycle() const {
        for (int t = 4; t <= n(); t <<= 1) {
            if (has_cycle(t)) return true;
        }
        return false;
    }

private:
    bool induced_path_dfs(std::vector<std::uint64_t>& used,
                          int left, int v, int previous) const {
        // The new vertex may only touch the immediately preceding path vertex.
        for (int w = 0; w < n(); ++w) {
            if (w != previous && (used[w >> 6] & (1ULL << (w & 63))) && has(v, w)) {
                return false;
            }
        }
        used[v >> 6] |= 1ULL << (v & 63);
        if (left == 0) {
            used[v >> 6] &= ~(1ULL << (v & 63));
            return true;
        }
        for (int w = 0; w < n(); ++w) {
            if (has(v, w) && !(used[w >> 6] & (1ULL << (w & 63)))) {
                if (induced_path_dfs(used, left - 1, w, v)) {
                    used[v >> 6] &= ~(1ULL << (v & 63));
                    return true;
                }
            }
        }
        used[v >> 6] &= ~(1ULL << (v & 63));
        return false;
    }

public:
    bool is_pk_free() const {
        if (k <= 1) return true;
        std::vector<std::uint64_t> used((n() + 63) >> 6, 0);
        for (int s = 0; s < n() - 1; ++s) {
            if (induced_path_dfs(used, k - 1, s, -1)) return false;
        }
        return true;
    }

    int highest_incomplete() const {
        for (int v = n() - 1; v >= 0; --v) {
            if (degree(v) < 3) return v;
        }
        return -1;
    }
};

struct Stats {
    std::atomic<unsigned long long> states{0};
    std::atomic<unsigned long long> branches{0};
    std::atomic<unsigned long long> backtracks{0};
};

struct SearchOptions { bool guided = false; };

static int structural_score(const BitGraph& g) {
    int degree_three = 0;
    int covered = 0;
    for (int v = 0; v < g.n(); ++v)
        if (g.degree(v) == 3) ++degree_three;
    for (int v = 0; v < g.n(); ++v) {
        for (int w = 0; w < g.n(); ++w) {
            if (g.has(v, w) && g.degree(w) == 3) {
                ++covered;
                break;
            }
        }
    }
    return 100 * degree_three + 30 * covered;
}

static void extend(BitGraph g, int anchor, Stats& stats,
                   std::atomic<bool>& found, const SearchOptions& options) {
    if (found.load(std::memory_order_relaxed)) return;
    ++stats.states;

    const int old_n = g.n();
    std::vector<int> safe(old_n - 1, 0);
    safe[anchor] = -1;

    // An edge which already creates a forbidden cycle can never be used in
    // any descendant, so mark it once for this recursion level.
    for (int u = 0; u < old_n - 1; ++u) {
        if (safe[u] == -1) continue;
        BitGraph test = g;
        test.edge(old_n - 1, u);
        if (test.has_power_two_cycle()) safe[u] = -1;
    }

    std::vector<int> free;
    for (int u = 0; u < old_n - 1; ++u)
        if (safe[u] == 0) free.push_back(u);

    if (free.size() >= 63) {
        std::cerr << "free-neighbor mask too large; use reference search\n";
        std::exit(2);
    }

    const std::uint64_t total = 1ULL << free.size();
    std::vector<std::uint64_t> masks;
    if (options.guided && free.size() <= 20) {
        struct Ranked { std::uint64_t mask; int score; };
        std::vector<Ranked> ranked;
        ranked.reserve(static_cast<std::size_t>(total));
        for (std::uint64_t mask = 0; mask < total; ++mask) {
            BitGraph candidate = g;
            for (std::size_t i = 0; i < free.size(); ++i)
                if (mask & (1ULL << i)) candidate.edge(old_n - 1, free[i]);
            ranked.push_back({mask, structural_score(candidate)});
        }
        std::sort(ranked.begin(), ranked.end(),
                  [](const Ranked& x, const Ranked& y) { return x.score > y.score; });
        for (const auto& item : ranked) masks.push_back(item.mask);
    } else {
        masks.resize(static_cast<std::size_t>(total));
        for (std::uint64_t mask = 0; mask < total; ++mask) masks[mask] = mask;
    }
    for (std::uint64_t mask : masks) {
        if (found.load(std::memory_order_relaxed)) return;
        ++stats.branches;
        BitGraph child = g;
        for (std::size_t i = 0; i < free.size(); ++i)
            if (mask & (1ULL << i)) child.edge(old_n - 1, free[i]);
        if (child.has_power_two_cycle()) {
            ++stats.backtracks;
            continue;
        }
        if (!child.is_pk_free()) {
            ++stats.backtracks;
            continue;
        }

        const int next_anchor = child.highest_incomplete();
        if (next_anchor == -1) {
            found.store(true, std::memory_order_relaxed);
            std::cout << "counterexample found (fast bitset search)\n";
            for (int v = 0; v < child.n(); ++v) {
                std::cout << v << ":";
                for (int w = v + 1; w < child.n(); ++w)
                    if (child.has(v, w)) std::cout << " " << w;
                std::cout << "\n";
            }
            return;
        }

        child.add_vertex();
        child.edge(child.n() - 1, next_anchor);
        extend(std::move(child), next_anchor, stats, found, options);
    }
}

struct Prefix {
    BitGraph graph;
    int anchor = -1;
};

static std::vector<Prefix> make_prefixes(int k, int split_depth) {
    // Conservative splitter: the first level is enough to expose independent
    // work to many CPUs while keeping memory bounded.
    (void)split_depth;
    BitGraph g(k);
    for (int i = 0; i < k; ++i) g.add_vertex();
    for (int i = 0; i + 1 < k; ++i) g.edge(i, i + 1);

    std::vector<Prefix> out;
    const int anchor = k - 2;
    const int old_n = g.n();
    std::vector<int> free;
    for (int u = 0; u < old_n - 1; ++u) {
        if (u == anchor) continue;
        BitGraph test = g;
        test.edge(old_n - 1, u);
        if (!test.has_power_two_cycle()) free.push_back(u);
    }
    if (free.size() >= 63) return out;
    for (std::uint64_t mask = 0; mask < (1ULL << free.size()); ++mask) {
        BitGraph child = g;
        child.edge(old_n - 1, anchor);
        for (std::size_t i = 0; i < free.size(); ++i)
            if (mask & (1ULL << i)) child.edge(old_n - 1, free[i]);
        // The initial P_k itself is not P_k-free.  Only after the first
        // endpoint extension has removed every induced P_k may we add the
        // next vertex and hand the state to the recursive search.
        if (child.has_power_two_cycle() || !child.is_pk_free()) continue;

        const int next_anchor = child.highest_incomplete();
        if (next_anchor == -1) {
            // This cannot normally happen at the initial level, but keeping
            // the test here makes the prefix generator self-contained.
            out.push_back(Prefix{std::move(child), -1});
            continue;
        }
        child.add_vertex();
        child.edge(child.n() - 1, next_anchor);
        out.push_back(Prefix{std::move(child), next_anchor});
    }
    return out;
}

int main(int argc, char** argv) {
    if (argc < 2 || argc > 5) {
        std::cerr << "Usage: " << argv[0] << " <k> [threads] [split-depth] [exact|guided]\n";
        return 1;
    }
    const int k = std::atoi(argv[1]);
    const unsigned threads = argc >= 3 ? std::max(1, std::atoi(argv[2]))
                                       : std::max(1u, std::thread::hardware_concurrency());
    const int split_depth = argc >= 4 ? std::max(1, std::atoi(argv[3])) : 1;
    SearchOptions options;
    if (argc >= 5) {
        const std::string mode(argv[4]);
        if (mode != "exact" && mode != "guided") {
            std::cerr << "mode must be exact or guided\n";
            return 1;
        }
        options.guided = mode == "guided";
    }

    const auto start = std::chrono::steady_clock::now();
    auto prefixes = make_prefixes(k, split_depth);
    Stats stats;
    std::atomic<bool> found{false};
    std::atomic<std::size_t> next{0};

    std::vector<std::thread> workers;
    for (unsigned t = 0; t < threads; ++t) {
        workers.emplace_back([&] {
            while (!found.load(std::memory_order_relaxed)) {
                const std::size_t i = next.fetch_add(1);
                if (i >= prefixes.size()) break;
                extend(prefixes[i].graph, prefixes[i].anchor, stats, found, options);
            }
        });
    }
    for (auto& worker : workers) worker.join();

    const double seconds = std::chrono::duration<double>(
        std::chrono::steady_clock::now() - start).count();
    std::cout << "complete: k=" << k
              << " prefixes=" << prefixes.size()
              << " states=" << stats.states.load()
              << " branches=" << stats.branches.load()
              << " backtracks=" << stats.backtracks.load()
              << " mode=" << (options.guided ? "guided" : "exact")
              << " seconds=" << seconds << "\n";
    return found.load() ? 100 : 0;
}
