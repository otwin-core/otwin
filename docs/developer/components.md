# Adding components

A component is a class that declares ports, parameters and constitutive
relations. It contains no numerics: the compiler reads its branches once and
never calls it again. Two cases, in increasing order of work.

## A composite: build it from primitives

Most devices are combinations of things the library already has. A battery
cell with an internal resistance is a capacitor and a resistor:

```python
import otwin
from otwin.components.base import Composite
from otwin.components.electrical import Capacitor, Resistor, Ground

class BatteryCell(Composite):
    type_name = "cell"
    domain = "electrical"

    def __init__(self, capacity=3600.0, resistance=0.05, *, voltage=3.7, name=None):
        super().__init__(name)
        store = Capacitor(capacity, voltage=voltage, name="store")   # 3600 F: 1 Ah per volt
        internal = Resistor(resistance, name="internal")
        self.add(store, internal)             # parts are renamed <cell>.store, <cell>.internal
        self.connect(store.p, internal.p)        # internal wiring
        self.expose("p", internal.n)          # the ports the outside sees
        self.expose("n", store.n)

cell, load, gnd = BatteryCell(name="cell"), Resistor(10.0, name="load"), Ground()
s = otwin.System(cell, load, gnd).connect(cell.p, load.p).connect(cell.n, load.n, gnd.port)
m = otwin.compile(s)
print(m.state_names)
run = m.simulate(t_span=(0, 3600), dt=10.0)
print(f"{run['cell.store.voltage'][0]:.3f} V -> {run['cell.store.voltage'][-1]:.3f} V")
```

```text
['cell.store.charge']
3.700 V -> 3.350 V
```

`add` takes the parts, `link` joins inner ports, `expose` publishes an
inner port under an outer name. The compiler flattens the composite; the
parts' states and parameters appear as `cell.store.charge`,
`cell.internal.resistance`. {class}`~otwin.components.composite.DCMotor` is a
composite across two domains and the template to copy for a pump, a valve
actuator or a heat exchanger.

Prefer a composite whenever the physics decomposes into storages, dissipators,
sources and two-ports. It costs one class and inherits every guarantee.

## A primitive: declare a constitutive relation

When the physics is a new *law* rather than a new arrangement, write a
primitive. A component declares:

- `domain` and `type_name` (class attributes);
- ports, with `self.add_port("p")`; the domain defaults to the class's;
- parameters, with `self.add_parameter(name, value, unit, positive=..., nonneg=...)`,
  which returns the parameter's **symbol** for use in laws;
- `branches()`, returning the constitutive relations.

Four kinds of branch:

| class | declares | you give |
|---|---|---|
| `StorageBranch(kind="across")` | state = ∫ through; across = dH/dx | `state`, `state_unit`, `quantity`, `initial`, `energy(x) -> Expr` |
| `StorageBranch(kind="through")` | state = ∫ across; through = dH/dx | the same |
| `ResistorBranch` | through = law(across) | `law(v) -> Expr` |
| `SourceBranch(kind="across" or "through")` | an imposed across or through | `value` (a number, or `None` for an input), `unit`, `quantity` |
| `TwoPortBranch` | transformer or gyrator between two port pairs | `kind`, `a2`, `b2`, `ratio` |

The energy and the law are Python functions of a symbol that return
expressions, built with ordinary arithmetic and {mod}`otwin.expr`. Here a
capacitor whose stored energy is not quadratic:

```python
from otwin.components.base import Component, StorageBranch

class Supercapacitor(Component):
    """A capacitor whose small-signal capacitance grows with voltage."""

    domain = "electrical"
    type_name = "supercapacitor"

    def __init__(self, capacitance=1.0, slope=0.1, *, voltage=0.0, name=None):
        super().__init__(name)
        self.add_port("p")
        self.add_port("n")
        self.C0 = self.add_parameter("capacitance", capacitance, "F")
        self.k = self.add_parameter("slope", slope, "1/V", positive=False)
        self.initial_voltage = float(voltage)

    def branches(self):
        return [
            StorageBranch(
                self, self.p, self.n, kind="across",
                state="charge", state_unit="C", quantity="charge",
                initial=self.initial_voltage * self.value("capacitance"),
                energy=lambda q: q * q / (2 * self.C0) - self.k * q**3 / (6 * self.C0**2),
            )
        ]

sc, r, gnd = Supercapacitor(2.0, 0.2, voltage=1.0, name="sc"), Resistor(5.0, name="r"), Ground()
m = otwin.compile(otwin.System(sc, r, gnd).connect(sc.p, r.p).connect(sc.n, r.n, gnd.port))
print(m.check_structure())
```

```text
{'J_skew': (True, 0.0), 'R_psd': (True, 0.2)}
```

The compiler differentiated the energy to get the port voltage
(`m.ir().grad_H` shows it), derived the discharge equation, and its Jacobian.
Nothing about the new component had to know any of that.

## Extra outputs

`extra_outputs(self, q)` returns `{name: (unit, expr)}` for quantities a
user thinks in but the state is not: `Tank` exposes `level = volume / area`,
`ThermalMass` exposes `temperature = heat / capacity`. `q.state`, `q.across`,
`q.through` and `q.params` give the compiled expressions of this component's
branches by label. A composite receives the merged quantities of all its
parts, keyed by the part's full name (`"bat.ocv"`, `"bat.ocv.charge"`), which
is how `Battery` computes `soc`, `voltage` and `current` from its parts.

## Rules the compiler enforces

- Parameters are validated at construction: `positive=True` by default.
- A `law` must be traceable: arithmetic, `abs`, and the functions in
  `otwin.expr`. Use `where` instead of `if`.
- A `ResistorBranch` may give `inverse=` (across as a function of through)
  instead of, or as well as, `law=`. With only `inverse`, the branch must sit
  in series with an element that fixes its flow; the compiler pins its across
  from that flow and refuses otherwise, naming the element to add.
- An across storage pins the potential across its ports, so two of them
  in parallel are refused. Merge them into one component when that is the
  physics.
- A nonlinear law on a node no storage or source pins is refused (a nonlinear
  algebraic loop). Give the node a storage or make the law linear.
- Parameter symbols are stable under renaming, so a component works
  unchanged inside a composite.

## What to ship with it

A closed-form result the component must reproduce, as a test in
`tests/engine/test_golden.py` (or the `otwin-systems` catalogue), and a
docstring that states the energy function or the law, with units.
