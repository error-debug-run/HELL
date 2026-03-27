// hell-rm/crates/app_finder/src/lib.rs

use pyo3::prelude::*;
use serde::{Deserialize, Serialize};

// ── platform modules ──────────────────────────────────────────────

#[cfg(target_os = "windows")]
mod windowsapps;

#[cfg(target_os = "linux")]
mod linux;

#[cfg(target_os = "macos")]
mod macos;


// ── shared app entry (used internally across all platform modules) ─

#[derive(Serialize, Deserialize, Debug, Clone)]
pub struct AppEntry {
    pub name:      String,
    pub exe_name:  String,
    pub full_path: String,
    pub args:      Vec<String>,
    pub app_type:  String,
    pub publisher: String,
}


// ── python-exposed wrapper ────────────────────────────────────────

#[pyclass]
#[derive(Clone)]
pub struct PyAppEntry {
    #[pyo3(get)]
    pub name: String,

    #[pyo3(get)]
    pub exe_name: String,

    #[pyo3(get, set)]
    pub full_path: String,

    #[pyo3(get)]
    pub args: Vec<String>,

    #[pyo3(get)]
    pub app_type: String,

    #[pyo3(get)]
    pub publisher: String,
}

impl From<AppEntry> for PyAppEntry {
    fn from(app: AppEntry) -> Self {
        PyAppEntry {
            name:      app.name,
            exe_name:  app.exe_name,
            full_path: app.full_path,
            args:      app.args,
            app_type:  app.app_type,
            publisher: app.publisher,
        }
    }
}


// ── platform dispatch ─────────────────────────────────────────────

pub fn scan_all() -> Vec<AppEntry> {
    #[cfg(target_os = "windows")]
    return windowsapps::scan();

    #[cfg(target_os = "linux")]
    return linux::scan();

    #[cfg(target_os = "macos")]
    return macos::scan();

    #[allow(unreachable_code)]
    vec![]
}


// ── python-exposed functions ──────────────────────────────────────

#[pyfunction]
fn scan_apps() -> PyResult<Vec<PyAppEntry>> {
    let apps = scan_all();
    Ok(apps.into_iter().map(PyAppEntry::from).collect())
}

/// Resolve a .lnk shortcut to its target exe and args.
/// Exposed to Python for direct use if needed.
#[cfg(target_os = "windows")]
#[pyfunction]
fn resolve_lnk(path: &str) -> Option<(String, Vec<String>)> {
    windowsapps::resolve_lnk(path)
}

// stub so the module compiles on non-Windows
#[cfg(not(target_os = "windows"))]
#[pyfunction]
fn resolve_lnk(_path: &str) -> Option<(String, Vec<String>)> {
    None
}


// ── module definition ─────────────────────────────────────────────

#[pyo3::pymodule]
fn app_finder(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<PyAppEntry>()?;
    m.add_function(wrap_pyfunction!(scan_apps, m)?)?;
    m.add_function(wrap_pyfunction!(resolve_lnk, m)?)?;
    Ok(())
}