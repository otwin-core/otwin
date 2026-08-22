#!/bin/bash -eu
# Build every fuzz target into $OUT, with its seed corpus.
#
# Called by ClusterFuzzLite inside the container defined by ../Dockerfile.

# The library itself, plus the optional decoders the ingest path can use. No
# torch: the fuzz targets never touch the learned models.
python3 -m pip install --upgrade pip
python3 -m pip install .

# Seed corpora. Random bytes almost never produce the "SunS" marker that starts
# a model chain, so without these the fuzzer spends its budget in the first
# four bytes of the discovery routine.
python3 fuzz/make_seed_corpus.py "$WORK/corpus"

# --collect-all is not optional. PyInstaller freezes each target into one
# executable and decides what to bundle by static analysis plus per-package
# hooks. OSS-Fuzz's base-builder pins PyInstaller 5.0.1 (April 2022); numpy 2.0
# moved its implementation from numpy.core to numpy._core and imports it
# dynamically, so the 2022 hook collects a set of modules that no longer exists
# and the frozen target dies on `import numpy` with
# `No module named 'numpy._core._exceptions'`. --collect-all walks the installed
# package instead of trusting the hook. scipy is listed for the same reason and
# not because it has failed yet.
for target in fuzz/fuzz_*.py; do
  name=$(basename "$target" .py)
  compile_python_fuzzer "$target" --collect-all numpy --collect-all scipy

  case "$name" in
    fuzz_sunspec_chain) seed="$WORK/corpus/sunspec_chain" ;;
    fuzz_manifest)      seed="$WORK/corpus/manifest" ;;
    *)                  seed="" ;;
  esac

  if [ -n "$seed" ] && [ -d "$seed" ]; then
    (cd "$seed" && zip -q -r "$OUT/${name}_seed_corpus.zip" .)
  fi
done
