# Installation

```bash
pip install "otwin[engine]"
```

Python 3.10 or newer. `otwin` itself pulls exactly two packages, NumPy and
SciPy. The `engine` extra adds `otwin-engine`, the compiled Rust runtime,
as a binary wheel for Linux, macOS and Windows.

Without the engine every model still compiles and runs, on a NumPy reference
backend that executes the same intermediate representation. It is about a
hundred times slower and it prints one warning the first time it is used.
`otwin.engine_available()` tells you which one you have.

## Extras

| Extra | Install | Brings in | For |
|---|---|---|---|
| `engine` | `pip install "otwin[engine]"` | otwin-engine | The compiled runtime |
| `modbus` | `pip install "otwin[modbus]"` | pymodbus | Generic Modbus TCP/RTU |
| `sunspec` | `pip install "otwin[sunspec]"` | pysunspec2, pymodbus | SunSpec model chains |
| `gp` | `pip install "otwin[gp]"` | scikit-learn | Gaussian-process residuals and intervals |
| `nn` | `pip install "otwin[nn]"` | PyTorch | Learned port-Hamiltonian models |
| `field` | `pip install "otwin[field]"` | modbus + sunspec | A field deployment |
| `all` | `pip install "otwin[all]"` | everything above | |

`nn` is a ~2 GB download and only two modules need it. It is not in `dev` for
that reason; the torch-free path is tested on every commit.

## Verify

```python
import otwin
print(otwin.__version__, otwin.engine_available())
```

The package ships a PEP 561 `py.typed` marker, so a project that installs
`otwin` and runs mypy gets its own call sites checked against these signatures.

## From source

```bash
git clone https://github.com/otwin-core/otwin
cd otwin
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest -q
```

To build the engine from source you need a Rust toolchain
([rustup](https://rustup.rs)) and `maturin`:

```bash
pip install maturin
maturin develop --release -m crates/otwin-engine/Cargo.toml
cargo test -p otwin-core
```

:::{warning}
Install into a virtual environment. `pip install -e ".[dev]"` against a system
Python pulls a large dependency tree into a place the OS package manager also
manages, and on some systems the resolver is killed part-way through, leaving
an environment that imports `otwin` but not NumPy.
:::

## Connectors are read-only

`otwin.io` can read a Modbus or SunSpec device. It cannot write to one.
Closed-loop actuation is deliberately out of scope: a library that can command
a grid-scale battery is a different kind of artifact with a different kind of
review, and this one has not had that review.
