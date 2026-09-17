//! Expression bytecode.
//!
//! The compiler hands the engine expression trees as nested JSON lists,
//! `["mul", ["const", 2.0], ["ref", 3]]`, with every symbol already replaced
//! by an index into the flat evaluation table `[states, inputs, params, t]`.
//! Each tree is flattened once into a postfix program and evaluated on a
//! small stack. No allocation happens per evaluation.

use crate::error::{EngineError, Result};
use serde_json::Value;

#[derive(Debug, Clone, Copy, PartialEq)]
pub enum Instr {
    Const(f64),
    Load(usize),
    Neg,
    Sqrt,
    Exp,
    Log,
    Abs,
    Tanh,
    Sin,
    Cos,
    Sign,
    Add,
    Sub,
    Mul,
    Div,
    Pow,
    Max,
    Min,
    Gt,
    Where,
    /// Piecewise polynomial of degree <= 2; the index points into `Program::tables`.
    Pw(usize),
}

/// A table for `Instr::Pw`: segment `i` covers `knots[i] <= x < knots[i+1]`
/// and evaluates `c0 + c1 d + c2 d^2` with `d = x - knots[i]`. The end
/// segments extrapolate.
#[derive(Debug, Clone, PartialEq)]
pub struct PwTable {
    knots: Vec<f64>,
    coefs: Vec<[f64; 3]>,
}

impl PwTable {
    #[inline]
    fn eval(&self, x: f64) -> f64 {
        let n = self.coefs.len();
        let i = if x >= self.knots[n] {
            n - 1
        } else if x < self.knots[1] {
            0
        } else {
            // largest i with knots[i] <= x
            match self
                .knots
                .binary_search_by(|k| k.partial_cmp(&x).unwrap_or(std::cmp::Ordering::Less))
            {
                Ok(i) => i.min(n - 1),
                Err(i) => i - 1,
            }
        };
        let d = x - self.knots[i];
        let [c0, c1, c2] = self.coefs[i];
        c0 + d * (c1 + d * c2)
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct Program {
    code: Vec<Instr>,
    tables: Vec<PwTable>,
    pub max_stack: usize,
    pub max_ref: Option<usize>,
}

impl Program {
    pub fn constant(v: f64) -> Program {
        Program {
            code: vec![Instr::Const(v)],
            tables: Vec::new(),
            max_stack: 1,
            max_ref: None,
        }
    }

    /// Parse one expression tree.
    pub fn from_json(v: &Value) -> Result<Program> {
        let mut code = Vec::new();
        let mut tables = Vec::new();
        parse_into(v, &mut code, &mut tables)?;
        let mut depth = 0usize;
        let mut max_stack = 0usize;
        let mut max_ref = None;
        for ins in &code {
            let (pop, push) = match ins {
                Instr::Const(_) => (0, 1),
                Instr::Load(i) => {
                    max_ref = Some(max_ref.map_or(*i, |m: usize| m.max(*i)));
                    (0, 1)
                }
                Instr::Neg
                | Instr::Sqrt
                | Instr::Exp
                | Instr::Log
                | Instr::Abs
                | Instr::Tanh
                | Instr::Sin
                | Instr::Cos
                | Instr::Sign
                | Instr::Pw(_) => (1, 1),
                Instr::Where => (3, 1),
                _ => (2, 1),
            };
            if depth < pop {
                return Err(EngineError::Malformed(
                    "stack underflow in expression".into(),
                ));
            }
            depth = depth - pop + push;
            max_stack = max_stack.max(depth);
        }
        if depth != 1 {
            return Err(EngineError::Malformed(
                "expression does not reduce to one value".into(),
            ));
        }
        Ok(Program {
            code,
            tables,
            max_stack,
            max_ref,
        })
    }

    /// Evaluate against the flat table. `stack` is scratch space, reused.
    #[inline]
    pub fn eval(&self, env: &[f64], stack: &mut Vec<f64>) -> f64 {
        stack.clear();
        for ins in &self.code {
            match *ins {
                Instr::Const(c) => stack.push(c),
                Instr::Load(i) => stack.push(env[i]),
                Instr::Neg => {
                    let a = stack.pop().unwrap();
                    stack.push(-a)
                }
                Instr::Sqrt => {
                    let a = stack.pop().unwrap();
                    stack.push(a.sqrt())
                }
                Instr::Exp => {
                    let a = stack.pop().unwrap();
                    stack.push(a.exp())
                }
                Instr::Log => {
                    let a = stack.pop().unwrap();
                    stack.push(a.ln())
                }
                Instr::Abs => {
                    let a = stack.pop().unwrap();
                    stack.push(a.abs())
                }
                Instr::Tanh => {
                    let a = stack.pop().unwrap();
                    stack.push(a.tanh())
                }
                Instr::Sin => {
                    let a = stack.pop().unwrap();
                    stack.push(a.sin())
                }
                Instr::Cos => {
                    let a = stack.pop().unwrap();
                    stack.push(a.cos())
                }
                Instr::Sign => {
                    let a = stack.pop().unwrap();
                    stack.push(if a == 0.0 { 0.0 } else { a.signum() })
                }
                Instr::Add => {
                    let b = stack.pop().unwrap();
                    let a = stack.pop().unwrap();
                    stack.push(a + b)
                }
                Instr::Sub => {
                    let b = stack.pop().unwrap();
                    let a = stack.pop().unwrap();
                    stack.push(a - b)
                }
                Instr::Mul => {
                    let b = stack.pop().unwrap();
                    let a = stack.pop().unwrap();
                    stack.push(a * b)
                }
                Instr::Div => {
                    let b = stack.pop().unwrap();
                    let a = stack.pop().unwrap();
                    stack.push(a / b)
                }
                Instr::Pow => {
                    let b = stack.pop().unwrap();
                    let a = stack.pop().unwrap();
                    stack.push(if b == 2.0 { a * a } else { a.powf(b) })
                }
                Instr::Max => {
                    let b = stack.pop().unwrap();
                    let a = stack.pop().unwrap();
                    stack.push(if a >= b { a } else { b })
                }
                Instr::Min => {
                    let b = stack.pop().unwrap();
                    let a = stack.pop().unwrap();
                    stack.push(if a <= b { a } else { b })
                }
                Instr::Gt => {
                    let b = stack.pop().unwrap();
                    let a = stack.pop().unwrap();
                    stack.push(if a > b { 1.0 } else { 0.0 })
                }
                Instr::Where => {
                    let b = stack.pop().unwrap();
                    let a = stack.pop().unwrap();
                    let c = stack.pop().unwrap();
                    stack.push(if c != 0.0 { a } else { b })
                }
                Instr::Pw(t) => {
                    let x = stack.pop().unwrap();
                    stack.push(self.tables[t].eval(x))
                }
            }
        }
        stack[0]
    }

    pub fn len(&self) -> usize {
        self.code.len()
    }

    pub fn is_empty(&self) -> bool {
        self.code.is_empty()
    }
}

fn parse_into(v: &Value, code: &mut Vec<Instr>, tables: &mut Vec<PwTable>) -> Result<()> {
    let arr = v
        .as_array()
        .ok_or_else(|| EngineError::Malformed(format!("expected a list, got {v}")))?;
    let op = arr
        .first()
        .and_then(Value::as_str)
        .ok_or_else(|| EngineError::Malformed("expression node without an operator".into()))?;
    let arity = |n: usize| -> Result<()> {
        if arr.len() != n + 1 {
            Err(EngineError::Malformed(format!(
                "{op} expects {n} operand(s), got {}",
                arr.len() - 1
            )))
        } else {
            Ok(())
        }
    };
    match op {
        "const" => {
            arity(1)?;
            let c = arr[1]
                .as_f64()
                .ok_or_else(|| EngineError::Malformed("const without a number".into()))?;
            code.push(Instr::Const(c));
        }
        "ref" => {
            arity(1)?;
            let i = arr[1]
                .as_u64()
                .ok_or_else(|| EngineError::Malformed("ref without an index".into()))?;
            code.push(Instr::Load(i as usize));
        }
        "sym" => {
            return Err(EngineError::Malformed(
                "expression still contains a named symbol; lower it first".into(),
            ))
        }
        "where" => {
            arity(3)?;
            for a in &arr[1..4] {
                parse_into(a, code, tables)?;
            }
            code.push(Instr::Where);
        }
        "pw" => {
            arity(3)?;
            parse_into(&arr[1], code, tables)?;
            let knots: Vec<f64> = arr[2]
                .as_array()
                .ok_or_else(|| EngineError::Malformed("pw knots must be a list".into()))?
                .iter()
                .map(|k| {
                    k.as_f64()
                        .ok_or_else(|| EngineError::Malformed("pw knot".into()))
                })
                .collect::<Result<_>>()?;
            let coefs: Vec<[f64; 3]> = arr[3]
                .as_array()
                .ok_or_else(|| EngineError::Malformed("pw coefs must be a list".into()))?
                .iter()
                .map(|c| {
                    let c = c
                        .as_array()
                        .filter(|c| c.len() == 3)
                        .ok_or_else(|| EngineError::Malformed("pw coef triple".into()))?;
                    Ok([
                        c[0].as_f64().unwrap_or(f64::NAN),
                        c[1].as_f64().unwrap_or(f64::NAN),
                        c[2].as_f64().unwrap_or(f64::NAN),
                    ])
                })
                .collect::<Result<_>>()?;
            if knots.len() < 2 || coefs.len() + 1 != knots.len() {
                return Err(EngineError::Malformed(
                    "pw needs n+1 knots and n coefficient triples".into(),
                ));
            }
            if knots.windows(2).any(|w| w[1] <= w[0]) {
                return Err(EngineError::Malformed("pw knots must increase".into()));
            }
            tables.push(PwTable { knots, coefs });
            code.push(Instr::Pw(tables.len() - 1));
        }
        _ => {
            let (n, ins) = match op {
                "neg" => (1, Instr::Neg),
                "sqrt" => (1, Instr::Sqrt),
                "exp" => (1, Instr::Exp),
                "log" => (1, Instr::Log),
                "abs" => (1, Instr::Abs),
                "tanh" => (1, Instr::Tanh),
                "sin" => (1, Instr::Sin),
                "cos" => (1, Instr::Cos),
                "sign" => (1, Instr::Sign),
                "add" => (2, Instr::Add),
                "sub" => (2, Instr::Sub),
                "mul" => (2, Instr::Mul),
                "div" => (2, Instr::Div),
                "pow" => (2, Instr::Pow),
                "max" => (2, Instr::Max),
                "min" => (2, Instr::Min),
                "gt" => (2, Instr::Gt),
                other => return Err(EngineError::Malformed(format!("unknown operator {other}"))),
            };
            arity(n)?;
            for a in &arr[1..=n] {
                parse_into(a, code, tables)?;
            }
            code.push(ins);
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn piecewise_interpolates_and_extrapolates() {
        // interp of (0,3) (1,3.5) (2,3.7) (3,4.2)
        let p = Program::from_json(&json!([
            "pw",
            ["ref", 0],
            [0.0, 1.0, 2.0, 3.0],
            [[3.0, 0.5, 0.0], [3.5, 0.2, 0.0], [3.7, 0.5, 0.0]]
        ]))
        .unwrap();
        let mut st = Vec::new();
        for (x, want) in [
            (-0.5, 2.75),
            (0.5, 3.25),
            (1.5, 3.6),
            (2.999, 4.1995),
            (3.0, 4.2),
            (4.0, 4.7),
        ] {
            assert!((p.eval(&[x], &mut st) - want).abs() < 1e-12, "x={x}");
        }
    }

    #[test]
    fn evaluates_arithmetic() {
        let p = Program::from_json(&json!([
            "add",
            ["mul", ["const", 2.0], ["ref", 0]],
            ["const", 1.0]
        ]))
        .unwrap();
        let mut st = Vec::new();
        assert_eq!(p.eval(&[3.0], &mut st), 7.0);
    }

    #[test]
    fn where_selects() {
        let p = Program::from_json(&json!([
            "where",
            ["gt", ["ref", 0], ["const", 0.0]],
            ["const", 1.0],
            ["const", -1.0]
        ]))
        .unwrap();
        let mut st = Vec::new();
        assert_eq!(p.eval(&[2.0], &mut st), 1.0);
        assert_eq!(p.eval(&[-2.0], &mut st), -1.0);
    }

    #[test]
    fn rejects_unlowered_symbols() {
        assert!(Program::from_json(&json!(["sym", "state", "q"])).is_err());
    }
}
