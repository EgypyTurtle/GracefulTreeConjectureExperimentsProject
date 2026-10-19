CXX ?= g++
CXXFLAGS ?= -O3 -std=c++17 -Wall -Wextra

.PHONY: all test clean
all: out/eg_search out/eg_refine out/reference

out:
	mkdir -p out

out/eg_search: search.cpp | out
	$(CXX) $(CXXFLAGS) -pthread $< -o $@

out/eg_refine: refine.cpp search.cpp | out
	$(CXX) $(CXXFLAGS) -Wno-unused-function -pthread refine.cpp -o $@

out/reference: reference/main.cpp reference/lib.cpp reference/graph.cpp reference/graph.h reference/lib.h | out
	$(CXX) $(CXXFLAGS) -Ireference reference/main.cpp reference/lib.cpp reference/graph.cpp -o $@

out/reference_audit: tests/reference_audit.cpp reference/graph.cpp reference/graph.h | out
	$(CXX) $(CXXFLAGS) -Ireference tests/reference_audit.cpp reference/graph.cpp -o $@

out/kernels: tests/kernels.cpp search.cpp reference/graph.cpp reference/graph.h | out
	$(CXX) $(CXXFLAGS) -Wno-unused-function -Ireference -pthread tests/kernels.cpp reference/graph.cpp -o $@

out/wide_oracles: tests/wide_oracles.cpp search.cpp reference/graph.cpp reference/graph.h | out
	$(CXX) $(CXXFLAGS) -Wno-unused-function -Ireference -pthread tests/wide_oracles.cpp reference/graph.cpp -o $@

test: all out/reference_audit out/kernels out/wide_oracles
	./out/kernels
	./out/wide_oracles
	python3 tests/test_verifier.py
	python3 tools/regression.py
	python3 tests/test_refine.py
	python3 tests/test_audit.py

clean:
	rm -f out/eg_search out/eg_refine out/reference out/reference_audit out/kernels out/wide_oracles
