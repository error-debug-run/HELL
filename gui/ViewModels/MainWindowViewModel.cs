using System;
using System.Net.Http;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using Avalonia;
using Avalonia.Controls.ApplicationLifetimes;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using gui.Models;
using gui.Services;
using gui.Views;
using System.Collections.ObjectModel;

namespace gui.ViewModels;

// ─────────────────────────────────────────────────────────────
// MainWindowViewModel
//
// This is now just a coordinator. It:
//   1. Holds all the observable UI state (what the view binds to)
//   2. Creates the services
//   3. Calls the services and maps their results onto UI state
//
// It does NOT contain any logic for how to read hardware,
// how to start processes, or how to call audio endpoints —
// that all lives in the Services folder.
//
// Python analogy: a top-level App class that holds references
// to subsystems and wires them together
// ─────────────────────────────────────────────────────────────

public partial class MainWindowViewModel : ViewModelBase
{
    // ── Theme constants ──────────────────────────────────────
    // Defined once here — no more hunting for "#A855F7" across the file
    private const string ColorPurple = "#A855F7";
    private const string ColorRed    = "#EF4444";
    private const string ColorGreen  = "#22C55E";
    private const string ColorMuted  = "#6B6080";
    private const string ColorDark   = "#3B2F5A";
    private const string ColorJobs   = "#A1770E";
    private const string ColorApps   = "#33A115";
    private const string ColorConfig   = "#A31580";

    // ── Services ─────────────────────────────────────────────
    // These do the actual work. ViewModel just calls them.
    private readonly HttpClient        _http    = new();
    private readonly HardwareService   _hardware;
    private readonly HellProcessService _hell;
    private readonly AudioService      _audio;
    private readonly CancellationTokenSource _cts = new();

    private const string ApiBase = "http://127.0.0.1:8000";

    // ─────────────────────────────────────────────────────────
    // TAB STATE
    // ─────────────────────────────────────────────────────────
    [ObservableProperty] private string _activeTab = "status";

    public bool IsStatusTab => ActiveTab == "status";
    public bool IsAppsTab   => ActiveTab == "apps";
    public bool IsJobsTab   => ActiveTab == "jobs";
    public bool IsConfigTab => ActiveTab == "config";

    public string StatusTabColor => ActiveTab == "status" ? ColorPurple : ColorMuted;
    public string AppsTabColor   => ActiveTab == "apps"   ? ColorApps : ColorMuted;
    public string JobsTabColor   => ActiveTab == "jobs"   ? ColorJobs : ColorMuted;
    public string ConfigTabColor => ActiveTab == "config" ? ColorConfig : ColorMuted;

    // ─────────────────────────────────────────────────────────
    // SYSTEM STATUS
    // ─────────────────────────────────────────────────────────
    [ObservableProperty] private string _currentMode = "IDLE";
    [ObservableProperty] private string _cpuUsage    = "Detecting...";
    [ObservableProperty] private string _ramUsage    = "Detecting...";
    [ObservableProperty] private string _gpuUsage    = "Detecting...";
    [ObservableProperty] private string _cpuName     = "Detecting...";
    [ObservableProperty] private string _ramTotal    = "";

    // ─────────────────────────────────────────────────────────
    // MIC VISUALIZER
    // ─────────────────────────────────────────────────────────
    [ObservableProperty] private string _micStatus = "idle";
    [ObservableProperty] private string _micColor  = ColorDark;
    [ObservableProperty] private double _bar1Size  = 4;
    [ObservableProperty] private double _bar2Size  = 6;
    [ObservableProperty] private double _bar3Size  = 8;
    [ObservableProperty] private double _bar4Size  = 6;
    [ObservableProperty] private double _bar5Size  = 4;

    // ─────────────────────────────────────────────────────────
    // API STATUS
    // ─────────────────────────────────────────────────────────
    [ObservableProperty] private string _apiStatus      = "● OFFLINE";
    [ObservableProperty] private string _apiStatusColor = ColorRed;

    // ─────────────────────────────────────────────────────────
    // HELL STATE
    // ─────────────────────────────────────────────────────────
    [ObservableProperty] private bool   _isRunning      = false;
    [ObservableProperty] private string _startStopLabel = "START HELL";
    [ObservableProperty] private string _startStopColor = "#7C3AED";

    // ─────────────────────────────────────────────────────────
    // AUDIO STATE
    // ─────────────────────────────────────────────────────────
    [ObservableProperty] private double _dbLevel         = 0;
    [ObservableProperty] private double _dbSliderValue   = 0;
    [ObservableProperty] private string _recordingStatus = "OFFLINE";
    [ObservableProperty] private string _recordingColor  = ColorMuted;

    // ─────────────────────────────────────────────────────────
    // MIC DEVICES
    // ─────────────────────────────────────────────────────────
    [ObservableProperty] private ObservableCollection<MicDevice> _micDevices = new();
    [ObservableProperty] private MicDevice? _selectedMicDevice;
    [ObservableProperty] private string _micSaveStatus = "";

    // ─────────────────────────────────────────────────────────
    // CONSTRUCTOR
    // Create services, pass them the shared HttpClient,
    // then kick off background loops.
    // ─────────────────────────────────────────────────────────
    public MainWindowViewModel()
    {
        _hardware = new HardwareService();
        _hell     = new HellProcessService(_http);
        _audio    = new AudioService(_http);

        // Run hardware init on a background thread (it touches
        // Registry + PerformanceCounters which can be slow)
        Task.Run(() =>
        {
            _hardware.Initialize();

            // Copy static info from service onto observable properties
            CpuName  = _hardware.CpuName;
            RamTotal = _hardware.RamTotal;
            GpuUsage = _hardware.GpuName;
        });

        _ = StartMicAnimation();
        _ = StartStatsPoll();
    }

    // ─────────────────────────────────────────────────────────
    // TAB SWITCHING
    // ─────────────────────────────────────────────────────────
    [RelayCommand]
    private async Task SelectTab(string tab)
    {
        ActiveTab = tab;

        // Notify the view that all tab-derived properties changed
        OnPropertyChanged(nameof(IsStatusTab));
        OnPropertyChanged(nameof(IsAppsTab));
        OnPropertyChanged(nameof(IsJobsTab));
        OnPropertyChanged(nameof(IsConfigTab));
        OnPropertyChanged(nameof(StatusTabColor));
        OnPropertyChanged(nameof(AppsTabColor));
        OnPropertyChanged(nameof(JobsTabColor));
        OnPropertyChanged(nameof(ConfigTabColor));

        if (tab == "config" && IsRunning)
            await LoadMicDevices();
    }

    // ─────────────────────────────────────────────────────────
    // MIC VISUALIZER ANIMATION
    // ─────────────────────────────────────────────────────────
    private async Task StartMicAnimation()
    {
        var rng = new Random();
        using var timer = new PeriodicTimer(TimeSpan.FromMilliseconds(100));

        while (await timer.WaitForNextTickAsync(_cts.Token).ConfigureAwait(false))
        {
            var active = MicStatus == "listening";

            Bar1Size = active ? rng.Next(4, 16) : 4;
            Bar2Size = active ? rng.Next(6, 20) : 6;
            Bar3Size = active ? rng.Next(8, 24) : 8;
            Bar4Size = active ? rng.Next(6, 20) : 6;
            Bar5Size = active ? rng.Next(4, 16) : 4;
        }
    }

    public void SetMicActive(bool active)
    {
        MicStatus = active ? "listening" : "idle";
        MicColor  = active ? ColorPurple : ColorDark;
    }

    // ─────────────────────────────────────────────────────────
    // STATS POLLING LOOP
    // Runs every 2s. Asks HardwareService for CPU/RAM,
    // then checks the API for current mode.
    // ─────────────────────────────────────────────────────────
    private async Task StartStatsPoll()
    {
        using var timer = new PeriodicTimer(TimeSpan.FromSeconds(2));

        while (await timer.WaitForNextTickAsync(_cts.Token).ConfigureAwait(false))
        {
            // Hardware usage — service does the math, we just display
            await Task.Run(() =>
            {
                var (cpu, ram) = _hardware.GetUsage();
                CpuUsage = cpu;
                RamUsage = ram;
            }, _cts.Token);

            // API status check
            try
            {
                var json = await _http.GetStringAsync($"{ApiBase}/status", _cts.Token);
                using var doc = System.Text.Json.JsonDocument.Parse(json);

                CurrentMode    = doc.RootElement.GetProperty("mode").GetString()?.ToUpper() ?? "IDLE";
                ApiStatus      = "● CONNECTED TO API";
                ApiStatusColor = ColorGreen;
            }
            catch
            {
                ApiStatus      = "● OFFLINE";
                ApiStatusColor = ColorRed;
                CurrentMode    = "IDLE";
            }
        }
    }

    // ─────────────────────────────────────────────────────────
    // TRAY MODE COMMANDS
    // ─────────────────────────────────────────────────────────
    [RelayCommand]
    private async Task StartupMode() => await SendIntent("startup mode");

    [RelayCommand]
    private async Task DevMode() => await SendIntent("dev mode");

    [RelayCommand]
    private async Task GameMode() => await SendIntent("game_mode");

    private async Task SendIntent(string intent)
    {
        try
        {
            await _http.PostAsync(
                $"{ApiBase}/intent",
                new StringContent(
                    $"{{\"input\": \"{intent}\"}}",
                    Encoding.UTF8,
                    "application/json"
                )
            );
        }
        catch { }
    }

    // ─────────────────────────────────────────────────────────
    // HELL PROCESS CONTROL
    // ─────────────────────────────────────────────────────────
    [RelayCommand]
    private async Task ToggleHell()
    {
        if (IsRunning) StopHell();
        else await StartHell();
    }

    private async Task StartHell()
    {
        var success = await _hell.StartAsync();

        if (success)
            SetRunningState(running: true);
        else
            ApiStatus = "● Failed to start";
    }

    private void StopHell()
    {
        _hell.Stop();
        SetRunningState(running: false);

        // Reset audio display
        DbLevel       = 0;
        DbSliderValue = 0;
        ApiStatus      = "● OFFLINE";
        ApiStatusColor = ColorRed;
    }

    // Centralises all the "is HELL running?" UI state in one place.
    // Previously this was duplicated across StartHell and StopHell.
    private void SetRunningState(bool running)
    {
        IsRunning       = running;
        StartStopLabel  = running ? "STOP HELL"  : "START HELL";
        StartStopColor  = running ? ColorRed     : "#7C3AED";
        RecordingStatus = running ? "STANDBY"    : "OFFLINE";
        RecordingColor  = ColorMuted;

        if (running)
            _ = PollAudioLevel();
    }

    // ─────────────────────────────────────────────────────────
    // AUDIO POLLING LOOP
    // Calls AudioService every 100ms while HELL is running.
    // Maps the AudioSnapshot result onto observable properties.
    // ─────────────────────────────────────────────────────────
    private async Task PollAudioLevel()
    {
        using var timer = new PeriodicTimer(TimeSpan.FromMilliseconds(100));

        while (IsRunning && await timer.WaitForNextTickAsync(_cts.Token))
        {
            var snapshot = await _audio.GetAudioLevelAsync(_cts.Token);

            if (snapshot == null)
                continue;

            DbLevel       = snapshot.Db;
            DbSliderValue = Math.Max(0, Math.Min(100, (snapshot.Db + 60) * 100 / 60));

            // Map mode string → display label + color
            RecordingStatus = snapshot.Mode switch
            {
                "command" => "LISTENING",
                "idle"    => "STANDBY",
                _         => "RECORDING",
            };

            RecordingColor = snapshot.Mode switch
            {
                "command" => ColorGreen,
                "idle"    => ColorMuted,
                _         => ColorPurple,
            };
        }
    }

    // ─────────────────────────────────────────────────────────
    // MIC DEVICES
    // ─────────────────────────────────────────────────────────
    [RelayCommand]
    private async Task LoadMicDevices()
    {
        var devices = await _audio.GetDevicesAsync();

        if (devices.Count == 0)
        {
            MicSaveStatus = "API offline — start HELL first";
            return;
        }

        MicDevices.Clear();
        foreach (var d in devices)
            MicDevices.Add(d);
    }

    [RelayCommand]
    private async Task SaveMicDevice()
    {
        if (SelectedMicDevice == null)
            return;

        var ok = await _audio.SaveDeviceAsync(SelectedMicDevice.Index);

        MicSaveStatus = ok
            ? $"Saved: {SelectedMicDevice.Name}"
            : "Save failed — API offline";
    }

    // ─────────────────────────────────────────────────────────
    // WINDOW CONTROL
    // ─────────────────────────────────────────────────────────
    [RelayCommand]
    private void OpenDashboard()
    {
        if (Application.Current?.ApplicationLifetime
            is IClassicDesktopStyleApplicationLifetime desktop)
        {
            if (desktop.MainWindow is { IsVisible: true })
            {
                desktop.MainWindow.Activate();
                return;
            }

            var window = new MainWindow { DataContext = this };
            desktop.MainWindow = window;
            window.Show();
            window.Activate();
        }
    }

    // ─────────────────────────────────────────────────────────
    // EXIT
    // ─────────────────────────────────────────────────────────
    [RelayCommand]
    private void Exit()
    {
        _cts.Cancel();
        _hell.Stop();

        if (Application.Current?.ApplicationLifetime
            is IClassicDesktopStyleApplicationLifetime desktop)
        {
            desktop.Shutdown();
        }
    }
}