"""The runtime: compiled models, states and trajectories.

``Model`` wraps a compiled representation and a backend (the Rust engine
when installed, NumPy otherwise). ``CustomDynamics`` gives a user-written
``f(x, u, t)`` the same surface.
"""

from .backends import EngineNotAvailable, engine_available
from .custom import CustomDynamics
from .model import Model, State, Trajectory

__all__ = [
    "Model",
    "State",
    "Trajectory",
    "CustomDynamics",
    "EngineNotAvailable",
    "engine_available",
]
