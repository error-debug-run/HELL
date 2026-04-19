using System;
using System.Diagnostics;
using System.Runtime.InteropServices;
using Microsoft.Win32;

namespace gui.Services;

// ─────────────────────────────────────────────────────────────
// HardwareService
// Responsible for: reading CPU name, RAM total, GPU name,
// and providing live CPU% + RAM% usage snapshots.
//
// Python equivalent: a class that reads /proc/cpuinfo,
// /proc/meminfo and wraps psutil.cpu_percent()
// ─────────────────────────────────────────────────────────────

public class HardwareService
{
    // ── Windows API struct for memory info ──────────────────
    // Think of this like ctypes in Python — we're calling a
    // raw Windows DLL function and need to pass it a struct.
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

    // ── Performance counters (Windows-specific polling) ─────
    // These are like psutil handles — you open them once,
    // then call NextValue() repeatedly to get live readings.
    private PerformanceCounter? _cpuCounter;
    private PerformanceCounter? _ramCounter;

    // ── Static info (read once at startup) ──────────────────
    public string CpuName  { get; private set; } = "Detecting...";
    public string RamTotal { get; private set; } = "";
    public string GpuName  { get; private set; } = "GPU";

    // ────────────────────────────────────────────────────────
    // Call once at startup. Reads static hardware info and
    // warms up the performance counters (first NextValue()
    // always returns 0 on Windows, so we call it here).
    // ────────────────────────────────────────────────────────
    public void Initialize()
    {
        try
        {
            // CPU usage counter
            _cpuCounter = new PerformanceCounter(
                "Processor Information",
                "% Processor Utility",
                "_Total",
                readOnly: true
            );
            _cpuCounter.NextValue(); // discard the always-zero first reading

            // Available RAM counter (in MB)
            _ramCounter = new PerformanceCounter(
                "Memory",
                "Available MBytes",
                readOnly: true
            );

            ReadCpuName();
            ReadRamTotal();
            ReadGpuName();
        }
        catch (Exception ex)
        {
            Console.WriteLine($"[HardwareService] Init error: {ex.Message}");
        }
    }

    // ────────────────────────────────────────────────────────
    // Returns a snapshot of current CPU% and RAM% usage.
    // Call this on a timer (every 2s is fine).
    // Returns a named tuple-like record so the caller can
    // destructure: var (cpu, ram) = hardware.GetUsage();
    // ────────────────────────────────────────────────────────
    public (string Cpu, string Ram) GetUsage()
    {
        try
        {
            // CPU — clamp to 100 because the counter can spike briefly over
            var cpu = _cpuCounter?.NextValue() ?? 0;
            var cpuStr = $"{(int)Math.Min(cpu, 100)}%";

            // RAM — counter gives available MB, we calculate used %
            var availMb = _ramCounter?.NextValue() ?? 0;
            var status = new MEMORYSTATUSEX();
            status.dwLength = (uint)Marshal.SizeOf(status);
            GlobalMemoryStatusEx(ref status);

            var totalMb = status.ullTotalPhys / 1024 / 1024;
            var usedPct = totalMb > 0 ? (1.0 - availMb / totalMb) * 100 : 0;
            var ramStr = $"{(int)usedPct}%";

            return (cpuStr, ramStr);
        }
        catch
        {
            return ("--", "--");
        }
    }

    // ── Private helpers ──────────────────────────────────────

    private void ReadCpuName()
    {
        try
        {
            // Windows Registry — like reading /proc/cpuinfo on Linux
            var key = Registry.LocalMachine
                .OpenSubKey(@"HARDWARE\DESCRIPTION\System\CentralProcessor\0");

            CpuName = key?.GetValue("ProcessorNameString")
                          ?.ToString()
                          ?.Trim()
                      ?? "Unknown CPU";
        }
        catch
        {
            CpuName = "Unknown CPU";
        }
    }

    private void ReadRamTotal()
    {
        try
        {
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

    private void ReadGpuName()
    {
        try
        {
            var key = Registry.LocalMachine
                .OpenSubKey(
                    @"SYSTEM\CurrentControlSet\Control\Class\" +
                    @"{4d36e968-e325-11ce-bfc1-08002be10318}\0000"
                );
            GpuName = key?.GetValue("DriverDesc")?.ToString() ?? "GPU";
        }
        catch
        {
            GpuName = "GPU";
        }
    }
}