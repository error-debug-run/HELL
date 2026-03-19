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

namespace gui.ViewModels;

public partial class MainWindowViewModel : ViewModelBase
{
    private readonly HttpClient _http   = new();
    private const    string     ApiBase = "http://127.0.0.1:8000";

    private PerformanceCounter? _cpuCounter;
    private PerformanceCounter? _ramCounter;

    // ── tab state ─────────────────────────────────────────
    [ObservableProperty] private string _activeTab   = "status";
    [ObservableProperty] private string _currentMode = "IDLE";
    [ObservableProperty] private string _cpuUsage    = "--";
    [ObservableProperty] private string _ramUsage    = "--";
    [ObservableProperty] private string _gpuUsage    = "--";
    [ObservableProperty] private string _cpuName     = "Detecting...";
    [ObservableProperty] private string _ramTotal    = "";

    // ── mic visualizer ────────────────────────────────────
    [ObservableProperty] private string _micStatus = "idle";
    [ObservableProperty] private string _micColor  = "#3B2F5A";
    [ObservableProperty] private double _bar1Size  = 4;
    [ObservableProperty] private double _bar2Size  = 6;
    [ObservableProperty] private double _bar3Size  = 8;
    [ObservableProperty] private double _bar4Size  = 6;
    [ObservableProperty] private double _bar5Size  = 4;

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
        var rng   = new Random();
        using var timer = new PeriodicTimer(TimeSpan.FromMilliseconds(100));

        while (await timer.WaitForNextTickAsync(_cts.Token)
                   .ConfigureAwait(false))
        {
            var active = MicStatus == "listening";
            Bar1Size   = active ? rng.Next(4,  16) : 4;
            Bar2Size   = active ? rng.Next(6,  20) : 6;
            Bar3Size   = active ? rng.Next(8,  24) : 8;
            Bar4Size   = active ? rng.Next(6,  20) : 6;
            Bar5Size   = active ? rng.Next(4,  16) : 4;
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
                CpuName  = "Could not detect";
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

        while (await timer.WaitForNextTickAsync())
        {
            await Task.Run(() =>
            {
                try
                {
                    var cpu = _cpuCounter?.NextValue() ?? 0;
                    CpuUsage = $"{(int)Math.Min(cpu, 100)}%";

                    var availMb = _ramCounter?.NextValue() ?? 0;
                    var status  = new MEMORYSTATUSEX();
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
                    Console.WriteLine($"Stats poll error: {ex.Message}");
                }
            });
        }
    }
    
    [RelayCommand]
    private void Exit()
    {
        _cts.Cancel();
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
        public uint  dwLength;
        public uint  dwMemoryLoad;
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
        MicColor  = active ? "#A855F7"   : "#3B2F5A";
    }
}