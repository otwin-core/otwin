# Conformance

One specification. Any number of implementations. Executable tests that decide which
of them got the physics right.

An implementation is **conformant** when the suite reports no failures against it and
at least one fixture passes. The suite is a package of its own, and it can judge an
implementation written in any language.

```{code-block} bash
pip install otwin-spec
otwin-conformance python
```

```text
  otwin conformance suite v0.1.0
  implementation: python (reference)

    PASS  dc_motor_coastdown_passivity   2 checks
    PASS  dc_motor_steady_state          3 checks
    PASS  iphs_second_law                3 checks
    PASS  manifest_roundtrip             3 checks
    PASS  phs_structure_water_tank       2 checks
    PASS  pumped_hydro_conservation      3 checks
    PASS  water_tank_drain_law           2 checks
    PASS  water_tank_passivity           2 checks

  8 passed, 0 failed, 0 unsupported
  conformant: yes
```

## The fixtures are not synthetic

Every fixture is a physical system whose correct answer is known in closed form.
Nothing is fitted, and nothing is compared against a previous run of the same code.

| Fixture | Ground truth |
|---|---|
| `phs_structure_water_tank` | `J + Jᵀ = 0` and `λ_min(R) ≥ 0`, algebraic identities |
| `water_tank_passivity` | `dH/dt ≤ 0` with the inflow off, run past the emptying time |
| `water_tank_drain_law` | `h(t) = (√h₀ − c_d·a·√(2g)·t/2A)²`, exact Torricelli discharge |
| `dc_motor_steady_state` | `ω_ss = VK/(R_e·b + K²)` and `I_ss = Vb/(R_e·b + K²)` |
| `dc_motor_coastdown_passivity` | two stores coupled by a gyrator, energy non-increasing |
| `pumped_hydro_conservation` | `dH/dt = −c(p_u − p_l)²`, the analytic penstock leakage |
| `iphs_second_law` | `dU/dt = 0` and `σ = λ(T₁−T₂)²/(T₁T₂) ≥ 0` rising |
| `manifest_roundtrip` | schema validity, lossless round-trip, `NaN` rejection |

The motor structure follows van der Schaft and Jeltsema (2014), example 2.5. The
irreversible system follows Ramírez, Maschke and Sbarbaro (2013).

The suite does not test whether two implementations produce similar numbers. It
tests whether an implementation satisfies physical properties and reproduces results
that are known independently of it.

## What a failure says

```text
    FAIL  dc_motor_steady_state   3 of 3 checks failed
          [fail] J_skew
                 expected: the gyrator coupling is skew-symmetric
                 max |J + J^T| = 0.1 > 1e-12. J is not skew-symmetric, so the
                 interconnection is not lossless and the power balance does not hold.
```

A failure names the check, the property it stands for, the two numbers compared and
what the discrepancy means physically. That is the difference between a test suite
and a red light.

## The suite has teeth, and proves it

A conformance suite that only ever passes is decoration. This one ships **mutants**,
deliberately broken implementations with one realistic defect each, and asserts that
every mutant is caught by the check meant to catch it rather than merely caught
somehow.

| Mutant | Caught by | Sensitivity |
|---|---|---|
| `J` not skew-symmetric | `J_skew` | `\|J + Jᵀ\| > 10⁻¹²` |
| `R` negative | `R_psd`, and passivity downstream | `λ_min < −10⁻¹²` |
| energy-leaking integrator | `energy_non_increasing` | any step-to-step gain above `10⁻⁹` J |
| gyrator constant off by 10 % | `phi_steady_state`, `p_steady_state` | detected down to 0.001 % |
| negative entropy production | `entropy_production_non_negative` | `σ < −10⁻¹²` |
| manifest writer emitting `NaN` | `rejects_nan` | any occurrence |
| an implementation with no physics at all | 7 of 8 fixtures | see below |
| diverged run | `energy_non_increasing` | refuses to answer on non-finite data |

A new fixture is only accepted with a mutant that proves its check works. A check
without a mutant is untested code protecting untested code.

## The adversary that is not trying

Every mutant above is a real implementation with one thing broken. The one that
actually threatens a suite like this is an implementation that is not trying at all,
one that reads its input, emits plausibly-shaped numbers and hopes.

An earlier version of the runner sent each implementation the whole fixture,
including the expected answers. Sixty lines of fabrication then scored eight out of
eight, bright green, containing no model, no integrator and no physics whatsoever.

The runner now strips the checks, the rationale and the derived quantities before the
document reaches the implementation. It receives the question, never the answer key.
The fabricator is kept permanently as a test, and a test asserts that it stays
caught.

It is still caught by only seven of the eight fixtures. `phs_structure_water_tank`
passes, because zero matrices are both skew-symmetric and positive semidefinite.
That is a real limit, and it is written down rather than hidden: the matrix checks
validate a *reported* matrix, never the model that produced the trajectory. Closing
it needs cross-consistency checks between the reported energy, the reported state and
the reported derivative, and that work is open.

Two further properties of the runner are worth naming, because both are ways a suite
like this usually rots.

**Silence is not conformance.** An implementation that reports no numbers gets every
check skipped, and a fixture whose checks all skipped does not pass. An empty
implementation cannot earn a green badge.

**A declared gap is different from a silent one.** An implementation may list a
fixture as unsupported and remain conformant so far. One that attempts a fixture and
gets it wrong fails.

## Judging an implementation in another language

An implementation is a **subprocess**, not a library. It reads a fixture on standard
input and writes numbers on standard output. That is the entire integration surface,
which is why the suite knows nothing about Julia or MATLAB and can still judge them.

```text
stdin  →  { "id": "dc_motor_steady_state", "model_kind": "dc_motor",
            "parameters": {...}, "scenario": {...} }
            # no "checks": the implementation gets the question, not the answers

stdout ←  { "fixture_id": "dc_motor_steady_state",
            "implementation": "julia",
            "outputs": { "t": [...], "state": [[...]], "energy": [...],
                         "matrices": {"J": [[[...]]], "R": [[[...]]]} },
            "unsupported": [] }
```

**An implementation reports numbers. It never judges itself.** If the MATLAB binding
checked its own passivity in MATLAB, a bug in the check would hide a bug in the
model. Here it reports an energy trace and the suite decides whether that trace is
monotone, through the same code path that judges Python.

```{code-block} bash
otwin-conformance "julia --project=. adapters/conformance.jl" --name julia
otwin-conformance "matlab -batch otwin_conformance" --name matlab
otwin-conformance python --report conformance.json --badge badge.json
```

`--badge` writes a `shields.io` endpoint payload, so any repository can display its
conformance status. Templates for new languages are in
[adapters/](https://github.com/otwin-core/otwin-spec/tree/main/adapters), and the
reference implementation of an adapter is about a hundred and thirty lines.

## Contributing a fixture

The most useful contribution to the specification is a new fixture: a physical
system with a closed-form answer that no current fixture covers. Thermal,
electrical, chemical, mechanical, all welcome. It needs four things.

1. A physical system and its parameters.
2. A closed-form or otherwise analytically known result.
3. A stated rationale: what would go wrong if this were not checked.
4. A mutant that proves the check works.

See [otwin-spec](https://github.com/otwin-core/otwin-spec) for the contribution
guide.
