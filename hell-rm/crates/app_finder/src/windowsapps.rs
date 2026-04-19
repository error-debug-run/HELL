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
use std::process::Command;

use crate::AppEntry;


// ─────────────────────────────────────────
// RAII COM GUARD
// ─────────────────────────────────────────

struct ComGuard;

impl ComGuard {
    fn init() -> Option<Self> {
        unsafe {
            let result = CoInitializeEx(None, COINIT_APARTMENTTHREADED);
            if result.is_ok() { Some(ComGuard) } else { None }
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
// ─────────────────────────────────────────

fn tokenize_command(cmd: &str) -> Vec<String> {
    let mut tokens    = Vec::new();
    let mut current   = String::new();
    let mut in_quotes = false;
    let mut chars     = cmd.trim().chars().peekable();

    while let Some(c) = chars.next() {
        match c {
            '"' => in_quotes = !in_quotes,
            ' ' | '\t' if !in_quotes => {
                if !current.is_empty() {
                    tokens.push(current.clone());
                    current.clear();
                }
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
// .LNK RESOLVER
// ─────────────────────────────────────────

pub fn resolve_lnk(path: &str) -> Option<(String, Vec<String>)> {
    let _com = ComGuard::init()?;

    unsafe {
        let shell_link: IShellLinkW =
            CoCreateInstance(&ShellLink, None, CLSCTX_INPROC_SERVER).ok()?;

        let persist: IPersistFile = shell_link.cast().ok()?;

        let wide: Vec<u16> = path.encode_utf16().chain(Some(0)).collect();
        persist.Load(PCWSTR(wide.as_ptr()), STGM_READ).ok()?;

        let mut path_buf = [0u16; 260];
        shell_link
            .GetPath(&mut path_buf, std::ptr::null_mut(), 0)
            .ok()?;

        let path_len = path_buf.iter().position(|&c| c == 0).unwrap_or(0);
        let target   = String::from_utf16_lossy(&path_buf[..path_len]).to_string();

        if target.is_empty() {
            return None;
        }

        let mut args_buf = [0u16; 1024];
        shell_link.GetArguments(&mut args_buf).ok()?;

        let args_len = args_buf.iter().position(|&c| c == 0).unwrap_or(0);
        let args_str = String::from_utf16_lossy(&args_buf[..args_len]);
        let args     = tokenize_command(&args_str);

        Some((target, args))
    }
}


// ─────────────────────────────────────────
// TOP-LEVEL SCAN
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
    apps.extend(get_uwp_apps());

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

    let uninstall: String = subkey
        .get_value("UninstallString")
        .or_else(|_| subkey.get_value("QuietUninstallString"))
        .unwrap_or_default();

    if !uninstall.trim().is_empty() {
        let (uninstall_exe, _) = parse_command(&uninstall);

        if let Some(parent) = Path::new(&uninstall_exe).parent() {
            let found = find_exe_in_dir(&parent.to_string_lossy(), display_name);
            if !found.is_empty() {
                return (found, vec![]);
            }
        }
    }

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
// UWP / MSIX APP FINDER
//
// Enumerates all installed UWP packages via
// PowerShell Get-AppxPackage, then reads each
// AppxManifest.xml directly to extract the
// real Application Id(s) and display name.
//
// app_type  = "uwp"
// full_path = shell:AppsFolder\<FamilyName>!<AppId>
// ─────────────────────────────────────────

pub fn get_uwp_apps() -> Vec<AppEntry> {
    let mut apps = Vec::new();

    // One PowerShell call — pipe-delimited rows
    // "PackageFamilyName|PublisherDisplayName|InstallLocation"
    let output = match Command::new("powershell")
        .args([
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            r#"Get-AppxPackage | ForEach-Object { "$($_.PackageFamilyName)|$($_.PublisherDisplayName)|$($_.InstallLocation)" }"#,
        ])
        .output()
    {
        Ok(o)  => o,
        Err(_) => return apps,
    };

    for line in String::from_utf8_lossy(&output.stdout).lines() {
        let line = line.trim();
        if line.is_empty() {
            continue;
        }

        let mut parts        = line.splitn(3, '|');
        let family_name      = match parts.next() { Some(s) if !s.trim().is_empty() => s.trim(), _ => continue };
        let publisher        = parts.next().unwrap_or("").trim().to_string();
        let install_location = parts.next().unwrap_or("").trim().to_string();

        // Read AppxManifest.xml → Vec<(app_id, display_name)>
        let app_ids = parse_appx_manifest(&install_location);

        if app_ids.is_empty() {
            // Manifest unreadable (system/framework package) — skip entirely.
            // These have no launchable Application entry anyway.
            continue;
        }

        for (app_id, display_name) in app_ids {
            let name = if !display_name.is_empty() {
                display_name
            } else {
                friendly_name(family_name)
            };

            apps.push(AppEntry {
                name,
                // no single .exe — use "FamilyName!AppId" as the canonical identity
                exe_name:  format!("{}!{}", family_name, app_id),
                full_path: format!("shell:AppsFolder\\{}!{}", family_name, app_id),
                args:      vec![],
                app_type:  "uwp".to_string(),
                publisher: "unknown".to_string(),
            });
        }
    }

    apps
}

// ── Manifest parser ───────────────────────────────────────────────────────────
// Returns Vec<(AppId, DisplayName)> for every <Application> in the manifest.
// Uses a minimal line-by-line scan — no XML crate needed.

fn parse_appx_manifest(install_location: &str) -> Vec<(String, String)> {
    if install_location.is_empty() {
        return vec![];
    }

    let content = match std::fs::read_to_string(
        Path::new(install_location).join("AppxManifest.xml")
    ) {
        Ok(c)  => c,
        Err(_) => return vec![],
    };

    let mut results = Vec::new();
    let mut rest    = content.as_str();

    while let Some(rel) = rest.to_lowercase().find("<application") {
        rest = &rest[rel..];

        let tag_end = match rest.find('>') {
            Some(i) => i,
            None    => break,
        };

        let tag = &rest[..=tag_end];

        if let Some(app_id) = attr_value(tag, "Id") {
            // look for VisualElements up to the closing </Application>
            let scope_end = rest
                .to_lowercase()
                .find("</application>")
                .unwrap_or(rest.len());

            let display_name = visual_display_name(&rest[..scope_end]);

            results.push((app_id, display_name));
        }

        // advance past this tag so we don't re-match it
        rest = &rest[tag_end + 1..];
    }

    results
}

// Extract `attr="value"` or `attr='value'` (case-insensitive attribute name).
fn attr_value(tag: &str, attr: &str) -> Option<String> {
    let lower   = tag.to_lowercase();
    let pattern = format!("{}=\"", attr.to_lowercase());

    let start = lower
        .find(&pattern)
        .map(|i| i + pattern.len())
        .or_else(|| {
            let p2 = format!("{}='", attr.to_lowercase());
            lower.find(&p2).map(|i| i + p2.len())
        })?;

    let value_end = tag[start..].find(|c| c == '"' || c == '\'')?;
    Some(tag[start..start + value_end].to_string())
}

// Pull DisplayName from the nearest <*:VisualElements DisplayName="..." />.
// Returns empty string for ms-resource: references (not resolvable here).
fn visual_display_name(fragment: &str) -> String {
    let lower = fragment.to_lowercase();

    let pos = match lower.find("visualelements") {
        Some(p) => p,
        None => return String::new(),
    };

    let tag_open = fragment[..pos].rfind('<').unwrap_or(pos);

    let tag_end = match fragment[pos..].find('>') {
        Some(i) => pos + i,
        None => fragment.len() - 1,
    };

    let tag = &fragment[tag_open..=tag_end.min(fragment.len() - 1)];
    let raw = attr_value(tag, "DisplayName").unwrap_or_default();

    if raw.starts_with("ms-resource:") {
        String::new()
    } else {
        raw
    }
}

// "Microsoft.WindowsCalculator_8wekyb3d8bbwe" → "Windows Calculator"
fn friendly_name(family: &str) -> String {
    let base    = family.split('_').next().unwrap_or(family);
    let trimmed = base.splitn(2, '.').nth(1).unwrap_or(base);

    let mut out = String::new();
    for (i, ch) in trimmed.chars().enumerate() {
        if ch.is_uppercase() && i > 0 {
            out.push(' ');
        }
        out.push(ch);
    }
    out
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

        if stem == app_lower                                { score += 100; }
        else if stem.contains(&app_lower)
            || app_lower.contains(&stem)                  { score += 50;  }

        if bad.iter().any(|b| stem.contains(b))            { score -= 100; }

        score -= stem.len() as i32;

        if score > best_score {
            best_score = score;
            best_match = exe.clone();
        }
    }

    if best_score >= 0 { best_match } else { String::new() }
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