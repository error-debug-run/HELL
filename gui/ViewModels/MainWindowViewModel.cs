using System;
using System.Net.Http;
using System.Threading;
using System.Threading.Tasks;
using Avalonia;
using Avalonia.Controls.ApplicationLifetimes;
using Avalonia.Media;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;

namespace gui.ViewModels;

public partial class MainWindowViewModel : ViewModelBase
{
    private readonly HttpClient _http   = new();
    private const    string     ApiBase = "http://127.0.0.1:8000";

    // ── tab state ─────────────────────────────────────────
    [ObservableProperty] private string _activeTab    = "status";
    [ObservableProperty] private string _currentMode  = "IDLE";
    [ObservableProperty] private string _cpuUsage     = "0%";
    [ObservableProperty] private string _ramUsage     = "0%";
    [ObservableProperty] private string _gpuUsage     = "0%";

    // ── mic visualizer ────────────────────────────────────
    [ObservableProperty] private string _micStatus    = "idle";
    [ObservableProperty] private string _micColor     = "#3B2F5A";
    [ObservableProperty] private double _bar1Size     = 6;
    [ObservableProperty] private double _bar2Size     = 8;
    [ObservableProperty] private double _bar3Size     = 10;
    [ObservableProperty] private double _bar4Size     = 8;
    [ObservableProperty] private double _bar5Size     = 6;

    // ── tab visibility ────────────────────────────────────
    public bool IsStatusTab => ActiveTab == "status";
    public bool IsAppsTab   => ActiveTab == "apps";
    public bool IsJobsTab   => ActiveTab == "jobs";
    public bool IsConfigTab => ActiveTab == "config";

    // ── tab colors ────────────────────────────────────────
    public string StatusTabColor => ActiveTab == "status" ? "#A855F7" : "#6B6080";
    public string AppsTabColor   => ActiveTab == "apps"   ? "#A855F7" : "#6B6080";
    public string JobsTabColor   => ActiveTab == "jobs"   ? "#A855F7" : "#6B6080";
    public string ConfigTabColor => ActiveTab == "config" ? "#A855F7" : "#6B6080";

    public MainWindowViewModel()
    {
        // start mic visualizer animation
        StartMicAnimation();
        // start polling system stats
        StartStatsPoll();
    }

    // ── tab switching ─────────────────────────────────────
    [RelayCommand]
    private void SelectTab(string tab)
    {
        ActiveTab = tab;
        OnPropertyChanged(nameof(IsStatusTab));
        OnPropertyChanged(nameof(IsAppsTab));
        OnPropertyChanged(nameof(IsJobsTab));
        OnPropertyChanged(nameof(IsConfigTab));
        OnPropertyChanged(nameof(StatusTabColor));
        OnPropertyChanged(nameof(AppsTabColor));
        OnPropertyChanged(nameof(JobsTabColor));
        OnPropertyChanged(nameof(ConfigTabColor));
    }

    // ── mic animation ─────────────────────────────────────
    private void StartMicAnimation()
    {
        var rng = new Random();
        var timer = new Timer(_ =>
        {
            // simulate audio levels — replace with real mic data later
            var active = MicStatus == "listening";
            Bar1Size = active ? rng.Next(4, 16) : 4;
            Bar2Size = active ? rng.Next(6, 20) : 6;
            Bar3Size = active ? rng.Next(8, 24) : 8;
            Bar4Size = active ? rng.Next(6, 20) : 6;
            Bar5Size = active ? rng.Next(4, 16) : 4;
        }, null, 0, 100);
    }

    // ── stats polling ─────────────────────────────────────
    private void StartStatsPoll()
    {
        var timer = new Timer(async _ =>
        {
            try
            {
                var response = await _http.GetStringAsync($"{ApiBase}/status");
                // parse response later when API is built
                CpuUsage = "12%";
                RamUsage = "34%";
                GpuUsage = "8%";
            }
            catch
            {
                // API not running — show placeholder
                CpuUsage = "--";
                RamUsage = "--";
                GpuUsage = "--";
            }
        }, null, 0, 3000);
    }

    // ── tray commands ─────────────────────────────────────
    [RelayCommand]
    private async Task StartupMode()
    {
        CurrentMode = "STARTUP";
        await SendIntent("startup_mode");
    }

    [RelayCommand]
    private async Task DevMode()
    {
        CurrentMode = "DEV";
        await SendIntent("dev_mode");
    }

    [RelayCommand]
    private async Task GameMode()
    {
        CurrentMode = "GAME";
        await SendIntent("game_mode");
    }

    [RelayCommand]
    private void OpenDashboard()
    {
        if (Application.Current?.ApplicationLifetime
            is IClassicDesktopStyleApplicationLifetime desktop)
        {
            desktop.MainWindow?.Show();
            desktop.MainWindow?.Activate();
            desktop.MainWindow!.ShowInTaskbar = true;
            desktop.MainWindow!.WindowState   =
                Avalonia.Controls.WindowState.Normal;
        }
    }

    [RelayCommand]
    private void Exit()
    {
        if (Application.Current?.ApplicationLifetime
            is IClassicDesktopStyleApplicationLifetime desktop)
        {
            desktop.Shutdown();
        }
    }

    // ── api ───────────────────────────────────────────────
    private async Task SendIntent(string intent)
    {
        try
        {
            await _http.PostAsync(
                $"{ApiBase}/intent",
                new StringContent(
                    $"{{\"input\": \"{intent}\"}}",
                    System.Text.Encoding.UTF8,
                    "application/json"
                )
            );
        }
        catch (Exception ex)
        {
            Console.WriteLine($"API not running: {ex.Message}");
        }
    }

    // ── public mic control (called by STT later) ──────────
    public void SetMicActive(bool active, double energy = 0)
    {
        MicStatus = active ? "listening" : "idle";
        MicColor  = active ? "#A855F7"   : "#3B2F5A";
    }
}