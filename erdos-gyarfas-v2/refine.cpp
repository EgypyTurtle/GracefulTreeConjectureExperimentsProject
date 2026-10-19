// SPDX-License-Identifier: MIT
// Expand only unfinished tasks into a new, independently runnable checkpoint.
#define EG_NO_MAIN
#include "search.cpp"

static int refine(const eg::fs::path& source, const eg::fs::path& target, std::size_t limit) {
    using namespace eg;
    if (!fs::exists(source / "tasks.txt")) throw std::runtime_error("source task manifest is missing");
    if (fs::weakly_canonical(source) == fs::weakly_canonical(target))
        throw std::runtime_error("source and destination must differ");
    RunLock source_lock(source / "run.lock");
    if (fs::exists(source / "candidate.txt")) throw std::runtime_error("source has a candidate; verify it first");
    if (fs::exists(target)) throw std::runtime_error("destination already exists; choose a new directory");

    const std::string manifest = read_file(source / "tasks.txt");
    std::istringstream header(manifest);
    std::string version;
    Options old;
    if (!(header >> version >> old.k >> old.split >> old.task_limit >> old.audit) || version != VERSION)
        throw std::runtime_error("unsupported source checkpoint version");
    Stats carried;
    auto old_tasks = read_tasks(old, manifest, carried);
    const Word identity = hash_text(manifest);
    std::vector<std::size_t> pending;
    std::size_t completed = 0;
    for (std::size_t i = 0; i < old_tasks.size(); ++i) {
        const auto done = source / "done" / (std::to_string(i) + ".txt");
        if (fs::exists(done)) {
            std::istringstream in(read_file(done));
            Word h; std::size_t id;
            if (!(in >> h >> id) || h != identity || id != i)
                throw std::runtime_error("source completion fingerprint mismatch");
            carried.merge(read_stats(in)); ++completed;
        } else pending.push_back(i);
    }
    if (limit < pending.size()) throw std::runtime_error("task limit is below the number of pending tasks");
    if (old.split >= 20) throw std::runtime_error("maximum supported split depth reached");
    if (carried.accepted + 1 < carried.states || carried.accepted + 1 - carried.states != pending.size())
        throw std::runtime_error("source frontier/statistics conservation check failed");

    fs::create_directories(target / "done");
    RunLock target_lock(target / "run.lock");
    Options next = old; next.split++; next.task_limit = limit; next.checkpoint = target;
    Control control; control.audit = old.audit;
    std::vector<Task> tasks;
    std::size_t expanded = 0, retained = 0;
    const auto start = std::chrono::steady_clock::now();
    auto last = start;
    std::cout << "refine_start: k=" << old.k << " completed_preserved=" << completed
              << " pending=" << pending.size() << " target_depth=" << next.split
              << " task_limit=" << limit << '\n' << std::flush;

    for (std::size_t index = 0; index < pending.size(); ++index) {
        if (interrupted) throw Cancelled{};
        Task& parent = old_tasks[pending[index]];
        const std::size_t remaining = pending.size() - index - 1;
        // Reserve one slot for every remaining parent. Never silently discard
        // a branch when the refined frontier hits the memory/task limit.
        const std::size_t budget = limit - tasks.size() - remaining;
        if (budget <= 1) {
            tasks.push_back(std::move(parent)); ++retained;
        } else {
            std::vector<Task> children;
            bool overflow = false;
            Engine engine(old.k, control);
            engine.explore(parent.graph, parent.anchor, 1, [&](const Graph& g, int anchor) {
                if (children.size() == budget) { overflow = true; control.stop = true; }
                else children.push_back({g, anchor});
            });
            if (interrupted) throw Cancelled{};
            if (!control.candidate.empty()) {
                atomic_write(target / "candidate.txt", control.candidate);
                std::cout << "candidate_found: " << (target / "candidate.txt").string() << '\n';
                return 100;
            }
            if (overflow) {
                control.stop = false;
                tasks.push_back(std::move(parent)); ++retained;
            } else {
                carried.merge(engine.stats);
                for (auto& child : children) tasks.push_back(std::move(child));
                ++expanded;
            }
        }
        const auto now = std::chrono::steady_clock::now();
        if (std::chrono::duration<double>(now - last).count() >= 5) {
            std::cout << "refine_progress: parents=" << index + 1 << '/' << pending.size()
                      << " tasks=" << tasks.size() << " expanded=" << expanded
                      << " retained=" << retained << '\n' << std::flush;
            last = now;
        }
    }
    if (interrupted) throw Cancelled{};
    if (carried.accepted + 1 < carried.states || carried.accepted + 1 - carried.states != tasks.size())
        throw std::runtime_error("refined frontier/statistics conservation check failed");
    const std::string updated = task_text(next, carried, tasks);
    std::ostringstream provenance;
    provenance << "source=" << fs::absolute(source).string() << '\n'
               << "source_manifest_fingerprint=" << identity << '\n'
               << "source_completed_preserved=" << completed << '\n'
               << "source_pending=" << pending.size() << '\n'
               << "expanded_parents=" << expanded << '\n'
               << "retained_parents=" << retained << '\n'
               << "target_tasks=" << tasks.size() << '\n'
               << "target_split_depth=" << next.split << '\n'
               << "target_task_limit=" << limit << '\n';
    // Publish the provenance before the new runnable manifest. An interrupted
    // refinement cannot look like a finished search or a valid empty run.
    atomic_write(target / "refinement.txt", provenance.str());
    atomic_write(target / "tasks.txt", updated);
    std::cout << "refine_complete: completed_preserved=" << completed
              << " old_pending=" << pending.size() << " expanded=" << expanded
              << " retained=" << retained << " new_tasks=" << tasks.size()
              << " checkpoint=" << target.string() << '\n' << std::flush;
    return 0;
}

int main(int argc, char** argv) {
    using namespace eg;
    try {
        fs::path source, target;
        std::size_t limit = 200000;
        for (int i = 1; i < argc; ++i) {
            const std::string arg = argv[i];
            if (arg == "--help") {
                std::cout << "eg_refine --from OLD --to NEW [--task-limit 200000]\n";
                return 0;
            }
            if (++i >= argc) throw std::runtime_error("missing option value");
            if (arg == "--from") source = argv[i];
            else if (arg == "--to") target = argv[i];
            else if (arg == "--task-limit") limit = std::stoull(argv[i]);
            else throw std::runtime_error("unknown option " + arg);
        }
        if (source.empty() || target.empty() || limit == 0)
            throw std::runtime_error("--from and --to are required, with a positive task limit");
        std::signal(SIGINT, signal_handler); std::signal(SIGTERM, signal_handler);
        return refine(source, target, limit);
    } catch (const Cancelled&) {
        std::cout << "incomplete_refinement: source is unchanged; choose a fresh destination on retry\n";
        return 130;
    } catch (const std::exception& e) {
        std::cerr << "error: " << e.what() << '\n'; return 2;
    }
}
