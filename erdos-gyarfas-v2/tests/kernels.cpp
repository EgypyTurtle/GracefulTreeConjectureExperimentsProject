#define EG_NO_MAIN
#include "../search.cpp"
#include "graph.h"
#include <random>

static void require(bool value, const char* message) {
    if (!value) throw std::runtime_error(message);
}

static void compare(const eg::Graph& g, std::uint64_t& checks) {
    Graph reference(3);
    for (int v = 0; v < g.n(); ++v) reference.add_node(v);
    for (int v = 0; v < g.n(); ++v) for (int u = v + 1; u < g.n(); ++u)
        if (g.edge(v, u)) reference.add_edge(v, u);
    for (int k = 3; k <= std::min(g.n() + 1, 9); ++k) {
        reference.k = k;
        require(g.has_pk(k) == !reference.is_ind_pk_free(), "induced-path mismatch"); ++checks;
    }
    // Pair equivalence is tested on arbitrary cores, not just reachable ones.
    for (int u = 0; u < g.n() - 1; ++u) for (int v = u + 1; v < g.n() - 1; ++v) {
        eg::Graph h = g;
        for (int w = 0; w < h.n() - 1; ++w) h.remove(w, h.n() - 1);
        const bool fast = h.incompatible(u, v);
        Graph old(3);
        for (int w = 0; w < h.n() - 1; ++w) old.add_node(w);
        for (int a = 0; a < h.n() - 1; ++a) for (int b = a + 1; b < h.n() - 1; ++b)
            if (h.edge(a, b)) old.add_edge(a, b);
        // Enumerate exact old-core paths independently (set adjacency).
        std::vector<bool> used(old.n, false);
        std::function<bool(int, int)> path = [&](int x, int left) {
            if (left == 0) return x == v;
            used[x] = true;
            for (int y : old.nodes[x]) if (!used[y] && path(y, left - 1)) { used[x] = false; return true; }
            used[x] = false; return false;
        };
        bool slow = false;
        for (int t = 4; t <= h.n(); t *= 2) if (path(u, t - 2)) { slow = true; break; }
        require(fast == slow, "pair incompatibility mismatch"); ++checks;
    }
}

int main() {
    try {
        std::uint64_t checks = 0;
        for (unsigned mask = 0; mask < (1u << 10); ++mask) {
            eg::Graph g; for (int v = 0; v < 5; ++v) g.add_vertex();
            int b = 0;
            for (int v = 0; v < 5; ++v) for (int u = v + 1; u < 5; ++u, ++b)
                if (mask & (1u << b)) g.add(v, u);
            compare(g, checks);
        }
        std::mt19937 rng(20261016);
        for (int sample = 0; sample < 1200; ++sample) {
            const int n = 6 + rng() % 7;
            eg::Graph g; for (int v = 0; v < n; ++v) g.add_vertex();
            for (int v = 0; v < n; ++v) for (int u = v + 1; u < n; ++u)
                if (rng() % 100 < static_cast<unsigned>(15 + sample % 65)) g.add(v, u);
            compare(g, checks);
            const eg::Word allowed = (eg::Word(1) << n) - 1;
            const int target = n - 1;
            for (int length : {2, 4, 6, 8}) {
                require(g.path64(0, target, length, 1, allowed) ==
                        g.path_mitm64(0, target, length, allowed), "meet-in-middle mismatch");
                ++checks;
            }
        }
        for (int n : {63, 64, 65, 127, 128, 129}) {
            eg::Graph g; for (int v = 0; v < n; ++v) g.add_vertex();
            for (int v = 1; v < n - 1; ++v) g.add(v - 1, v);
            require(g.has_pk(n - 1), "wide path missed");
            require(!g.has_pk(n), "wide disconnected graph path false positive");
            require(g.incompatible(0, 2), "wide C4 pair missed");
            require(g.incompatible(0, 6), "wide C8 pair missed");
            require(g.incompatible(0, 30), "C32 pair missed");
            require(!g.incompatible(0, 31), "odd-length tree path pair false positive");
            if (n >= 65) require(g.incompatible(0, 62), "wide C64 pair missed");
            g.pop_vertex(); require(g.n() == n - 1, "pop size");
            ++checks;
        }
        std::cout << "PASS kernel comparisons=" << checks << '\n';
        return 0;
    } catch (const std::exception& e) { std::cerr << "FAIL " << e.what() << '\n'; return 1; }
}
