//! Time integration.
//!
//! Four methods. `Midpoint` is the default: the implicit midpoint rule keeps
//! the discrete power balance of a port-Hamiltonian system, so with the ports
//! closed the stored energy of a model with quadratic energy cannot rise on
//! any step. `Rk45` is Dormand-Prince with error control for smooth problems
//! where speed matters more than structure. `Rk4` and `Euler` are fixed-step
//! references.
//!
//! Inputs are given on the same time grid as the output, either held over
//! each interval or interpolated linearly. Control laws that depend on the
//! state are expressed in the model itself (the compiler turns them into
//! expressions), so the integrator never calls back into Python.

use crate::error::{EngineError, Result};
use crate::model::{Model, Scratch};
use rayon::prelude::*;

#[derive(Debug, Clone, Copy, PartialEq)]
pub enum Method {
    Euler,
    Rk4,
    Rk45,
    Midpoint,
}

impl Method {
    pub fn parse(name: &str) -> Result<Method> {
        match name {
            "euler" => Ok(Method::Euler),
            "rk4" => Ok(Method::Rk4),
            "rk45" | "adaptive" => Ok(Method::Rk45),
            "midpoint" | "implicit_midpoint" | "auto" => Ok(Method::Midpoint),
            other => Err(EngineError::Unknown(format!(
                "unknown solver {other:?}; choose euler, rk4, rk45 or midpoint"
            ))),
        }
    }

    pub fn name(&self) -> &'static str {
        match self {
            Method::Euler => "euler",
            Method::Rk4 => "rk4",
            Method::Rk45 => "rk45",
            Method::Midpoint => "midpoint",
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq)]
pub enum Interp {
    Hold,
    Linear,
}

impl Interp {
    pub fn parse(name: &str) -> Result<Interp> {
        match name {
            "hold" | "zoh" | "previous" => Ok(Interp::Hold),
            "linear" => Ok(Interp::Linear),
            other => Err(EngineError::Unknown(format!(
                "unknown input interpolation {other:?}; choose hold or linear"
            ))),
        }
    }
}

#[derive(Debug, Clone, Copy)]
pub struct Options {
    pub rtol: f64,
    pub atol: f64,
    pub newton_tol: f64,
    pub max_newton: usize,
    pub max_substeps: usize,
    pub record_outputs: bool,
    pub record_energy: bool,
}

impl Default for Options {
    fn default() -> Options {
        Options {
            rtol: 1e-8,
            atol: 1e-10,
            newton_tol: 1e-10,
            max_newton: 50,
            max_substeps: 1_000_000,
            record_outputs: true,
            record_energy: true,
        }
    }
}

/// The inputs over the output grid: `values` is `len(t) x n_inputs`, row-major.
#[derive(Debug, Clone)]
pub struct Inputs<'a> {
    pub values: Option<&'a [f64]>,
    pub interp: Interp,
}

impl<'a> Inputs<'a> {
    pub fn none() -> Inputs<'a> {
        Inputs {
            values: None,
            interp: Interp::Hold,
        }
    }

    /// Input at a time inside interval `k` (between grid points k and k+1),
    /// `theta` in [0, 1].
    #[inline]
    fn at(&self, k: usize, theta: f64, m: usize, out: &mut [f64]) {
        match self.values {
            None => {
                for v in out.iter_mut().take(m) {
                    *v = 0.0;
                }
            }
            Some(vals) => {
                let row0 = &vals[k * m..(k + 1) * m];
                match self.interp {
                    Interp::Hold => out[..m].copy_from_slice(row0),
                    Interp::Linear => {
                        let n_rows = vals.len() / m.max(1);
                        let k1 = (k + 1).min(n_rows - 1);
                        let row1 = &vals[k1 * m..(k1 + 1) * m];
                        for i in 0..m {
                            out[i] = row0[i] + theta * (row1[i] - row0[i]);
                        }
                    }
                }
            }
        }
    }
}

#[derive(Debug, Clone, Default)]
pub struct Stats {
    pub steps: usize,
    pub rhs_evals: usize,
    pub newton_iterations: usize,
    pub jacobian_evals: usize,
    pub rejected_steps: usize,
}

#[derive(Debug, Clone)]
pub struct Trajectory {
    pub t: Vec<f64>,
    /// `len(t) x n_states`, row-major.
    pub x: Vec<f64>,
    /// `len(t) x n_inputs`, row-major: the input as the integrator saw it at each grid point.
    pub u: Vec<f64>,
    pub energy: Vec<f64>,
    pub supplied_power: Vec<f64>,
    /// `len(t) x n_outputs`, row-major.
    pub outputs: Vec<f64>,
    pub stats: Stats,
    pub method: Method,
}

struct Work {
    s: Scratch,
    k1: Vec<f64>,
    k2: Vec<f64>,
    k3: Vec<f64>,
    k4: Vec<f64>,
    ks: Vec<f64>,
    out: Vec<f64>,
    xt: Vec<f64>,
    xm: Vec<f64>,
    u: Vec<f64>,
    jac: Vec<f64>,
    lu: Vec<f64>,
    piv: Vec<usize>,
    res: Vec<f64>,
    stats: Stats,
}

impl Work {
    fn new(m: &Model) -> Work {
        let n = m.n_states;
        Work {
            s: Scratch::for_model(m),
            k1: vec![0.0; n],
            k2: vec![0.0; n],
            k3: vec![0.0; n],
            k4: vec![0.0; n],
            ks: vec![0.0; 7 * n],
            out: vec![0.0; m.outputs.len()],
            xt: vec![0.0; n],
            xm: vec![0.0; n],
            u: vec![0.0; m.n_inputs.max(1)],
            jac: vec![0.0; n * n],
            lu: vec![0.0; n * n],
            piv: vec![0; n],
            res: vec![0.0; n],
            stats: Stats::default(),
        }
    }
}

fn check_finite(x: &[f64], t: f64) -> Result<()> {
    if x.iter().any(|v| !v.is_finite()) {
        return Err(EngineError::NonFinite {
            time: t,
            what: "the state".into(),
        });
    }
    Ok(())
}

// ---------------------------------------------------------------------------
// Explicit fixed-step methods. `u_of(theta, out)` gives the input at a fraction
// of the step.
// ---------------------------------------------------------------------------
fn euler_step(
    m: &Model,
    x: &mut [f64],
    t: f64,
    h: f64,
    u_of: &dyn Fn(f64, &mut [f64]),
    w: &mut Work,
) {
    u_of(0.0, &mut w.u);
    m.rhs_into(x, &w.u, t, &mut w.k1, &mut w.s);
    w.stats.rhs_evals += 1;
    for i in 0..x.len() {
        x[i] += h * w.k1[i];
    }
}

fn rk4_step(
    m: &Model,
    x: &mut [f64],
    t: f64,
    h: f64,
    u_of: &dyn Fn(f64, &mut [f64]),
    w: &mut Work,
) {
    let n = x.len();
    u_of(0.0, &mut w.u);
    m.rhs_into(x, &w.u, t, &mut w.k1, &mut w.s);
    for i in 0..n {
        w.xt[i] = x[i] + 0.5 * h * w.k1[i];
    }
    u_of(0.5, &mut w.u);
    m.rhs_into(&w.xt, &w.u, t + 0.5 * h, &mut w.k2, &mut w.s);
    for i in 0..n {
        w.xt[i] = x[i] + 0.5 * h * w.k2[i];
    }
    m.rhs_into(&w.xt, &w.u, t + 0.5 * h, &mut w.k3, &mut w.s);
    for i in 0..n {
        w.xt[i] = x[i] + h * w.k3[i];
    }
    u_of(1.0, &mut w.u);
    m.rhs_into(&w.xt, &w.u, t + h, &mut w.k4, &mut w.s);
    w.stats.rhs_evals += 4;
    for i in 0..n {
        x[i] += h / 6.0 * (w.k1[i] + 2.0 * w.k2[i] + 2.0 * w.k3[i] + w.k4[i]);
    }
}

// ---------------------------------------------------------------------------
// Dormand-Prince 5(4) with step-size control inside one output interval.
// ---------------------------------------------------------------------------
const DP_C: [f64; 7] = [0.0, 1.0 / 5.0, 3.0 / 10.0, 4.0 / 5.0, 8.0 / 9.0, 1.0, 1.0];
const DP_B: [f64; 7] = [
    35.0 / 384.0,
    0.0,
    500.0 / 1113.0,
    125.0 / 192.0,
    -2187.0 / 6784.0,
    11.0 / 84.0,
    0.0,
];
const DP_E: [f64; 7] = [
    35.0 / 384.0 - 5179.0 / 57600.0,
    0.0,
    500.0 / 1113.0 - 7571.0 / 16695.0,
    125.0 / 192.0 - 393.0 / 640.0,
    -2187.0 / 6784.0 + 92097.0 / 339200.0,
    11.0 / 84.0 - 187.0 / 2100.0,
    -1.0 / 40.0,
];
const DP_A: [[f64; 6]; 7] = [
    [0.0; 6],
    [1.0 / 5.0, 0.0, 0.0, 0.0, 0.0, 0.0],
    [3.0 / 40.0, 9.0 / 40.0, 0.0, 0.0, 0.0, 0.0],
    [44.0 / 45.0, -56.0 / 15.0, 32.0 / 9.0, 0.0, 0.0, 0.0],
    [
        19372.0 / 6561.0,
        -25360.0 / 2187.0,
        64448.0 / 6561.0,
        -212.0 / 729.0,
        0.0,
        0.0,
    ],
    [
        9017.0 / 3168.0,
        -355.0 / 33.0,
        46732.0 / 5247.0,
        49.0 / 176.0,
        -5103.0 / 18656.0,
        0.0,
    ],
    [
        35.0 / 384.0,
        0.0,
        500.0 / 1113.0,
        125.0 / 192.0,
        -2187.0 / 6784.0,
        11.0 / 84.0,
    ],
];

/// Integrate from `t0` to `t1` adaptively, with `u_of(theta)` giving the input
/// at fraction `theta` of the output interval. `h_guess` is carried between calls.
#[allow(clippy::too_many_arguments)]
fn rk45_interval(
    m: &Model,
    x: &mut [f64],
    t0: f64,
    t1: f64,
    u_of: &dyn Fn(f64, &mut [f64]),
    opts: &Options,
    h_guess: &mut f64,
    w: &mut Work,
) -> Result<()> {
    let n = x.len();
    let span = t1 - t0;
    let mut t = t0;
    let mut h = if *h_guess > 0.0 {
        h_guess.min(span)
    } else {
        span
    };
    let mut substeps = 0usize;
    let theta = |tt: f64| ((tt - t0) / span).clamp(0.0, 1.0);
    while t < t1 - 1e-14 * span.abs().max(1.0) {
        if t + h > t1 {
            h = t1 - t;
        }
        // stages
        for stage in 0..7 {
            for i in 0..n {
                let mut acc = x[i];
                for j in 0..stage.min(6) {
                    let a = DP_A[stage][j];
                    if a != 0.0 {
                        acc += h * a * w.ks[j * n + i];
                    }
                }
                w.xt[i] = acc;
            }
            u_of(theta(t + DP_C[stage] * h), &mut w.u);
            let (xt, ks, u, s) = (&w.xt, &mut w.ks, &w.u, &mut w.s);
            m.rhs_into(
                xt,
                u,
                t + DP_C[stage] * h,
                &mut ks[stage * n..(stage + 1) * n],
                s,
            );
        }
        w.stats.rhs_evals += 7;
        // error estimate and candidate
        let mut err = 0.0f64;
        for i in 0..n {
            let mut xn = x[i];
            let mut e = 0.0;
            for j in 0..7 {
                let k = w.ks[j * n + i];
                xn += h * DP_B[j] * k;
                e += h * DP_E[j] * k;
            }
            w.xm[i] = xn;
            let sc = opts.atol + opts.rtol * x[i].abs().max(xn.abs());
            err = err.max((e / sc).abs());
        }
        if !err.is_finite() {
            return Err(EngineError::NonFinite {
                time: t,
                what: "the error estimate".into(),
            });
        }
        if err <= 1.0 {
            t += h;
            x.copy_from_slice(&w.xm);
            w.stats.steps += 1;
            let f = if err == 0.0 {
                5.0
            } else {
                (0.9 * err.powf(-0.2)).clamp(0.2, 5.0)
            };
            h *= f;
        } else {
            w.stats.rejected_steps += 1;
            h *= (0.9 * err.powf(-0.25)).clamp(0.1, 0.9);
        }
        substeps += 1;
        if substeps > opts.max_substeps {
            return Err(EngineError::Convergence {
                time: t,
                detail: format!(
                    "more than {} adaptive substeps in one output interval",
                    opts.max_substeps
                ),
            });
        }
        if h < 1e-14 * span.abs().max(1.0) {
            return Err(EngineError::Convergence {
                time: t,
                detail:
                    "the adaptive step collapsed; the right-hand side may be discontinuous or stiff"
                        .into(),
            });
        }
    }
    *h_guess = h;
    Ok(())
}

// ---------------------------------------------------------------------------
// Implicit midpoint with a modified Newton iteration.
// ---------------------------------------------------------------------------
fn lu_factor(a: &mut [f64], n: usize, piv: &mut [usize]) -> bool {
    for k in 0..n {
        let mut p = k;
        let mut best = a[k * n + k].abs();
        for i in k + 1..n {
            let v = a[i * n + k].abs();
            if v > best {
                best = v;
                p = i;
            }
        }
        if best == 0.0 || !best.is_finite() {
            return false;
        }
        piv[k] = p;
        if p != k {
            for j in 0..n {
                a.swap(k * n + j, p * n + j);
            }
        }
        let d = a[k * n + k];
        for i in k + 1..n {
            let f = a[i * n + k] / d;
            a[i * n + k] = f;
            if f != 0.0 {
                for j in k + 1..n {
                    a[i * n + j] -= f * a[k * n + j];
                }
            }
        }
    }
    true
}

fn lu_solve(a: &[f64], n: usize, piv: &[usize], b: &mut [f64]) {
    for k in 0..n {
        let p = piv[k];
        if p != k {
            b.swap(k, p);
        }
        for i in k + 1..n {
            b[i] -= a[i * n + k] * b[k];
        }
    }
    for i in (0..n).rev() {
        let mut s = b[i];
        for j in i + 1..n {
            s -= a[i * n + j] * b[j];
        }
        b[i] = s / a[i * n + i];
    }
}

/// The implicit midpoint step, retried on two half steps when Newton fails,
/// up to a depth that divides the step by 64.
fn midpoint_step(
    m: &Model,
    x: &mut [f64],
    t: f64,
    h: f64,
    u_of: &dyn Fn(f64, &mut [f64]),
    opts: &Options,
    w: &mut Work,
) -> Result<()> {
    midpoint_recursive(m, x, t, h, u_of, opts, w, 0)
}

#[allow(clippy::too_many_arguments)]
fn midpoint_recursive(
    m: &Model,
    x: &mut [f64],
    t: f64,
    h: f64,
    u_of: &dyn Fn(f64, &mut [f64]),
    opts: &Options,
    w: &mut Work,
    depth: usize,
) -> Result<()> {
    let saved = x.to_vec();
    match midpoint_once(m, x, t, h, u_of, opts, w) {
        Ok(()) => Ok(()),
        Err(e) => {
            if depth >= 6 {
                return Err(e);
            }
            x.copy_from_slice(&saved);
            w.stats.rejected_steps += 1;
            let half = 0.5 * h;
            midpoint_recursive(m, x, t, half, u_of, opts, w, depth + 1)?;
            midpoint_recursive(m, x, t + half, half, u_of, opts, w, depth + 1)
        }
    }
}

fn midpoint_once(
    m: &Model,
    x: &mut [f64],
    t: f64,
    h: f64,
    u_of: &dyn Fn(f64, &mut [f64]),
    opts: &Options,
    w: &mut Work,
) -> Result<()> {
    let n = x.len();
    let tm = t + 0.5 * h;
    u_of(0.5, &mut w.u);
    // predictor: explicit Euler
    m.rhs_into(x, &w.u, tm, &mut w.k1, &mut w.s);
    w.stats.rhs_evals += 1;
    for i in 0..n {
        w.xt[i] = x[i] + h * w.k1[i];
    }
    let mut have_lu = false;
    let mut iter = 0usize;
    loop {
        for i in 0..n {
            w.xm[i] = 0.5 * (x[i] + w.xt[i]);
        }
        m.rhs_into(&w.xm, &w.u, tm, &mut w.k2, &mut w.s);
        w.stats.rhs_evals += 1;
        let mut rnorm = 0.0f64;
        let mut xnorm = 0.0f64;
        for i in 0..n {
            w.res[i] = w.xt[i] - x[i] - h * w.k2[i];
            rnorm = rnorm.max(w.res[i].abs());
            xnorm = xnorm.max(w.xt[i].abs());
        }
        if !rnorm.is_finite() {
            return Err(EngineError::NonFinite {
                time: t,
                what: "the Newton residual".into(),
            });
        }
        if rnorm <= opts.newton_tol * (1.0 + xnorm) {
            break;
        }
        if iter >= opts.max_newton {
            return Err(EngineError::Convergence {
                time: t,
                detail: format!(
                    "Newton residual {rnorm:.3e} after {iter} iterations (tolerance {:.1e}); reduce the step or use rk45",
                    opts.newton_tol
                ),
            });
        }
        if !have_lu || iter % 4 == 3 {
            m.jacobian_into(&w.xm, &w.u, tm, &mut w.jac, &mut w.s);
            w.stats.jacobian_evals += 1;
            for i in 0..n {
                for j in 0..n {
                    w.lu[i * n + j] = -0.5 * h * w.jac[i * n + j] + if i == j { 1.0 } else { 0.0 };
                }
            }
            if !lu_factor(&mut w.lu, n, &mut w.piv) {
                return Err(EngineError::Convergence {
                    time: t,
                    detail: "the Newton iteration matrix is singular".into(),
                });
            }
            have_lu = true;
        }
        lu_solve(&w.lu, n, &w.piv, &mut w.res);
        for i in 0..n {
            w.xt[i] -= w.res[i];
        }
        iter += 1;
        w.stats.newton_iterations += 1;
    }
    x.copy_from_slice(&w.xt);
    Ok(())
}

// ---------------------------------------------------------------------------
// Public entry points
// ---------------------------------------------------------------------------

/// One step of the chosen method from `(x, t)` over `dt` with a constant input.
pub fn step(
    m: &Model,
    x: &[f64],
    u: &[f64],
    t: f64,
    dt: f64,
    method: Method,
    opts: &Options,
) -> Result<Vec<f64>> {
    m.check_shapes(x, u)?;
    let mut w = Work::new(m);
    let mut xn = x.to_vec();
    let u_of = |_theta: f64, out: &mut [f64]| out[..u.len()].copy_from_slice(u);
    match method {
        Method::Euler => euler_step(m, &mut xn, t, dt, &u_of, &mut w),
        Method::Rk4 => rk4_step(m, &mut xn, t, dt, &u_of, &mut w),
        Method::Rk45 => {
            let mut hg = 0.0;
            rk45_interval(m, &mut xn, t, t + dt, &u_of, opts, &mut hg, &mut w)?
        }
        Method::Midpoint => midpoint_step(m, &mut xn, t, dt, &u_of, opts, &mut w)?,
    }
    check_finite(&xn, t + dt)?;
    Ok(xn)
}

/// Integrate over the grid `t`, reporting the state at every grid point.
pub fn simulate(
    m: &Model,
    x0: &[f64],
    t: &[f64],
    inputs: &Inputs<'_>,
    method: Method,
    opts: &Options,
) -> Result<Trajectory> {
    let n = m.n_states;
    let mi = m.n_inputs;
    if x0.len() != n {
        return Err(EngineError::Shape(format!(
            "initial state has {} entries, the model has {} states",
            x0.len(),
            n
        )));
    }
    if t.len() < 2 {
        return Err(EngineError::Shape(
            "the time grid needs at least two points".into(),
        ));
    }
    for k in 1..t.len() {
        if t[k] <= t[k - 1] || t[k].is_nan() {
            return Err(EngineError::Shape(format!(
                "the time grid must be strictly increasing (t[{}] = {} after t[{}] = {})",
                k,
                t[k],
                k - 1,
                t[k - 1]
            )));
        }
    }
    if let Some(v) = inputs.values {
        if mi == 0 && !v.is_empty() {
            return Err(EngineError::Shape(
                "the model has no inputs but inputs were given".into(),
            ));
        }
        if mi > 0 && v.len() != t.len() * mi {
            return Err(EngineError::Shape(format!(
                "inputs must be len(t) x n_inputs = {} x {} = {} values, got {}",
                t.len(),
                mi,
                t.len() * mi,
                v.len()
            )));
        }
    } else if mi > 0 {
        // no inputs given: zero. Allowed.
    }
    let n_out = if opts.record_outputs {
        m.outputs.len()
    } else {
        0
    };
    let n_t = t.len();
    let mut traj = Trajectory {
        t: t.to_vec(),
        x: vec![0.0; n_t * n],
        u: vec![0.0; n_t * mi],
        energy: vec![0.0; if opts.record_energy { n_t } else { 0 }],
        supplied_power: vec![0.0; if opts.record_energy { n_t } else { 0 }],
        outputs: vec![0.0; n_t * n_out],
        stats: Stats::default(),
        method,
    };
    let mut w = Work::new(m);
    let mut x = x0.to_vec();
    check_finite(&x, t[0])?;
    let mut h_guess = 0.0;
    let mut u_now = vec![0.0; mi.max(1)];
    let record = |k: usize, x: &[f64], w: &mut Work, traj: &mut Trajectory, u_now: &mut [f64]| {
        traj.x[k * n..(k + 1) * n].copy_from_slice(x);
        let kk = k.min(n_t - 2);
        let theta = if k == n_t - 1 { 1.0 } else { 0.0 };
        inputs.at(kk, theta, mi, u_now);
        if mi > 0 {
            traj.u[k * mi..(k + 1) * mi].copy_from_slice(&u_now[..mi]);
        }
        if opts.record_energy {
            traj.energy[k] = m.energy(x, &mut w.s);
            traj.supplied_power[k] = m.supplied_power(x, &u_now[..mi], t[k], &mut w.s);
        }
        if n_out > 0 {
            let (out, s) = (&mut w.out, &mut w.s);
            m.outputs_into(x, &u_now[..mi], t[k], out, s);
            traj.outputs[k * n_out..(k + 1) * n_out].copy_from_slice(out);
        }
    };
    record(0, &x, &mut w, &mut traj, &mut u_now);
    for k in 0..n_t - 1 {
        let (t0, t1) = (t[k], t[k + 1]);
        let h = t1 - t0;
        let u_of = |theta: f64, out: &mut [f64]| inputs.at(k, theta, mi, out);
        match method {
            Method::Euler => {
                euler_step(m, &mut x, t0, h, &u_of, &mut w);
                w.stats.steps += 1;
            }
            Method::Rk4 => {
                rk4_step(m, &mut x, t0, h, &u_of, &mut w);
                w.stats.steps += 1;
            }
            Method::Rk45 => rk45_interval(m, &mut x, t0, t1, &u_of, opts, &mut h_guess, &mut w)?,
            Method::Midpoint => {
                midpoint_step(m, &mut x, t0, h, &u_of, opts, &mut w)?;
                w.stats.steps += 1;
            }
        }
        check_finite(&x, t1)?;
        record(k + 1, &x, &mut w, &mut traj, &mut u_now);
    }
    traj.stats = w.stats;
    Ok(traj)
}

/// Many independent simulations, in parallel. Each entry of `x0s` is one
/// initial state; `param_sets`, if given, is one parameter vector per run.
pub fn simulate_batch(
    m: &Model,
    x0s: &[Vec<f64>],
    t: &[f64],
    inputs: &Inputs<'_>,
    param_sets: Option<&[Vec<f64>]>,
    method: Method,
    opts: &Options,
) -> Result<Vec<Trajectory>> {
    if let Some(ps) = param_sets {
        if ps.len() != x0s.len() {
            return Err(EngineError::Shape(format!(
                "{} initial states but {} parameter sets",
                x0s.len(),
                ps.len()
            )));
        }
    }
    x0s.par_iter()
        .enumerate()
        .map(|(i, x0)| {
            let mut local;
            let model_ref: &Model = if let Some(ps) = param_sets {
                local = m.clone();
                local.set_params(&ps[i])?;
                &local
            } else {
                m
            };
            simulate(model_ref, x0, t, inputs, method, opts)
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    /// dx/dt = -x, one parameter (unused), one input (unused)
    fn decay() -> Model {
        Model::from_value(&json!({
            "n_states": 1, "n_inputs": 0, "n_params": 0, "param_values": [],
            "rhs": [["neg", ["ref", 0]]],
            "jacobian": [["const", -1.0]],
            "energy": ["mul", ["const", 0.5], ["mul", ["ref", 0], ["ref", 0]]],
            "grad_H": [["ref", 0]], "port_outputs": [], "port_values": [],
            "output_names": [], "outputs": []
        }))
        .unwrap()
    }

    #[test]
    fn methods_agree_on_decay() {
        let m = decay();
        let t: Vec<f64> = (0..=100).map(|i| i as f64 * 0.01).collect();
        let exact = (-1.0f64).exp();
        for method in [Method::Euler, Method::Rk4, Method::Rk45, Method::Midpoint] {
            let tr =
                simulate(&m, &[1.0], &t, &Inputs::none(), method, &Options::default()).unwrap();
            let last = tr.x[tr.x.len() - 1];
            let tol = match method {
                Method::Euler => 1e-2,
                Method::Midpoint => 1e-4,
                _ => 1e-7,
            };
            assert!((last - exact).abs() < tol, "{method:?}: {last} vs {exact}");
        }
    }

    #[test]
    fn energy_never_rises_with_midpoint() {
        let m = decay();
        let t: Vec<f64> = (0..=50).map(|i| i as f64 * 0.1).collect();
        let tr = simulate(
            &m,
            &[1.0],
            &t,
            &Inputs::none(),
            Method::Midpoint,
            &Options::default(),
        )
        .unwrap();
        for k in 1..tr.energy.len() {
            assert!(tr.energy[k] <= tr.energy[k - 1] + 1e-15);
        }
    }

    #[test]
    fn rejects_bad_grid() {
        let m = decay();
        assert!(simulate(
            &m,
            &[1.0],
            &[0.0, 0.0],
            &Inputs::none(),
            Method::Rk4,
            &Options::default()
        )
        .is_err());
    }
}
