//! # otwin-core
//!
//! The dynamics engine behind [OTwin](https://github.com/otwin-core/otwin).
//!
//! The Python side describes a physical system with components and compiles
//! it into a port-Hamiltonian intermediate representation whose entries are
//! symbolic expressions. This crate loads the lowered form of that IR and
//! runs it: expression bytecode ([`expr`]), the compiled [`model::Model`],
//! and the integrators in [`solver`]. Nothing here knows what a resistor is.
//! That is deliberate. The engine executes equations; the compiler decides
//! what they are.

#![allow(clippy::needless_range_loop)]

pub mod error;
pub mod expr;
pub mod model;
pub mod solver;

pub use error::{EngineError, Result};
pub use model::{Model, Scratch};
pub use solver::{
    simulate, simulate_batch, step, Inputs, Interp, Method, Options, Stats, Trajectory,
};

/// Version of the engine crate.
pub const VERSION: &str = env!("CARGO_PKG_VERSION");
