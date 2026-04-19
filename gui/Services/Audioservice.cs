using System;
using System.Collections.Generic;
using System.Net.Http;
using System.Text;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;
using gui.Models;

namespace gui.Services;

// ─────────────────────────────────────────────────────────────
// AudioService
// Responsible for: fetching mic device list, saving the
// selected mic, and polling the live dB audio level.
//
// Python equivalent: a class using httpx or aiohttp to call
// your FastAPI backend endpoints for audio state
// ─────────────────────────────────────────────────────────────

public class AudioService
{
    private const string ApiBase = "http://127.0.0.1:8000";

    private readonly HttpClient _http;

    public AudioService(HttpClient http)
    {
        _http = http;
    }

    // ────────────────────────────────────────────────────────
    // Fetches the list of available mic devices from the API.
    // Returns a list of MicDevice, or empty list on failure.
    //
    // Python equivalent:
    //   resp = requests.get(f"{API_BASE}/audio/devices")
    //   return resp.json()["devices"]
    // ────────────────────────────────────────────────────────
    public async Task<List<MicDevice>> GetDevicesAsync()
    {
        var result = new List<MicDevice>();

        try
        {
            var json = await _http.GetStringAsync($"{ApiBase}/audio/devices");
            using var doc = JsonDocument.Parse(json);
            var devices = doc.RootElement.GetProperty("devices");

            foreach (var device in devices.EnumerateArray())
            {
                result.Add(new MicDevice
                {
                    Index = device.GetProperty("index").GetInt32(),
                    Name  = device.GetProperty("name").GetString() ?? "",
                });
            }
        }
        catch (Exception ex)
        {
            Console.WriteLine($"[AudioService] GetDevices error: {ex.Message}");
        }

        return result;
    }

    // ────────────────────────────────────────────────────────
    // Saves the selected mic device index to the backend.
    // Returns true on success, false on failure.
    //
    // Python equivalent:
    //   resp = requests.post(f"{API_BASE}/audio/device",
    //                        json={"index": index})
    //   return resp.ok
    // ────────────────────────────────────────────────────────
    public async Task<bool> SaveDeviceAsync(int deviceIndex)
    {
        try
        {
            var body = JsonSerializer.Serialize(new { index = deviceIndex });

            var response = await _http.PostAsync(
                $"{ApiBase}/audio/device",
                new StringContent(body, Encoding.UTF8, "application/json")
            );

            return response.IsSuccessStatusCode;
        }
        catch (Exception ex)
        {
            Console.WriteLine($"[AudioService] SaveDevice error: {ex.Message}");
            return false;
        }
    }

    // ────────────────────────────────────────────────────────
    // A single poll of the audio level endpoint.
    // Returns an AudioSnapshot record, or null on failure.
    //
    // The ViewModel calls this in a loop on a timer and updates
    // its observable properties from the result.
    //
    // Python equivalent:
    //   resp = requests.get(f"{API_BASE}/audio/level")
    //   data = resp.json()
    //   return {"db": data["db"], "mode": data["mode"]}
    // ────────────────────────────────────────────────────────
    public async Task<AudioSnapshot?> GetAudioLevelAsync(CancellationToken ct)
    {
        try
        {
            var json = await _http.GetStringAsync($"{ApiBase}/audio/level", ct);
            using var doc = JsonDocument.Parse(json);
            var root = doc.RootElement;

            return new AudioSnapshot
            {
                Db   = root.GetProperty("db").GetDouble(),
                Mode = root.GetProperty("mode").GetString() ?? "idle",
            };
        }
        catch
        {
            // Returns null so the ViewModel knows the poll failed
            return null;
        }
    }
}

// ─────────────────────────────────────────────────────────────
// AudioSnapshot — plain data holder, like a Python dataclass.
// Just bundles db + mode together so GetAudioLevelAsync can
// return both values at once cleanly.
// ─────────────────────────────────────────────────────────────
public record AudioSnapshot
{
    public double Db   { get; init; }
    public string Mode { get; init; } = "idle";
}