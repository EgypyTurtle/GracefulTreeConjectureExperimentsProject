// SPDX-License-Identifier: MIT
#include <algorithm>
#include <atomic>
#include <chrono>
#include <csignal>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <functional>
#include <iomanip>
#include <iostream>
#include <mutex>
#include <sstream>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>
#ifdef _WIN32
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#else
#include <fcntl.h>
#include <sys/file.h>
#include <unistd.h>
#endif

namespace eg {
using Word = std::uint64_t;
using Mask = std::vector<Word>;
namespace fs = std::filesystem;
static constexpr const char* VERSION = "eg-v2.1";
static volatile std::sig_atomic_t interrupted = 0;
static void signal_handler(int) { interrupted = 1; }
struct Cancelled {};
static thread_local const std::atomic<bool>* cancellation = nullptr;
static thread_local std::uint64_t kernel_steps = 0;
static void poll_kernel() {
    if ((++kernel_steps & 4095) == 0 &&
        (interrupted || (cancellation && cancellation->load(std::memory_order_relaxed)))) throw Cancelled{};
}
static int first(Word x) { return __builtin_ctzll(x); }
static bool bit(const Mask& m, int v) { return (m[v / 64] >> (v % 64)) & 1; }
static void set(Mask& m, int v) { m[v / 64] |= Word(1) << (v % 64); }
static void clear(Mask& m, int v) { m[v / 64] &= ~(Word(1) << (v % 64)); }

struct Graph {
    std::vector<Mask> a;
    int n() const { return static_cast<int>(a.size()); }
    int words() const { return (n() + 63) / 64; }
    bool edge(int u, int v) const { return bit(a[u], v); }
    void add_vertex() {
        const int w = (n() + 64) / 64;
        for (auto& row : a) row.resize(w);
        a.emplace_back(w, 0);
    }
    void add(int u, int v) { set(a[u], v); set(a[v], u); }
    void remove(int u, int v) { clear(a[u], v); clear(a[v], u); }
    void pop_vertex() {
        const int v = n() - 1;
        for (int u = 0; u < v; ++u) clear(a[u], v);
        a.pop_back();
        for (auto& row : a) row.resize(words());
    }
    int degree(int v) const {
        int d = 0;
        for (Word x : a[v]) d += __builtin_popcountll(x);
        return d;
    }
    int anchor() const {
        for (int v = n() - 1; v >= 0; --v) if (degree(v) < 3) return v;
        return -1;
    }

    bool path64(int v, int target, int left, Word used, Word allowed) const {
        poll_kernel();
        if (left == 1) return edge(v, target);
        if (left >= 6 && (left % 4) == 2) {
            // Deleting already-used internal vertices can disconnect the
            // target or leave too few vertices for a path of this length.
            const Word available = allowed & (~used | (Word(1) << v));
            Word reached = Word(1) << target;
            Word frontier = reached;
            while (frontier) {
                const int u = first(frontier); frontier &= frontier - 1;
                const Word fresh = a[u][0] & available & ~reached;
                reached |= fresh; frontier |= fresh;
            }
            if (!(reached & (Word(1) << v)) || __builtin_popcountll(reached) <= left) return false;
        }
        Word candidates = a[v][0] & allowed & ~used & ~(Word(1) << target);
        while (candidates) {
            const int u = first(candidates); candidates &= candidates - 1;
            if (path64(u, target, left - 1, used | (Word(1) << u), allowed)) return true;
        }
        return false;
    }
    bool path_wide(int v, int target, int left, Mask& used, int excluded) const {
        poll_kernel();
        if (left == 1) return edge(v, target);
        for (int w = 0; w < words(); ++w) {
            Word candidates = a[v][w] & ~used[w];
            while (candidates) {
                const int u = 64 * w + first(candidates); candidates &= candidates - 1;
                if (u == target || u == excluded) continue;
                set(used, u);
                const bool yes = path_wide(u, target, left - 1, used, excluded);
                clear(used, u);
                if (yes) return true;
            }
        }
        return false;
    }

    bool path_mitm64(int source, int target, int length, Word allowed) const {
        // Keep both half-paths simple. They form a simple full path exactly
        // when their visited masks intersect only at the common midpoint.
        constexpr std::size_t cap = 131072;
        std::vector<std::vector<Word>> halves(n());
        std::size_t count = 0;
        bool overflow = false;
        std::function<void(int, int, Word)> left = [&](int v, int remaining, Word used) {
            poll_kernel();
            if (remaining == 0) {
                if (count == cap) { overflow = true; return; }
                halves[v].push_back(used); ++count;
                return;
            }
            Word next = a[v][0] & allowed & ~used & ~(Word(1) << target);
            while (next && !overflow) {
                const int u = first(next); next &= next - 1;
                left(u, remaining - 1, used | (Word(1) << u));
            }
        };
        const int half = length / 2;
        left(source, half, Word(1) << source);
        // The cap bounds extra per-thread memory. Overflow uses the original
        // exact DFS; it never turns an unfinished check into a negative result.
        if (overflow) return path64(source, target, length, Word(1) << source, allowed);
        if (count == 0) return false;
        std::function<bool(int, int, Word)> right = [&](int v, int remaining, Word used) {
            poll_kernel();
            if (remaining == 0) {
                const Word midpoint = Word(1) << v;
                for (Word other : halves[v]) {
                    poll_kernel();
                    if ((other & used) == midpoint) return true;
                }
                return false;
            }
            Word next = a[v][0] & allowed & ~used & ~(Word(1) << source);
            while (next) {
                const int u = first(next); next &= next - 1;
                if (right(u, remaining - 1, used | (Word(1) << u))) return true;
            }
            return false;
        };
        return right(target, length - half, Word(1) << target);
    }

    // A forbidden cycle through newest exists iff two of its neighbors are
    // joined in the old core by a simple path of length 2^j - 2.
    bool incompatible(int u, int v) const {
        const int newest = n() - 1;
        for (int w = 0; w < words(); ++w) {
            Word common = a[u][w] & a[v][w];
            if (w == newest / 64) common &= ~(Word(1) << (newest % 64));
            if (common) return true;
        }
        for (std::int64_t length = 8; length <= n(); length *= 2) {
            if (n() <= 64) {
                const Word allowed = ~(Word(1) << newest);
                const bool yes = length >= 32
                    ? path_mitm64(u, v, static_cast<int>(length) - 2, allowed)
                    : path64(u, v, static_cast<int>(length) - 2, Word(1) << u, allowed);
                if (yes) return true;
            } else {
                Mask used(words(), 0); set(used, u);
                if (path_wide(u, v, static_cast<int>(length) - 2, used, newest)) return true;
            }
        }
        return false;
    }

    bool induced64(int v, int left, Word used, Word blocked) const {
        poll_kernel();
        if (left == 0) return true;
        const Word valid = n() == 64 ? ~Word(0) : (Word(1) << n()) - 1;
        const Word available = valid & ~used & ~blocked;
        if (__builtin_popcountll(available) < left) return false;
        Word candidates = a[v][0] & available;
        while (candidates) {
            const int u = first(candidates); candidates &= candidates - 1;
            if (induced64(u, left - 1, used | (Word(1) << u), blocked | a[v][0])) return true;
        }
        return false;
    }
    bool induced_wide(int v, int left, Mask& used, const Mask& blocked) const {
        poll_kernel();
        if (left == 0) return true;
        Mask next_blocked = blocked;
        for (int w = 0; w < words(); ++w) next_blocked[w] |= a[v][w];
        for (int w = 0; w < words(); ++w) {
            Word candidates = a[v][w] & ~used[w] & ~blocked[w];
            while (candidates) {
                const int u = 64 * w + first(candidates); candidates &= candidates - 1;
                set(used, u);
                const bool yes = induced_wide(u, left - 1, used, next_blocked);
                clear(used, u);
                if (yes) return true;
            }
        }
        return false;
    }
    bool has_pk(int k) const {
        if (k > n()) return false;
        if (k == 1) return n() != 0;
        // Every path with >=2 vertices has an endpoint other than n-1.
        for (int s = 0; s < n() - 1; ++s) {
            if (n() <= 64) {
                if (induced64(s, k - 1, Word(1) << s, 0)) return true;
            } else {
                Mask used(words(), 0), blocked(words(), 0); set(used, s);
                if (induced_wide(s, k - 1, used, blocked)) return true;
            }
        }
        return false;
    }
    std::string text() const {
        std::ostringstream out;
        out << n() << '\n';
        for (int v = 0; v < n(); ++v) {
            out << v << ':';
            for (int u = v + 1; u < n(); ++u) if (edge(v, u)) out << ' ' << u;
            out << '\n';
        }
        return out.str();
    }
};

struct Stats {
    std::uint64_t states = 0, subsets = 0, accepted = 0, path_prunes = 0;
    std::uint64_t pair_tests = 0, conflict_prunes = 0, digest = 0;
    int max_n = 0;
    void merge(const Stats& s) {
        states += s.states; subsets += s.subsets; accepted += s.accepted;
        path_prunes += s.path_prunes; pair_tests += s.pair_tests;
        conflict_prunes += s.conflict_prunes; digest += s.digest;
        max_n = std::max(max_n, s.max_n);
    }
};
static Word hash_text(const std::string& s) {
    Word h = 14695981039346656037ULL;
    for (unsigned char c : s) { h ^= c; h *= 1099511628211ULL; }
    return h;
}

struct Control {
    std::atomic<bool> stop{false};
    std::mutex mutex;
    std::string candidate;
    bool audit = false;
};
struct Task { Graph graph; int anchor; };

struct Engine {
    int k;
    Control& control;
    Stats stats;
    std::uint64_t polls = 0;
    Engine(int kk, Control& c) : k(kk), control(c) {}
    bool stopped() {
        if ((++polls & 1023) == 0 && interrupted) control.stop = true;
        return control.stop.load(std::memory_order_relaxed);
    }
    using Emit = std::function<void(const Graph&, int)>;

    void explore(Graph& g, int anchor, int split_left = -1, const Emit& emit = {}) {
        if (stopped()) return;
        if (split_left == 0) { emit(g, anchor); return; }
        ++stats.states; stats.max_n = std::max(stats.max_n, g.n());
        const int newest = g.n() - 1;
        std::vector<int> optional;
        std::vector<int> selected{anchor};
        // Per-pending-vertex cache. All tests use the immutable old core;
        // adding other edges incident to newest never changes a pair result.
        std::vector<std::int8_t> cache(newest * newest, -1);
        auto conflict = [&](int u, int v) {
            if (u > v) std::swap(u, v);
            auto& value = cache[u * newest + v];
            if (value < 0) { ++stats.pair_tests; value = g.incompatible(u, v) ? 1 : 0; }
            return value == 1;
        };
        for (int u = 0; u < newest; ++u) {
            if (u == anchor) continue;
            if (conflict(u, anchor)) ++stats.conflict_prunes;
            else optional.push_back(u);
        }

        auto visit = [&] {
            ++stats.subsets;
            if (g.has_pk(k)) { ++stats.path_prunes; return; }
            ++stats.accepted;
            if (control.audit) stats.digest += hash_text(g.text());
            const int next_anchor = g.anchor();
            if (next_anchor == -1) {
                std::lock_guard<std::mutex> lock(control.mutex);
                if (control.candidate.empty()) control.candidate = g.text();
                control.stop = true;
                return;
            }
            g.add_vertex(); g.add(g.n() - 1, next_anchor);
            explore(g, next_anchor, split_left < 0 ? -1 : split_left - 1, emit);
            g.pop_vertex();
        };
        // Enumerate independent sets of the pair-conflict graph. A conflict
        // removes every superset containing that pair, since cycles persist.
        std::function<void(int)> subsets = [&](int start) {
            if (stopped()) return;
            visit();
            for (int i = start; i < static_cast<int>(optional.size()); ++i) {
                if (stopped()) return;
                const int u = optional[i];
                bool bad = false;
                for (int v : selected) if (conflict(u, v)) { bad = true; break; }
                if (bad) { ++stats.conflict_prunes; continue; }
                selected.push_back(u); g.add(newest, u);
                subsets(i + 1);
                g.remove(newest, u); selected.pop_back();
            }
        };
        subsets(0);
    }
};

static Graph initial(int k) {
    Graph g;
    for (int v = 0; v < k; ++v) g.add_vertex();
    for (int v = 1; v < k; ++v) g.add(v - 1, v);
    return g;
}
static void write_stats(std::ostream& out, const Stats& s) {
    out << s.states << ' ' << s.subsets << ' ' << s.accepted << ' '
        << s.path_prunes << ' ' << s.pair_tests << ' ' << s.conflict_prunes
        << ' ' << s.digest << ' ' << s.max_n << '\n';
}
static Stats read_stats(std::istream& in) {
    Stats s;
    if (!(in >> s.states >> s.subsets >> s.accepted >> s.path_prunes
             >> s.pair_tests >> s.conflict_prunes >> s.digest >> s.max_n))
        throw std::runtime_error("invalid checkpoint statistics");
    return s;
}

// Close and sync before publishing a file, so a power loss cannot turn a
// partially written task into a completed task. Directory sync is POSIX only.
static void atomic_write(const fs::path& path, const std::string& data) {
    fs::path temp = path; temp += ".tmp";
    {
        std::ofstream out(temp, std::ios::binary | std::ios::trunc);
        out << data; out.flush();
        if (!out) throw std::runtime_error("cannot write " + temp.string());
    }
#ifdef _WIN32
    HANDLE h = CreateFileW(temp.wstring().c_str(), GENERIC_WRITE, FILE_SHARE_READ,
                           nullptr, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr);
    if (h == INVALID_HANDLE_VALUE) throw std::runtime_error("checkpoint open failed");
    const bool ok = FlushFileBuffers(h); CloseHandle(h);
    if (!ok || !MoveFileExW(temp.wstring().c_str(), path.wstring().c_str(),
                            MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH))
        throw std::runtime_error("checkpoint publish failed");
#else
    int fd = ::open(temp.c_str(), O_WRONLY);
    if (fd < 0) throw std::runtime_error("checkpoint open failed");
    const int result = ::fsync(fd); ::close(fd);
    if (result != 0) throw std::runtime_error("checkpoint sync failed");
    fs::rename(temp, path);
    fd = ::open(path.parent_path().c_str(), O_RDONLY | O_DIRECTORY);
    if (fd < 0) throw std::runtime_error("checkpoint directory open failed");
    const int directory_result = ::fsync(fd); ::close(fd);
    if (directory_result != 0) throw std::runtime_error("checkpoint directory sync failed");
#endif
}

struct RunLock {
#ifdef _WIN32
    HANDLE handle;
    explicit RunLock(const fs::path& path) {
        handle = CreateFileW(path.wstring().c_str(), GENERIC_WRITE, 0, nullptr,
                             OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);
        if (handle == INVALID_HANDLE_VALUE) throw std::runtime_error("checkpoint directory is locked");
    }
    ~RunLock() { CloseHandle(handle); }
#else
    int fd;
    explicit RunLock(const fs::path& path) {
        fd = ::open(path.c_str(), O_CREAT | O_RDWR, 0600);
        if (fd < 0) throw std::runtime_error("cannot open run lock");
        if (::flock(fd, LOCK_EX | LOCK_NB) != 0) { ::close(fd); throw std::runtime_error("checkpoint directory is locked"); }
    }
    ~RunLock() { ::close(fd); }
#endif
};

struct Options {
    int k = 0, threads = 8, split = 3;
    std::size_t task_limit = 20000;
    double progress = 10, seconds = 0;
    bool audit = false;
    fs::path checkpoint;
};
static std::string config(const Options& o) {
    std::ostringstream s;
    s << VERSION << ' ' << o.k << ' ' << o.split << ' ' << o.task_limit << ' ' << o.audit << '\n';
    return s.str();
}
static std::vector<Task> make_tasks(const Options& o, Control& c, Stats& generation) {
    std::vector<Task> tasks{{initial(o.k), o.k - 2}};
    // Replace an entire layer, never a subset of a parent. A bounded layer
    // either fits or remains as its original tasks, so coverage is preserved.
    for (int level = 0; level < o.split; ++level) {
        std::vector<Task> next;
        Stats layer;
        bool too_many = false;
        for (auto& task : tasks) {
            Engine e{o.k, c};
            e.explore(task.graph, task.anchor, 1, [&](const Graph& g, int a) {
                if (next.size() < o.task_limit) next.push_back({g, a});
                else { too_many = true; c.stop = true; }
            });
            layer.merge(e.stats);
            if (c.stop) break;
        }
        if (!c.candidate.empty() || interrupted) break;
        if (too_many) {
            c.stop = false;
            std::cout << "split_limit: retaining layer " << level
                      << " tasks=" << tasks.size() << '\n' << std::flush;
            break;
        }
        generation.merge(layer); tasks = std::move(next);
        std::cout << "split: depth=" << level + 1 << " tasks=" << tasks.size() << '\n' << std::flush;
        if (tasks.empty()) break;
    }
    return tasks;
}
static std::string task_text(const Options& o, const Stats& generation, const std::vector<Task>& tasks) {
    std::ostringstream out;
    out << config(o); write_stats(out, generation); out << tasks.size() << '\n';
    for (const auto& t : tasks) {
        out << t.graph.n() << ' ' << t.anchor << '\n';
        for (int u = 0; u < t.graph.n(); ++u) {
            for (Word w : t.graph.a[u]) out << w << ' ';
            out << '\n';
        }
    }
    return out.str();
}
static std::vector<Task> read_tasks(const Options& o, const std::string& data, Stats& generation) {
    std::istringstream in(data);
    std::string line; std::getline(in, line);
    if (line + '\n' != config(o)) throw std::runtime_error("checkpoint options/version differ; choose a new directory");
    generation = read_stats(in);
    std::size_t count;
    if (!(in >> count) || count > o.task_limit) throw std::runtime_error("invalid task count");
    std::vector<Task> tasks;
    for (std::size_t i = 0; i < count; ++i) {
        int n, a;
        if (!(in >> n >> a) || n < o.k || n > o.k + o.split || a < 0 || a >= n - 1)
            throw std::runtime_error("invalid task header");
        Graph g;
        for (int j = 0; j < n; ++j) g.add_vertex();
        for (auto& row : g.a) for (auto& word : row)
            if (!(in >> word)) throw std::runtime_error("truncated tasks");
        tasks.push_back({std::move(g), a});
    }
    return tasks;
}
static std::string read_file(const fs::path& p) {
    std::ifstream in(p, std::ios::binary);
    if (!in) throw std::runtime_error("cannot read " + p.string());
    return {std::istreambuf_iterator<char>(in), std::istreambuf_iterator<char>()};
}

static int run(const Options& o) {
    const auto start = std::chrono::steady_clock::now();
    auto elapsed = [&] { return std::chrono::duration<double>(std::chrono::steady_clock::now() - start).count(); };
    fs::create_directories(o.checkpoint / "done");
    RunLock lock(o.checkpoint / "run.lock");
    if (fs::exists(o.checkpoint / "candidate.txt")) {
        std::cout << "candidate_present: verify " << (o.checkpoint / "candidate.txt").string() << '\n';
        return 100;
    }
    Control control; control.audit = o.audit;
    Stats generation;
    std::vector<Task> tasks;
    std::string manifest;
    if (fs::exists(o.checkpoint / "tasks.txt")) {
        manifest = read_file(o.checkpoint / "tasks.txt");
        tasks = read_tasks(o, manifest, generation);
    } else {
        tasks = make_tasks(o, control, generation);
        if (!control.candidate.empty()) {
            atomic_write(o.checkpoint / "candidate.txt", control.candidate); return 100;
        }
        if (interrupted) { std::cout << "interrupted_during_split: no complete task manifest saved\n"; return 130; }
        manifest = task_text(o, generation, tasks);
        atomic_write(o.checkpoint / "tasks.txt", manifest);
    }
    const Word identity = hash_text(manifest);
    Stats aggregate = generation;
    std::vector<std::size_t> pending;
    std::size_t reused = 0;
    for (std::size_t i = 0; i < tasks.size(); ++i) {
        const auto path = o.checkpoint / "done" / (std::to_string(i) + ".txt");
        if (fs::exists(path)) {
            std::istringstream in(read_file(path));
            Word h; std::size_t id;
            if (!(in >> h >> id) || h != identity || id != i) throw std::runtime_error("task completion fingerprint mismatch");
            aggregate.merge(read_stats(in)); ++reused;
        } else pending.push_back(i);
    }
    std::atomic<std::size_t> next{0}, completed{reused}, active{0};
    std::atomic<int> alive{0};
    std::mutex result_mutex;
    std::string error;
    std::cout << "start: version=" << VERSION << " k=" << o.k << " threads=" << o.threads
              << " tasks=" << tasks.size() << " reused=" << reused << " pending=" << pending.size()
              << " checkpoint=" << o.checkpoint.string() << '\n' << std::flush;
    std::vector<std::thread> workers;
    for (int t = 0; t < o.threads && t < static_cast<int>(pending.size()); ++t) {
        ++alive;
        workers.emplace_back([&] {
            cancellation = &control.stop;
            try {
                while (!control.stop.load()) {
                    const auto index = next.fetch_add(1);
                    if (index >= pending.size()) break;
                    ++active;
                    const auto id = pending[index];
                    Graph g = tasks[id].graph;
                    Engine e{o.k, control}; e.explore(g, tasks[id].anchor);
                    if (!control.stop.load()) {
                        std::ostringstream out; out << identity << ' ' << id << '\n'; write_stats(out, e.stats);
                        atomic_write(o.checkpoint / "done" / (std::to_string(id) + ".txt"), out.str());
                        { std::lock_guard<std::mutex> guard(result_mutex); aggregate.merge(e.stats); }
                        ++completed;
                    }
                    --active;
                }
            } catch (const Cancelled&) {
                control.stop = true;
            } catch (const std::exception& e) {
                std::lock_guard<std::mutex> guard(result_mutex); error = e.what(); control.stop = true;
            }
            --alive;
        });
    }
    double last_progress = elapsed();
    while (alive.load()) {
        if (interrupted || (o.seconds > 0 && elapsed() >= o.seconds)) control.stop = true;
        if (elapsed() - last_progress >= o.progress) {
            std::cout << "progress: done=" << completed << '/' << tasks.size()
                      << " active=" << active << " seconds=" << elapsed() << '\n' << std::flush;
            last_progress = elapsed();
        }
        std::this_thread::sleep_for(std::chrono::milliseconds(100));
    }
    for (auto& thread : workers) thread.join();
    if (!error.empty()) throw std::runtime_error(error);
    if (!control.candidate.empty()) {
        atomic_write(o.checkpoint / "candidate.txt", control.candidate);
        std::cout << "candidate_found: " << (o.checkpoint / "candidate.txt").string() << '\n' << std::flush;
        return 100;
    }
    const bool complete = completed == tasks.size();
    std::ostringstream summary;
    summary << (complete ? "complete" : "incomplete") << ": version=" << VERSION
            << " k=" << o.k << " done=" << completed << '/' << tasks.size()
            << " seconds_this_run=" << elapsed() << " states=" << aggregate.states
            << " accepted=" << aggregate.accepted << " subsets=" << aggregate.subsets
            << " path_prunes=" << aggregate.path_prunes << " pair_tests=" << aggregate.pair_tests
            << " conflict_prunes=" << aggregate.conflict_prunes << " max_n=" << aggregate.max_n
            << " audit_digest=" << aggregate.digest << '\n';
    atomic_write(o.checkpoint / (complete ? "summary.txt" : "last_interruption.txt"), summary.str());
    std::cout << summary.str() << std::flush;
    return complete ? 0 : (interrupted ? 130 : 3);
}
} // namespace eg

#ifndef EG_NO_MAIN
int main(int argc, char** argv) {
    using namespace eg;
    try {
        Options o;
        for (int i = 1; i < argc; ++i) {
            const std::string arg = argv[i];
            auto value = [&]() -> std::string {
                if (++i >= argc) throw std::runtime_error("missing value for " + arg);
                return argv[i];
            };
            if (arg == "--k") o.k = std::stoi(value());
            else if (arg == "--threads") o.threads = std::stoi(value());
            else if (arg == "--split-depth") o.split = std::stoi(value());
            else if (arg == "--task-limit") o.task_limit = std::stoull(value());
            else if (arg == "--progress") o.progress = std::stod(value());
            else if (arg == "--time-limit") o.seconds = std::stod(value());
            else if (arg == "--checkpoint") o.checkpoint = value();
            else if (arg == "--audit") o.audit = true;
            else if (arg == "--help") {
                std::cout << "eg_search --k K [--threads 8] [--split-depth 3] [--task-limit 20000]\n"
                             "          [--checkpoint DIR] [--progress 10] [--time-limit SECONDS] [--audit]\n";
                return 0;
            } else throw std::runtime_error("unknown option " + arg);
        }
        if (o.k < 3 || o.k > 10000 || o.threads < 1 || o.threads > 1024 || o.split < 0
            || o.split > 20 || o.task_limit < 1 || o.progress <= 0 || o.seconds < 0)
            throw std::runtime_error("invalid search parameters");
        if (o.checkpoint.empty()) o.checkpoint = "checkpoints/k" + std::to_string(o.k);
        std::signal(SIGINT, signal_handler); std::signal(SIGTERM, signal_handler);
        return run(o);
    } catch (const std::exception& e) {
        std::cerr << "error: " << e.what() << '\n' << std::flush; return 2;
    } catch (const Cancelled&) {
        std::cout << "incomplete: interrupted during task generation\n" << std::flush; return 130;
    }
}
#endif
