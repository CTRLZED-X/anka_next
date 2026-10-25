namespace DofusCoordinateBridge;

public interface IDofusMapAdapter
{
    string Name { get; }
    long? LoadedMapId { get; }
    long MapGeneration { get; }
    void Tick();
    FightEntryResponse ResolveFightEntry(FightEntryRequest request);
    CoordinateResponse Resolve(CoordinateRequest request);
    MapCoordinatesResponse Coordinates();
    ObservationResponse Observe(RuntimeObservation observation);
    AutomationStatus AutomationStatus();
    BridgeHealth Health();
    DiscoveryResponse Discover();
}
