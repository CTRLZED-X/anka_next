namespace DofusCoordinateBridge;

public sealed class CoordinatePoint
{
    public int X { get; set; }
    public int Y { get; set; }

    public CoordinatePoint() { }

    public CoordinatePoint(int x, int y)
    {
        X = x;
        Y = y;
    }
}

public sealed class CoordinateRequest
{
    public string RequestId { get; set; } = "";
    public long MapId { get; set; }
    public int CellId { get; set; }
    public int? CellFloor { get; set; }
    public string Purpose { get; set; } = "MONSTER_GROUP_CLICK";
    public long? TargetEntityId { get; set; }
    public string RequestedAtUtc { get; set; }
}


public sealed class FightEntryRequest
{
    public string RequestId { get; set; } = "";
    public long MapId { get; set; }
    public int LaunchCellId { get; set; }
    public long FightInstanceId { get; set; }
    public long? LeaderActorId { get; set; }
    public long? OriginWorldEntityId { get; set; }
    public long? PresentationId { get; set; }
    public List<int> CandidateCellIds { get; set; } = new();
    public int? JoinAnchorCellId { get; set; }
    public string RequestedAtUtc { get; set; }
}

public sealed class FightEntryResponse
{
    public string RequestId { get; set; } = "";
    public long MapId { get; set; }
    public int LaunchCellId { get; set; }
    public long FightInstanceId { get; set; }
    public string Status { get; set; } = "FIGHT_ENTRY_NOT_PROVEN";
    public int? ClientX { get; set; }
    public int? ClientY { get; set; }
    public int? ScreenX { get; set; }
    public int? ScreenY { get; set; }
    public float? WorldX { get; set; }
    public float? WorldY { get; set; }
    public float? WorldZ { get; set; }
    public string TargetHierarchy { get; set; }
    public double Confidence { get; set; }
    public string CoordinateSpace { get; set; }
    public int? SourceClientWidth { get; set; }
    public int? SourceClientHeight { get; set; }
    public bool SourceVerified { get; set; }
    public bool InsideCameraViewport { get; set; }
    public long? LoadedMapId { get; set; }
    public long MapGeneration { get; set; }
    public long CoordinateGeneration { get; set; }
    public string Error { get; set; }
    public object Diagnostics { get; set; }
}

public sealed class CoordinateResponse
{
    public string RequestId { get; set; } = "";
    public long MapId { get; set; }
    public int CellId { get; set; }
    public string Status { get; set; } = "COORDINATE_RESOLUTION_FAILED";
    public int? ClientX { get; set; }
    public int? ClientY { get; set; }
    public int? ScreenX { get; set; }
    public int? ScreenY { get; set; }
    public float? WorldX { get; set; }
    public float? WorldY { get; set; }
    public float? WorldZ { get; set; }
    public bool StaticallyWalkable { get; set; }
    public bool Projectable { get; set; }
    public bool ClickableForMonsterGroup { get; set; }
    public string Purpose { get; set; }
    public long? TargetEntityId { get; set; }
    public bool EntityAnchorVerified { get; set; }
    public int? EntityAnchorCellId { get; set; }
    public int? EntityNearestCellId { get; set; }
    public bool ExactCellAnchorVerified { get; set; }
    public string ExactCellAnchorHierarchy { get; set; }
    public double? ExactCellAnchorPlanarError { get; set; }
    public int? EntityClientX { get; set; }
    public int? EntityClientY { get; set; }
    public int? EntityScreenX { get; set; }
    public int? EntityScreenY { get; set; }
    public string CoordinateSpace { get; set; }
    public int? SourceClientWidth { get; set; }
    public int? SourceClientHeight { get; set; }
    public bool InsideCameraViewport { get; set; }
    public List<CoordinatePoint> ClientPolygon { get; set; } = new();
    public List<CoordinatePoint> ScreenPolygon { get; set; } = new();
    public List<CoordinatePoint> SafeClientPoints { get; set; } = new();
    public List<CoordinatePoint> SafeScreenPoints { get; set; } = new();
    public bool VerifiedByDofusPicker { get; set; }
    public bool VerifiedByRuntimeGrid { get; set; }
    public bool SourceVerified { get; set; }
    public bool EntityAnchored { get; set; }
    public int ValidatedCellCount { get; set; }
    public int RequiredEntityAnchorCells { get; set; }
    public bool CellAnchorVerificationSupported { get; set; }
    public bool CellAnchorsVerified { get; set; }
    public int ValidatedCellAnchorCount { get; set; }
    public int RequiredCellAnchorCount { get; set; }
    public object CellAnchorDiagnostics { get; set; }
    public string SourceType { get; set; }
    public string SourceMember { get; set; }
    public int ValidSampleCount { get; set; }
    public int? EstimatedClickablePixels { get; set; }
    public long? LoadedMapId { get; set; }
    public bool MapLoaded { get; set; }
    public bool CellResolved { get; set; }
    public bool Visible { get; set; }
    public bool OnScreen { get; set; }
    public string Source { get; set; } = "dofus_authoritative_cell_map";
    public long MapGeneration { get; set; }
    public long CoordinateGeneration { get; set; }
    public string WindowFingerprint { get; set; }
    public string CameraFingerprint { get; set; }
    public string ResolvedAtUtc { get; set; } = DateTime.UtcNow.ToString("O");
    public string Error { get; set; }
    public object Diagnostics { get; set; }
}

public sealed class ObservationActor
{
    public long? ActorId { get; set; }
    public long? EntityId { get; set; }
    public string Side { get; set; }
    public string ActorType { get; set; }
    public bool IsPlayerControlled { get; set; }
    public int? ActorStaticId { get; set; }
    public int? CellId { get; set; }
    public int? CellFloor { get; set; }
    public int? Hp { get; set; }
    public bool? Alive { get; set; }
}

public sealed class CellFloorObservation
{
    public int CellId { get; set; }
    public int? Floor { get; set; }
}

public sealed class RuntimeObservation
{
    public string Status { get; set; }
    public string Source { get; set; }
    public long? MapId { get; set; }
    public string MapContext { get; set; }
    public long? CombatId { get; set; }
    public string FightPhase { get; set; }
    public bool ActiveFight { get; set; }
    public long? PlayerActorId { get; set; }
    public long? PlayerEntityId { get; set; }
    public int? PlayerCellId { get; set; }
    public string ObservationSignature { get; set; }
    public string ObservationEpoch { get; set; }
    public string AccountId { get; set; }
    public string ClientInstanceId { get; set; }
    public long? CanonicalRevision { get; set; }
    public string SentAtUtc { get; set; }
    public List<ObservationActor> Actors { get; set; } = new();
    public List<CellFloorObservation> CellFloors { get; set; } = new();
    public List<int> WalkableCellIds { get; set; } = new();
}

public sealed class ObservationResponse
{
    public string Status { get; set; } = "OBSERVATION_ACCEPTED";
    public bool Accepted { get; set; } = true;
    public bool Changed { get; set; }
    public long? LoadedMapId { get; set; }
    public long MapGeneration { get; set; }
    public string MapContext { get; set; }
    public long? CombatId { get; set; }
    public string ProjectionSignature { get; set; }
    public string WindowFingerprint { get; set; }
    public string CameraFingerprint { get; set; }
    public string CellGeometryFingerprint { get; set; }
    public int? SourceClientWidth { get; set; }
    public int? SourceClientHeight { get; set; }
    public int ActorsObserved { get; set; }
    public int ActorsMatched { get; set; }
    public int CalibrationSamples { get; set; }
    public int RequiredSamples { get; set; }
    public bool CalibrationReady { get; set; }
    public string CoordinateMode { get; set; } = "dofus_authoritative_cell_map";
    public bool DirectReady { get; set; }
    public bool PickerReady { get; set; }
    public bool PickerScanning { get; set; }
    public int ResolvedCellCount { get; set; }
    public int WalkableCellCount { get; set; }
    public int InsideViewportCount { get; set; }
    public bool SourceVerified { get; set; }
    public bool EntityAnchored { get; set; }
    public int ValidatedCellCount { get; set; }
    public int RequiredEntityAnchorCells { get; set; }
    public bool CellAnchorVerificationSupported { get; set; }
    public bool CellAnchorsVerified { get; set; }
    public int ValidatedCellAnchorCount { get; set; }
    public int RequiredCellAnchorCount { get; set; }
    public object CellAnchorDiagnostics { get; set; }
    public string SourceType { get; set; }
    public string SourceMember { get; set; }
    public long CoordinateGeneration { get; set; }
    public int? AnchorCellId { get; set; }
    public double? CalibrationRmsError { get; set; }
    public string EvidenceFile { get; set; }
    public string Error { get; set; }
    public object Diagnostics { get; set; }
}

public sealed class BridgeHealth
{
    public string BridgeVersion { get; set; }
    public string ClientInstanceId { get; set; }
    public int ProcessId { get; set; }
    public long ProcessStartTime { get; set; }
    public int BridgePort { get; set; }
    public string Status { get; set; } = "WAITING_FOR_DECODER";
    public bool Available { get; set; } = true;
    public string Source { get; set; } = "unity_bridge";
    public string Adapter { get; set; } = "dofus_authoritative_cell_map";
    public long? LoadedMapId { get; set; }
    public long MapGeneration { get; set; }
    public string MapContext { get; set; }
    public long? CombatId { get; set; }
    public string ProjectionSignature { get; set; }
    public string WindowFingerprint { get; set; }
    public string CameraFingerprint { get; set; }
    public string CellGeometryFingerprint { get; set; }
    public int? SourceClientWidth { get; set; }
    public int? SourceClientHeight { get; set; }
    public int CalibrationSamples { get; set; }
    public int RequiredSamples { get; set; }
    public bool CalibrationReady { get; set; }
    public string CoordinateMode { get; set; } = "dofus_authoritative_cell_map";
    public bool DirectReady { get; set; }
    public bool PickerReady { get; set; }
    public bool PickerScanning { get; set; }
    public int ResolvedCellCount { get; set; }
    public int WalkableCellCount { get; set; }
    public int InsideViewportCount { get; set; }
    public bool SourceVerified { get; set; }
    public bool EntityAnchored { get; set; }
    public int ValidatedCellCount { get; set; }
    public int RequiredEntityAnchorCells { get; set; }
    public bool CellAnchorVerificationSupported { get; set; }
    public bool CellAnchorsVerified { get; set; }
    public int ValidatedCellAnchorCount { get; set; }
    public int RequiredCellAnchorCount { get; set; }
    public object CellAnchorDiagnostics { get; set; }
    public string SourceType { get; set; }
    public string SourceMember { get; set; }
    public long CoordinateGeneration { get; set; }
    public int? AnchorCellId { get; set; }
    public double? CalibrationRmsError { get; set; }
    public string LastObservationAtUtc { get; set; }
    public string LastObservationEpoch { get; set; }
    public string LastObservationAccountId { get; set; }
    public string LastObservationClientInstanceId { get; set; }
    public long? LastObservationCanonicalRevision { get; set; }
}

public sealed class AutomationStatus
{
    public string Status { get; set; } = "WAITING_FOR_DECODER";
    public long? LoadedMapId { get; set; }
    public long MapGeneration { get; set; }
    public string MapContext { get; set; }
    public long? CombatId { get; set; }
    public string ProjectionSignature { get; set; }
    public string WindowFingerprint { get; set; }
    public string CameraFingerprint { get; set; }
    public string CellGeometryFingerprint { get; set; }
    public int? SourceClientWidth { get; set; }
    public int? SourceClientHeight { get; set; }
    public string LastObservationSignature { get; set; }
    public string LastObservationAtUtc { get; set; }
    public string LastObservationEpoch { get; set; }
    public string LastObservationAccountId { get; set; }
    public string LastObservationClientInstanceId { get; set; }
    public long? LastObservationCanonicalRevision { get; set; }
    public int ObservationsAccepted { get; set; }
    public int EvidenceFilesWritten { get; set; }
    public int CalibrationSamples { get; set; }
    public int RequiredSamples { get; set; }
    public bool CalibrationReady { get; set; }
    public string CoordinateMode { get; set; } = "dofus_authoritative_cell_map";
    public bool DirectReady { get; set; }
    public bool PickerReady { get; set; }
    public bool PickerScanning { get; set; }
    public int ResolvedCellCount { get; set; }
    public int WalkableCellCount { get; set; }
    public int InsideViewportCount { get; set; }
    public bool SourceVerified { get; set; }
    public bool EntityAnchored { get; set; }
    public int ValidatedCellCount { get; set; }
    public int RequiredEntityAnchorCells { get; set; }
    public bool CellAnchorVerificationSupported { get; set; }
    public bool CellAnchorsVerified { get; set; }
    public int ValidatedCellAnchorCount { get; set; }
    public int RequiredCellAnchorCount { get; set; }
    public object CellAnchorDiagnostics { get; set; }
    public string SourceType { get; set; }
    public string SourceMember { get; set; }
    public long CoordinateGeneration { get; set; }
    public int? AnchorCellId { get; set; }
    public double? CalibrationRmsError { get; set; }
    public string EvidenceDirectory { get; set; }
    public object LastMatchDiagnostics { get; set; }
}

public sealed class DiscoveryResponse
{
    public string Status { get; set; } = "DISCOVERY_WRITTEN";
    public string SourceFile { get; set; } = "";
    public string GeneratedAtUtc { get; set; } = "";
    public int ProcessId { get; set; }
    public long ProcessStartTime { get; set; }
    public long? LoadedMapId { get; set; }
    public long MapGeneration { get; set; }
    public long CoordinateGeneration { get; set; }
    public string ObservationEpoch { get; set; }
    public string AccountId { get; set; }
    public string ClientInstanceId { get; set; }
    public long? CanonicalRevision { get; set; }
    public int CameraCandidates { get; set; }
    public int ObjectCandidates { get; set; }
}

public sealed class MapCoordinateCell
{
    public int CellId { get; set; }
    public bool StaticallyWalkable { get; set; }
    public bool Projectable { get; set; }
    public bool ClickableForMonsterGroup { get; set; }
    public float WorldX { get; set; }
    public float WorldY { get; set; }
    public float WorldZ { get; set; }
    public int? ClientX { get; set; }
    public int? ClientY { get; set; }
    public int? ScreenX { get; set; }
    public int? ScreenY { get; set; }
    public bool InsideCameraViewport { get; set; }
    public float CameraDepth { get; set; }
    public string SourceType { get; set; }
    public string SourceMember { get; set; }
    public bool SourceVerified { get; set; }
}

public sealed class MapCoordinatesResponse
{
    public string Status { get; set; } = "COORDINATE_NOT_READY";
    public long? MapId { get; set; }
    public long MapGeneration { get; set; }
    public long CoordinateGeneration { get; set; }
    public string SourceType { get; set; }
    public string SourceMember { get; set; }
    public bool SourceVerified { get; set; }
    public int TotalMapCells { get; set; } = 560;
    public int WalkableCellCount { get; set; }
    public int GeneratedCoordinateCount { get; set; }
    public int ProjectableCellCount { get; set; }
    public int MonsterClickableCellCount { get; set; }
    public int InsideViewportCount { get; set; }
    public string CameraName { get; set; }
    public string ProjectionSignature { get; set; }
    public string WindowFingerprint { get; set; }
    public string CameraFingerprint { get; set; }
    public string CellGeometryFingerprint { get; set; }
    public int? SourceClientWidth { get; set; }
    public int? SourceClientHeight { get; set; }
    public string GeneratedAtUtc { get; set; }
    public string Error { get; set; }
    public List<MapCoordinateCell> Cells { get; set; } = new();
    public object Diagnostics { get; set; }
}
