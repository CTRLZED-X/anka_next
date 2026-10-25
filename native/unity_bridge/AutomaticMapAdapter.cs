using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using BepInEx;
using BepInEx.Logging;
using UnityEngine;

namespace DofusCoordinateBridge;

/// <summary>
/// Builds a complete cached map from Dofus's live CustomGridGenerator. A
/// website lookup never performs discovery, projection, or calibration.
/// </summary>
public sealed class AutomaticMapAdapter : IDofusMapAdapter
{
    private readonly ManualLogSource _log;
    private readonly RuntimeSceneScanner _scanner = new();
    private readonly string _rootDirectory;
    private readonly string _evidenceDirectory;
    private RuntimeObservation _lastObservation;
    private string _lastObservationSignature;
    private string _lastObservationAtUtc;
    private long? _loadedMapId;
    private long? _lastCombatId;
    private string _lastMapContext;
    private long _mapGeneration;
    private long _coordinateGeneration;
    private int _observationsAccepted;
    private int _evidenceFilesWritten;
    private AuthoritativeCellPositionSource _source;
    private Camera _camera;
    private MapCoordinatesResponse _coordinates = new();
    private Dictionary<int, MapCoordinateCell> _coordinateByCell = new();
    private string _lastProjectionSignature;
    private string _lastError;
    private object _sourceDiscoveryDiagnostics;
    private object _cameraDiagnostics;
    private object _actorDiagnostics;
    private bool _cellAnchorsVerified;
    private int _validatedCellAnchorCount;
    private object _cellAnchorDiagnostics;
    private const int RequiredCellAnchorCount = 2;
    private const double MaximumCellAnchorPlanarError = 6.0;
    private float _nextTickAt;

    public AutomaticMapAdapter(ManualLogSource log)
    {
        _log = log;
        var generationEpoch = NewGenerationEpoch();
        _mapGeneration = generationEpoch;
        _coordinateGeneration = generationEpoch;
        _rootDirectory = Path.Combine(Paths.ConfigPath, "DofusCoordinateBridge");
        _evidenceDirectory = Path.Combine(_rootDirectory, "evidence");
        Directory.CreateDirectory(_evidenceDirectory);
    }

    private static long NewGenerationEpoch()
    {
        var bytes = new byte[8];
        using (var rng = RandomNumberGenerator.Create())
            rng.GetBytes(bytes);
        var raw = BitConverter.ToUInt64(bytes, 0);
        // Keep the sign bit and one additional high bit clear, leaving an
        // enormous monotonic increment range for this bridge instance.
        return (long)(raw & 0x3fffffffffffffffUL) + 1;
    }

    private static string LocalClientInstanceId(DofusWindowMetrics window)
    {
        using var process = System.Diagnostics.Process.GetCurrentProcess();
        return CoordinateProjection.ClientInstanceId(
            window, process.Id, process.StartTime.ToFileTimeUtc());
    }

    private bool ObservationMatchesWindow(DofusWindowMetrics window) =>
        _lastObservation != null
        && string.Equals(
            _lastObservation.ClientInstanceId,
            LocalClientInstanceId(window),
            StringComparison.Ordinal);

    public string Name => "dofus_authoritative_cell_map";
    private string CurrentSourceMember => _source?.SelectedMember ?? AuthoritativeCellPositionSource.SourceMember;
    public long? LoadedMapId => _loadedMapId;
    public long MapGeneration => _mapGeneration;

    public void Tick()
    {
        if (Time.realtimeSinceStartup < _nextTickAt) return;
        _nextTickAt = Time.realtimeSinceStartup + 0.25f;
        if (_source?.ProjectionVerified != true
            || _camera == null
            || _lastObservation == null
            || !_loadedMapId.HasValue)
            return;
        if (!CoordinateProjection.TryGetDofusWindow(out var window, out var windowError))
        {
            _lastError = windowError;
            _coordinates = NotReadyCoordinates("COORDINATE_NOT_READY", _lastError);
            _coordinateByCell.Clear();
            _lastProjectionSignature = null;
            return;
        }
        if (!ObservationMatchesWindow(window))
        {
            _lastError = "The current Dofus window no longer matches the accepted canonical client instance.";
            _coordinates = NotReadyCoordinates("COORDINATE_NOT_READY", _lastError);
            _coordinateByCell.Clear();
            _lastProjectionSignature = null;
            return;
        }
        var signature = ProjectionSignature(window);
        if (!string.Equals(signature, _lastProjectionSignature, StringComparison.Ordinal))
        {
            RebuildCoordinateCache(window, "runtime_projection_changed");
        }
    }

    public FightEntryResponse ResolveFightEntry(FightEntryRequest request)
    {
        if (request == null)
            return new FightEntryResponse { Status = "FIGHT_ENTRY_NOT_PROVEN", Error = "Fight-entry request is missing." };
        if (!_loadedMapId.HasValue)
            return FightEntryFailure(request, "MAP_NOT_LOADED", "No active Dofus map is loaded.");
        if (_loadedMapId.Value != request.MapId)
            return FightEntryFailure(request, "MAP_ID_MISMATCH", $"Dofus currently has map {_loadedMapId.Value} loaded.");
        if (request.LaunchCellId < 0 || request.LaunchCellId >= AuthoritativeCellPositionSource.CellCount)
            return FightEntryFailure(request, "CELL_NOT_FOUND", "launch_cell_id must be between 0 and 559.");
        if (request.FightInstanceId <= 0)
            return FightEntryFailure(request, "FIGHT_ENTRY_NOT_PROVEN", "A positive fight_instance_id is required.");
        if (_source?.ProjectionVerified != true || _camera == null)
            return FightEntryFailure(request, "FIGHT_ENTRY_NOT_PROVEN", "The follower-local live map projection is not verified.");
        if (!CoordinateProjection.TryGetDofusWindow(out var window, out var windowError))
            return FightEntryFailure(request, "FIGHT_ENTRY_NOT_PROVEN", windowError ?? "Dofus window is unavailable.");
        if (!ObservationMatchesWindow(window))
            return FightEntryFailure(request, "FIGHT_ENTRY_NOT_PROVEN", "Canonical observation does not belong to the current follower window.");
        if (!CoordinateTableIsReady()
            || !string.Equals(ProjectionSignature(window), _lastProjectionSignature, StringComparison.Ordinal))
            return FightEntryFailure(request, "FIGHT_ENTRY_NOT_PROVEN", "Projection generation is not current for the follower window.");

        var target = _scanner.FindFightEntryTarget(request, _camera, _source.SnapshotPositions(), out var diagnostics);
        if (target == null)
            return FightEntryFailure(
                request,
                "FIGHT_ENTRY_NOT_PROVEN",
                "No unique strong live fight-entry object could be proven for this fight.",
                diagnostics);
        if (!CoordinateProjection.TryProject(target.WorldPosition, _camera, window, out var projected)
            || !projected.InsideCameraViewport)
            return FightEntryFailure(
                request,
                "FIGHT_ENTRY_NOT_PROVEN",
                "The proven fight-entry object is not safely projectable in the current follower viewport.",
                diagnostics);

        if (!string.Equals(ProjectionSignature(window), _lastProjectionSignature, StringComparison.Ordinal))
            return FightEntryFailure(request, "FIGHT_ENTRY_NOT_PROVEN", "Projection changed during fight-entry resolution.");

        return new FightEntryResponse
        {
            RequestId = request.RequestId,
            MapId = request.MapId,
            LaunchCellId = request.LaunchCellId,
            FightInstanceId = request.FightInstanceId,
            Status = "RESOLVED",
            ClientX = projected.ClientX,
            ClientY = projected.ClientY,
            ScreenX = projected.ScreenX,
            ScreenY = projected.ScreenY,
            WorldX = target.WorldX,
            WorldY = target.WorldY,
            WorldZ = target.WorldZ,
            TargetHierarchy = target.Hierarchy,
            Confidence = target.Confidence,
            CoordinateSpace = "BRIDGE_CLIENT_RELATIVE_WITH_SCREEN_DIAGNOSTIC",
            SourceClientWidth = window.ClientWidth,
            SourceClientHeight = window.ClientHeight,
            SourceVerified = true,
            InsideCameraViewport = true,
            LoadedMapId = _loadedMapId,
            MapGeneration = _mapGeneration,
            CoordinateGeneration = _coordinateGeneration,
            Diagnostics = diagnostics
        };
    }

    public CoordinateResponse Resolve(CoordinateRequest request)
    {
        if (!_loadedMapId.HasValue)
            return Failure(request, "MAP_NOT_LOADED", "No active Dofus map is loaded.");
        if (_loadedMapId.Value != request.MapId)
            return Failure(request, "MAP_ID_MISMATCH", $"Dofus currently has map {_loadedMapId.Value} loaded.");
        if (request.CellId < 0 || request.CellId >= AuthoritativeCellPositionSource.CellCount)
            return Failure(request, "CELL_NOT_FOUND", "cell_id must be between 0 and 559.");
        if (_source?.ProjectionVerified != true)
            return Failure(
                request,
                "CELL_POSITION_SOURCE_UNVERIFIED",
                _source?.LastError ?? _lastError ?? "The authoritative Dofus cell-position source is not verified for the loaded map.");
        if (!CoordinateTableIsReady())
            return Failure(
                request,
                "COORDINATE_NOT_READY",
                _coordinates.Error ?? _lastError ?? "The map coordinate table is not ready.");
        if (!_coordinateByCell.TryGetValue(request.CellId, out var cell))
            return Failure(
                request,
                "CELL_NOT_FOUND",
                "The requested cell is not present in the authoritative 560-cell projection table.");
        var purpose = string.IsNullOrWhiteSpace(request.Purpose)
            ? "MONSTER_GROUP_CLICK"
            : request.Purpose.Trim().ToUpperInvariant();
        if (purpose == "MONSTER_GROUP_CLICK" && !cell.ClickableForMonsterGroup)
            return Failure(
                request,
                cell.InsideCameraViewport ? "COORDINATE_NOT_READY" : "CELL_OUTSIDE_VIEWPORT",
                cell.InsideCameraViewport
                    ? "The requested cell is not currently safe for a monster-group click."
                    : "The requested monster-group cell is outside the current camera viewport.");

        if (!CoordinateProjection.TryGetDofusWindow(out var responseWindow, out var responseWindowError))
            return Failure(request, "COORDINATE_NOT_READY", responseWindowError ?? "Dofus window is unavailable for coordinate-space validation.");
        if (!ObservationMatchesWindow(responseWindow))
            return Failure(request, "COORDINATE_NOT_READY", "Canonical observation does not belong to the current Dofus window.");
        if (!string.Equals(ProjectionSignature(responseWindow), _lastProjectionSignature, StringComparison.Ordinal))
            return Failure(request, "COORDINATE_NOT_READY", "Projection changed after the cached coordinate table was validated.");

        ActorRuntimeMatch targetEntity = null;
        ProjectedPoint targetProjection = null;
        int? targetNearestCell = null;
        object targetDiagnostics = null;
        bool exactCellAnchorVerified = false;
        string exactCellAnchorHierarchy = null;
        double? exactCellPlanarError = null;
        object exactCellAnchorDiagnostics = null;
        ProjectedPoint exactCellProjection = null;

        // A spell target is authorized by the structurally verified runtime
        // grid.  If an exact rendered cell object exists, use it as a local
        // corroborating point; otherwise the cached runtime-grid cell remains the
        // authority. This avoids coupling action safety to obfuscated GameObject
        // names while keeping fail-closed MapId/CellId/generation validation.
        if (purpose == "SPELL_TARGET_CLICK"
            && _scanner.TryFindExactCellAnchor(
                request.CellId,
                out var spellCellWorld,
                out exactCellAnchorHierarchy,
                out exactCellAnchorDiagnostics)
            && CoordinateProjection.TryProject(spellCellWorld, _camera, responseWindow, out exactCellProjection)
            && exactCellProjection.InsideCameraViewport)
        {
            exactCellAnchorVerified = true;
            exactCellPlanarError = 0.0;
        }

        if (request.TargetEntityId.HasValue)
        {
            if (_lastObservation == null)
                return Failure(request, "TARGET_ENTITY_NOT_OBSERVED", "No current Canonical observation is available for entity validation.");
            targetEntity = _scanner.ResolveActorAnchor(
                _lastObservation,
                request.TargetEntityId.Value,
                request.CellId,
                _camera,
                out targetDiagnostics);
            if (targetEntity == null)
                return Failure(
                    request,
                    "TARGET_ENTITY_NOT_FOUND",
                    $"Unity interaction anchor for entity {request.TargetEntityId.Value} on CellId {request.CellId} could not be proven unambiguously.",
                    targetDiagnostics);
            if (!targetEntity.CellId.HasValue || targetEntity.CellId.Value != request.CellId)
                return Failure(
                    request, "TARGET_ENTITY_CELL_MISMATCH",
                    $"Canonical target entity CellId {targetEntity.CellId?.ToString() ?? "UNKNOWN"} does not match requested CellId {request.CellId}.",
                    targetDiagnostics);

            var positions = _source.SnapshotPositions();
            targetNearestCell = NearestCell(positions, targetEntity.WorldPosition);
            if (targetNearestCell != request.CellId)
                return Failure(
                    request, "TARGET_ENTITY_CELL_MISMATCH",
                    $"Unity target entity is nearest CellId {targetNearestCell}, not requested CellId {request.CellId}.",
                    targetDiagnostics);

            // Entity safety is the conjunction of canonical EntityId->CellId and
            // the live entity's nearest cell on the structurally verified runtime
            // grid. A literal cell::<id> object may corroborate the result, but is
            // not required because that hierarchy is an unstable presentation
            // detail rather than game semantics.
            if (_scanner.TryFindExactCellAnchor(
                    request.CellId,
                    out var exactCellWorld,
                    out exactCellAnchorHierarchy,
                    out exactCellAnchorDiagnostics))
            {
                var exactDx = (double)targetEntity.WorldX - exactCellWorld.x;
                var exactDy = (double)targetEntity.WorldY - exactCellWorld.y;
                exactCellPlanarError = Math.Sqrt(exactDx * exactDx + exactDy * exactDy);
                const double ExactCellAnchorTolerance = 20.0;
                exactCellAnchorVerified = double.IsFinite(exactCellPlanarError.Value)
                    && exactCellPlanarError.Value <= ExactCellAnchorTolerance;
                if (!exactCellAnchorVerified)
                    return Failure(
                        request, "TARGET_ENTITY_CELL_MISMATCH",
                        $"Unity target entity disagrees with the optional exact rendered CellId {request.CellId} anchor by {exactCellPlanarError:F2} world units.",
                        new { target = targetDiagnostics, cell_anchor = exactCellAnchorDiagnostics, exact_cell_planar_error = exactCellPlanarError });
            }

            if (!CoordinateProjection.TryProject(targetEntity.WorldPosition, _camera, responseWindow, out targetProjection)
                || !targetProjection.InsideCameraViewport)
                return Failure(request, "TARGET_ENTITY_OUTSIDE_VIEWPORT", "The exact target Unity entity is not safely projectable in the current viewport.");
        }

        if (!string.Equals(ProjectionSignature(responseWindow), _lastProjectionSignature, StringComparison.Ordinal))
            return Failure(request, "COORDINATE_NOT_READY", "Projection changed during coordinate resolution.");

        return new CoordinateResponse
        {
            RequestId = request.RequestId,
            MapId = request.MapId,
            CellId = request.CellId,
            Status = "RESOLVED",
            ClientX = exactCellProjection?.ClientX ?? cell.ClientX,
            ClientY = exactCellProjection?.ClientY ?? cell.ClientY,
            ScreenX = exactCellProjection?.ScreenX ?? cell.ScreenX,
            ScreenY = exactCellProjection?.ScreenY ?? cell.ScreenY,
            WorldX = cell.WorldX,
            WorldY = cell.WorldY,
            WorldZ = cell.WorldZ,
            StaticallyWalkable = cell.StaticallyWalkable,
            Projectable = cell.Projectable,
            ClickableForMonsterGroup = cell.ClickableForMonsterGroup,
            Purpose = purpose,
            TargetEntityId = request.TargetEntityId,
            EntityAnchorVerified = targetEntity != null && targetNearestCell == request.CellId,
            EntityAnchorCellId = targetEntity?.CellId,
            EntityNearestCellId = targetNearestCell,
            ExactCellAnchorVerified = exactCellAnchorVerified,
            ExactCellAnchorHierarchy = exactCellAnchorHierarchy,
            ExactCellAnchorPlanarError = exactCellPlanarError,
            EntityClientX = targetProjection?.ClientX,
            EntityClientY = targetProjection?.ClientY,
            EntityScreenX = targetProjection?.ScreenX,
            EntityScreenY = targetProjection?.ScreenY,
            CoordinateSpace = "BRIDGE_CLIENT_RELATIVE_WITH_SCREEN_DIAGNOSTIC",
            SourceClientWidth = responseWindow.ClientWidth,
            SourceClientHeight = responseWindow.ClientHeight,
            InsideCameraViewport = targetProjection?.InsideCameraViewport ?? exactCellProjection?.InsideCameraViewport ?? cell.InsideCameraViewport,
            SafeClientPoints = new List<CoordinatePoint> { new(exactCellProjection?.ClientX ?? cell.ClientX ?? 0, exactCellProjection?.ClientY ?? cell.ClientY ?? 0) },
            SafeScreenPoints = new List<CoordinatePoint> { new(exactCellProjection?.ScreenX ?? cell.ScreenX ?? 0, exactCellProjection?.ScreenY ?? cell.ScreenY ?? 0) },
            VerifiedByDofusPicker = false,
            VerifiedByRuntimeGrid = true,
            SourceVerified = true,
            SourceType = cell.SourceType,
            SourceMember = cell.SourceMember,
            LoadedMapId = _loadedMapId,
            MapLoaded = true,
            CellResolved = true,
            Visible = cell.InsideCameraViewport,
            OnScreen = cell.InsideCameraViewport,
            Source = Name,
            MapGeneration = _mapGeneration,
            CoordinateGeneration = _coordinateGeneration,
            WindowFingerprint = _coordinates?.WindowFingerprint,
            CameraFingerprint = _coordinates?.CameraFingerprint,
            Diagnostics = new
            {
                lookup = "cached_map_coordinate",
                no_calculation_performed = true,
                source = _source.Summary(),
                camera = CameraSummary(_camera),
                map_context = _lastMapContext,
                exact_cell = exactCellAnchorVerified ? new
                {
                    cell_id = request.CellId,
                    hierarchy = exactCellAnchorHierarchy,
                    planar_error = exactCellPlanarError,
                    diagnostics = exactCellAnchorDiagnostics,
                    client = exactCellProjection == null ? null : new { x = exactCellProjection.ClientX, y = exactCellProjection.ClientY },
                    screen = exactCellProjection == null ? null : new { x = exactCellProjection.ScreenX, y = exactCellProjection.ScreenY }
                } : null,
                target_entity = targetEntity == null ? null : new
                {
                    entity_id = targetEntity.EntityId,
                    canonical_cell_id = targetEntity.CellId,
                    nearest_grid_cell_id = targetNearestCell,
                    exact_cell_anchor_verified = exactCellAnchorVerified,
                    exact_cell_anchor_hierarchy = exactCellAnchorHierarchy,
                    exact_cell_planar_error = exactCellPlanarError,
                    exact_cell_anchor_diagnostics = exactCellAnchorDiagnostics,
                    hierarchy = targetEntity.Hierarchy,
                    world = new { x = targetEntity.WorldX, y = targetEntity.WorldY, z = targetEntity.WorldZ },
                    client = targetProjection == null ? null : new { x = targetProjection.ClientX, y = targetProjection.ClientY },
                    screen = targetProjection == null ? null : new { x = targetProjection.ScreenX, y = targetProjection.ScreenY },
                    diagnostics = targetDiagnostics
                }
            }
        };
    }

    public MapCoordinatesResponse Coordinates()
    {
        return _coordinates ?? NotReadyCoordinates(CurrentStatus(), _lastError);
    }

    public ObservationResponse Observe(RuntimeObservation observation)
    {
        if (observation == null || !observation.MapId.HasValue || observation.MapId.Value < 0)
            return RejectObservation("INVALID_OBSERVATION", "map_id is required.");
        if (string.IsNullOrWhiteSpace(observation.AccountId)
            || !observation.AccountId.StartsWith("acct-", StringComparison.Ordinal)
            || string.IsNullOrWhiteSpace(observation.ClientInstanceId)
            || !observation.ClientInstanceId.StartsWith("client-", StringComparison.Ordinal)
            || string.IsNullOrWhiteSpace(observation.ObservationSignature)
            || string.IsNullOrWhiteSpace(observation.ObservationEpoch)
            || !observation.CanonicalRevision.HasValue
            || observation.CanonicalRevision.Value < 0)
            return RejectObservation(
                "INVALID_OBSERVATION_PROVENANCE",
                "account_id, client_instance_id, observation_signature, observation_epoch and a non-negative canonical_revision are required.");

        if (!CoordinateProjection.TryGetDofusWindow(out var identityWindow, out var identityWindowError))
            return RejectObservation(
                "OBSERVATION_CLIENT_WINDOW_UNAVAILABLE",
                identityWindowError ?? "The local Dofus window is unavailable for observation identity validation.");
        if (!string.Equals(
                observation.ClientInstanceId,
                LocalClientInstanceId(identityWindow),
                StringComparison.Ordinal))
            return RejectObservation(
                "OBSERVATION_CLIENT_INSTANCE_MISMATCH",
                "Canonical observation client_instance_id does not identify this Dofus window/process generation.");

        var observationEpochChanged = false;
        if (_lastObservation != null)
        {
            if (!string.Equals(observation.AccountId, _lastObservation.AccountId, StringComparison.Ordinal)
                || !string.Equals(observation.ClientInstanceId, _lastObservation.ClientInstanceId, StringComparison.Ordinal))
                return RejectObservation(
                    "OBSERVATION_SCOPE_MISMATCH",
                    "Observation account/client scope does not match the bridge's latched canonical scope.");

            observationEpochChanged = !string.Equals(
                observation.ObservationEpoch,
                _lastObservation.ObservationEpoch,
                StringComparison.Ordinal);

            if (!observationEpochChanged)
            {
                if (observation.CanonicalRevision.Value < _lastObservation.CanonicalRevision.Value)
                    return RejectObservation(
                        "STALE_OBSERVATION_REVISION",
                        "Canonical observation revision moved backwards.");
                if (observation.CanonicalRevision.Value == _lastObservation.CanonicalRevision.Value)
                {
                    if (!string.Equals(
                            observation.ObservationSignature,
                            _lastObservationSignature,
                            StringComparison.Ordinal))
                        return RejectObservation(
                            "OBSERVATION_REVISION_CONFLICT",
                            "The same canonical revision was received with a different observation signature.");
                    // Exact duplicate delivery is idempotent. Do not repeat discovery,
                    // rewrite evidence, increment counters, or mutate projection state.
                    return Observation(false, 0, null);
                }
            }
        }
        var stableWorld = !observation.ActiveFight
                          && string.Equals(observation.MapContext, "WORLD", StringComparison.OrdinalIgnoreCase);
        if (!observation.ActiveFight && !stableWorld)
            return new ObservationResponse
            {
                Status = "WAITING_FOR_STABLE_MAP",
                Accepted = false,
                Error = "A stable world map or an active fight is required."
            };

        var mapId = observation.MapId.Value;
        var changed = !string.Equals(
            _lastObservationSignature,
            observation.ObservationSignature,
            StringComparison.Ordinal);
        var mapContext = observation.ActiveFight ? "FIGHT" : "WORLD";
        var generationChanged = observationEpochChanged
                                || _loadedMapId != mapId
                                || !string.Equals(_lastMapContext, mapContext, StringComparison.Ordinal)
                                || (observation.ActiveFight && _lastCombatId != observation.CombatId);
        if (generationChanged)
        {
            _loadedMapId = mapId;
            _lastMapContext = mapContext;
            _lastCombatId = observation.ActiveFight ? observation.CombatId : null;
            _mapGeneration++;
            ResetMapState();
            changed = true;
            _log?.LogInfo(
                $"Authoritative cell map switched to map {mapId}, context {mapContext}, combat {observation.CombatId}, generation {_mapGeneration}.");
        }

        _lastObservation = observation;
        _lastObservationSignature = observation.ObservationSignature ?? "";
        _lastObservationAtUtc = DateTime.UtcNow.ToString("O");
        _observationsAccepted++;

        var walkableIds = SanitizeWalkableIds(observation.WalkableCellIds);
        if (walkableIds.Count == 0)
        {
            _lastError = "Static walkability data is unavailable for the loaded map.";
            _coordinates = NotReadyCoordinates("COORDINATE_NOT_READY", _lastError);
            return Observation(changed, 0, null);
        }

        if (_source == null || _source.SourceObject == null)
        {
            if (!AuthoritativeCellPositionSource.TryDiscover(
                    out _source,
                    out _sourceDiscoveryDiagnostics,
                    out var discoveryError))
            {
                _lastError = discoveryError;
                _coordinates = NotReadyCoordinates("CELL_POSITION_SOURCE_UNVERIFIED", _lastError);
                var evidence = changed ? WriteEvidence(Array.Empty<ActorRuntimeMatch>()) : null;
                return Observation(changed, 0, evidence);
            }
        }

        IReadOnlyList<Vector3> positions;
        var matches = new List<ActorRuntimeMatch>();

        // R5.172: projection geometry is certified independently from actor
        // identity in both WORLD and FIGHT contexts.  Ankama may rename/move
        // actor GameObjects without changing the authoritative 560-cell grid.
        // The expensive layered resolver runs only when an action actually requires entity identity; passive observation never performs the full reflected scan.
        // Entity identity is therefore resolved only at the action boundary.
        if (!TryPrepareStructuralProjection(out positions, out _camera, out _cameraDiagnostics))
        {
            _coordinates = NotReadyCoordinates("CELL_POSITION_SOURCE_UNVERIFIED", _lastError);
            var evidence = changed ? WriteEvidence(matches) : null;
            return Observation(changed, 0, evidence);
        }

        var exactMatches = _scanner.FindExactActorAnchors(observation, null, out var exactDiagnostics);
        matches.AddRange(exactMatches);
        _actorDiagnostics = new
        {
            mode = observation.ActiveFight
                ? "FIGHT_STRUCTURAL_PROJECTION_ENTITY_DECOUPLED"
                : "WORLD_STRUCTURAL_PROJECTION_ENTITY_DECOUPLED",
            exact = exactDiagnostics,
            matched_actor_count = exactMatches.Count,
            entity_resolution_required_at_action_boundary = true,
            reflected_entity_scan_during_observe = false
        };

        // Exact rendered cell GameObjects are useful diagnostics when Ankama
        // exposes them, but their hierarchy/name is not a stable protocol. The
        // complete reflected 560-cell converter + camera is the projection
        // authority. Keep sampling anchors without allowing a rename to disable
        // the whole automation stack.
        ValidateExactCellAnchors(positions, _camera, observation);

        string evidenceFile = null;
        string windowError = null;
        DofusWindowMetrics window = null;
        if (_source.ProjectionVerified && _camera != null
            && CoordinateProjection.TryGetDofusWindow(out window, out windowError)
            && string.Equals(
                observation.ClientInstanceId,
                LocalClientInstanceId(window),
                StringComparison.Ordinal))
        {
            var signature = ProjectionSignature(window);
            var cachedWalkableIds = _coordinateByCell.Values
                .Where(cell => cell.StaticallyWalkable)
                .Select(cell => cell.CellId)
                .OrderBy(cellId => cellId)
                .ToArray();
            var walkabilityChanged = !walkableIds.SequenceEqual(cachedWalkableIds);
            if (!string.Equals(_coordinates?.Status, "MAP_COORDINATES_READY", StringComparison.Ordinal)
                || !string.Equals(signature, _lastProjectionSignature, StringComparison.Ordinal)
                || walkabilityChanged)
            {
                RebuildCoordinateCache(
                    window,
                    generationChanged
                        ? "map_changed"
                        : walkabilityChanged
                            ? "walkability_changed"
                            : "projection_changed");
            }
        }
        else
        {
            var wrongClientWindow = _source.ProjectionVerified
                && _camera != null
                && window != null
                && !string.Equals(
                    observation.ClientInstanceId,
                    LocalClientInstanceId(window),
                    StringComparison.Ordinal);
            _lastError = wrongClientWindow
                ? "The current Dofus window does not match the canonical observation client instance."
                : _source.ProjectionVerified
                    ? _camera == null
                        ? "The gameplay camera could not be proven from authoritative cell projections."
                        : "The Dofus window could not be read."
                    : _source.LastError;
            if (!string.IsNullOrWhiteSpace(windowError)) _lastError = windowError;
            _coordinates = NotReadyCoordinates(
                _source.ProjectionVerified ? "COORDINATE_NOT_READY" : "CELL_POSITION_SOURCE_UNVERIFIED",
                _lastError);
            _coordinateByCell.Clear();
            if (_source.ProjectionVerified && _camera != null)
                _lastProjectionSignature = null;
        }
        if (changed || !string.Equals(_coordinates.Status, "MAP_COORDINATES_READY", StringComparison.Ordinal))
            evidenceFile = WriteEvidence(matches);

        return Observation(changed, matches.Count, evidenceFile);
    }

    public AutomationStatus AutomationStatus()
    {
        var status = CurrentStatus();
        return new AutomationStatus
        {
            Status = status,
            LoadedMapId = _loadedMapId,
            MapGeneration = _mapGeneration,
            MapContext = _lastObservation?.MapContext,
            CombatId = _lastObservation?.CombatId,
            ProjectionSignature = _coordinates?.ProjectionSignature ?? _lastProjectionSignature,
            WindowFingerprint = _coordinates?.WindowFingerprint,
            CameraFingerprint = _coordinates?.CameraFingerprint,
            CellGeometryFingerprint = _coordinates?.CellGeometryFingerprint,
            SourceClientWidth = _coordinates?.SourceClientWidth,
            SourceClientHeight = _coordinates?.SourceClientHeight,
            LastObservationSignature = _lastObservationSignature,
            LastObservationAtUtc = _lastObservationAtUtc,
            LastObservationEpoch = _lastObservation?.ObservationEpoch,
            LastObservationAccountId = _lastObservation?.AccountId,
            LastObservationClientInstanceId = _lastObservation?.ClientInstanceId,
            LastObservationCanonicalRevision = _lastObservation == null ? null : _lastObservation.CanonicalRevision,
            ObservationsAccepted = _observationsAccepted,
            EvidenceFilesWritten = _evidenceFilesWritten,
            CalibrationSamples = _source?.DistinctValidatedCells ?? 0,
            RequiredSamples = _lastObservation?.ActiveFight == true ? 2 : 0,
            CalibrationReady = _source?.ProjectionVerified == true,
            CoordinateMode = Name,
            DirectReady = status == "MAP_COORDINATES_READY",
            ResolvedCellCount = _coordinates?.GeneratedCoordinateCount ?? 0,
            WalkableCellCount = _coordinates?.WalkableCellCount ?? 0,
            InsideViewportCount = _coordinates?.InsideViewportCount ?? 0,
            SourceVerified = _source?.ProjectionVerified == true,
            EntityAnchored = _source?.Verified == true,
            ValidatedCellCount = _source?.DistinctValidatedCells ?? 0,
            RequiredEntityAnchorCells = 2,
            CellAnchorVerificationSupported = true,
            CellAnchorsVerified = _cellAnchorsVerified,
            ValidatedCellAnchorCount = _validatedCellAnchorCount,
            RequiredCellAnchorCount = RequiredCellAnchorCount,
            CellAnchorDiagnostics = _cellAnchorDiagnostics,
            SourceType = AuthoritativeCellPositionSource.SourceType,
            SourceMember = CurrentSourceMember,
            CoordinateGeneration = _coordinateGeneration,
            EvidenceDirectory = _evidenceDirectory,
            LastMatchDiagnostics = new
            {
                source_discovery = _sourceDiscoveryDiagnostics,
                source_validation = _source?.Summary(),
                camera_selection = _cameraDiagnostics,
                actors = _actorDiagnostics,
                cell_anchors = _cellAnchorDiagnostics,
                last_error = _lastError
            }
        };
    }

    public BridgeHealth Health()
    {
        var status = AutomationStatus();
        return new BridgeHealth
        {
            Status = status.Status,
            Adapter = Name,
            LoadedMapId = status.LoadedMapId,
            MapGeneration = status.MapGeneration,
            MapContext = status.MapContext,
            CombatId = status.CombatId,
            ProjectionSignature = status.ProjectionSignature,
            WindowFingerprint = status.WindowFingerprint,
            CameraFingerprint = status.CameraFingerprint,
            CellGeometryFingerprint = status.CellGeometryFingerprint,
            SourceClientWidth = status.SourceClientWidth,
            SourceClientHeight = status.SourceClientHeight,
            CalibrationSamples = status.CalibrationSamples,
            RequiredSamples = status.RequiredSamples,
            CalibrationReady = status.CalibrationReady,
            CoordinateMode = Name,
            DirectReady = status.DirectReady,
            ResolvedCellCount = status.ResolvedCellCount,
            WalkableCellCount = status.WalkableCellCount,
            InsideViewportCount = status.InsideViewportCount,
            SourceVerified = status.SourceVerified,
            EntityAnchored = status.EntityAnchored,
            ValidatedCellCount = status.ValidatedCellCount,
            RequiredEntityAnchorCells = status.RequiredEntityAnchorCells,
            CellAnchorVerificationSupported = status.CellAnchorVerificationSupported,
            CellAnchorsVerified = status.CellAnchorsVerified,
            ValidatedCellAnchorCount = status.ValidatedCellAnchorCount,
            RequiredCellAnchorCount = status.RequiredCellAnchorCount,
            CellAnchorDiagnostics = status.CellAnchorDiagnostics,
            SourceType = status.SourceType,
            SourceMember = status.SourceMember,
            CoordinateGeneration = status.CoordinateGeneration,
            LastObservationAtUtc = status.LastObservationAtUtc,
            LastObservationEpoch = status.LastObservationEpoch,
            LastObservationAccountId = status.LastObservationAccountId,
            LastObservationClientInstanceId = status.LastObservationClientInstanceId,
            LastObservationCanonicalRevision = status.LastObservationCanonicalRevision
        };
    }

    public DiscoveryResponse Discover()
    {
        var generatedAtUtc = DateTime.UtcNow.ToString("O");
        using var process = System.Diagnostics.Process.GetCurrentProcess();
        var processId = process.Id;
        var processStartTime = process.StartTime.ToFileTimeUtc();
        var payload = new
        {
            generated_at_utc = generatedAtUtc,
            process_id = processId,
            process_start_time = processStartTime,
            observation_epoch = _lastObservation?.ObservationEpoch,
            account_id = _lastObservation?.AccountId,
            client_instance_id = _lastObservation?.ClientInstanceId,
            canonical_revision = _lastObservation?.CanonicalRevision,
            adapter = Name,
            loaded_map_id = _loadedMapId,
            map_generation = _mapGeneration,
            coordinate_generation = _coordinateGeneration,
            automation = AutomationStatus(),
            coordinates = _coordinates,
            source_discovery = _sourceDiscoveryDiagnostics,
            source_validation = _source?.Summary(),
            camera_selection = _cameraDiagnostics,
            camera = CameraSummary(_camera),
            actors = _actorDiagnostics,
            cell_anchors = _cellAnchorDiagnostics,
            scene = _scanner.DiscoverySnapshot(_lastObservation),
            production_fallback = "NONE"
        };
        // Multi-account clients share one BepInEx config directory. A single
        // fixed discovery filename is a last-writer-wins race between Dofus
        // processes and can attach another account's scene evidence to an
        // incident. Persist one immutable-current file per process identity.
        var output = Path.Combine(_rootDirectory, $"DofusCoordinateBridge.discovery.{processId}.json");
        Directory.CreateDirectory(_rootDirectory);
        File.WriteAllText(output, JsonSerializer.Serialize(payload, Json.Options));
        _log?.LogInfo($"Authoritative cell-map discovery report written to {output}.");
        return new DiscoveryResponse
        {
            SourceFile = output,
            GeneratedAtUtc = generatedAtUtc,
            ProcessId = processId,
            ProcessStartTime = processStartTime,
            LoadedMapId = _loadedMapId,
            MapGeneration = _mapGeneration,
            CoordinateGeneration = _coordinateGeneration,
            ObservationEpoch = _lastObservation?.ObservationEpoch,
            AccountId = _lastObservation?.AccountId,
            ClientInstanceId = _lastObservation?.ClientInstanceId,
            CanonicalRevision = _lastObservation?.CanonicalRevision,
            CameraCandidates = Camera.allCameras.Count(camera => camera != null),
            ObjectCandidates = _source == null ? 0 : AuthoritativeCellPositionSource.CellCount
        };
    }

    private void RebuildCoordinateCache(DofusWindowMetrics window, string reason)
    {
        if (_source?.ProjectionVerified != true || _camera == null || !_loadedMapId.HasValue)
        {
            _coordinates = NotReadyCoordinates("COORDINATE_NOT_READY", _lastError);
            return;
        }

        var walkableIds = SanitizeWalkableIds(_lastObservation?.WalkableCellIds);
        var walkableSet = new HashSet<int>(walkableIds);
        var records = new List<MapCoordinateCell>(AuthoritativeCellPositionSource.CellCount);
        for (var cellId = 0; cellId < AuthoritativeCellPositionSource.CellCount; cellId++)
        {
            if (!_source.TryGetWorldPosition(cellId, out var world)
                || !CoordinateProjection.TryProject(world, _camera, window, out var point))
            {
                _lastError = $"Dofus did not return a projectable authoritative position for cell {cellId}.";
                _coordinates = NotReadyCoordinates("COORDINATE_NOT_READY", _lastError);
                _coordinateByCell.Clear();
                _lastProjectionSignature = null;
                return;
            }
            var inside = point.InsideCameraViewport;
            records.Add(new MapCoordinateCell
            {
                CellId = cellId,
                StaticallyWalkable = walkableSet.Contains(cellId),
                Projectable = true,
                ClickableForMonsterGroup = inside,
                WorldX = world.x,
                WorldY = world.y,
                WorldZ = world.z,
                ClientX = point.ClientX,
                ClientY = point.ClientY,
                ScreenX = point.ScreenX,
                ScreenY = point.ScreenY,
                InsideCameraViewport = inside,
                CameraDepth = point.CameraDepth,
                SourceType = AuthoritativeCellPositionSource.SourceType,
                SourceMember = CurrentSourceMember,
                SourceVerified = true
            });
        }

        _coordinateGeneration++;
        _lastProjectionSignature = ProjectionSignature(window);
        _coordinateByCell = records.ToDictionary(record => record.CellId);
        _lastError = null;
        _coordinates = new MapCoordinatesResponse
        {
            Status = "MAP_COORDINATES_READY",
            MapId = _loadedMapId,
            MapGeneration = _mapGeneration,
            CoordinateGeneration = _coordinateGeneration,
            SourceType = AuthoritativeCellPositionSource.SourceType,
            SourceMember = CurrentSourceMember,
            SourceVerified = true,
            WalkableCellCount = walkableIds.Count,
            GeneratedCoordinateCount = records.Count,
            ProjectableCellCount = records.Count(record => record.Projectable),
            MonsterClickableCellCount = records.Count(record => record.ClickableForMonsterGroup),
            InsideViewportCount = records.Count(record => record.InsideCameraViewport),
            CameraName = _camera.name,
            ProjectionSignature = _lastProjectionSignature,
            WindowFingerprint = $"{window.Handle}:{window.ScreenLeft}:{window.ScreenTop}:{window.ClientWidth}:{window.ClientHeight}",
            CameraFingerprint = $"{_camera.GetInstanceID()}:{_camera.pixelWidth}:{_camera.pixelHeight}:{_camera.orthographic}:{_camera.orthographicSize}",
            CellGeometryFingerprint = BuildCellGeometryFingerprint(records, window),
            SourceClientWidth = window.ClientWidth,
            SourceClientHeight = window.ClientHeight,
            GeneratedAtUtc = DateTime.UtcNow.ToString("O"),
            Cells = records,
            Diagnostics = new
            {
                rebuild_reason = reason,
                projection_signature = _lastProjectionSignature,
                source = _source.Summary(),
                camera = CameraSummary(_camera),
                window = window.Summary()
            }
        };
        _log?.LogInfo(
            $"MAP_COORDINATES_READY map={_loadedMapId} cells={records.Count} walkable={walkableIds.Count} clickable={_coordinates.MonsterClickableCellCount} inside={_coordinates.InsideViewportCount} generation={_coordinateGeneration}.");
    }

    private static string BuildCellGeometryFingerprint(IEnumerable<MapCoordinateCell> records, DofusWindowMetrics window)
    {
        // Deliberately hash only client-relative cell geometry plus client size.
        // HWND, desktop origin, camera instance IDs, process IDs, and screen
        // coordinates are account-local and must not prevent safe reuse.
        var builder = new StringBuilder(560 * 16);
        builder.Append(window.ClientWidth).Append('x').Append(window.ClientHeight).Append('|');
        foreach (var cell in records.OrderBy(cell => cell.CellId))
        {
            builder
                .Append(cell.CellId).Append(':')
                .Append(cell.ClientX).Append(',')
                .Append(cell.ClientY).Append(';');
        }

        using var sha256 = SHA256.Create();
        var bytes = Encoding.UTF8.GetBytes(builder.ToString());
        return Convert.ToHexString(sha256.ComputeHash(bytes)).ToLowerInvariant();
    }

    private static ObservationResponse RejectObservation(string status, string error)
    {
        return new ObservationResponse
        {
            Status = status,
            Accepted = false,
            Changed = false,
            Error = error
        };
    }

    private ObservationResponse Observation(bool changed, int actorsMatched, string evidenceFile)
    {
        var status = CurrentStatus();
        return new ObservationResponse
        {
            Status = status,
            Accepted = true,
            Changed = changed,
            LoadedMapId = _loadedMapId,
            MapGeneration = _mapGeneration,
            MapContext = _lastObservation?.MapContext,
            CombatId = _lastObservation?.CombatId,
            ProjectionSignature = _coordinates?.ProjectionSignature ?? _lastProjectionSignature,
            WindowFingerprint = _coordinates?.WindowFingerprint,
            CameraFingerprint = _coordinates?.CameraFingerprint,
            CellGeometryFingerprint = _coordinates?.CellGeometryFingerprint,
            SourceClientWidth = _coordinates?.SourceClientWidth,
            SourceClientHeight = _coordinates?.SourceClientHeight,
            ActorsObserved = _lastObservation?.Actors?.Count ?? 0,
            ActorsMatched = actorsMatched,
            CalibrationSamples = _source?.DistinctValidatedCells ?? 0,
            RequiredSamples = _lastObservation?.ActiveFight == true ? 2 : 0,
            CalibrationReady = _source?.ProjectionVerified == true,
            CoordinateMode = Name,
            DirectReady = status == "MAP_COORDINATES_READY",
            ResolvedCellCount = _coordinates?.GeneratedCoordinateCount ?? 0,
            WalkableCellCount = _coordinates?.WalkableCellCount ?? 0,
            InsideViewportCount = _coordinates?.InsideViewportCount ?? 0,
            SourceVerified = _source?.ProjectionVerified == true,
            EntityAnchored = _source?.Verified == true,
            ValidatedCellCount = _source?.DistinctValidatedCells ?? 0,
            RequiredEntityAnchorCells = 2,
            CellAnchorVerificationSupported = true,
            CellAnchorsVerified = _cellAnchorsVerified,
            ValidatedCellAnchorCount = _validatedCellAnchorCount,
            RequiredCellAnchorCount = RequiredCellAnchorCount,
            CellAnchorDiagnostics = _cellAnchorDiagnostics,
            SourceType = AuthoritativeCellPositionSource.SourceType,
            SourceMember = CurrentSourceMember,
            CoordinateGeneration = _coordinateGeneration,
            EvidenceFile = evidenceFile,
            Error = status == "MAP_COORDINATES_READY" ? null : _lastError,
            Diagnostics = new
            {
                source_discovery = _sourceDiscoveryDiagnostics,
                source_validation = _source?.Summary(),
                camera_selection = _cameraDiagnostics,
                actors = _actorDiagnostics,
                cell_anchors = _cellAnchorDiagnostics
            }
        };
    }

    private bool TryPrepareStructuralProjection(
        out IReadOnlyList<Vector3> positions,
        out Camera camera,
        out object diagnostics)
    {
        positions = Array.Empty<Vector3>();
        camera = null;
        diagnostics = null;
        if (_source == null)
        {
            _lastError = "The Dofus grid source is unavailable.";
            return false;
        }

        var directPositions = _source.SnapshotPositionsForMode("DIRECT_DOFUS_WORLD");
        var directCamera = CoordinateProjection.SelectGameplayCamera(
            directPositions,
            _source.SourceObject,
            out var directCameraDiagnostics);
        var directScore = ProjectionScore(directCamera, directPositions);

        var transformedPositions = _source.SnapshotPositionsForMode("GENERATOR_TRANSFORM_POINT");
        var transformedCamera = CoordinateProjection.SelectGameplayCamera(
            transformedPositions,
            _source.SourceObject,
            out var transformedCameraDiagnostics);
        var transformedScore = ProjectionScore(transformedCamera, transformedPositions);

        var useDirect = directScore >= transformedScore;
        var selectedMode = useDirect ? "DIRECT_DOFUS_WORLD" : "GENERATOR_TRANSFORM_POINT";
        var selectedScore = useDirect ? directScore : transformedScore;
        positions = useDirect ? directPositions : transformedPositions;
        camera = useDirect ? directCamera : transformedCamera;
        diagnostics = new
        {
            mode = "STRUCTURAL_GRID_PROJECTION",
            direct_score = directScore,
            transformed_score = transformedScore,
            selected_mode = selectedMode,
            minimum_score = 40,
            direct_camera = directCameraDiagnostics,
            transformed_camera = transformedCameraDiagnostics
        };
        if (camera == null || selectedScore < 40)
        {
            _lastError = $"No projection candidate placed enough Dofus cells in the gameplay viewport (best={selectedScore}).";
            return false;
        }
        if (!_source.SelectStructuralProjectionMode(
                selectedMode,
                $"grid-camera-viewport-score:{selectedScore}"))
        {
            _lastError = _source.LastError;
            return false;
        }
        _lastError = null;
        return true;
    }

    private bool ValidateExactCellAnchors(
        IReadOnlyList<Vector3> positions,
        Camera camera,
        RuntimeObservation observation)
    {
        _cellAnchorsVerified = false;
        _validatedCellAnchorCount = 0;
        _cellAnchorDiagnostics = null;
        if (positions == null || positions.Count != AuthoritativeCellPositionSource.CellCount || camera == null)
        {
            _lastError = "Exact rendered-cell validation requires the complete 560-cell grid and gameplay camera.";
            return false;
        }
        if (!CoordinateProjection.TryGetDofusWindow(out var window, out var windowError))
        {
            _lastError = windowError ?? "Dofus window is unavailable for exact rendered-cell validation.";
            return false;
        }

        var candidateIds = new List<int>();
        void AddCandidate(int? cellId)
        {
            if (!cellId.HasValue || cellId.Value < 0 || cellId.Value >= AuthoritativeCellPositionSource.CellCount)
                return;
            if (!candidateIds.Contains(cellId.Value)) candidateIds.Add(cellId.Value);
        }

        AddCandidate(observation?.PlayerCellId);
        foreach (var actor in observation?.Actors ?? new List<ObservationActor>())
            AddCandidate(actor?.CellId);

        var walkable = SanitizeWalkableIds(observation?.WalkableCellIds);
        if (walkable.Count > 0)
        {
            foreach (var fraction in new[] { 0.15, 0.35, 0.55, 0.75, 0.90 })
            {
                var index = Math.Min(walkable.Count - 1, Math.Max(0, (int)Math.Round((walkable.Count - 1) * fraction)));
                AddCandidate(walkable[index]);
            }
        }
        foreach (var fallback in new[] { 140, 280, 420 }) AddCandidate(fallback);

        var samples = new List<object>();
        foreach (var cellId in candidateIds.Take(12))
        {
            var sourceWorld = positions[cellId];
            if (float.IsNaN(sourceWorld.x) || float.IsInfinity(sourceWorld.x)
                || float.IsNaN(sourceWorld.y) || float.IsInfinity(sourceWorld.y)
                || float.IsNaN(sourceWorld.z) || float.IsInfinity(sourceWorld.z))
            {
                samples.Add(new { cell_id = cellId, accepted = false, reason = "SOURCE_POSITION_NONFINITE" });
                continue;
            }
            if (!_scanner.TryFindExactCellAnchor(cellId, out var anchorWorld, out var hierarchy, out var anchorDiagnostics))
            {
                samples.Add(new { cell_id = cellId, accepted = false, reason = "EXACT_CELL_ANCHOR_NOT_FOUND", diagnostics = anchorDiagnostics });
                continue;
            }

            var nearestCell = NearestCell(positions, anchorWorld);
            var dx = (double)sourceWorld.x - anchorWorld.x;
            var dy = (double)sourceWorld.y - anchorWorld.y;
            var planarError = Math.Sqrt(dx * dx + dy * dy);
            var sourceProjected = CoordinateProjection.TryProject(sourceWorld, camera, window, out var sourcePoint);
            var anchorProjected = CoordinateProjection.TryProject(anchorWorld, camera, window, out var anchorPoint);
            double? clientError = null;
            if (sourceProjected && anchorProjected)
            {
                var cdx = (double)sourcePoint.ClientX - anchorPoint.ClientX;
                var cdy = (double)sourcePoint.ClientY - anchorPoint.ClientY;
                clientError = Math.Sqrt(cdx * cdx + cdy * cdy);
            }
            var accepted = nearestCell == cellId
                           && double.IsFinite(planarError)
                           && planarError <= MaximumCellAnchorPlanarError
                           && sourceProjected && anchorProjected
                           && sourcePoint.InsideCameraViewport
                           && anchorPoint.InsideCameraViewport;
            if (accepted) _validatedCellAnchorCount++;
            samples.Add(new
            {
                cell_id = cellId,
                accepted,
                hierarchy,
                nearest_grid_cell_id = nearestCell,
                planar_error = planarError,
                maximum_planar_error = MaximumCellAnchorPlanarError,
                source_inside_viewport = sourceProjected && sourcePoint.InsideCameraViewport,
                anchor_inside_viewport = anchorProjected && anchorPoint.InsideCameraViewport,
                client_projection_error = clientError,
                source_world = new { x = sourceWorld.x, y = sourceWorld.y, z = sourceWorld.z },
                anchor_world = new { x = anchorWorld.x, y = anchorWorld.y, z = anchorWorld.z },
                diagnostics = anchorDiagnostics
            });
            if (_validatedCellAnchorCount >= RequiredCellAnchorCount && samples.Count >= 3)
                break;
        }

        _cellAnchorsVerified = _validatedCellAnchorCount >= RequiredCellAnchorCount;
        _cellAnchorDiagnostics = new
        {
            status = _cellAnchorsVerified ? "EXACT_CELL_ANCHORS_VERIFIED" : "EXACT_CELL_ANCHORS_INSUFFICIENT",
            required = RequiredCellAnchorCount,
            validated = _validatedCellAnchorCount,
            candidate_count = candidateIds.Count,
            maximum_planar_error = MaximumCellAnchorPlanarError,
            samples = samples.ToArray()
        };
        if (!_cellAnchorsVerified)
        {
            _lastError = $"Validated {_validatedCellAnchorCount}/{RequiredCellAnchorCount} exact rendered cell anchors against the authoritative grid.";
            return false;
        }
        _lastError = null;
        return true;
    }

    private static int ProjectionScore(Camera camera, IReadOnlyList<Vector3> positions)
    {
        if (camera == null || positions == null) return 0;
        var score = 0;
        foreach (var world in positions)
        {
            if (float.IsNaN(world.x) || float.IsInfinity(world.x)
                || float.IsNaN(world.y) || float.IsInfinity(world.y)
                || float.IsNaN(world.z) || float.IsInfinity(world.z))
                continue;
            try
            {
                var viewport = camera.WorldToViewportPoint(world);
                if (viewport.z > 0f
                    && viewport.x >= -0.05f && viewport.x <= 1.05f
                    && viewport.y >= -0.05f && viewport.y <= 1.05f)
                    score++;
            }
            catch { }
        }
        return score;
    }

    private string CurrentStatus()
    {
        if (!_loadedMapId.HasValue) return "WAITING_FOR_DECODER";
        if (_source == null) return "DISCOVERING_CELL_POSITION_SOURCE";
        if (!_source.ProjectionVerified) return "CELL_POSITION_SOURCE_UNVERIFIED";
        if (_camera == null) return "CAMERA_NOT_FOUND";
        if (CoordinateTableIsReady()) return "MAP_COORDINATES_READY";
        return "GENERATING_MAP_COORDINATES";
    }

    private bool CoordinateTableIsReady()
    {
        if (!string.Equals(_coordinates?.Status, "MAP_COORDINATES_READY", StringComparison.Ordinal))
            return false;
        return _coordinates.TotalMapCells == AuthoritativeCellPositionSource.CellCount
               && _coordinates.GeneratedCoordinateCount == AuthoritativeCellPositionSource.CellCount
               && _coordinates.ProjectableCellCount == AuthoritativeCellPositionSource.CellCount
               && _coordinateByCell.Count == AuthoritativeCellPositionSource.CellCount
               && (_coordinates.Cells?.Count ?? 0) == AuthoritativeCellPositionSource.CellCount;
    }

    private void ResetMapState()
    {
        _source = null;
        _camera = null;
        _coordinates = NotReadyCoordinates("DISCOVERING_CELL_POSITION_SOURCE", null);
        _coordinateByCell.Clear();
        _lastProjectionSignature = null;
        _lastError = null;
        _sourceDiscoveryDiagnostics = null;
        _cameraDiagnostics = null;
        _actorDiagnostics = null;
        _cellAnchorsVerified = false;
        _validatedCellAnchorCount = 0;
        _cellAnchorDiagnostics = null;
    }

    private MapCoordinatesResponse NotReadyCoordinates(string status, string error)
    {
        return new MapCoordinatesResponse
        {
            Status = status,
            MapId = _loadedMapId,
            MapGeneration = _mapGeneration,
            CoordinateGeneration = _coordinateGeneration,
            SourceType = AuthoritativeCellPositionSource.SourceType,
            SourceMember = CurrentSourceMember,
            SourceVerified = _source?.ProjectionVerified == true,
            WalkableCellCount = SanitizeWalkableIds(_lastObservation?.WalkableCellIds).Count,
            Error = error,
            Cells = new List<MapCoordinateCell>()
        };
    }


    private FightEntryResponse FightEntryFailure(
        FightEntryRequest request,
        string status,
        string error,
        object diagnostics = null)
    {
        return new FightEntryResponse
        {
            RequestId = request?.RequestId ?? "",
            MapId = request?.MapId ?? 0,
            LaunchCellId = request?.LaunchCellId ?? -1,
            FightInstanceId = request?.FightInstanceId ?? 0,
            Status = status,
            Error = error,
            LoadedMapId = _loadedMapId,
            MapGeneration = _mapGeneration,
            CoordinateGeneration = _coordinateGeneration,
            SourceVerified = _source?.ProjectionVerified == true,
            Diagnostics = diagnostics ?? new
            {
                strategy = "fight_entry_fail_closed",
                no_ground_cell_fallback = true,
                source = _source?.Summary()
            }
        };
    }

    private CoordinateResponse Failure(CoordinateRequest request, string status, string error, object failureDiagnostics = null)
    {
        return new CoordinateResponse
        {
            RequestId = request.RequestId,
            MapId = request.MapId,
            CellId = request.CellId,
            Status = status,
            Error = error,
            LoadedMapId = _loadedMapId,
            MapLoaded = _loadedMapId.HasValue,
            Source = Name,
            SourceVerified = _source?.ProjectionVerified == true,
            SourceType = AuthoritativeCellPositionSource.SourceType,
            SourceMember = CurrentSourceMember,
            MapGeneration = _mapGeneration,
            CoordinateGeneration = _coordinateGeneration,
            Diagnostics = new
            {
                lookup = "cached_map_coordinate",
                no_calculation_performed = true,
                source = _source?.Summary(),
                actors = _actorDiagnostics,
                failure = failureDiagnostics
            }
        };
    }

    private string WriteEvidence(IReadOnlyList<ActorRuntimeMatch> matches)
    {
        try
        {
            Directory.CreateDirectory(_evidenceDirectory);
            var output = Path.Combine(
                _evidenceDirectory,
                $"authoritative-cell-map-{DateTime.UtcNow:yyyyMMdd-HHmmss-fff}-map-{_loadedMapId}-generation-{_mapGeneration}.json");
            var payload = new
            {
                generated_at_utc = DateTime.UtcNow.ToString("O"),
                coordinate_mode = Name,
                map_id = _loadedMapId,
                map_generation = _mapGeneration,
                coordinate_generation = _coordinateGeneration,
                observation = _lastObservation,
                status = CurrentStatus(),
                source_discovery = _sourceDiscoveryDiagnostics,
                source_validation = _source?.Summary(),
                camera_selection = _cameraDiagnostics,
                camera = CameraSummary(_camera),
                actors = (matches ?? Array.Empty<ActorRuntimeMatch>()).Take(100).Select(MatchSummary).ToArray(),
                cell_anchors = _cellAnchorDiagnostics,
                coordinate_summary = new
                {
                    status = _coordinates?.Status,
                    walkable_cell_count = _coordinates?.WalkableCellCount,
                    generated_coordinate_count = _coordinates?.GeneratedCoordinateCount,
                    inside_viewport_count = _coordinates?.InsideViewportCount
                },
                last_error = _lastError,
                production_fallback = "NONE"
            };
            File.WriteAllText(output, JsonSerializer.Serialize(payload, Json.Options));
            _evidenceFilesWritten++;
            return output;
        }
        catch (Exception error)
        {
            _log?.LogWarning("Could not write authoritative cell-map evidence: " + error.Message);
            return null;
        }
    }

    private static int NearestCell(IReadOnlyList<Vector3> positions, Vector3 observed)
    {
        var selected = -1;
        var selectedDistance = double.PositiveInfinity;
        for (var cellId = 0; cellId < (positions?.Count ?? 0); cellId++)
        {
            var candidate = positions[cellId];
            var dx = candidate.x - observed.x;
            var dy = candidate.y - observed.y;
            var distance = dx * dx + dy * dy;
            if (double.IsNaN(distance) || double.IsInfinity(distance) || distance >= selectedDistance)
                continue;
            selectedDistance = distance;
            selected = cellId;
        }
        return selected;
    }

    private string ProjectionSignature(DofusWindowMetrics window) =>
        $"{_source?.TransformSignature()}::{CoordinateProjection.ProjectionSignature(_camera, window)}";

    private static List<int> SanitizeWalkableIds(IEnumerable<int> values) =>
        (values ?? Array.Empty<int>())
        .Where(cellId => cellId >= 0 && cellId < AuthoritativeCellPositionSource.CellCount)
        .Distinct()
        .OrderBy(cellId => cellId)
        .ToList();

    private static object CameraSummary(Camera camera)
    {
        if (camera == null) return null;
        try
        {
            var rect = camera.pixelRect;
            return new
            {
                name = camera.name,
                instance_id = camera.GetInstanceID(),
                enabled = camera.enabled,
                orthographic = camera.orthographic,
                depth = camera.depth,
                culling_mask = camera.cullingMask,
                pixel_rect = new { x = rect.x, y = rect.y, width = rect.width, height = rect.height },
                target_texture = camera.targetTexture == null
                    ? null
                    : new
                    {
                        name = camera.targetTexture.name,
                        width = camera.targetTexture.width,
                        height = camera.targetTexture.height
                    },
                position = new
                {
                    x = camera.transform.position.x,
                    y = camera.transform.position.y,
                    z = camera.transform.position.z
                }
            };
        }
        catch
        {
            return new { name = camera.name, status = "CAMERA_SUMMARY_UNAVAILABLE" };
        }
    }

    private static object MatchSummary(ActorRuntimeMatch match) => match == null ? null : new
    {
        actor_id = match.ActorId,
        entity_id = match.EntityId,
        cell_id = match.CellId,
        is_player_controlled = match.IsPlayerControlled,
        hierarchy = match.Hierarchy,
        world = new { x = match.WorldX, y = match.WorldY, z = match.WorldZ },
        confidence = match.Confidence
    };
}
