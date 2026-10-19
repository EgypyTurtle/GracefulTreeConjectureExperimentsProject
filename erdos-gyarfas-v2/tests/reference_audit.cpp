#include "graph.h"
#include <cstdint>
#include <iostream>
#include <sstream>
#include <cstdlib>

static std::uint64_t states = 0, accepted = 0, digest = 0;
static void explore(Graph& g, int anchor) {
    ++states;
    std::vector<int> safe(g.n - 1, 0); safe[anchor] = -1;
    g.init_safe_neighbors(safe);
    bool success = true;
    while (success) {
        if (g.is_ind_pk_free()) {
            ++accepted;
            std::ostringstream out; out << g.n << '\n';
            for (int v = 0; v < g.n; ++v) {
                out << v << ':';
                for (int u = v + 1; u < g.n; ++u) if (g.nodes[v].count(u)) out << ' ' << u;
                out << '\n';
            }
            std::uint64_t h = 14695981039346656037ULL;
            for (unsigned char c : out.str()) { h ^= c; h *= 1099511628211ULL; }
            digest += h;
            const int next = g.get_highest_incomplete_node();
            if (next == -1) { std::cout << "candidate\n"; std::exit(100); }
            const int v = g.n; g.add_node(v); g.add_edge(v, next);
            explore(g, next); g.remove_node(v);
        }
        g.remove_edges(safe); success = g.update_next_safe_neighbors(safe);
    }
}
int main(int argc, char** argv) {
    if (argc != 2) return 2;
    const int k = std::atoi(argv[1]); if (k < 3) return 2;
    Graph g(k); for (int i = 0; i < k; ++i) g.add_node(i);
    for (int i = 1; i < k; ++i) g.add_edge(i - 1, i);
    explore(g, k - 2);
    std::cout << "states=" << states << " accepted=" << accepted << " audit_digest=" << digest << '\n';
}
