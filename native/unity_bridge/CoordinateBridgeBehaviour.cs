using System.Collections.Concurrent;
using System.Diagnostics;
using System.Net.Sockets;
using System.Text.Json;
using BepInEx.Logging;
using UnityEngine;

namespace DofusCoordinateBridge;

public sealed class CoordinateBridgeBehaviour : MonoBehaviour
{
    private readonly ConcurrentQueue<PendingCall> _calls = new();
    private IDofusMapAdapter _adapter;
    private LocalHttpServer _server;
    private ManualLogSource _log;
    private int _port;

    public int Initialize(ManualLogSource log, int port, int portCount, bool discoveryOnStart)
    {
        _log = log;
        _adapter = new AutomaticMapAdapter(log);
        var attempts = Math.Max(1, portCount);
        SocketException lastSocketError = null;
        for (var offset = 0; offset < portCount; offset++)
        {
            var candidatePort = checked(port + offset);
            var candidate = new LocalHttpServer(candidatePort, Enqueue);
            try
            {
                candidate.Start();
                _server = candidate;
                _port = candidatePort;
                if (discoveryOnStart) _calls.Enqueue(PendingCall.Discover());
                return _port;
            }
            catch (SocketException error)
            {
                lastSocketError = error;
                candidate.Dispose();
            }
        }
        throw new InvalidOperationException(
            $"No free localhost bridge port in range {port}..{port + attempts - 1}.",
            lastSocketError
        );
    }

    public void Update()
    {
        _adapter?.Tick();
        while (_calls.TryDequeue(out var call))
        {
            try
            {
                call.Complete(Handle(call));
            }
            catch (Exception error)
            {
                if (_log != null) _log.LogError(error);
                call.Fail(error);
            }
        }
    }

    public void OnDestroy()
    {
        if (_server != null) _server.Dispose();
    }

    private string Handle(PendingCall call)
    {
        var adapter = _adapter ?? throw new InvalidOperationException("Map adapter is unavailable.");
        return call.Route switch
        {
            "/health" => JsonSerializer.Serialize(Health(adapter), Json.Options),
            "/automation" => JsonSerializer.Serialize(adapter.AutomationStatus(), Json.Options),
            "/coordinates" => JsonSerializer.Serialize(adapter.Coordinates(), Json.Options),
            "/discover" => JsonSerializer.Serialize(adapter.Discover(), Json.Options),
            "/observe" => JsonSerializer.Serialize(
                adapter.Observe(JsonSerializer.Deserialize<RuntimeObservation>(call.Body, Json.Options)
                    ?? throw new InvalidDataException("Observation body is missing.")),
                Json.Options),
            "/resolve_fight_entry" => JsonSerializer.Serialize(
                adapter.ResolveFightEntry(JsonSerializer.Deserialize<FightEntryRequest>(call.Body, Json.Options)
                    ?? throw new InvalidDataException("Fight-entry request body is missing.")),
                Json.Options),
            "/resolve" => JsonSerializer.Serialize(
                adapter.Resolve(JsonSerializer.Deserialize<CoordinateRequest>(call.Body, Json.Options)
                    ?? throw new InvalidDataException("Request body is missing.")),
                Json.Options),
            _ => JsonSerializer.Serialize(new { status = "NOT_FOUND" }, Json.Options)
        };
    }

    private BridgeHealth Health(IDofusMapAdapter adapter)
    {
        var health = adapter.Health();
        health.BridgeVersion = Plugin.PluginVersion;
        using var process = Process.GetCurrentProcess();
        health.ProcessId = process.Id;
        health.ProcessStartTime = process.StartTime.ToFileTimeUtc();
        health.BridgePort = _port;
        return health;
    }

    private string Enqueue(string route, string body)
    {
        var call = new PendingCall(route, body);
        _calls.Enqueue(call);
        var timeoutSeconds = route switch
        {
            "/observe" or "/discover" => 20,
            // Entity/fight-entry resolution can perform a bounded reflected scene
            // search on the Unity main thread.  Give it a distinct budget so a
            // healthy first-time resolver is not misclassified as bridge loss.
            "/resolve" or "/resolve_fight_entry" => 12,
            _ => 6
        };
        var timeout = TimeSpan.FromSeconds(timeoutSeconds);
        if (!call.Wait(timeout))
        {
            return JsonSerializer.Serialize(new
            {
                status = "COORDINATE_RESOLUTION_FAILED",
                error = $"Unity main-thread dispatch timed out after {timeoutSeconds}s.",
                route,
                dispatch_timeout_seconds = timeoutSeconds
            }, Json.Options);
        }
        return call.Result;
    }
}

internal sealed class PendingCall
{
    private readonly ManualResetEventSlim _completed = new(false);
    private Exception _error;

    public PendingCall(string route, string body)
    {
        Route = route;
        Body = body;
    }

    public string Route { get; }
    public string Body { get; }
    public string Result { get; private set; } = "";

    public static PendingCall Discover() => new("/discover", "");

    public void Complete(string result)
    {
        Result = result;
        _completed.Set();
    }

    public void Fail(Exception error)
    {
        _error = error;
        _completed.Set();
    }

    public bool Wait(TimeSpan timeout)
    {
        var completed = _completed.Wait(timeout);
        if (_error != null) throw _error;
        return completed;
    }
}
