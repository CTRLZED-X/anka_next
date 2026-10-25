using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;
using UnityEngine;

namespace DofusCoordinateBridge;

public sealed class DofusWindowMetrics
{
    public IntPtr Handle { get; set; }
    public int ClientWidth { get; set; }
    public int ClientHeight { get; set; }
    public int ScreenLeft { get; set; }
    public int ScreenTop { get; set; }

    public bool ContainsClient(CoordinatePoint point) =>
        point != null && point.X >= 0 && point.Y >= 0 && point.X < ClientWidth && point.Y < ClientHeight;

    public CoordinatePoint ClientToScreen(CoordinatePoint point) =>
        new(ScreenLeft + point.X, ScreenTop + point.Y);

    public CoordinatePoint ScreenToClient(CoordinatePoint point) =>
        new(point.X - ScreenLeft, point.Y - ScreenTop);

    public object Summary() => new
    {
        client_width = ClientWidth,
        client_height = ClientHeight,
        screen_left = ScreenLeft,
        screen_top = ScreenTop
    };
}

public sealed class ProjectedPoint
{
    public int ClientX { get; set; }
    public int ClientY { get; set; }
    public int ScreenX { get; set; }
    public int ScreenY { get; set; }
    public float CameraDepth { get; set; }
    public bool InsideCameraViewport { get; set; }
}

public static class CoordinateProjection
{
    private static IntPtr _cachedWindow;

    public static string ClientInstanceId(DofusWindowMetrics window, int processId, long processStartTime)
    {
        if (window == null || window.Handle == IntPtr.Zero || processId <= 0 || processStartTime <= 0)
            throw new ArgumentException("A valid Dofus window/process generation is required.");
        var raw = $"{window.Handle.ToInt64()}:{processId}:{processStartTime}";
        using var sha256 = SHA256.Create();
        var digest = Convert.ToHexString(sha256.ComputeHash(Encoding.ASCII.GetBytes(raw))).ToLowerInvariant();
        return "client-" + digest[..16];
    }

    public static bool TryGetDofusWindow(out DofusWindowMetrics metrics, out string error)
    {
        metrics = null;
        error = null;

        var process = Process.GetCurrentProcess();
        var candidates = new HashSet<IntPtr>();
        AddCandidate(candidates, _cachedWindow);
        try
        {
            process.Refresh();
            AddCandidate(candidates, process.MainWindowHandle);
        }
        catch
        {
            // Some Unity/IL2CPP builds do not publish MainWindowHandle.
        }
        try
        {
            var foreground = GetForegroundWindow();
            if (BelongsToProcess(foreground, (uint)process.Id))
                AddCandidate(candidates, foreground);
        }
        catch
        {
            // Foreground-window discovery is only an optimization.
        }
        try
        {
            EnumWindows((window, _) =>
            {
                if (BelongsToProcess(window, (uint)process.Id))
                    AddCandidate(candidates, window);
                return true;
            }, IntPtr.Zero);
        }
        catch
        {
            // The candidates already collected remain usable.
        }

        DofusWindowMetrics best = null;
        long bestArea = -1;
        foreach (var window in candidates)
        {
            if (!TryReadMetrics(window, out var candidate)) continue;
            var area = (long)candidate.ClientWidth * candidate.ClientHeight;
            if (IsWindowVisible(window)) area += 1L << 50;
            if (area <= bestArea) continue;
            best = candidate;
            bestArea = area;
        }
        if (best == null)
        {
            error = candidates.Count == 0
                ? "No top-level Dofus window handle belongs to the current process."
                : $"No Dofus window has a valid client area ({candidates.Count} handle(s) inspected).";
            return false;
        }

        _cachedWindow = best.Handle;
        metrics = best;
        return true;
    }

    private static void AddCandidate(ISet<IntPtr> candidates, IntPtr window)
    {
        if (window != IntPtr.Zero) candidates.Add(window);
    }

    private static bool BelongsToProcess(IntPtr window, uint processId)
    {
        if (window == IntPtr.Zero) return false;
        GetWindowThreadProcessId(window, out var ownerProcessId);
        return ownerProcessId == processId;
    }

    private static bool TryReadMetrics(IntPtr window, out DofusWindowMetrics metrics)
    {
        metrics = null;
        if (window == IntPtr.Zero || !IsWindow(window) || !GetClientRect(window, out var rect))
            return false;
        var width = rect.Right - rect.Left;
        var height = rect.Bottom - rect.Top;
        if (width <= 0 || height <= 0) return false;
        var origin = new NativePoint { X = 0, Y = 0 };
        if (!ClientToScreen(window, ref origin)) return false;
        metrics = new DofusWindowMetrics
        {
            Handle = window,
            ClientWidth = width,
            ClientHeight = height,
            ScreenLeft = origin.X,
            ScreenTop = origin.Y
        };
        return true;
    }

    public static bool TryWorldToClient(
        Vector3 worldPosition,
        Camera camera,
        DofusWindowMetrics window,
        out CoordinatePoint clientPoint)
    {
        clientPoint = null;
        if (camera == null || window == null) return false;
        if (!TryProject(worldPosition, camera, window, out var projected)
            || !projected.InsideCameraViewport)
            return false;
        clientPoint = new CoordinatePoint(projected.ClientX, projected.ClientY);
        return true;
    }

    public static bool TryProject(
        Vector3 worldPosition,
        Camera camera,
        DofusWindowMetrics window,
        out ProjectedPoint projected)
    {
        projected = null;
        if (camera == null || window == null || !IsFinite(worldPosition)) return false;
        Vector3 viewport;
        try { viewport = camera.WorldToViewportPoint(worldPosition); }
        catch { return false; }
        if (!IsFinite(viewport)) return false;

        float surfaceWidth;
        float surfaceHeight;
        float unityX;
        float unityY;
        try
        {
            if (camera.targetTexture != null)
            {
                surfaceWidth = Math.Max(1, camera.targetTexture.width);
                surfaceHeight = Math.Max(1, camera.targetTexture.height);
                unityX = viewport.x * surfaceWidth;
                unityY = viewport.y * surfaceHeight;
            }
            else
            {
                surfaceWidth = Math.Max(1, Screen.width);
                surfaceHeight = Math.Max(1, Screen.height);
                var rect = camera.pixelRect;
                unityX = rect.x + viewport.x * rect.width;
                unityY = rect.y + viewport.y * rect.height;
            }
        }
        catch
        {
            return false;
        }

        var clientX = (int)Math.Round(unityX * window.ClientWidth / surfaceWidth);
        var clientY = (int)Math.Round((surfaceHeight - unityY) * window.ClientHeight / surfaceHeight);
        var clientPoint = new CoordinatePoint(clientX, clientY);
        projected = new ProjectedPoint
        {
            ClientX = clientX,
            ClientY = clientY,
            ScreenX = window.ScreenLeft + clientX,
            ScreenY = window.ScreenTop + clientY,
            CameraDepth = viewport.z,
            InsideCameraViewport = viewport.z > 0
                                   && viewport.x >= 0 && viewport.x <= 1
                                   && viewport.y >= 0 && viewport.y <= 1
                                   && window.ContainsClient(clientPoint)
        };
        return true;
    }

    public static Camera SelectGameplayCamera(
        IReadOnlyList<Vector3> cellPositions,
        GameObject sourceObject,
        out object diagnostics)
    {
        Camera selected = null;
        var selectedScore = double.NegativeInfinity;
        var candidates = new List<object>();
        foreach (var camera in Camera.allCameras)
        {
            if (camera == null || !camera.enabled) continue;
            var projected = new List<Vector3>();
            for (var cellId = 0; cellId < (cellPositions?.Count ?? 0); cellId += 17)
            {
                var world = cellPositions[cellId];
                if (!IsFinite(world)) continue;
                try
                {
                    var point = camera.WorldToViewportPoint(world);
                    if (IsFinite(point) && point.z > 0) projected.Add(point);
                }
                catch
                {
                    // A camera that cannot project authoritative cells is not useful.
                }
            }
            var inside = projected.Count(point =>
                point.x >= 0 && point.x <= 1 && point.y >= 0 && point.y <= 1);
            var spreadX = projected.Count == 0 ? 0 : projected.Max(point => point.x) - projected.Min(point => point.x);
            var spreadY = projected.Count == 0 ? 0 : projected.Max(point => point.y) - projected.Min(point => point.y);
            var includesLayer = false;
            try
            {
                includesLayer = sourceObject != null
                                && (camera.cullingMask & (1 << sourceObject.layer)) != 0;
            }
            catch { }
            var name = (camera.name ?? "").ToLowerInvariant();
            var score = inside * 100.0
                        + Math.Min(2.0, spreadX) * 25.0
                        + Math.Min(2.0, spreadY) * 25.0
                        + (includesLayer ? 1000.0 : -1000.0)
                        + (camera.orthographic ? 50.0 : 0.0)
                        + (name.Contains("main") || name.Contains("world") || name.Contains("game") ? 10.0 : 0.0)
                        - (name.Contains("ui") || name.Contains("overlay") ? 200.0 : 0.0);
            candidates.Add(new
            {
                name = camera.name,
                instance_id = SafeInstanceId(camera),
                enabled = camera.enabled,
                orthographic = camera.orthographic,
                depth = camera.depth,
                culling_mask = camera.cullingMask,
                source_layer_included = includesLayer,
                sampled_cells_in_front = projected.Count,
                sampled_cells_inside_viewport = inside,
                viewport_spread_x = spreadX,
                viewport_spread_y = spreadY,
                score
            });
            if (score <= selectedScore) continue;
            selected = camera;
            selectedScore = score;
        }
        diagnostics = new
        {
            selection = "authoritative_cell_projection_and_source_layer",
            selected = selected?.name,
            selected_instance_id = SafeInstanceId(selected),
            candidates
        };
        return selected;
    }

    public static string ProjectionSignature(Camera camera, DofusWindowMetrics window)
    {
        if (camera == null || window == null) return "UNAVAILABLE";
        try
        {
            var transform = camera.transform;
            var rect = camera.pixelRect;
            var texture = camera.targetTexture;
            var projection = camera.projectionMatrix;
            return string.Join("|", new[]
            {
                SafeInstanceId(camera).ToString(),
                window.Handle.ToInt64().ToString(),
                Round(transform.position.x), Round(transform.position.y), Round(transform.position.z),
                Round(transform.rotation.x), Round(transform.rotation.y),
                Round(transform.rotation.z), Round(transform.rotation.w),
                Round(projection.m00), Round(projection.m01), Round(projection.m02), Round(projection.m03),
                Round(projection.m10), Round(projection.m11), Round(projection.m12), Round(projection.m13),
                Round(projection.m20), Round(projection.m21), Round(projection.m22), Round(projection.m23),
                Round(rect.x), Round(rect.y), Round(rect.width), Round(rect.height),
                (texture == null ? 0 : texture.GetInstanceID()).ToString(),
                (texture == null ? 0 : texture.width).ToString(),
                (texture == null ? 0 : texture.height).ToString(),
                Screen.width.ToString(), Screen.height.ToString(),
                window.ClientWidth.ToString(), window.ClientHeight.ToString(),
                window.ScreenLeft.ToString(), window.ScreenTop.ToString()
            });
        }
        catch
        {
            return "UNAVAILABLE";
        }
    }

    private static bool IsFinite(Vector3 value) =>
        !float.IsNaN(value.x) && !float.IsInfinity(value.x)
        && !float.IsNaN(value.y) && !float.IsInfinity(value.y)
        && !float.IsNaN(value.z) && !float.IsInfinity(value.z);

    private static int SafeInstanceId(UnityEngine.Object value)
    {
        try { return value == null ? 0 : value.GetInstanceID(); }
        catch { return 0; }
    }

    private static string Round(float value) => Math.Round(value, 5).ToString("R");

    [StructLayout(LayoutKind.Sequential)]
    private struct NativeRect
    {
        public int Left;
        public int Top;
        public int Right;
        public int Bottom;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct NativePoint
    {
        public int X;
        public int Y;
    }

    [DllImport("user32.dll")]
    private static extern bool GetClientRect(IntPtr window, out NativeRect rectangle);

    [DllImport("user32.dll")]
    private static extern bool ClientToScreen(IntPtr window, ref NativePoint point);

    private delegate bool EnumWindowsCallback(IntPtr window, IntPtr parameter);

    [DllImport("user32.dll")]
    private static extern bool EnumWindows(EnumWindowsCallback callback, IntPtr parameter);

    [DllImport("user32.dll")]
    private static extern uint GetWindowThreadProcessId(IntPtr window, out uint processId);

    [DllImport("user32.dll")]
    private static extern IntPtr GetForegroundWindow();

    [DllImport("user32.dll")]
    private static extern bool IsWindow(IntPtr window);

    [DllImport("user32.dll")]
    private static extern bool IsWindowVisible(IntPtr window);
}
