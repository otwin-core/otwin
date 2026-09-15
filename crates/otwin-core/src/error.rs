//! Errors the engine reports. Every variant names what went wrong in the
//! language of the model, not of the solver internals.

use std::fmt;

#[derive(Debug, Clone, PartialEq)]
pub enum EngineError {
    /// The lowered IR could not be parsed.
    Malformed(String),
    /// An argument has the wrong length or shape.
    Shape(String),
    /// A solver did not converge.
    Convergence { time: f64, detail: String },
    /// A value became NaN or infinite.
    NonFinite { time: f64, what: String },
    /// A method or option name is unknown.
    Unknown(String),
}

impl fmt::Display for EngineError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            EngineError::Malformed(s) => write!(f, "malformed model: {s}"),
            EngineError::Shape(s) => write!(f, "{s}"),
            EngineError::Convergence { time, detail } => {
                write!(f, "the implicit step at t = {time} did not converge: {detail}")
            }
            EngineError::NonFinite { time, what } => {
                write!(f, "{what} became non-finite at t = {time}")
            }
            EngineError::Unknown(s) => write!(f, "{s}"),
        }
    }
}

impl std::error::Error for EngineError {}

pub type Result<T> = std::result::Result<T, EngineError>;
