use serde::{Deserialize, Serialize};
use std::collections::HashMap;

// ─────────────────────────────────────────────────────────
// DATA STRUCTURES
// ─────────────────────────────────────────────────────────

#[derive(Debug, Deserialize, Clone)]
pub struct AppEntry {
    pub name: String,
    pub exe_name: Option<String>,
    pub full_path: Option<String>,
    pub resolved_path: Option<String>,
    pub args: Option<Vec<String>>,
    pub app_type: Option<String>,
    pub publisher: Option<String>,
    pub action: Option<String>,
    pub window_title: Option<String>,
}

#[derive(Debug, Serialize, PartialEq, Eq, Hash, Clone)]
#[serde(rename_all = "lowercase")]
pub enum AppCategory {
    Win32,
    Electron,
    Uwp,
    Web,
    Browser,
    System,
    Jvm,
    DotnetDesktop,
    GameEngine,
    NativeCrossPlatform,
    TrayApp,
    Installer,
    ConsoleHybrid,
    Unknown,
}

impl std::fmt::Display for AppCategory {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        let s = match self {
            Self::Win32               => "win32",
            Self::Electron            => "electron",
            Self::Uwp                 => "uwp",
            Self::Web                 => "web",
            Self::Browser             => "browser",
            Self::System              => "system",
            Self::Jvm                 => "jvm_desktop",
            Self::DotnetDesktop       => "dotnet_desktop",
            Self::GameEngine          => "game_engine",
            Self::NativeCrossPlatform => "native_cross_platform",
            Self::TrayApp             => "tray_app",
            Self::Installer           => "installer",
            Self::ConsoleHybrid       => "console_hybrid",
            Self::Unknown             => "unknown",
        };
        write!(f, "{}", s)
    }
}

#[derive(Debug, Serialize)]
pub struct ClassificationResult {
    pub name: String,
    pub category: AppCategory,
    pub confidence: u8,
    pub reason: String,
}

// ─────────────────────────────────────────────────────────
// SCORING ENGINE
// ─────────────────────────────────────────────────────────

#[derive(Default, Debug)]
struct Score {
    value: i32,
    reasons: Vec<String>,
}

impl Score {
    fn add(&mut self, weight: i32, reason: impl Into<String>) {
        self.value += weight;
        self.reasons.push(reason.into());
    }
}

// ─────────────────────────────────────────────────────────
// CONSTANTS
// ─────────────────────────────────────────────────────────

const BROWSER_EXE: &[&str] = &[
    "chrome.exe", "chromium.exe", "msedge.exe", "msedge_proxy.exe",
    "firefox.exe", "brave.exe", "opera.exe", "vivaldi.exe", "arc.exe",
];

const ELECTRON_EXE: &[&str] = &[
    "discord.exe", "code.exe", "cursor.exe", "slack.exe", "teams.exe",
    "notion.exe", "obsidian.exe", "figma.exe", "1password.exe", "bitwarden.exe",
    "signal.exe", "whatsapp.exe", "zoom.exe", "postman.exe", "insomnia.exe",
    "githubdesktop.exe", "gitkraken.exe", "hyper.exe", "terminus.exe",
    "tableplus.exe", "linear.exe", "loom.exe", "skype.exe",
];

const SYSTEM_EXE: &[&str] = &[
    "explorer.exe", "notepad.exe", "calc.exe", "mspaint.exe", "taskmgr.exe",
    "regedit.exe", "cmd.exe", "powershell.exe", "pwsh.exe", "msiexec.exe",
    "svchost.exe", "winlogon.exe", "csrss.exe", "dwm.exe", "conhost.exe",
    "werfault.exe", "snippingtool.exe", "wordpad.exe", "write.exe",
    "charmap.exe", "dxdiag.exe", "msconfig.exe",
];

const JVM_LAUNCHER_EXE: &[&str] = &[
    "idea64.exe", "pycharm64.exe", "webstorm64.exe", "clion64.exe","javaw.exe", "java.exe",
    // JetBrains IDEs
    "idea64.exe", "idea.exe","rustrover64.exe",
    "pycharm64.exe", "pycharm.exe",
    "webstorm64.exe", "webstorm.exe",
    "clion64.exe", "clion.exe",
    "goland64.exe", "goland.exe",
    "rider64.exe", "rider.exe",
    "datagrip64.exe", "datagrip.exe",
    "rubymine64.exe", "rubymine.exe",
    "phpstorm64.exe", "phpstorm.exe",
    "dataspell64.exe", "dataspell.exe",
    "fleet.exe",
    "toolbox.exe",          // JetBrains Toolbox
    // Eclipse family
    "eclipse.exe",
    "sts.exe",              // Spring Tool Suite
    // Android Studio (ships its own exe via jpackage)
    "androidstudio64.exe", "androidstudio.exe", "studio64.exe",
    // Other common JVM desktop apps
    "jmeter.exe",
    "dbeaver.exe",
    "squirrelsql.exe",
    "burpsuite.exe",        // PortSwigger Burp Suite
    "sourcetrail.exe",
    "jabref.exe",
    "freemind.exe",
    "freeplane.exe",

];

const JVM_PATH_FRAGS: &[&str] = &[
    "\\jbr\\", "\\jre\\", "\\jdk\\", "\\jre\\bin\\",
    "\\jdk\\bin\\",
    "\\runtime\\bin\\",   // JetBrains bundled JBR layout
    "\\jbr\\bin\\",       // JetBrains Runtime
    "\\java\\bin\\",    "\\jetbrains\\",
    "\\intellij idea",
    "\\android studio",
    "\\eclipse\\",
    "\\dbeaver\\",
    "\\jmeter\\",
    "\\burp suite",
];

const DOTNET_APP_EXE: &[&str] = &[
    "devenv.exe", "msbuild.exe", "winword.exe", "excel.exe",    "dotnet.exe",    // Microsoft Office / 365
    "winword.exe", "excel.exe", "powerpnt.exe", "outlook.exe", "onenote.exe",
    "msaccess.exe", "mspub.exe", "visio.exe", "teams.exe",
    // Visual Studio family
    "devenv.exe",           // Visual Studio IDE
    "blend.exe",            // Blend for Visual Studio
    "sqlservr.exe",
    // Windows built-in .NET apps
    "mmc.exe",              // Microsoft Management Console
    // Common .NET desktop apps
    "paint.net.exe",
    "keepass.exe", "keepassxc.exe",
    "sharex.exe",
    "greenshot.exe",
    "irfanview.exe",        // IrfanView (64-bit .NET port)
    "handbrake.exe",
    "filezilla.exe",
    "winmerge.exe",
    "tortoisegit.exe", "tortoisesvn.exe",
    "linqpad.exe", "linqpad7.exe",
    "dnspy.exe",            // .NET debugger/decompiler
    "ilspy.exe",            // ILSpy decompiler
    "dotpeek.exe",          // JetBrains dotPeek
    "rider.exe",            // also a JVM launcher but .NET-targeted IDE
    "msbuild.exe",
    "nuget.exe",


];

const DOTNET_PATH_FRAGS: &[&str] = &[
    "\\dotnet\\", "\\microsoft.net\\",    "\\microsoft.net\\",
    "\\dotnet\\",
    "\\microsoft visual studio\\",
    "\\microsoft office\\",
    "\\paint.net\\",
    "\\sharex\\",
    "\\keepass\\",
    "\\handbrake\\",
    "\\winmerge\\",

];

const GAME_ENGINE_EXE: &[&str] = &[
    "unity.exe", "unityhub.exe", "ue4editor.exe", "godot.exe",    // Unity
    "unityhub.exe",
    "unity.exe",
    // Unreal Engine
    "unrealengine.exe", "ue4editor.exe", "ue5editor.exe",
    // Godot
    "godot.exe", "godot4.exe", "godot_v4.exe",
    // Game launchers / platforms (these host/launch games)
    "steam.exe", "steamwebhelper.exe",
    "epicgameslauncher.exe",
    "gog galaxy.exe", "goggalaxy.exe",
    "origin.exe", "eadesktop.exe",
    "ubisoft connect.exe", "ubisoftconnect.exe", "uplaypc.exe",
    "battle.net.exe", "battlenet.exe",
    "xboxapp.exe",
    // Game engines / frameworks
    "rpgmaker.exe",
    "gamemaker.exe", "gamemakerstudio2.exe",
    "construct3.exe",
    "defold.exe",
    "pygame.exe",

];

const GAME_ENGINE_PATH_FRAGS: &[&str] = &[
    "\\unity\\", "\\unreal\\", "\\steam\\",    "\\unity\\",
    "\\unreal engine\\",
    "\\epic games\\",
    "\\godot\\",
    "\\steam\\",
    "\\steamapps\\",
    "\\gog galaxy\\",
    "\\origin games\\",
    "\\ubisoft game launcher\\",
    "\\battle.net\\",

];

const CONSOLE_HYBRID_EXE: &[&str] = &[
    "wt.exe", "wezterm.exe", "alacritty.exe",    "wt.exe",               // Windows Terminal
    "alacritty.exe",
    "wezterm.exe", "wezterm-gui.exe",
    "kitty.exe",
    "mintty.exe",           // Cygwin/MSYS2 terminal
    "conemu64.exe", "conemu.exe", "conemuportable.exe",
    "cmder.exe",
    "tabby.exe",
    "fluent terminal.exe", "fluentterminal.exe",
    "windowsterminal.exe",
    // REPLs that spawn a window
    "julia.exe",
    "r.exe", "rgui.exe",
    "idle.exe",             // Python IDLE
    "python.exe", "pythonw.exe",  // lower confidence; also CLI
    "ipython.exe",
    "jupyter.exe",
    // DB consoles that open a GUI window from CLI
    "mysql workbench.exe", "mysqlworkbench.exe",
    "pgadmin4.exe",

];

const TRAY_APP_EXE: &[&str] = &[
    "rainmeter.exe", "everything.exe",    "autohotkey.exe", "autohotkey32.exe", "autohotkey64.exe",
    "everything.exe",       // Voidtools Everything search
    "rainmeter.exe",
    "flux.exe",             // f.lux display color temp
    "f.lux.exe",
    "reshade.exe",
    "keypirinha.exe",
    "launchy.exe",
    "wox.exe",
    "listary.exe",
    "ditto.exe",            // clipboard manager
    "carnac.exe",           // keystroke visualizer
    "cpuz.exe", "gpuz.exe",
    "hwinfo64.exe", "hwinfo32.exe",
    "msiafterburner.exe",
    "coretemp.exe",
    "speedfan.exe",
    "fan control.exe", "fancontrol.exe",
    "classicshell.exe", "openshell.exe",
    "startisback.exe",
    "winaero tweaker.exe", "winaerotweaker.exe",
    "eartrumpet.exe",
    "twinkle tray.exe", "twinkletray.exe",
    "powertoys.exe",        // some modes are tray-only
    "sysinternals.exe",

];

const INSTALLER_EXE: &[&str] = &[
    "setup.exe", "install.exe", "installer.exe", "uninstall.exe",    "setup.exe", "install.exe", "installer.exe", "uninstall.exe",
    "uninstaller.exe", "uninst.exe",
    // NSIS
    "nsis.exe",
    // Inno Setup
    "is.exe",
    // WiX / Windows Installer
    "msiexec.exe",          // already in SYSTEM_EXE, but kept for clarity
    // InstallShield
    "isscript.exe", "setup64.exe",
    // Squirrel (app update, acts as installer during first run)
    "update.exe",

];

const NATIVE_CROSS_EXE: &[&str] = &[
    "vlc.exe", "qbittorrent.exe", "gimp.exe",    // Qt-based apps
    "vlc.exe",
    "virtualbox.exe", "vboxheadless.exe", "vboxmanage.exe",
    "qt creator.exe", "qtcreator.exe",
    "qbittorrent.exe",
    "musescore4.exe", "musescore.exe",
    "kicad.exe",
    "openscad.exe",
    "freeplane.exe",
    // Flutter desktop
    // (no universal exe; detected via path fragment below)
    // Tauri apps
    // (detected via path fragment; exe names are app-specific)
    // GTK on Windows
    "gimp.exe",
    "inkscape.exe",
    "gedit.exe",
    "glade.exe",
    // wxWidgets
    "audacity.exe",
    "codeblocks.exe",

];

const SYSTEM_PATH_FRAGS: &[&str] = &[
    "\\windows\\system32\\",
];

const INSTALLER_PATH_FRAGS: &[&str] = &[
    "\\temp\\", "\\appdata\\local\\temp\\",
];

// ─────────────────────────────────────────────────────────
// HELPERS
// ─────────────────────────────────────────────────────────

fn norm(s: &str) -> String {
    s.to_lowercase()
}

fn contains_any(hay: &str, needles: &[&str]) -> bool {
    needles.iter().any(|n| hay.contains(n))
}

// ─────────────────────────────────────────────────────────
// CLASSIFIER
// ─────────────────────────────────────────────────────────

pub fn classify(entry: &AppEntry) -> ClassificationResult {
    let exe = norm(entry.exe_name.as_deref().unwrap_or(""));
    let path = norm(entry.resolved_path.as_deref()
        .or(entry.full_path.as_deref())
        .unwrap_or(""));

    let args: Vec<String> = entry.args.as_deref()
        .unwrap_or(&[])
        .iter()
        .map(|a| norm(a))
        .collect();

    let mut scores: HashMap<AppCategory, Score> = HashMap::new();

    macro_rules! score {
        ($cat:expr, $w:expr, $r:expr) => {
            scores.entry($cat).or_default().add($w, $r);
        };
    }

    // ── Runtime signals

    if JVM_LAUNCHER_EXE.contains(&exe.as_str()) {
        score!(AppCategory::Jvm, 100, "JVM launcher");
    }
    if exe == "javaw.exe" && args.contains(&"-jar".to_string()) {
        score!(AppCategory::Jvm, 95, "java -jar");
    }
    if contains_any(&path, JVM_PATH_FRAGS) {
        score!(AppCategory::Jvm, 70, "JVM path");
    }

    if DOTNET_APP_EXE.contains(&exe.as_str()) {
        score!(AppCategory::DotnetDesktop, 95, ".NET app");
    }
    if exe == "dotnet.exe" {
        score!(AppCategory::DotnetDesktop, 70, "dotnet host");
    }
    if contains_any(&path, DOTNET_PATH_FRAGS) {
        score!(AppCategory::DotnetDesktop, 60, ".NET path");
    }

    if ELECTRON_EXE.contains(&exe.as_str()) {
        score!(AppCategory::Electron, 95, "Electron app");
    }

    if BROWSER_EXE.contains(&exe.as_str()) {
        score!(AppCategory::Browser, 90, "browser");

        if args.iter().any(|a| a.starts_with("--app")) {
            score!(AppCategory::Web, 95, "PWA mode");
            score!(AppCategory::Browser, -20, "override");
        }
    }

    // ── System

    if SYSTEM_EXE.contains(&exe.as_str()) {
        score!(AppCategory::System, 100, "system exe");
    }
    if contains_any(&path, SYSTEM_PATH_FRAGS) {
        score!(AppCategory::System, 60, "system path");
    }

    if args.iter().any(|a| a.starts_with("shell:appsfolder")) {
        score!(AppCategory::Uwp, 100, "UWP launch");
    }
    if path.contains("\\windowsapps\\") {
        score!(AppCategory::Uwp, 90, "WindowsApps");
    }

    // ── Behavior

    if INSTALLER_EXE.contains(&exe.as_str()) {
        score!(AppCategory::Installer, 100, "installer exe");
    }
    if contains_any(&path, INSTALLER_PATH_FRAGS) {
        score!(AppCategory::Installer, 80, "temp installer");
    }

    if GAME_ENGINE_EXE.contains(&exe.as_str()) {
        score!(AppCategory::GameEngine, 100, "game engine");
    }
    if contains_any(&path, GAME_ENGINE_PATH_FRAGS) {
        score!(AppCategory::GameEngine, 80, "game path");
    }

    if CONSOLE_HYBRID_EXE.contains(&exe.as_str()) {
        score!(AppCategory::ConsoleHybrid, 90, "terminal");
    }

    if TRAY_APP_EXE.contains(&exe.as_str()) {
        score!(AppCategory::TrayApp, 85, "tray");
    }

    if NATIVE_CROSS_EXE.contains(&exe.as_str()) {
        score!(AppCategory::NativeCrossPlatform, 85, "cross-platform");
    }

    // ── Fallback

    if exe.ends_with(".exe") || path.ends_with(".exe") {
        score!(AppCategory::Win32, 40, "fallback");
    }

    // ── Conflict resolution

    if scores.contains_key(&AppCategory::Electron)
        && scores.contains_key(&AppCategory::Browser)
    {
        score!(AppCategory::Browser, -30, "electron wins");
    }

    if scores.contains_key(&AppCategory::Jvm)
        && scores.contains_key(&AppCategory::DotnetDesktop)
    {
        score!(AppCategory::DotnetDesktop, -25, "jvm wins");
    }

    // ── Final selection

    let mut best = AppCategory::Unknown;
    let mut best_score = i32::MIN;
    let mut best_reason = String::new();

    for (cat, sc) in &scores {
        if sc.value > best_score {
            best = cat.clone();
            best_score = sc.value;
            best_reason = sc.reasons.join(" | ");
        }
    }

    ClassificationResult {
        name: entry.name.clone(),
        category: best,
        confidence: best_score.clamp(0, 100) as u8,
        reason: if best_score <= 0 {
            "no strong signals".into()
        } else {
            best_reason
        },
    }
}

// ─────────────────────────────────────────────────────────

pub fn classify_all(entries: &[AppEntry]) -> Vec<ClassificationResult> {
    entries.iter().map(classify).collect()
}