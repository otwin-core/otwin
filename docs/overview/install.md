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
| `opcua` | `pip install "otwin[opcua]"` | asyncua | OPC UA, read-only |
| `gp` | `pip install "otwin[gp]"` | scikit-learn | Gaussian-process residuals and intervals |
| `nn` | `pip install "otwin[nn]"` | PyTorch | Learned port-Hamiltonian models |
| `field` | `pip install "otwin[field]"` | modbus + sunspec | A field deployment |
| `tutorials` | `pip install "otwin[tutorials]"` | matplotlib, seaborn, pandas | Running the tutorials and their plots |
| `all` | `pip install "otwin[all]"` | engine, modbus, sunspec, nn, gp | |

`nn` is a ~2 GB download and only two modules need it. It is not in `dev` for
that reason; the torch-free path is tested on every commit. `opcua` is left out
of `field` and `all` on purpose: asyncua is licensed LGPL-3.0-or-later, unlike
the rest of the dependencies, so it is installed only when you ask for it.

## Verify

```python
import otwin
print(otwin.__version__, otwin.engine_available())
```

The package ships a PEP 561 `py.typed` marker, so a project that installs
`otwin` and runs mypy gets its own call sites checked against these signatures.

## Check where a release came from

Every file of a release is built on GitHub Actions and signed there, and the
signatures are public. You can check that the wheel you have was built from
this repository, without trusting the download.

On PyPI, each file of a release carries a PEP 740 attestation, verified by PyPI
itself: the files list on [pypi.org/project/otwin](https://pypi.org/project/otwin/#files)
shows who built each one. With the GitHub CLI you can check a file you have
downloaded:

```bash
pip download otwin --no-deps -d .
gh attestation verify otwin-*.whl --repo otwin-core/otwin
```

The build runs in its own reusable workflow, isolated from the rest of the
release, which is what SLSA Build Level 3 asks for. To check that too, name the
workflow that signed it:

```bash
gh attestation verify otwin-*.whl --repo otwin-core/otwin \
  --signer-workflow otwin-core/otwin/.github/workflows/build-artifacts.yml
```

## From Julia

[Otwin.jl](https://github.com/otwin-core/otwin/tree/main/julia/Otwin.jl) calls
this package through PythonCall, with Julia values in and out. It installs a
private Python and `otwin` the first time it loads; you do not need a Python of
your own.

```julia
using Pkg
Pkg.add(url = "https://github.com/otwin-core/otwin", subdir = "julia/Otwin.jl")
```

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

`otwin.io` can read a Modbus, SunSpec or OPC UA device. It cannot write to one.
Closed-loop actuation is deliberately out of scope: a library that can command
a grid-scale battery is a different kind of artifact with a different kind of
review, and this one has not had that review.
