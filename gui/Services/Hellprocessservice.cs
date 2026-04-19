using System;
using System.Diagnostics;
using System.Net.Http;
using System.Threading.Tasks;

namespace gui.Services;

// ─────────────────────────────────────────────────────────────
// HellProcessService
// Responsible for: launching the Python backend process,
// waiting for its API to come online, and killing it cleanly.
//
// Python equivalent: a class wrapping subprocess.Popen
// with an asyncio health-check loop
// ─────────────────────────────────────────────────────────────

public class HellProcessService
{
    // ── Config — change paths here if HELL moves ─────────────
    // Keeping these as constants means you only update one place.
    // Later you could load these from appsettings.json instead.
    private const string PythonExe = @"D:\HELL\.venv\Scripts\python.exe";
    private const string WorkingDir = @"D:\HELL";
    private const string HealthUrl  = "http://127.0.0.1:8000/health";

    private readonly HttpClient _http;
    private Process? _process;

    // IsRunning is readable from outside but only settable here
    public bool IsRunning { get; private set; } = false;

    // ── Constructor ─────────────────────────────────────────
    // We take HttpClient as a parameter (dependency injection)
    // rather than creating one inside — same idea as passing
    // a requests.Session into a Python class instead of
    // calling requests.get() directly. Avoids socket exhaustion.
    public HellProcessService(HttpClient http)
    {
        _http = http;
    }

    // ────────────────────────────────────────────────────────
    // Starts the Python backend process and waits for its
    // HTTP API to come online before returning.
    //
    // Returns true if startup succeeded, false if it timed out.
    // ────────────────────────────────────────────────────────
    public async Task<bool> StartAsync()
    {
        // Like subprocess.Popen in Python — we configure the
        // process before starting it
        _process = new Process
        {
            StartInfo = new ProcessStartInfo
            {
                FileName         = PythonExe,
                Arguments        = "main.py",
                WorkingDirectory = WorkingDir,
                UseShellExecute  = false,   // don't open a shell window
                CreateNoWindow   = true,    // run silently in background
                RedirectStandardOutput = true,
                RedirectStandardError  = true,
            }
        };

        // Wire up output handlers before starting.
        // Like doing proc.stdout.readline() in a thread in Python.
        _process.OutputDataReceived += (_, e) =>
        {
            if (e.Data != null)
                Console.WriteLine($"[HELL] {e.Data}");
        };
        _process.ErrorDataReceived += (_, e) =>
        {
            if (e.Data != null)
                Console.WriteLine($"[HELL ERR] {e.Data}");
        };

        _process.Start();
        _process.BeginOutputReadLine(); // start async reading of stdout
        _process.BeginErrorReadLine();  // start async reading of stderr

        // Wait for the FastAPI server to be ready
        var apiReady = await WaitForApiAsync(maxWaitMs: 10000);

        if (apiReady)
            IsRunning = true;

        return apiReady;
    }

    // ────────────────────────────────────────────────────────
    // Kills the process and cleans up.
    // entireProcessTree: true means we also kill any child
    // processes the Python script may have spawned.
    // ────────────────────────────────────────────────────────
    public void Stop()
    {
        try
        {
            _process?.Kill(entireProcessTree: true);
            _process?.Dispose();
            _process = null;
        }
        catch (Exception ex)
        {
            Console.WriteLine($"[HellProcessService] Stop error: {ex.Message}");
        }
        finally
        {
            // Always mark as stopped even if Kill() threw
            IsRunning = false;
        }
    }

    // ── Private helpers ──────────────────────────────────────

    // Polls the /health endpoint until it responds OK or we time out.
    // Python equivalent: polling with requests.get() in a while loop
    // with asyncio.sleep(0.5) between attempts.
    private async Task<bool> WaitForApiAsync(int maxWaitMs = 10000)
    {
        var start = DateTime.Now;

        while ((DateTime.Now - start).TotalMilliseconds < maxWaitMs)
        {
            try
            {
                var response = await _http.GetAsync(HealthUrl);
                if (response.IsSuccessStatusCode)
                    return true;
            }
            catch
            {
                // API not ready yet — swallow the error and retry
            }

            await Task.Delay(500); // wait 500ms before next attempt
        }

        Console.WriteLine("[HellProcessService] API did not come online in time.");
        return false;
    }
}