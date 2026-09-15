//! Python bindings for `otwin-core`.
//!
//! One class, `Model`, built from the lowered IR as JSON text. Arrays cross
//! the boundary as NumPy arrays; the model and every numerical buffer live on
//! the Rust side. The Python package `otwin` wraps this module and falls back
//! to a NumPy implementation of the same IR when it is not installed.

use numpy::{IntoPyArray, PyArray1, PyArray2, PyArrayMethods, PyReadonlyArray1, PyReadonlyArray2};
use otwin_core::{simulate, simulate_batch, step, EngineError, Inputs, Interp, Method, Options, Trajectory};
use pyo3::exceptions::{PyRuntimeError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::PyDict;

fn to_py(e: EngineError) -> PyErr {
    match e {
        EngineError::Convergence { .. } | EngineError::NonFinite { .. } => PyRuntimeError::new_err(e.to_string()),
        _ => PyValueError::new_err(e.to_string()),
    }
}

#[allow(clippy::too_many_arguments)]
fn options(
    rtol: f64,
    atol: f64,
    newton_tol: f64,
    max_newton: usize,
    record_outputs: bool,
    record_energy: bool,
) -> Options {
    Options {
        rtol,
        atol,
        newton_tol,
        max_newton,
        max_substeps: 1_000_000,
        record_outputs,
        record_energy,
    }
}

fn trajectory_to_dict<'py>(py: Python<'py>, tr: Trajectory, n: usize, m: usize, n_out: usize) -> PyResult<Bound<'py, PyDict>> {
    let d = PyDict::new(py);
    let nt = tr.t.len();
    d.set_item("t", tr.t.into_pyarray(py))?;
    d.set_item("x", tr.x.into_pyarray(py).reshape([nt, n])?)?;
    d.set_item("u", tr.u.into_pyarray(py).reshape([nt, m])?)?;
    d.set_item("energy", tr.energy.into_pyarray(py))?;
    d.set_item("supplied_power", tr.supplied_power.into_pyarray(py))?;
    let n_out_rec = if nt > 0 { tr.outputs.len() / nt } else { n_out };
    d.set_item("outputs", tr.outputs.into_pyarray(py).reshape([nt, n_out_rec])?)?;
    let stats = PyDict::new(py);
    stats.set_item("steps", tr.stats.steps)?;
    stats.set_item("rhs_evals", tr.stats.rhs_evals)?;
    stats.set_item("newton_iterations", tr.stats.newton_iterations)?;
    stats.set_item("jacobian_evals", tr.stats.jacobian_evals)?;
    stats.set_item("rejected_steps", tr.stats.rejected_steps)?;
    stats.set_item("method", tr.method.name())?;
    d.set_item("stats", stats)?;
    Ok(d)
}

/// A compiled physical model, executed in Rust.
#[pyclass(name = "Model", module = "otwin_engine")]
pub struct PyModel {
    inner: otwin_core::Model,
}

#[pymethods]
impl PyModel {
    /// Build from the lowered IR (``PHSIR.lower()``) serialised as JSON.
    #[new]
    fn new(json: &str) -> PyResult<Self> {
        let inner = otwin_core::Model::from_json_str(json).map_err(to_py)?;
        Ok(PyModel { inner })
    }

    #[getter]
    fn n_states(&self) -> usize {
        self.inner.n_states
    }

    #[getter]
    fn n_inputs(&self) -> usize {
        self.inner.n_inputs
    }

    #[getter]
    fn n_params(&self) -> usize {
        self.inner.n_params
    }

    #[getter]
    fn output_names(&self) -> Vec<String> {
        self.inner.output_names.clone()
    }

    #[getter]
    fn params<'py>(&self, py: Python<'py>) -> Bound<'py, PyArray1<f64>> {
        self.inner.params.clone().into_pyarray(py)
    }

    #[setter]
    fn set_params(&mut self, p: PyReadonlyArray1<f64>) -> PyResult<()> {
        self.inner.set_params(p.as_slice()?).map_err(to_py)
    }

    #[getter]
    fn has_jacobian(&self) -> bool {
        self.inner.jacobian.is_some()
    }

    /// dx/dt at (x, u, t).
    #[pyo3(signature = (x, u=None, t=0.0))]
    fn rhs<'py>(&self, py: Python<'py>, x: PyReadonlyArray1<f64>, u: Option<PyReadonlyArray1<f64>>, t: f64) -> PyResult<Bound<'py, PyArray1<f64>>> {
        let xs = x.as_slice()?;
        let zeros = vec![0.0; self.inner.n_inputs];
        let us: &[f64] = match &u {
            Some(a) => a.as_slice()?,
            None => &zeros,
        };
        self.inner.check_shapes(xs, us).map_err(to_py)?;
        Ok(self.inner.rhs(xs, us, t).into_pyarray(py))
    }

    /// d(dx/dt)/dx at (x, u, t), shape (n, n).
    #[pyo3(signature = (x, u=None, t=0.0))]
    fn jacobian<'py>(&self, py: Python<'py>, x: PyReadonlyArray1<f64>, u: Option<PyReadonlyArray1<f64>>, t: f64) -> PyResult<Bound<'py, PyArray2<f64>>> {
        let xs = x.as_slice()?;
        let zeros = vec![0.0; self.inner.n_inputs];
        let us: &[f64] = match &u {
            Some(a) => a.as_slice()?,
            None => &zeros,
        };
        self.inner.check_shapes(xs, us).map_err(to_py)?;
        let n = self.inner.n_states;
        Ok(self.inner.jacobian(xs, us, t).into_pyarray(py).reshape([n, n])?)
    }

    /// Stored energy H(x).
    fn energy(&self, x: PyReadonlyArray1<f64>) -> PyResult<f64> {
        let xs = x.as_slice()?;
        if xs.len() != self.inner.n_states {
            return Err(PyValueError::new_err(format!(
                "state has {} entries, the model has {} states",
                xs.len(),
                self.inner.n_states
            )));
        }
        let mut s = otwin_core::Scratch::for_model(&self.inner);
        Ok(self.inner.energy(xs, &mut s))
    }

    /// grad H(x).
    fn grad_h<'py>(&self, py: Python<'py>, x: PyReadonlyArray1<f64>) -> PyResult<Bound<'py, PyArray1<f64>>> {
        let xs = x.as_slice()?;
        if xs.len() != self.inner.n_states {
            return Err(PyValueError::new_err("state length mismatch"));
        }
        Ok(self.inner.grad_h(xs).into_pyarray(py))
    }

    /// Named outputs at (x, u, t).
    #[pyo3(signature = (x, u=None, t=0.0))]
    fn outputs<'py>(&self, py: Python<'py>, x: PyReadonlyArray1<f64>, u: Option<PyReadonlyArray1<f64>>, t: f64) -> PyResult<Bound<'py, PyArray1<f64>>> {
        let xs = x.as_slice()?;
        let zeros = vec![0.0; self.inner.n_inputs];
        let us: &[f64] = match &u {
            Some(a) => a.as_slice()?,
            None => &zeros,
        };
        self.inner.check_shapes(xs, us).map_err(to_py)?;
        Ok(self.inner.outputs(xs, us, t).into_pyarray(py))
    }

    /// Port outputs y (the conjugate of each port's u).
    #[pyo3(signature = (x, u=None, t=0.0))]
    fn port_outputs<'py>(&self, py: Python<'py>, x: PyReadonlyArray1<f64>, u: Option<PyReadonlyArray1<f64>>, t: f64) -> PyResult<Bound<'py, PyArray1<f64>>> {
        let xs = x.as_slice()?;
        let zeros = vec![0.0; self.inner.n_inputs];
        let us: &[f64] = match &u {
            Some(a) => a.as_slice()?,
            None => &zeros,
        };
        self.inner.check_shapes(xs, us).map_err(to_py)?;
        Ok(self.inner.port_outputs(xs, us, t).into_pyarray(py))
    }

    /// Power entering through all ports at (x, u, t).
    #[pyo3(signature = (x, u=None, t=0.0))]
    fn supplied_power(&self, x: PyReadonlyArray1<f64>, u: Option<PyReadonlyArray1<f64>>, t: f64) -> PyResult<f64> {
        let xs = x.as_slice()?;
        let zeros = vec![0.0; self.inner.n_inputs];
        let us: &[f64] = match &u {
            Some(a) => a.as_slice()?,
            None => &zeros,
        };
        self.inner.check_shapes(xs, us).map_err(to_py)?;
        let mut s = otwin_core::Scratch::for_model(&self.inner);
        Ok(self.inner.supplied_power(xs, us, t, &mut s))
    }

    /// One integration step with a constant input.
    #[pyo3(signature = (x, u, t, dt, method="midpoint", rtol=1e-8, atol=1e-10, newton_tol=1e-10, max_newton=50))]
    #[allow(clippy::too_many_arguments)]
    fn step<'py>(
        &self,
        py: Python<'py>,
        x: PyReadonlyArray1<f64>,
        u: Option<PyReadonlyArray1<f64>>,
        t: f64,
        dt: f64,
        method: &str,
        rtol: f64,
        atol: f64,
        newton_tol: f64,
        max_newton: usize,
    ) -> PyResult<Bound<'py, PyArray1<f64>>> {
        let xs = x.as_slice()?;
        let zeros = vec![0.0; self.inner.n_inputs];
        let us: &[f64] = match &u {
            Some(a) => a.as_slice()?,
            None => &zeros,
        };
        let m = Method::parse(method).map_err(to_py)?;
        let opts = options(rtol, atol, newton_tol, max_newton, false, false);
        let xn = step(&self.inner, xs, us, t, dt, m, &opts).map_err(to_py)?;
        Ok(xn.into_pyarray(py))
    }

    /// Integrate over a time grid.
    ///
    /// ``u`` is ``(len(t), n_inputs)`` or ``None`` for zero inputs. Returns a
    /// dict with ``t``, ``x``, ``u``, ``energy``, ``supplied_power``,
    /// ``outputs`` and ``stats``.
    #[pyo3(signature = (x0, t, u=None, method="midpoint", interp="hold", rtol=1e-8, atol=1e-10, newton_tol=1e-10, max_newton=50, record_outputs=true, record_energy=true))]
    #[allow(clippy::too_many_arguments)]
    fn simulate<'py>(
        &self,
        py: Python<'py>,
        x0: PyReadonlyArray1<f64>,
        t: PyReadonlyArray1<f64>,
        u: Option<PyReadonlyArray2<f64>>,
        method: &str,
        interp: &str,
        rtol: f64,
        atol: f64,
        newton_tol: f64,
        max_newton: usize,
        record_outputs: bool,
        record_energy: bool,
    ) -> PyResult<Bound<'py, PyDict>> {
        let m = Method::parse(method).map_err(to_py)?;
        let ip = Interp::parse(interp).map_err(to_py)?;
        let opts = options(rtol, atol, newton_tol, max_newton, record_outputs, record_energy);
        let x0s = x0.as_slice()?;
        let ts = t.as_slice()?;
        let u_owned: Option<Vec<f64>> = match &u {
            Some(a) => Some(a.as_array().iter().copied().collect()),
            None => None,
        };
        let inputs = Inputs { values: u_owned.as_deref(), interp: ip };
        let tr = py
            .detach(|| simulate(&self.inner, x0s, ts, &inputs, m, &opts))
            .map_err(to_py)?;
        trajectory_to_dict(py, tr, self.inner.n_states, self.inner.n_inputs, self.inner.outputs.len())
    }

    /// Many simulations in parallel: ``x0s`` is ``(N, n_states)``, ``params``
    /// optionally ``(N, n_params)``. Returns ``x`` of shape ``(N, len(t), n_states)``
    /// and ``energy`` of shape ``(N, len(t))``.
    #[pyo3(signature = (x0s, t, u=None, params=None, method="midpoint", interp="hold", rtol=1e-8, atol=1e-10, newton_tol=1e-10, max_newton=50))]
    #[allow(clippy::too_many_arguments)]
    fn simulate_batch<'py>(
        &self,
        py: Python<'py>,
        x0s: PyReadonlyArray2<f64>,
        t: PyReadonlyArray1<f64>,
        u: Option<PyReadonlyArray2<f64>>,
        params: Option<PyReadonlyArray2<f64>>,
        method: &str,
        interp: &str,
        rtol: f64,
        atol: f64,
        newton_tol: f64,
        max_newton: usize,
    ) -> PyResult<Bound<'py, PyDict>> {
        let m = Method::parse(method).map_err(to_py)?;
        let ip = Interp::parse(interp).map_err(to_py)?;
        let opts = options(rtol, atol, newton_tol, max_newton, false, true);
        let ts = t.as_slice()?;
        let x0v: Vec<Vec<f64>> = x0s.as_array().rows().into_iter().map(|r| r.to_vec()).collect();
        let pv: Option<Vec<Vec<f64>>> = params.as_ref().map(|p| p.as_array().rows().into_iter().map(|r| r.to_vec()).collect());
        let u_owned: Option<Vec<f64>> = u.as_ref().map(|a| a.as_array().iter().copied().collect());
        let inputs = Inputs { values: u_owned.as_deref(), interp: ip };
        let trs = py
            .detach(|| simulate_batch(&self.inner, &x0v, ts, &inputs, pv.as_deref(), m, &opts))
            .map_err(to_py)?;
        let nb = trs.len();
        let nt = ts.len();
        let n = self.inner.n_states;
        let mut x = Vec::with_capacity(nb * nt * n);
        let mut e = Vec::with_capacity(nb * nt);
        for tr in trs {
            x.extend_from_slice(&tr.x);
            e.extend_from_slice(&tr.energy);
        }
        let d = PyDict::new(py);
        d.set_item("t", ts.to_vec().into_pyarray(py))?;
        d.set_item("x", x.into_pyarray(py).reshape([nb, nt, n])?)?;
        d.set_item("energy", e.into_pyarray(py).reshape([nb, nt])?)?;
        Ok(d)
    }

    fn __repr__(&self) -> String {
        format!(
            "otwin_engine.Model(n_states={}, n_inputs={}, n_params={}, jacobian={})",
            self.inner.n_states,
            self.inner.n_inputs,
            self.inner.n_params,
            if self.inner.jacobian.is_some() { "analytic" } else { "finite-difference" }
        )
    }
}

#[pymodule]
fn otwin_engine(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<PyModel>()?;
    m.add("__version__", otwin_core::VERSION)?;
    m.add("SOLVERS", vec!["euler", "rk4", "rk45", "midpoint"])?;
    Ok(())
}
