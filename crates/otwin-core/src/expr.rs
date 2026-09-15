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
}

#[derive(Debug, Clone, PartialEq)]
pub struct Program {
    code: Vec<Instr>,
    pub max_stack: usize,
    pub max_ref: Option<usize>,
}

impl Program {
    pub fn constant(v: f64) -> Program {
        Program {
            code: vec![Instr::Const(v)],
            max_stack: 1,
            max_ref: None,
        }
    }

    /// Parse one expression tree.
    pub fn from_json(v: &Value) -> Result<Program> {
        let mut code = Vec::new();
        parse_into(v, &mut code)?;
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
                | Instr::Sign => (1, 1),
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

fn parse_into(v: &Value, code: &mut Vec<Instr>) -> Result<()> {
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
                parse_into(a, code)?;
            }
            code.push(Instr::Where);
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
                parse_into(a, code)?;
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
