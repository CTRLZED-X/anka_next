using BepInEx;
using BepInEx.Unity.IL2CPP;

namespace DofusCoordinateBridge;

[BepInPlugin(PluginGuid, PluginName, PluginVersion)]
public sealed class Plugin : BasePlugin
{
    public const string PluginGuid = "local.dofus.coordinatebridge";
    public const string PluginName = "Dofus Coordinate Bridge";
    public const string PluginVersion = "2.2.76";

    public override void Load()
    {
        var port = Config.Bind("Bridge", "Port", 8765, "First localhost bridge port to try.").Value;
        var portCount = Config.Bind("Bridge", "PortCount", 32, "Number of consecutive localhost bridge ports available to Dofus clients.").Value;
        var discoveryOnStart = Config.Bind(
            "Discovery",
            "RunOnStart",
            false,
            "Write a candidate report when the plugin starts."
        ).Value;

        var component = AddComponent<CoordinateBridgeBehaviour>();
        var selectedPort = component.Initialize(Log, port, portCount, discoveryOnStart);
        Log.LogInfo($"Coordinate bridge listening on http://127.0.0.1:{selectedPort}");
    }
}
