# Guides

Task by task, in the order you would meet them: describe the asset, build
it from devices, run it, add what the physics leaves out, then the ISO 13374 blocks that turn a
simulation into a twin: acquire, condition, estimate, forecast, advise. Each
page is what you are trying to do, the call that does it, and the trap that
comes with it.

If you want the mathematics instead, go to [Concepts](../concepts/index.md).
If you know the name you want, go to the [API reference](../api/index.md).

```{toctree}
:maxdepth: 1

modelling
devices
simulate
greybox
io
signal
estimate
forecast
advise
model
```

## Which block am I in?

| I want to… | Page |
|---|---|
| describe a machine as components and get a model | [Modelling](modelling.md) |
| build a battery module or a pump line from its data sheet and step it | [Devices](devices.md) |
| run it, with a control law, or a thousand times | [Simulation](simulate.md) |
| add what the physics leaves out and fit it from data | [Grey-box models](greybox.md) |
| read a battery inverter over Modbus | [Acquire](io.md) |
| turn irregular timestamps into a uniform grid | [Condition](signal.md) |
| recover a state of charge I cannot measure | [Estimate](estimate.md) |
| write `H`, `J`, `R`, `g` myself | [The advanced API](model.md) |
| predict capacity in 60 cycles, with a band | [Forecast](forecast.md) |
| decide whether I am allowed to act on it | [Advise](advise.md) |
