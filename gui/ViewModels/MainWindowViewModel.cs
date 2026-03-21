using System;
using System.Diagnostics;
using System.Net.Http;
using System.Runtime.InteropServices;
using System.Threading;
using System.Threading.Tasks;
using Avalonia;
using Avalonia.Controls.ApplicationLifetimes;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using gui.Views;
using Microsoft.Win32;
using System.Diagnostics;

namespace gui.ViewModels;

public partial class MainWindowViewModel : ViewModelBase
{
    private readonly HttpClient _http = new();
    private const string ApiBase = "http://127.0.0.1:8000";

    private PerformanceCounter? _cpuCounter;
    private PerformanceCounter? _ramCounter;

    // ── tab state ─────────────────────────────────────────
    [ObservableProperty] private string _activeTab = "status";
    [ObservableProperty] private string _currentMode = "IDLE";
    [ObservableProperty] private string _cpuUsage = "--";
    [ObservableProperty] private string _ramUsage = "--";
    [ObservableProperty] private string _gpuUsage = "--";
    [ObservableProperty] private string _cpuName = "Detecting...";
    [ObservableProperty] private string _ramTotal = "";

    // ── mic visualizer ────────────────────────────────────
    [ObservableProperty] private string _micStatus = "idle";
    [ObservableProperty] private string _micColor = "#3B2F5A";
    [ObservableProperty] private double _bar1Size = 4;
    [ObservableProperty] private double _bar2Size = 6;
    [ObservableProperty] private double _bar3Size = 8;
    [ObservableProperty] private double _bar4Size = 6;
    [ObservableProperty] private double _bar5Size = 4;
    [ObservableProperty] private string _apiStatus = "● OFFLINE";
    [ObservableProperty] private string _apiStatusColor = "#EF4444";

    // ── tab visibility ────────────────────────────────────
    public bool IsStatusTab => ActiveTab == "status";
    public bool IsAppsTab => ActiveTab == "apps";
    public bool IsJobsTab => ActiveTab == "jobs";
    public bool IsConfigTab => ActiveTab == "config";

    // ── tab colors ────────────────────────────────────────
    public string StatusTabColor => ActiveTab == "status" ? "#A855F7" : "#6B6080";
    public string AppsTabColor => ActiveTab == "apps" ? "#A855F7" : "#6B6080";
    public string JobsTabColor => ActiveTab == "jobs" ? "#A855F7" : "#6B6080";
    public string ConfigTabColor => ActiveTab == "config" ? "#A855F7" : "#6B6080";

    public MainWindowViewModel()
    {
        _ = StartMicAnimation();
        InitHardware();
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
    private async Task StartMicAnimation()
    {
        var rng = new Random();
        using var timer = new PeriodicTimer(TimeSpan.FromMilliseconds(100));

        while (await timer.WaitForNextTickAsync(_cts.Token)
                   .ConfigureAwait(false))
        {
            var active = MicStatus == "listening";
            Bar1Size = active ? rng.Next(4, 16) : 4;
            Bar2Size = active ? rng.Next(6, 20) : 6;
            Bar3Size = active ? rng.Next(8, 24) : 8;
            Bar4Size = active ? rng.Next(6, 20) : 6;
            Bar5Size = active ? rng.Next(4, 16) : 4;
        }
    }

    // ── hardware init ─────────────────────────────────────
    private void InitHardware()
    {
        Task.Run(() =>
        {
            try
            {
                // CPU counter — most accurate way on Windows
                _cpuCounter = new PerformanceCounter(
                    "Processor Information", "% Processor Utility",
                    "_Total", true
                );
                // first read is always 0 — discard it
                _cpuCounter.NextValue();

                // available RAM in MB
                _ramCounter = new PerformanceCounter(
                    "Memory", "Available MBytes", true
                );

                // get CPU name from registry — instant, no WMI
                var key = Registry.LocalMachine
                    .OpenSubKey(
                        @"HARDWARE\DESCRIPTION\System\CentralProcessor\0"
                    );
                CpuName = key?.GetValue("ProcessorNameString")
                              ?.ToString()
                              ?.Trim()
                          ?? "Unknown CPU";

                // get total RAM
                GetRamTotal();

                // get GPU name from registry
                GetGpuName();

                // start polling loop
                _ = StartStatsPoll();
            }
            catch (Exception ex)
            {
                Console.WriteLine($"Hardware init error: {ex.Message}");
                CpuName = "Could not detect";
                CpuUsage = "--";
                RamUsage = "--";
                GpuUsage = "--";
            }
        });
    }

    private void GetRamTotal()
    {
        try
        {
            // GlobalMemoryStatusEx via P/Invoke
            var status = new MEMORYSTATUSEX();
            status.dwLength = (uint)Marshal.SizeOf(status);
            GlobalMemoryStatusEx(ref status);
            var totalGb = status.ullTotalPhys / 1024 / 1024 / 1024;
            RamTotal = $"{totalGb}GB";
        }
        catch
        {
            RamTotal = "";
        }
    }

    private void GetGpuName()
    {
        try
        {
            var key = Registry.LocalMachine
                .OpenSubKey(
                    @"SYSTEM\CurrentControlSet\Control\Class\" +
                    @"{4d36e968-e325-11ce-bfc1-08002be10318}\0000"
                );
            GpuUsage = key?.GetValue("DriverDesc")
                           ?.ToString()
                       ?? "GPU";
        }
        catch
        {
            GpuUsage = "GPU";
        }
    }

    private readonly CancellationTokenSource _cts = new();

    private async Task StartStatsPoll()
    {
        using var timer = new PeriodicTimer(TimeSpan.FromSeconds(2));

        while (await timer.WaitForNextTickAsync(_cts.Token)
                   .ConfigureAwait(false))
        {
            // local hardware stats
            await Task.Run(() =>
            {
                try
                {
                    var cpu = _cpuCounter?.NextValue() ?? 0;
                    CpuUsage = $"{(int)Math.Min(cpu, 100)}%";

                    var availMb = _ramCounter?.NextValue() ?? 0;
                    var status = new MEMORYSTATUSEX();
                    status.dwLength = (uint)Marshal.SizeOf(status);
                    GlobalMemoryStatusEx(ref status);
                    var totalMb = status.ullTotalPhys / 1024 / 1024;
                    var usedPct = totalMb > 0
                        ? (1.0 - availMb / totalMb) * 100
                        : 0;
                    RamUsage = $"{(int)usedPct}%";
                }
                catch (Exception ex)
                {
                    Console.WriteLine($"Hardware error: {ex.Message}");
                }
            }, _cts.Token);

            // API status — mode + connection indicator
            try
            {
                var json = await _http.GetStringAsync(
                    $"{ApiBase}/status", _cts.Token
                );

                using var doc = System.Text.Json.JsonDocument.Parse(json);
                var root = doc.RootElement;

                CurrentMode = root
                    .GetProperty("mode")
                    .GetString()
                    ?.ToUpper() ?? "IDLE";

                ApiStatus = "● CONNECTED TO API";
                ApiStatusColor = "#22C55E";
            }
            catch
            {
                ApiStatus = "● OFFLINE";
                ApiStatusColor = "#EF4444";
                CurrentMode = "IDLE";
            }
        }
    }

    [RelayCommand]
    private async Task Exit()
    {
        _cts.Cancel();
        await StopHell();
        if (Application.Current?.ApplicationLifetime
            is IClassicDesktopStyleApplicationLifetime desktop)
        {
            desktop.Shutdown();
        }
    }

    // ── P/Invoke for memory info ───────────────────────────
    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Auto)]
    private struct MEMORYSTATUSEX
    {
        public uint dwLength;
        public uint dwMemoryLoad;
        public ulong ullTotalPhys;
        public ulong ullAvailPhys;
        public ulong ullTotalPageFile;
        public ulong ullAvailPageFile;
        public ulong ullTotalVirtual;
        public ulong ullAvailVirtual;
        public ulong ullAvailExtendedVirtual;
    }

    [DllImport("kernel32.dll", CharSet = CharSet.Auto, SetLastError = true)]
    private static extern bool GlobalMemoryStatusEx(ref MEMORYSTATUSEX lpBuffer);

    // ── tray commands ─────────────────────────────────────
    [RelayCommand]
    private async Task StartupMode()
    {
        CurrentMode = "STARTUP";
        await SendIntent("startup mode");
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

    private async Task SendIntent(string intent)
    {
        try
        {
            var json = $"{{\"input\": \"{intent}\"}}";
            Console.WriteLine("Sending JSON: " + json);

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

    public void SetMicActive(bool active)
    {
        MicStatus = active ? "listening" : "idle";
        MicColor = active ? "#A855F7" : "#3B2F5A";
    }


    // fields
    private Process? _hellProcess;
    [ObservableProperty] private bool _isRunning = false;
    [ObservableProperty] private string _startStopLabel = "START HELL";
    [ObservableProperty] private string _startStopColor = "#7C3AED";
    [ObservableProperty] private double _dbLevel = 0;
    [ObservableProperty] private double _dbSliderValue = 0;
    [ObservableProperty] private string _recordingStatus = "OFFLINE";
    [ObservableProperty] private string _recordingColor = "#6B6080";

    [RelayCommand]
    private async Task ToggleHell()
    {
        if (IsRunning)
            await StopHell();
        else
            await StartHell();
    }

    private async Task StartHell()
    {
        var pythonPath = @"D:\HELL\.venv\Scripts\python.exe";
        var hellRoot   = @"D:\HELL";

        _hellProcess = new Process
        {
            StartInfo = new ProcessStartInfo
            {
                FileName               = pythonPath,
                Arguments              = "main.py",
                WorkingDirectory       = hellRoot,
                UseShellExecute        = false,
                CreateNoWindow         = true,
                RedirectStandardOutput = true,
                RedirectStandardError  = true,
            }
        };

        _hellProcess.OutputDataReceived += (_, e) =>
        {
            if (e.Data != null)
                Console.WriteLine($"[HELL] {e.Data}");
        };
        _hellProcess.ErrorDataReceived += (_, e) =>
        {
            if (e.Data != null)
                Console.WriteLine($"[HELL ERR] {e.Data}");
        };

        _hellProcess.Start();
        _hellProcess.BeginOutputReadLine();
        _hellProcess.BeginErrorReadLine();

        Console.WriteLine($"HELL core started: PID {_hellProcess.Id}");

        await WaitForApi();

        IsRunning       = true;
        StartStopLabel  = "STOP HELL";
        StartStopColor  = "#EF4444";
        RecordingStatus = "STANDBY";
        RecordingColor  = "#6B6080";

        _ = PollAudioLevel();
    }

    private async Task StopHell()
    {
        try
        {
            _hellProcess?.Kill(entireProcessTree: true);
            _hellProcess?.Dispose();
            _hellProcess = null;
        }
        catch
        {
        }

        IsRunning = false;
        StartStopLabel = "START HELL";
        StartStopColor = "#7C3AED";
        RecordingStatus = "OFFLINE";
        RecordingColor = "#6B6080";
        DbLevel = 0;
        DbSliderValue = 0;
        ApiStatus = "● OFFLINE";
        ApiStatusColor = "#EF4444";
    }

    private async Task WaitForApi(int maxWaitMs = 10000)
    {
        var start = DateTime.Now;
        Console.WriteLine("Waiting for API...");

        while ((DateTime.Now - start).TotalMilliseconds < maxWaitMs)
        {
            try
            {
                var response = await _http.GetAsync($"{ApiBase}/health");
                Console.WriteLine($"API response: {response.StatusCode}");
                if (response.IsSuccessStatusCode)
                {
                    Console.WriteLine("API is up!");
                    return;
                }
            }
            catch (Exception ex)
            {
                Console.WriteLine($"API not yet: {ex.Message}");
            }
            await Task.Delay(500);
        }

        Console.WriteLine("API wait timed out");
    }
    private async Task PollAudioLevel()
    {
        using var timer = new PeriodicTimer(TimeSpan.FromMilliseconds(100));

        while (IsRunning &&
               await timer.WaitForNextTickAsync(_cts.Token))
        {
            try
            {
                var json = await _http.GetStringAsync(
                    $"{ApiBase}/audio/level", _cts.Token
                );
                using var doc = System.Text.Json.JsonDocument.Parse(json);
                var root = doc.RootElement;

                var db = root.GetProperty("db").GetDouble();
                var mode = root.GetProperty("mode").GetString() ?? "idle";

                // convert db (-60 to 0) to slider (0 to 100)
                DbLevel = db;
                DbSliderValue = Math.Max(0, Math.Min(100, (db + 60) * 100 / 60));

                RecordingStatus = mode == "command" ? "LISTENING" :
                    mode == "idle" ? "STANDBY" : "RECORDING";
                RecordingColor = mode == "command" ? "#22C55E" :
                    mode == "idle" ? "#6B6080" : "#A855F7";
            }
            catch
            {
            }
        }
    }

    private async Task<string?> FindPython()
    {
        // try common Python locations
        var candidates = new[]
        {
            @"C:\Users\Admin\AppData\Local\Programs\Python\Python310\python.exe",
            @"C:\Python310\python.exe",
            "python",
            "python3",
        };

        foreach (var candidate in candidates)
        {
            try
            {
                var p = Process.Start(new ProcessStartInfo
                {
                    FileName = candidate,
                    Arguments = "--version",
                    UseShellExecute = false,
                    CreateNoWindow = true,
                    RedirectStandardOutput = true,
                });
                await p!.WaitForExitAsync();
                if (p.ExitCode == 0) return candidate;
            }
            catch
            {
            }
        }

        return null;
    }
}