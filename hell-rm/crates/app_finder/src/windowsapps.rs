// hell-rm/crates/app_finder/src/windowsapps.rs

use std::path::Path;

use windows::{
    core::PCWSTR,
    Win32::{
        System::Com::{
            CoCreateInstance, CoInitializeEx, CoUninitialize,
            IPersistFile, CLSCTX_INPROC_SERVER, COINIT_APARTMENTTHREADED, STGM_READ,
        },
        UI::Shell::{IShellLinkW, ShellLink},
    },
};
use windows::core::Interface;
use winreg::{enums::*, RegKey};

use crate::AppEntry;


// ─────────────────────────────────────────
// RAII COM GUARD
// Ensures CoUninitialize is always called,
// even if resolve_lnk returns early via `?`
// ─────────────────────────────────────────

struct ComGuard;

impl ComGuard {
    fn init() -> Option<Self> {
        unsafe {
            let result = CoInitializeEx(None, COINIT_APARTMENTTHREADED);
            // S_OK (0x0) = freshly initialized
            // S_FALSE (0x1) = already initialized on this thread
            // both are valid success codes
            if result.is_ok() {
                Some(ComGuard)
            } else {
                None
            }
        }
    }
}

impl Drop for ComGuard {
    fn drop(&mut self) {
        unsafe { CoUninitialize() }
    }
}


// ─────────────────────────────────────────
// COMMAND LINE TOKENIZER
// Handles quoted paths and quoted arguments.
// e.g. `"C:\Program Files\app.exe" --flag "some path"`
//   -> ["C:\Program Files\app.exe", "--flag", "some path"]
// ─────────────────────────────────────────

fn tokenize_command(cmd: &str) -> Vec<String> {
    let mut tokens    = Vec::new();
    let mut current   = String::new();
    let mut in_quotes = false;
    let mut chars     = cmd.trim().chars().peekable();

    while let Some(c) = chars.next() {
        match c {
            // toggle quoted region — strip the quote char itself
            '"' => in_quotes = !in_quotes,

            // unquoted whitespace → token boundary
            ' ' | '\t' if !in_quotes => {
                if !current.is_empty() {
                    tokens.push(current.clone());
                    current.clear();
                }
                // consume runs of whitespace
                while matches!(chars.peek(), Some(' ') | Some('\t')) {
                    chars.next();
                }
            }

            _ => current.push(c),
        }
    }

    if !current.is_empty() {
        tokens.push(current);
    }

    tokens
}

/// Split a full command string into (exe_path, args).
fn parse_command(cmd: &str) -> (String, Vec<String>) {
    let mut tokens = tokenize_command(cmd);
    if tokens.is_empty() {
        return (String::new(), vec![]);
    }
    let exe  = tokens.remove(0);
    let args = tokens;
    (exe, args)
}


// ─────────────────────────────────────────
// .LNK RESOLVER  (pub — called from lib.rs)
// ─────────────────────────────────────────

pub fn resolve_lnk(path: &str) -> Option<(String, Vec<String>)> {
    let _com = ComGuard::init()?;

    unsafe {
        let shell_link: IShellLinkW =
            CoCreateInstance(&ShellLink, None, CLSCTX_INPROC_SERVER).ok()?;

        let persist: IPersistFile = shell_link.cast().ok()?;

        let wide: Vec<u16> = path.encode_utf16().chain(Some(0)).collect();
        persist.Load(PCWSTR(wide.as_ptr()), STGM_READ).ok()?;

        // ── target path ────────────────────────────────
        let mut path_buf = [0u16; 260];
        shell_link
            .GetPath(&mut path_buf, std::ptr::null_mut(), 0)
            .ok()?;

        let path_len = path_buf.iter().position(|&c| c == 0).unwrap_or(0);
        let target   = String::from_utf16_lossy(&path_buf[..path_len]).to_string();

        if target.is_empty() {
            return None;
        }

        // ── arguments ──────────────────────────────────
        // 1024 instead of 260 — args can easily exceed MAX_PATH
        let mut args_buf = [0u16; 1024];
        shell_link.GetArguments(&mut args_buf).ok()?;

        let args_len = args_buf.iter().position(|&c| c == 0).unwrap_or(0);
        let args_str = String::from_utf16_lossy(&args_buf[..args_len]);

        // tokenize respects quoted args like --path "C:\My Dir"
        let args = tokenize_command(&args_str);

        Some((target, args))
    }
}


// ─────────────────────────────────────────
// TOP-LEVEL SCAN  (pub — called from lib.rs)
// ─────────────────────────────────────────

pub fn scan() -> Vec<AppEntry> {
    let mut apps = Vec::new();

    apps.extend(scan_registry(
        HKEY_LOCAL_MACHINE,
        r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
    ));
    apps.extend(scan_registry(
        HKEY_LOCAL_MACHINE,
        r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall",
    ));
    apps.extend(scan_registry(
        HKEY_CURRENT_USER,
        r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
    ));
    apps.extend(scan_start_menu());
    apps.extend(scan_store_apps());

    apps
}


// ─────────────────────────────────────────
// REGISTRY SCAN
// ─────────────────────────────────────────

fn scan_registry(hive: winreg::HKEY, path: &str) -> Vec<AppEntry> {
    let mut apps = Vec::new();

    let key = match RegKey::predef(hive).open_subkey(path) {
        Ok(k)  => k,
        Err(_) => return apps,
    };

    for name in key.enum_keys().flatten() {
        let subkey = match key.open_subkey(&name) {
            Ok(k)  => k,
            Err(_) => continue,
        };

        let display_name: String = match subkey.get_value("DisplayName") {
            Ok(v)  => v,
            Err(_) => continue,
        };

        if display_name.trim().is_empty() {
            continue;
        }

        let publisher: String = subkey.get_value("Publisher").unwrap_or_default();

        let (exe_path, args) = resolve_exe_and_args(&subkey, &display_name);
        if exe_path.is_empty() {
            continue;
        }

        let exe_name = Path::new(&exe_path)
            .file_name()
            .and_then(|n| n.to_str())
            .unwrap_or("")
            .to_string();

        apps.push(AppEntry {
            name:      display_name.trim().to_string(),
            exe_name,
            full_path: exe_path,
            args,
            app_type:  "exe".to_string(),
            publisher,
        });
    }

    apps
}


// ─────────────────────────────────────────
// EXE + ARG RESOLVER
// ─────────────────────────────────────────

fn resolve_exe_and_args(subkey: &RegKey, display_name: &str) -> (String, Vec<String>) {

    // ── 1. DisplayIcon ───────────────────────────────────────────────
    let display_icon: String = subkey.get_value("DisplayIcon").unwrap_or_default();

    if !display_icon.trim().is_empty() {
        let cleaned = display_icon
            .split(',')
            .next()
            .unwrap_or("")
            .trim()
            .trim_matches('"')
            .to_string();

        if is_good_exe(&cleaned) {
            return (cleaned, vec![]);
        }
    }

    // ── 2. UninstallString — extract location only, never use its args ──
    let uninstall: String = subkey
        .get_value("UninstallString")
        .or_else(|_| subkey.get_value("QuietUninstallString"))
        .unwrap_or_default();

    if !uninstall.trim().is_empty() {
        let (uninstall_exe, _) = parse_command(&uninstall); // ← drop args entirely

        // search the parent dir for a real launch exe
        if let Some(parent) = Path::new(&uninstall_exe).parent() {
            let found = find_exe_in_dir(&parent.to_string_lossy(), display_name);
            if !found.is_empty() {
                return (found, vec![]); // ← no args, we found the real exe
            }
        }
    }

    // ── 3. InstallLocation ───────────────────────────────────────────
    let install_location: String = subkey.get_value("InstallLocation").unwrap_or_default();

    if !install_location.trim().is_empty() {
        let found = find_exe_in_dir(&install_location, display_name);
        if !found.is_empty() {
            return (found, vec![]);
        }
    }

    (String::new(), vec![])
}


// ─────────────────────────────────────────
// GOOD EXE FILTER
// ─────────────────────────────────────────

fn is_good_exe(path: &str) -> bool {
    if !path.to_lowercase().ends_with(".exe") {
        return false;
    }

    if !Path::new(path).exists() {
        return false;
    }

    let stem = Path::new(path)
        .file_stem()
        .and_then(|s| s.to_str())
        .unwrap_or("")
        .to_lowercase();

    let bad = ["update", "setup", "uninstall", "helper", "crash", "repair"];
    !bad.iter().any(|b| stem.contains(b))
}


// ─────────────────────────────────────────
// START MENU (.lnk)
// ─────────────────────────────────────────

fn scan_start_menu() -> Vec<AppEntry> {
    let mut apps = Vec::new();

    let appdata = std::env::var("APPDATA").unwrap_or_default();

    let folders = [
        r"C:\ProgramData\Microsoft\Windows\Start Menu\Programs".to_string(),
        format!(r"{}\Microsoft\Windows\Start Menu\Programs", appdata),
    ];

    for folder in &folders {
        scan_lnk_folder(folder, &mut apps);
    }

    apps
}

fn scan_lnk_folder(folder: &str, apps: &mut Vec<AppEntry>) {
    let path = Path::new(folder);
    if !path.exists() {
        return;
    }

    let entries = match std::fs::read_dir(path) {
        Ok(e)  => e,
        Err(_) => return,
    };

    for entry in entries.flatten() {
        let p = entry.path();

        if p.is_dir() {
            scan_lnk_folder(&p.to_string_lossy(), apps);
            continue;
        }

        if p.extension().and_then(|e| e.to_str()) != Some("lnk") {
            continue;
        }

        let name = p
            .file_stem()
            .and_then(|s| s.to_str())
            .unwrap_or("")
            .to_string();

        if let Some((resolved_path, args)) = resolve_lnk(&p.to_string_lossy()) {
            if resolved_path.is_empty() {
                continue;
            }

            let exe_name = Path::new(&resolved_path)
                .file_name()
                .and_then(|n| n.to_str())
                .unwrap_or("")
                .to_string();

            apps.push(AppEntry {
                name,
                exe_name,
                full_path: resolved_path,
                args,
                app_type:  "lnk".to_string(),
                publisher: String::new(),
            });
        }
    }
}


// ─────────────────────────────────────────
// STORE / UWP APPS
// ─────────────────────────────────────────

fn scan_store_apps() -> Vec<AppEntry> {
    let mut apps = Vec::new();

    let hklm = RegKey::predef(HKEY_LOCAL_MACHINE);
    let key = match hklm.open_subkey(
        r"SOFTWARE\Microsoft\Windows\CurrentVersion\Appx\AppxAllUserStore\Applications",
    ) {
        Ok(k)  => k,
        Err(_) => return apps,
    };

    for pkg_name in key.enum_keys().flatten() {
        apps.push(AppEntry {
            name:      pkg_name.clone(),
            exe_name:  pkg_name.clone(),
            full_path: format!("shell:appsFolder\\{}", pkg_name),
            args:      vec![],
            app_type:  "pwa".to_string(),
            publisher: String::new(),
        });
    }

    apps
}


// ─────────────────────────────────────────
// EXE DISCOVERY
// ─────────────────────────────────────────

fn find_exe_in_dir(dir: &str, app_name: &str) -> String {
    let path = Path::new(dir);
    if !path.exists() || !path.is_dir() {
        return String::new();
    }

    let mut exes = Vec::new();
    collect_exes(path, &mut exes, 0);

    if exes.is_empty() {
        return String::new();
    }

    let app_lower = app_name.to_lowercase();
    let bad       = ["update", "setup", "uninstall", "helper", "crash", "repair", "squirrel"];

    let mut best_score = i32::MIN;
    let mut best_match = String::new();

    for exe in &exes {
        let stem = Path::new(exe)
            .file_stem()
            .and_then(|s| s.to_str())
            .unwrap_or("")
            .to_lowercase();

        let mut score: i32 = 0;

        if stem == app_lower {
            score += 100;
        } else if stem.contains(&app_lower) || app_lower.contains(&stem) {
            score += 50;
        }

        if bad.iter().any(|b| stem.contains(b)) {
            score -= 100;
        }

        score -= stem.len() as i32;

        if score > best_score {
            best_score = score;
            best_match = exe.clone();
        }
    }

    if best_score >= 0 {
        best_match
    } else {
        String::new()
    }
}

fn collect_exes(dir: &Path, exes: &mut Vec<String>, depth: u32) {
    if depth > 2 {
        return;
    }

    if let Ok(entries) = std::fs::read_dir(dir) {
        for entry in entries.flatten() {
            let p = entry.path();

            if p.is_dir() {
                collect_exes(&p, exes, depth + 1);
            } else if p.extension().and_then(|e| e.to_str()) == Some("exe") {
                exes.push(p.to_string_lossy().to_string());
            }
        }
    }
}