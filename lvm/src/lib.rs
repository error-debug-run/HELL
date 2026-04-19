use pyo3::prelude::*;
use pyo3::types::PyDict;
use serde::Serialize;
use std::mem;
use std::ptr;
use winapi::shared::minwindef::{FALSE, TRUE};
use winapi::shared::windef::HWND;
use winapi::um::handleapi::CloseHandle;
use winapi::um::processthreadsapi::OpenProcess;
use winapi::um::psapi::GetModuleBaseNameA;
use winapi::um::winnt::{PROCESS_QUERY_INFORMATION, PROCESS_VM_READ};
use winapi::um::winuser::*;

#[derive(Serialize, Debug, Clone)]
pub struct WindowInfo {
    hwnd: u64,
    title: String,
    class: String,
    pid: u32,
    exe: String,
    visible: bool,
    responsive: bool,
}

// ─────────────────────────────────────────────────────────
// RUST -> PYTHON BRIDGE (THE FIX)
// ─────────────────────────────────────────────────────────

/// This is the `lvm.verify()` function your apps.py is calling
#[pyfunction]
fn verify(py: Python, target: &PyDict) -> PyResult<PyObject> {
    // 1. Extract the dict payload passed from Python
    let target_pid = target.get_item("pid")
        .ok().flatten().and_then(|v| v.extract::<u32>().ok());

    let target_exe = target.get_item("exe")
        .ok().flatten().and_then(|v| v.extract::<String>().ok())
        .map(|s| s.to_lowercase());

    let target_title = target.get_item("title")
        .ok().flatten().and_then(|v| v.extract::<String>().ok())
        .map(|s| s.to_lowercase());

    // 2. Scan all windows
    let windows = get_windows();

    let mut best_score = 0.0;
    let mut best_hwnd = 0;

    // 3. Calculate score (Python expects >= 0.85 for success)
    for w in windows {
        let mut current_score = 0.0;

        // Massive signal: The PID matches exactly what we just launched
        if let Some(pid) = target_pid {
            if w.pid == pid { current_score += 0.6; }
        }

        // Strong signal: The exe name matches
        if let Some(ref exe) = target_exe {
            if w.exe.to_lowercase().contains(exe) { current_score += 0.3; }
        }

        // Minor signal: Title contains our target string
        if let Some(ref title) = target_title {
            if w.title.to_lowercase().contains(title) { current_score += 0.15; }
        }

        if current_score > best_score {
            best_score = current_score;
            best_hwnd = w.hwnd;
        }
    }

    // 4. Return result back to Python as a dictionary
    let result = PyDict::new(py);
    result.set_item("score", best_score)?;
    result.set_item("hwnd", best_hwnd)?;

    Ok(result.into())
}

/// A Python module implemented in Rust. The name of this function must match
/// the `lib.name` setting in the `Cargo.toml`, else Python will not be able to
/// import the module.
#[pymodule]
fn lvm(_py: Python, m: &PyModule) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(verify, m)?)?;
    Ok(())
}

// ─────────────────────────────────────────────────────────
// YOUR EXISTING WINAPI LOGIC
// ─────────────────────────────────────────────────────────

pub fn get_windows() -> Vec<WindowInfo> {
    let mut windows: Vec<WindowInfo> = Vec::new();
    unsafe {
        EnumWindows(Some(enum_windows_proc), &mut windows as *mut _ as isize);
    }
    windows
}

unsafe extern "system" fn enum_windows_proc(hwnd: HWND, lparam: isize) -> i32 {
    let windows = &mut *(lparam as *mut Vec<WindowInfo>);

    if IsWindowVisible(hwnd) == FALSE { return TRUE as i32; }

    let mut title_buf = [0i8; 512];
    let len = GetWindowTextA(hwnd, title_buf.as_mut_ptr(), 512);
    if len == 0 { return TRUE as i32; }

    let title = String::from_utf8_lossy(&title_buf[..len as usize].iter().map(|&c| c as u8).collect::<Vec<u8>>()).to_string();
    if title.trim().is_empty() { return TRUE as i32; }

    let mut class_buf = [0i8; 256];
    let class_len = GetClassNameA(hwnd, class_buf.as_mut_ptr(), 256);
    let class = if class_len > 0 {
        String::from_utf8_lossy(&class_buf[..class_len as usize].iter().map(|&c| c as u8).collect::<Vec<u8>>()).to_string()
    } else {
        String::new()
    };

    let mut pid: u32 = 0;
    GetWindowThreadProcessId(hwnd, &mut pid);

    let exe = get_exe_from_pid(pid);
    let responsive = is_responsive(hwnd);

    windows.push(WindowInfo {
        hwnd: hwnd as u64, title, class, pid, exe, visible: true, responsive,
    });

    TRUE as i32
}

unsafe fn get_exe_from_pid(pid: u32) -> String {
    let handle = OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, 0, pid);
    if handle.is_null() { return String::new(); }

    let mut buf = [0i8; 260];
    let len = GetModuleBaseNameA(handle, ptr::null_mut(), buf.as_mut_ptr(), 260);
    CloseHandle(handle);

    if len == 0 { return String::new(); }
    String::from_utf8_lossy(&buf[..len as usize].iter().map(|&c| c as u8).collect::<Vec<u8>>()).to_string()
}

unsafe fn is_responsive(hwnd: HWND) -> bool {
    let mut result = 0usize;
    let ok = SendMessageTimeoutA(hwnd, WM_NULL, 0, 0, SMTO_ABORTIFHUNG, 300, &mut result);
    ok != 0
}