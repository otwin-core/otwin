# Guides

One page per ISO 13374 block, in the order data moves through them. Each is
task-oriented: what you are trying to do, the call that does it, and the trap
that comes with it.

If you want the mathematics instead, go to [Concepts](../concepts/index.md).
If you know the name you want, go to the [API reference](../api/index.md).

```{toctree}
:maxdepth: 1

io
signal
estimate
model
forecast
advise
```

## Which block am I in?

| I want to… | Block |
|---|---|
| read a battery inverter over Modbus | [Acquire](io.md) |
| turn irregular timestamps into a uniform grid | [Condition](signal.md) |
| recover a state of charge I cannot measure | [Estimate](estimate.md) |
| write the asset as an energy balance | [Model](model.md) |
| predict capacity in 60 cycles, with a band | [Forecast](forecast.md) |
| decide whether I am allowed to act on it | [Advise](advise.md) |
