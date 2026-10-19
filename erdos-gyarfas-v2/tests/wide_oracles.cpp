#define EG_NO_MAIN
#include "../search.cpp"
#include "graph.h"
#include <numeric>
#include <queue>
#include <random>

static bool exact_pair(const std::vector<std::vector<int>>& core, int u, int v, int total_n) {
    std::vector<bool> used(core.size(), false);
    std::function<bool(int, int)> walk = [&](int x, int left) {
        if (left == 0) return x == v;
        used[x] = true;
        for (int y : core[x]) {
            if (!used[y] && (y != v || left == 1) && walk(y, left - 1)) {
                used[x] = false; return true;
            }
        }
        used[x] = false; return false;
    };
    for (int cycle = 4; cycle <= total_n; cycle *= 2)
        if (walk(u, cycle - 2)) return true;
    return false;
}

int main() {
    try {
        std::mt19937 rng(20261019);
        std::uint64_t checks = 0;
        for (int sample = 0; sample < 100; ++sample) {
            const int n = 65 + static_cast<int>(rng() % 66);
            eg::Graph graph;
            Graph reference(14);
            for (int v = 0; v < n; ++v) { graph.add_vertex(); reference.add_node(v); }
            std::vector<int> labels(n - 1);
            std::iota(labels.begin(), labels.end(), 0);
            std::shuffle(labels.begin(), labels.end(), rng);
            std::vector<std::vector<int>> core(n - 1);
            for (int i = 1; i < n - 1; ++i) {
                if (rng() % 7 == 0) continue;
                const int u = labels[i], v = labels[rng() % i];
                graph.add(u, v); reference.add_edge(u, v);
                core[u].push_back(v); core[v].push_back(u);
            }
            graph.add(n - 1, labels[0]); reference.add_edge(n - 1, labels[0]);
            for (int k : {3, 8, 14, 20}) {
                reference.k = k;
                if (graph.has_pk(k) == reference.is_ind_pk_free())
                    throw std::runtime_error("wide induced-path mismatch");
                ++checks;
            }
            for (int u = 0; u < n - 1; u += 3) {
                std::vector<int> distances(n - 1, -1);
                std::queue<int> queue; queue.push(u); distances[u] = 0;
                while (!queue.empty()) {
                    const int x = queue.front(); queue.pop();
                    for (int y : core[x]) if (distances[y] < 0) {
                        distances[y] = distances[x] + 1; queue.push(y);
                    }
                }
                // A forest has at most one simple u-v path. BFS distance is
                // therefore an independent exact oracle for every cycle size.
                for (int v = u + 1; v < n - 1; v += 2) {
                    const int length = distances[v] + 2;
                    const bool expected = distances[v] >= 2 && (length & (length - 1)) == 0;
                    if (graph.incompatible(u, v) != expected)
                        throw std::runtime_error("wide forest distance oracle mismatch");
                    ++checks;
                }
            }
        }
        const auto forest_checks = checks;
        // Relabel cyclic cores across multiple words, with isolated padding.
        // The oracle stores adjacency lists and enumerates exact simple paths.
        for (int sample = 0; sample < 40; ++sample) {
            const int n = 65 + static_cast<int>(rng() % 66);
            eg::Graph graph;
            Graph reference(3);
            std::vector<std::vector<int>> core(n - 1);
            for (int v = 0; v < n; ++v) { graph.add_vertex(); reference.add_node(v); }
            std::vector<int> labels(n - 1);
            std::iota(labels.begin(), labels.end(), 0);
            std::shuffle(labels.begin(), labels.end(), rng);
            const int support = 7 + sample % 3;
            auto add = [&](int u, int v) {
                graph.add(u, v); reference.add_edge(u, v);
                core[u].push_back(v); core[v].push_back(u);
            };
            for (int i = 0; i < support; ++i) for (int j = i + 1; j < support; ++j)
                if (rng() % 100 < 35) add(labels[i], labels[j]);
            graph.add(n - 1, labels[0]); reference.add_edge(n - 1, labels[0]);
            for (int k : {3, 6, 9, 14}) {
                reference.k = k;
                if (graph.has_pk(k) == reference.is_ind_pk_free())
                    throw std::runtime_error("wide cyclic induced-path mismatch");
                ++checks;
            }
            for (int i = 0; i < support; ++i) for (int j = i + 1; j < support; ++j) {
                if (graph.incompatible(labels[i], labels[j]) != exact_pair(core, labels[i], labels[j], n))
                    throw std::runtime_error("wide cyclic exact-path mismatch");
                ++checks;
            }
        }
        for (int n : {65, 66, 72, 73, 128, 129, 130}) {
            eg::Graph graph;
            std::vector<std::vector<int>> core(n - 1);
            for (int v = 0; v < n; ++v) graph.add_vertex();
            for (int v = 0; v < n - 1; ++v) {
                const int u = (v + 1) % (n - 1);
                graph.add(v, u); core[v].push_back(u); core[u].push_back(v);
            }
            graph.add(n - 1, 0);
            for (int u = 0; u < n - 1; u += 7) for (int v = u + 1; v < n - 1; v += 5) {
                if (graph.incompatible(u, v) != exact_pair(core, u, v, n))
                    throw std::runtime_error("wide ring exact-path mismatch");
                ++checks;
            }
        }
        std::cout << "PASS wide independent comparisons=" << checks << '\n';
        std::cout << "forest=" << forest_checks << " cyclic=" << checks - forest_checks << '\n';
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "FAIL " << error.what() << '\n'; return 1;
    }
}
