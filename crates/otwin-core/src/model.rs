//! The compiled model: the executable form of a physical system.
//!
//! A `Model` owns the bytecode for the right-hand side, its Jacobian, the
//! stored energy and its gradient, the port outputs and the named outputs,
//! together with the current parameter values. It is immutable apart from
//! the parameters, and it is `Send + Sync`, so batches can run in parallel.
//!
//! Evaluation table layout: `[x_0..x_n, u_0..u_m, p_0..p_k, t]`.

use crate::error::{EngineError, Result};
use crate::expr::Program;
use serde_json::Value;

#[derive(Debug, Clone)]
pub struct Model {
    pub n_states: usize,
    pub n_inputs: usize,
    pub n_params: usize,
    pub params: Vec<f64>,
    pub rhs: Vec<Program>,
    pub jacobian: Option<Vec<Program>>,
    pub energy: Program,
    pub grad_h: Vec<Program>,
    pub port_outputs: Vec<Program>,
    pub port_values: Vec<Program>,
    pub outputs: Vec<Program>,
    pub output_names: Vec<String>,
}

/// Scratch buffers so that the inner loop never allocates.
pub struct Scratch {
    pub env: Vec<f64>,
    pub stack: Vec<f64>,
    pub tmp: Vec<f64>,
}

impl Scratch {
    pub fn for_model(m: &Model) -> Scratch {
        Scratch {
            env: vec![0.0; m.table_len()],
            stack: Vec::with_capacity(64),
            tmp: vec![0.0; m.n_states * 8 + 8],
        }
    }
}

fn programs(v: Option<&Value>, what: &str) -> Result<Vec<Program>> {
    let arr = v
        .and_then(Value::as_array)
        .ok_or_else(|| EngineError::Malformed(format!("missing list {what}")))?;
    arr.iter().map(Program::from_json).collect()
}

impl Model {
    /// Load the lowered IR (`PHSIR.lower()` on the Python side) from JSON text.
    pub fn from_json_str(text: &str) -> Result<Model> {
        let v: Value = serde_json::from_str(text)
            .map_err(|e| EngineError::Malformed(format!("not JSON: {e}")))?;
        Model::from_value(&v)
    }

    pub fn from_value(v: &Value) -> Result<Model> {
        let get_usize = |k: &str| -> Result<usize> {
            v.get(k)
                .and_then(Value::as_u64)
                .map(|x| x as usize)
                .ok_or_else(|| EngineError::Malformed(format!("missing integer {k}")))
        };
        let n_states = get_usize("n_states")?;
        let n_inputs = get_usize("n_inputs")?;
        let n_params = get_usize("n_params")?;
        let params: Vec<f64> = v
            .get("param_values")
            .and_then(Value::as_array)
            .ok_or_else(|| EngineError::Malformed("missing param_values".into()))?
            .iter()
            .map(|x| x.as_f64().unwrap_or(f64::NAN))
            .collect();
        if params.len() != n_params {
            return Err(EngineError::Malformed("param_values length differs from n_params".into()));
        }
        let rhs = programs(v.get("rhs"), "rhs")?;
        if rhs.len() != n_states {
            return Err(EngineError::Malformed("rhs length differs from n_states".into()));
        }
        let jacobian = match v.get("jacobian") {
            Some(Value::Null) | None => None,
            Some(j) => {
                let progs = programs(Some(j), "jacobian")?;
                if progs.len() != n_states * n_states {
                    return Err(EngineError::Malformed("jacobian is not n_states^2 long".into()));
                }
                Some(progs)
            }
        };
        let energy = match v.get("energy") {
            Some(Value::Null) | None => Program::constant(0.0),
            Some(e) => Program::from_json(e)?,
        };
        let grad_h = match v.get("grad_H") {
            Some(Value::Null) | None => Vec::new(),
            Some(g) => programs(Some(g), "grad_H")?,
        };
        let port_outputs = match v.get("port_outputs") {
            Some(Value::Null) | None => Vec::new(),
            Some(p) => programs(Some(p), "port_outputs")?,
        };
        let port_values = match v.get("port_values") {
            Some(Value::Null) | None => Vec::new(),
            Some(p) => programs(Some(p), "port_values")?,
        };
        if port_values.len() != port_outputs.len() {
            return Err(EngineError::Malformed("port_values and port_outputs differ in length".into()));
        }
        let outputs = match v.get("outputs") {
            Some(Value::Null) | None => Vec::new(),
            Some(o) => programs(Some(o), "outputs")?,
        };
        let output_names: Vec<String> = v
            .get("output_names")
            .and_then(Value::as_array)
            .map(|a| a.iter().map(|s| s.as_str().unwrap_or("").to_string()).collect())
            .unwrap_or_default();
        if output_names.len() != outputs.len() {
            return Err(EngineError::Malformed("output_names and outputs differ in length".into()));
        }
        let model = Model {
            n_states,
            n_inputs,
            n_params,
            params,
            rhs,
            jacobian,
            energy,
            grad_h,
            port_outputs,
            port_values,
            outputs,
            output_names,
        };
        let table = model.table_len();
        for p in model
            .rhs
            .iter()
            .chain(model.jacobian.iter().flatten())
            .chain(std::iter::once(&model.energy))
            .chain(model.grad_h.iter())
            .chain(model.port_outputs.iter())
            .chain(model.port_values.iter())
            .chain(model.outputs.iter())
        {
            if let Some(r) = p.max_ref {
                if r >= table {
                    return Err(EngineError::Malformed(format!(
                        "expression refers to table slot {r} but the table has {table} entries"
                    )));
                }
            }
        }
        Ok(model)
    }

    #[inline]
    pub fn table_len(&self) -> usize {
        self.n_states + self.n_inputs + self.n_params + 1
    }

    pub fn set_params(&mut self, p: &[f64]) -> Result<()> {
        if p.len() != self.n_params {
            return Err(EngineError::Shape(format!(
                "expected {} parameter values, got {}",
                self.n_params,
                p.len()
            )));
        }
        self.params.copy_from_slice(p);
        Ok(())
    }

    /// Fill the evaluation table.
    #[inline]
    pub fn fill_env(&self, x: &[f64], u: &[f64], t: f64, env: &mut [f64]) {
        let n = self.n_states;
        let m = self.n_inputs;
        env[..n].copy_from_slice(&x[..n]);
        if m > 0 {
            env[n..n + m].copy_from_slice(&u[..m]);
        }
        env[n + m..n + m + self.n_params].copy_from_slice(&self.params);
        env[n + m + self.n_params] = t;
    }

    /// dx/dt into `out`.
    #[inline]
    pub fn rhs_into(&self, x: &[f64], u: &[f64], t: f64, out: &mut [f64], s: &mut Scratch) {
        self.fill_env(x, u, t, &mut s.env);
        for (i, p) in self.rhs.iter().enumerate() {
            out[i] = p.eval(&s.env, &mut s.stack);
        }
    }

    pub fn rhs(&self, x: &[f64], u: &[f64], t: f64) -> Vec<f64> {
        let mut s = Scratch::for_model(self);
        let mut out = vec![0.0; self.n_states];
        self.rhs_into(x, u, t, &mut out, &mut s);
        out
    }

    /// Row-major n x n Jacobian of the right-hand side with respect to x.
    /// Analytic when the compiler supplied one, finite differences otherwise.
    pub fn jacobian_into(&self, x: &[f64], u: &[f64], t: f64, out: &mut [f64], s: &mut Scratch) {
        let n = self.n_states;
        if let Some(j) = &self.jacobian {
            self.fill_env(x, u, t, &mut s.env);
            let mut finite = true;
            for (k, p) in j.iter().enumerate() {
                out[k] = p.eval(&s.env, &mut s.stack);
                finite &= out[k].is_finite();
            }
            if finite {
                return;
            }
            // the analytic form has a removable singularity here (a square
            // root at zero, say); fall through to finite differences
        }
        // finite differences
        let mut f0 = vec![0.0; n];
        let mut f1 = vec![0.0; n];
        let mut xp = x.to_vec();
        self.rhs_into(x, u, t, &mut f0, s);
        for j in 0..n {
            let h = 1e-7 * (1.0 + x[j].abs());
            xp[j] = x[j] + h;
            self.rhs_into(&xp, u, t, &mut f1, s);
            xp[j] = x[j];
            for i in 0..n {
                out[i * n + j] = (f1[i] - f0[i]) / h;
            }
        }
    }

    pub fn jacobian(&self, x: &[f64], u: &[f64], t: f64) -> Vec<f64> {
        let mut s = Scratch::for_model(self);
        let mut out = vec![0.0; self.n_states * self.n_states];
        self.jacobian_into(x, u, t, &mut out, &mut s);
        out
    }

    pub fn energy(&self, x: &[f64], s: &mut Scratch) -> f64 {
        let zeros = vec![0.0; self.n_inputs];
        self.fill_env(x, &zeros, 0.0, &mut s.env);
        self.energy.eval(&s.env, &mut s.stack)
    }

    pub fn grad_h(&self, x: &[f64]) -> Vec<f64> {
        let mut s = Scratch::for_model(self);
        let zeros = vec![0.0; self.n_inputs];
        self.fill_env(x, &zeros, 0.0, &mut s.env);
        self.grad_h.iter().map(|p| p.eval(&s.env, &mut s.stack)).collect()
    }

    pub fn outputs_into(&self, x: &[f64], u: &[f64], t: f64, out: &mut [f64], s: &mut Scratch) {
        self.fill_env(x, u, t, &mut s.env);
        for (i, p) in self.outputs.iter().enumerate() {
            out[i] = p.eval(&s.env, &mut s.stack);
        }
    }

    pub fn outputs(&self, x: &[f64], u: &[f64], t: f64) -> Vec<f64> {
        let mut s = Scratch::for_model(self);
        let mut out = vec![0.0; self.outputs.len()];
        self.outputs_into(x, u, t, &mut out, &mut s);
        out
    }

    /// The conjugate output of every port (delivered current for a voltage
    /// source, velocity for a force, ...).
    pub fn port_outputs(&self, x: &[f64], u: &[f64], t: f64) -> Vec<f64> {
        let mut s = Scratch::for_model(self);
        self.fill_env(x, u, t, &mut s.env);
        self.port_outputs.iter().map(|p| p.eval(&s.env, &mut s.stack)).collect()
    }

    /// Power entering through all ports, `sum_k y_k u_k`.
    pub fn supplied_power(&self, x: &[f64], u: &[f64], t: f64, s: &mut Scratch) -> f64 {
        self.fill_env(x, u, t, &mut s.env);
        let mut total = 0.0;
        for (y, v) in self.port_outputs.iter().zip(self.port_values.iter()) {
            total += y.eval(&s.env, &mut s.stack) * v.eval(&s.env, &mut s.stack);
        }
        total
    }

    pub fn check_shapes(&self, x: &[f64], u: &[f64]) -> Result<()> {
        if x.len() != self.n_states {
            return Err(EngineError::Shape(format!(
                "state has {} entries, the model has {} states",
                x.len(),
                self.n_states
            )));
        }
        if u.len() != self.n_inputs {
            return Err(EngineError::Shape(format!(
                "input has {} entries, the model has {} inputs",
                u.len(),
                self.n_inputs
            )));
        }
        Ok(())
    }
}
