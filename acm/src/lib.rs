use pyo3::prelude::*;
use pyo3::types::PyDict;

pub mod classifier;  // pub so main.rs can access it

pub use classifier::{AppEntry, classify_all};  // re-export

use classifier::classify;

fn dict_to_entry(py: Python, dict: &PyDict) -> PyResult<AppEntry> {
    let json = py.import("json")?;
    let json_str: String = json.call_method1("dumps", (dict,))?.extract()?;
    let entry: AppEntry = serde_json::from_str(&json_str)
        .map_err(|e| PyErr::new::<pyo3::exceptions::PyValueError, _>(format!("{}", e)))?;
    Ok(entry)
}

#[pyfunction]
fn classify_py(py: Python, entry: &PyDict) -> PyResult<PyObject> {
    let rust_entry = dict_to_entry(py, entry)?;
    let result = classify(&rust_entry);
    let json_str = serde_json::to_string(&result)
        .map_err(|e| PyErr::new::<pyo3::exceptions::PyValueError, _>(format!("{}", e)))?;
    let json = py.import("json")?;
    let py_obj = json.call_method1("loads", (json_str,))?;
    Ok(py_obj.into())
}

#[pymodule]
fn acm(py: Python, m: &PyModule) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(classify_py, m)?)?;
    Ok(())
}