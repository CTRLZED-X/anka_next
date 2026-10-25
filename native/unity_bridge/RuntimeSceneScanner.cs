using System.Reflection;
using System.Text.Json.Serialization;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace DofusCoordinateBridge;

public sealed class ActorRuntimeMatch
{
    public long? ActorId { get; set; }
    public long? EntityId { get; set; }
    public int? CellId { get; set; }
    public int? CellFloor { get; set; }
    public bool IsPlayerControlled { get; set; }
    public string Side { get; set; }
    public string ActorType { get; set; }
    public string Hierarchy { get; set; }
    public string ComponentType { get; set; }
    public float WorldX { get; set; }
    public float WorldY { get; set; }
    public float WorldZ { get; set; }
    public double Score { get; set; }
    public double Confidence { get; set; }
    public bool OnScreen { get; set; }
    public float ScreenX { get; set; }
    public float ScreenY { get; set; }
    public string[] MatchedMembers { get; set; } = Array.Empty<string>();
    public string[] ComponentHints { get; set; } = Array.Empty<string>();

    [JsonIgnore]
    public Vector3 WorldPosition => new(WorldX, WorldY, WorldZ);
}


public sealed class FightEntryRuntimeMatch
{
    public string Hierarchy { get; set; }
    public string ComponentType { get; set; }
    public float WorldX { get; set; }
    public float WorldY { get; set; }
    public float WorldZ { get; set; }
    public double Score { get; set; }
    public double Confidence { get; set; }
    public double LaunchCellPlanarDistance { get; set; }
    public bool OnScreen { get; set; }
    public string[] Evidence { get; set; } = Array.Empty<string>();

    [JsonIgnore]
    public Vector3 WorldPosition => new(WorldX, WorldY, WorldZ);
}

public sealed class FightEntryRuntimeProbe
{
    public string Hierarchy { get; set; }
    public string ComponentType { get; set; }
    public int NearestCellId { get; set; }
    public double NearestCellPlanarDistance { get; set; }
    public bool SemanticHint { get; set; }
    public string[] NumericMembers { get; set; } = Array.Empty<string>();
    public string[] ComponentHints { get; set; } = Array.Empty<string>();
}

public sealed class VisualTransformSnapshot
{
    public string SceneName { get; set; }
    public string Hierarchy { get; set; }
    public int Depth { get; set; }
    public float WorldX { get; set; }
    public float WorldY { get; set; }
    public float WorldZ { get; set; }
    public float ScreenX { get; set; }
    public float ScreenY { get; set; }
    public bool OnScreen { get; set; }
    public bool VisualHint { get; set; }
    public bool UiHint { get; set; }
    public string[] ComponentHints { get; set; } = Array.Empty<string>();
    [JsonIgnore]
    public Vector3 WorldPosition => new(WorldX, WorldY, WorldZ);
}

internal sealed class NumericMember
{
    public string Path { get; set; }
    public long Value { get; set; }
}

internal sealed class ComponentSnapshot
{
    public Component Component { get; set; }
    public string SceneName { get; set; }
    public string Hierarchy { get; set; }
    public int Depth { get; set; }
    public string ComponentType { get; set; }
    public string[] ComponentHints { get; set; }
    public bool Active { get; set; }
    public bool VisualHint { get; set; }
    public bool UiHint { get; set; }
    public Vector3 WorldPosition { get; set; }
    public List<NumericMember> Numbers { get; set; }
}

internal sealed class RuntimeSceneScan
{
    public List<ComponentSnapshot> Components { get; set; } = new();
    public List<VisualTransformSnapshot> VisualTransforms { get; set; } = new();
    public List<object> Scenes { get; set; } = new();
    public int TraversedGameObjects { get; set; }
    public int ResourceFallbackObjects { get; set; }
    public int ReflectedComponents { get; set; }
}

public sealed class RuntimeSceneScanner
{
    private const int MaxGameObjects = 24000;
    private const int MaxComponents = 40000;
    private const int MaxVisualTransforms = 40000;
    private const int MaxReflectedComponents = 2500;
    private const int MaxMembersPerObject = 96;
    private const int MaxNestedDepth = 2;
    private static readonly Dictionary<Type, FieldInfo[]> FieldCache = new();
    private static readonly Dictionary<Type, PropertyInfo[]> PropertyCache = new();
    private static readonly object ReflectionCacheLock = new();
    private RuntimeSceneScan _fightEntryScanCache;
    private string _fightEntryScanCacheKey;
    private DateTime _fightEntryScanCacheAtUtc = DateTime.MinValue;

    public Camera SelectGameplayCamera()
    {
        Camera best = null;
        var bestScore = double.NegativeInfinity;
        foreach (var camera in Camera.allCameras)
        {
            if (camera == null || !camera.enabled) continue;
            var name = ((camera.name ?? "") + " " + (camera.GetType().FullName ?? "")).ToLowerInvariant();
            var score = camera.pixelWidth * camera.pixelHeight / 100000.0;
            if (name.Contains("ui") || name.Contains("overlay") || name.Contains("hud")) score -= 100;
            if (name.Contains("game") || name.Contains("main") || name.Contains("world") || name.Contains("render")) score += 20;
            if (camera.targetTexture == null) score += 10;
            score -= Math.Abs(camera.depth) * 0.05;
            if (score > bestScore)
            {
                best = camera;
                bestScore = score;
            }
        }
        return best ?? Camera.main;
    }

    public bool TryFindExactCellAnchor(
        int cellId,
        out Vector3 world,
        out string hierarchy,
        out object diagnostics)
    {
        world = default;
        hierarchy = null;
        diagnostics = null;
        if (cellId < 0 || cellId >= 560)
        {
            diagnostics = new { status = "CELL_ID_OUT_OF_RANGE", cell_id = cellId };
            return false;
        }

        var expectedName = $"cell::{cellId}";
        GameObject selected = null;
        var method = "GameObject.Find";
        try { selected = GameObject.Find(expectedName); }
        catch { selected = null; }

        // GameObject.Find only sees active objects and can be ambiguous if multiple
        // scenes contain the same short name. Prefer the exact GraphicCells object
        // when the resource fallback is available.
        if (selected == null || !IsGraphicCell(selected))
        {
            method = "Resources.FindObjectsOfTypeAll";
            try
            {
                selected = Resources.FindObjectsOfTypeAll<GameObject>()
                    .Where(candidate => candidate != null
                                        && string.Equals(candidate.name, expectedName, StringComparison.Ordinal))
                    .OrderByDescending(candidate => IsGraphicCell(candidate))
                    .ThenByDescending(candidate => candidate.activeInHierarchy)
                    .FirstOrDefault();
            }
            catch { selected = null; }
        }

        if (selected != null && (!selected.activeInHierarchy || !IsGraphicCell(selected)))
        {
            diagnostics = new
            {
                status = "CELL_GAMEOBJECT_NOT_LIVE_GRAPHIC",
                cell_id = cellId,
                expected_name = expectedName,
                method,
                active = selected.activeInHierarchy,
                graphic_cells = IsGraphicCell(selected)
            };
            selected = null;
        }

        if (selected == null)
        {
            diagnostics = diagnostics ?? new
            {
                status = "CELL_GAMEOBJECT_NOT_FOUND",
                cell_id = cellId,
                expected_name = expectedName
            };
            return false;
        }

        try
        {
            var transform = selected.transform;
            world = transform.position;
            hierarchy = HierarchyPath(transform, selected.scene.name ?? "DofusUnity");
            if (!IsFinite(world))
            {
                diagnostics = new
                {
                    status = "CELL_TRANSFORM_INVALID",
                    cell_id = cellId,
                    expected_name = expectedName,
                    hierarchy,
                    world = Vector(world)
                };
                return false;
            }

            diagnostics = new
            {
                status = "EXACT_CELL_GAMEOBJECT_MATCH",
                method,
                cell_id = cellId,
                expected_name = expectedName,
                hierarchy,
                graphic_cells = IsGraphicCell(selected),
                world = Vector(world)
            };
            return true;
        }
        catch (Exception error)
        {
            diagnostics = new
            {
                status = "CELL_TRANSFORM_READ_FAILED",
                cell_id = cellId,
                expected_name = expectedName,
                error = error.Message
            };
            return false;
        }
    }

    private static bool IsGraphicCell(GameObject candidate)
    {
        if (candidate == null) return false;
        try
        {
            var hierarchy = HierarchyPath(candidate.transform, candidate.scene.name ?? "DofusUnity");
            return hierarchy.IndexOf("/GraphicCells/", StringComparison.OrdinalIgnoreCase) >= 0;
        }
        catch
        {
            return false;
        }
    }

    public ActorRuntimeMatch FindPlayerAnchor(
        RuntimeObservation observation,
        Camera camera,
        out object diagnostics)
    {
        diagnostics = null;
        if (observation == null)
        {
            diagnostics = new { status = "NO_OBSERVATION" };
            return null;
        }

        var actor = (observation.Actors ?? new List<ObservationActor>())
            .FirstOrDefault(item => item != null
                                    && item.IsPlayerControlled
                                    && item.CellId.HasValue
                                    && item.CellId.Value >= 0
                                    && item.CellId.Value < 560)
                    ?? (observation.Actors ?? new List<ObservationActor>())
                        .FirstOrDefault(item => item != null
                                                && item.EntityId.HasValue
                                                && observation.PlayerEntityId.HasValue
                                                && item.EntityId == observation.PlayerEntityId
                                                && item.CellId.HasValue);
        if (actor == null || !actor.CellId.HasValue)
        {
            diagnostics = new { status = "PLAYER_ACTOR_NOT_IN_OBSERVATION" };
            return null;
        }

        var entityId = actor.EntityId ?? observation.PlayerEntityId;
        if (!entityId.HasValue || entityId.Value <= 0)
        {
            diagnostics = new
            {
                status = "PLAYER_ENTITY_ID_UNAVAILABLE",
                actor_id = actor.ActorId,
                cell_id = actor.CellId
            };
            return null;
        }

        var expectedNames = new[]
        {
            $"entity_character_{entityId.Value}",
            $"Entity {entityId.Value}"
        };
        var candidates = new List<GameObject>();
        var methods = new List<string>();
        try
        {
            foreach (var candidate in Resources.FindObjectsOfTypeAll<GameObject>())
            {
                if (candidate == null) continue;
                if (!expectedNames.Any(name => string.Equals(candidate.name, name, StringComparison.Ordinal))) continue;
                candidates.Add(candidate);
                methods.Add($"Resources.FindObjectsOfTypeAll:{candidate.name}");
            }
        }
        catch { }
        if (candidates.Count == 0)
        {
            foreach (var expectedName in expectedNames)
            {
                try
                {
                    var direct = GameObject.Find(expectedName);
                    if (direct == null) continue;
                    candidates.Add(direct);
                    methods.Add($"GameObject.Find:{expectedName}");
                }
                catch { }
            }
        }

        var active = candidates
            .Where(candidate => candidate != null && candidate.activeInHierarchy)
            .GroupBy(candidate =>
            {
                try { return candidate.GetInstanceID(); }
                catch { return 0; }
            })
            .Select(group => group.First())
            .ToList();
        if (active.Count != 1)
        {
            diagnostics = new
            {
                status = active.Count == 0 ? "PLAYER_GAMEOBJECT_NOT_FOUND" : "PLAYER_GAMEOBJECT_AMBIGUOUS",
                expected_names = expectedNames,
                entity_id = entityId,
                cell_id = actor.CellId,
                active_match_count = active.Count,
                methods = methods.Take(20).ToArray(),
                candidates = active.Take(10).Select(candidate => new
                {
                    name = candidate.name,
                    hierarchy = HierarchyPath(candidate.transform, candidate.scene.name ?? "DofusUnity")
                }).ToArray()
            };
            return null;
        }

        var selected = active[0];
        Transform transform;
        Vector3 world;
        string hierarchy;
        try
        {
            transform = selected.transform;
            world = transform.position;
            hierarchy = HierarchyPath(transform, selected.scene.name ?? "DofusUnity");
        }
        catch (Exception error)
        {
            diagnostics = new
            {
                status = "PLAYER_TRANSFORM_READ_FAILED",
                selected_name = selected.name,
                error = error.Message
            };
            return null;
        }

        if (!IsFinite(world))
        {
            diagnostics = new
            {
                status = "PLAYER_TRANSFORM_INVALID",
                selected_name = selected.name,
                world = Vector(world)
            };
            return null;
        }

        var onScreen = TryProject(camera, world, out var screenPoint);
        var result = new ActorRuntimeMatch
        {
            ActorId = actor.ActorId ?? observation.PlayerActorId,
            EntityId = entityId,
            CellId = actor.CellId ?? observation.PlayerCellId,
            CellFloor = actor.CellFloor,
            IsPlayerControlled = true,
            Side = actor.Side,
            ActorType = actor.ActorType,
            Hierarchy = hierarchy,
            ComponentType = "UnityEngine.GameObject/Transform",
            WorldX = world.x,
            WorldY = world.y,
            WorldZ = world.z,
            Score = 1000.0,
            Confidence = 0.99,
            OnScreen = onScreen,
            ScreenX = screenPoint.x,
            ScreenY = screenPoint.y,
            MatchedMembers = new[] { "gameobject_name:exact_signed_player_root" },
            ComponentHints = Array.Empty<string>()
        };
        diagnostics = new
        {
            status = "EXACT_PLAYER_GAMEOBJECT_MATCH",
            strategy = "exact_signed_player_gameobject_names",
            methods = methods.Take(20).ToArray(),
            selected_name = selected.name,
            hierarchy,
            actor_id = result.ActorId,
            entity_id = result.EntityId,
            cell_id = result.CellId,
            cell_floor = result.CellFloor,
            world = Vector(world),
            screen = new { x = result.ScreenX, y = result.ScreenY },
            on_screen = onScreen
        };
        return result;
    }


    public List<ActorRuntimeMatch> FindExactActorAnchors(
        RuntimeObservation observation,
        Camera camera,
        out object diagnostics)
    {
        var matches = new List<ActorRuntimeMatch>();
        var details = new List<object>();
        var actors = (observation?.Actors ?? new List<ObservationActor>())
            .Where(actor => actor != null
                            && actor.EntityId.HasValue
                            && actor.EntityId.Value != 0
                            && actor.CellId.HasValue
                            && actor.CellId.Value >= 0
                            && actor.CellId.Value < 560)
            .ToList();

        // Build the exact-name index once per resolution pass. The old code
        // performed Resources.FindObjectsOfTypeAll<GameObject>() separately for
        // every actor, multiplying a full Unity object scan by the number of
        // visible entities.  Exact identity still remains fail-closed: every
        // actor must have exactly one active root after instance-id deduplication.
        var expectedNameSet = new HashSet<string>(StringComparer.Ordinal);
        foreach (var actor in actors)
        {
            expectedNameSet.Add($"entity_character_{actor.EntityId.Value}");
            expectedNameSet.Add($"Entity {actor.EntityId.Value}");
        }

        var indexedByName = new Dictionary<string, List<GameObject>>(StringComparer.Ordinal);
        var globalScanSucceeded = false;
        var scannedGameObjectCount = 0;
        try
        {
            foreach (var candidate in Resources.FindObjectsOfTypeAll<GameObject>())
            {
                scannedGameObjectCount++;
                if (candidate == null || !expectedNameSet.Contains(candidate.name)) continue;
                if (!indexedByName.TryGetValue(candidate.name, out var bucket))
                {
                    bucket = new List<GameObject>();
                    indexedByName[candidate.name] = bucket;
                }
                bucket.Add(candidate);
            }
            globalScanSucceeded = true;
        }
        catch
        {
            globalScanSucceeded = false;
        }

        foreach (var actor in actors)
        {
            // Dofus has used at least two stable active-root naming schemes:
            // older builds expose entity_character_<id>, while the current
            // Unity scene observed in R5.185 exposes `Entity <signed-id>`.
            // Exact leaf equality is strong identity evidence; ancestor name
            // matching is deliberately forbidden because `/entities` is shared.
            var expectedNames = new[]
            {
                $"entity_character_{actor.EntityId.Value}",
                $"Entity {actor.EntityId.Value}"
            };
            var candidates = new List<GameObject>();
            var methods = new List<string>();

            foreach (var expectedName in expectedNames)
            {
                if (indexedByName.TryGetValue(expectedName, out var indexed))
                {
                    candidates.AddRange(indexed);
                    methods.Add($"Resources.FindObjectsOfTypeAll:{expectedName}");
                }
                // If the global resource scan is unavailable, retain a bounded
                // active-object fallback rather than failing open to fuzzy names.
                if (!globalScanSucceeded)
                {
                    try
                    {
                        var direct = GameObject.Find(expectedName);
                        if (direct != null)
                        {
                            candidates.Add(direct);
                            methods.Add($"GameObject.Find:{expectedName}");
                        }
                    }
                    catch { }
                }
            }

            var inactiveMatches = candidates
                .Where(candidate => candidate != null && !candidate.activeInHierarchy)
                .ToList();
            var unique = candidates
                .Where(candidate => candidate != null && candidate.activeInHierarchy)
                .GroupBy(candidate =>
                {
                    try { return candidate.GetInstanceID(); }
                    catch { return 0; }
                })
                .Select(group => group.First())
                .ToList();

            if (unique.Count != 1)
            {
                details.Add(new
                {
                    status = unique.Count == 0 && inactiveMatches.Count > 0
                        ? "ACTOR_GAMEOBJECT_INACTIVE"
                        : unique.Count == 0 ? "ACTOR_GAMEOBJECT_NOT_FOUND" : "ACTOR_GAMEOBJECT_AMBIGUOUS",
                    actor_id = actor.ActorId,
                    entity_id = actor.EntityId,
                    cell_id = actor.CellId,
                    expected_names = expectedNames,
                    active_match_count = unique.Count,
                    inactive_match_count = inactiveMatches.Count,
                    methods = methods.Take(20).ToArray(),
                    candidates = unique.Take(10).Select(candidate => new
                    {
                        name = candidate.name,
                        hierarchy = HierarchyPath(candidate.transform, candidate.scene.name ?? "DofusUnity")
                    }).ToArray()
                });
                continue;
            }

            var selected = unique[0];
            try
            {
                var transform = selected.transform;
                var world = transform.position;
                if (!IsFinite(world)) continue;
                var hierarchy = HierarchyPath(transform, selected.scene.name ?? "DofusUnity");
                var onScreen = TryProject(camera, world, out var screenPoint);
                var match = new ActorRuntimeMatch
                {
                    ActorId = actor.ActorId,
                    EntityId = actor.EntityId,
                    CellId = actor.CellId,
                    CellFloor = actor.CellFloor,
                    IsPlayerControlled = actor.IsPlayerControlled,
                    Side = actor.Side,
                    ActorType = actor.ActorType,
                    Hierarchy = hierarchy,
                    ComponentType = "UnityEngine.GameObject/Transform",
                    WorldX = world.x,
                    WorldY = world.y,
                    WorldZ = world.z,
                    Score = 1000.0,
                    Confidence = 0.99,
                    OnScreen = onScreen,
                    ScreenX = screenPoint.x,
                    ScreenY = screenPoint.y,
                    MatchedMembers = new[] { "gameobject_name:exact_signed_entity_root" }
                };
                matches.Add(match);
                details.Add(new
                {
                    status = "EXACT_ACTOR_GAMEOBJECT_MATCH",
                    actor_id = actor.ActorId,
                    entity_id = actor.EntityId,
                    cell_id = actor.CellId,
                    selected_name = selected.name,
                    hierarchy,
                    world = Vector(world)
                });
            }
            catch (Exception error)
            {
                details.Add(new
                {
                    status = "ACTOR_TRANSFORM_READ_FAILED",
                    actor_id = actor.ActorId,
                    entity_id = actor.EntityId,
                    cell_id = actor.CellId,
                    error = error.Message
                });
            }
        }

        diagnostics = new
        {
            strategy = "exact_signed_entity_gameobject_names_single_scene_scan",
            requested_actor_count = observation?.Actors?.Count ?? 0,
            eligible_actor_count = actors.Count,
            matched_actor_count = matches.Count,
            scene_scan_succeeded = globalScanSucceeded,
            scanned_gameobject_count = scannedGameObjectCount,
            actors = details.Take(100).ToArray()
        };
        return matches;
    }


    public FightEntryRuntimeMatch FindFightEntryTarget(
        FightEntryRequest request,
        Camera camera,
        IReadOnlyList<Vector3> runtimeGridPositions,
        out object diagnostics)
    {
        diagnostics = null;
        if (request == null)
        {
            diagnostics = new { status = "FIGHT_ENTRY_REQUEST_MISSING" };
            return null;
        }
        if (runtimeGridPositions == null
            || runtimeGridPositions.Count < AuthoritativeCellPositionSource.CellCount
            || request.LaunchCellId < 0
            || request.LaunchCellId >= AuthoritativeCellPositionSource.CellCount
            || !IsFinite(runtimeGridPositions[request.LaunchCellId]))
        {
            diagnostics = new
            {
                status = "FIGHT_ENTRY_RUNTIME_GRID_UNAVAILABLE",
                launch_cell_id = request.LaunchCellId,
                runtime_grid_count = runtimeGridPositions?.Count ?? 0
            };
            return null;
        }

        // The structurally verified 560-cell runtime grid is the spatial
        // authority. Literal `cell::<id>` GameObjects are presentation details
        // and are only optional diagnostics/corroboration; requiring them here
        // would reintroduce the current-build hierarchy coupling removed by
        // R5.173/R5.186.
        var anchorCells = new List<(int CellId, Vector3 World, string Hierarchy)>
        {
            (request.LaunchCellId, runtimeGridPositions[request.LaunchCellId], $"runtime-grid:{request.LaunchCellId}")
        };
        var hintCellIds = (request.CandidateCellIds ?? new List<int>())
            .Concat(request.JoinAnchorCellId.HasValue ? new[] { request.JoinAnchorCellId.Value } : Array.Empty<int>())
            .Where(cell => cell >= 0 && cell < AuthoritativeCellPositionSource.CellCount)
            .Distinct()
            .ToArray();
        foreach (var cellId in hintCellIds)
        {
            if (cellId == request.LaunchCellId) continue;
            var world = runtimeGridPositions[cellId];
            if (IsFinite(world))
                anchorCells.Add((cellId, world, $"runtime-grid:{cellId}"));
        }

        var optionalLaunchCellResolved = TryFindExactCellAnchor(
            request.LaunchCellId,
            out var optionalLaunchCellWorld,
            out var optionalLaunchCellHierarchy,
            out var launchDiagnostics);

        // Fight-entry discovery is deliberately entity/object based. GraphicCells
        // and entity_character_ objects are location/actor anchors and are never
        // accepted as the interactive join target themselves. This prevents the
        // R5.79 failure where a join attempt became a ground MOVE_REQUEST.
        var scanKey = $"{request.MapId}:{request.FightInstanceId}:{request.PresentationId}:{string.Join(",", hintCellIds.OrderBy(x => x))}";
        RuntimeSceneScan scan;
        if (_fightEntryScanCache != null
            && string.Equals(_fightEntryScanCacheKey, scanKey, StringComparison.Ordinal)
            && (DateTime.UtcNow - _fightEntryScanCacheAtUtc).TotalSeconds < 1.0)
        {
            scan = _fightEntryScanCache;
        }
        else
        {
            scan = SnapshotRuntime(camera);
            _fightEntryScanCache = scan;
            _fightEntryScanCacheKey = scanKey;
            _fightEntryScanCacheAtUtc = DateTime.UtcNow;
        }
        var candidates = new List<FightEntryRuntimeMatch>();
        var nearbyProbes = new List<FightEntryRuntimeProbe>();
        foreach (var snapshot in scan.Components)
        {
            if (snapshot == null || !snapshot.Active || !IsFinite(snapshot.WorldPosition)) continue;
            var lower = (snapshot.Hierarchy + " " + snapshot.ComponentType + " "
                         + string.Join(" ", snapshot.ComponentHints ?? Array.Empty<string>())).ToLowerInvariant();
            if (lower.Contains("/graphiccells/") || lower.Contains("cell::")
                || IsEntityIdentityRootHierarchy(snapshot.Hierarchy)) continue;
            if (snapshot.UiHint) continue;

            var nearestAnchor = anchorCells
                .Select(anchor => new
                {
                    anchor.CellId,
                    Distance = Math.Sqrt(
                        Math.Pow((double)snapshot.WorldPosition.x - anchor.World.x, 2)
                        + Math.Pow((double)snapshot.WorldPosition.y - anchor.World.y, 2))
                })
                .OrderBy(item => item.Distance)
                .First();
            var planar = nearestAnchor.Distance;
            if (!double.IsFinite(planar) || planar > 180.0) continue;

            var semanticHint = lower.Contains("fight") || lower.Contains("combat")
                               || lower.Contains("join") || lower.Contains("sword")
                               || lower.Contains("challenge") || lower.Contains("placement");
            var onScreen = TryProject(camera, snapshot.WorldPosition, out _);
            if (!onScreen) continue;

            if (nearbyProbes.Count < 240 && (planar <= 120.0 || semanticHint))
            {
                nearbyProbes.Add(new FightEntryRuntimeProbe
                {
                    Hierarchy = snapshot.Hierarchy,
                    ComponentType = snapshot.ComponentType,
                    NearestCellId = nearestAnchor.CellId,
                    NearestCellPlanarDistance = planar,
                    SemanticHint = semanticHint,
                    NumericMembers = (snapshot.Numbers ?? new List<NumericMember>())
                        .Take(16).Select(item => $"{item.Path}={item.Value}").ToArray(),
                    ComponentHints = (snapshot.ComponentHints ?? Array.Empty<string>()).Take(16).ToArray()
                });
            }

            var evidence = new List<string>();
            var identityEvidence = 0;
            var candidateCellEvidence = nearestAnchor.CellId != request.LaunchCellId || hintCellIds.Contains(nearestAnchor.CellId);
            double score = 0.0;
            if (candidateCellEvidence)
            {
                score += planar <= 30.0 ? 100.0 : planar <= 70.0 ? 60.0 : 25.0;
                evidence.Add("candidate_cell:" + nearestAnchor.CellId);
            }

            var fightNumbers = snapshot.Numbers
                .Where(item => item.Value == request.FightInstanceId).Take(3).ToArray();
            if (fightNumbers.Length > 0)
            {
                identityEvidence++;
                score += 240.0 + Math.Min(2, fightNumbers.Length - 1) * 25.0;
                evidence.AddRange(fightNumbers.Select(item => "fight_id:" + item.Path));
            }
            if (LeafContainsIdentifier(snapshot.Hierarchy, request.FightInstanceId))
            {
                identityEvidence++;
                score += 220.0;
                evidence.Add("hierarchy:fight_id");
            }

            if (request.PresentationId.HasValue)
            {
                var presentationNumbers = snapshot.Numbers
                    .Where(item => item.Value == request.PresentationId.Value).Take(4).ToArray();
                if (presentationNumbers.Length > 0)
                {
                    identityEvidence += 2;
                    score += 360.0 + Math.Min(3, presentationNumbers.Length - 1) * 25.0;
                    evidence.AddRange(presentationNumbers.Select(item => "presentation_id:" + item.Path));
                }
                if (LeafContainsIdentifier(snapshot.Hierarchy, request.PresentationId.Value))
                {
                    identityEvidence += 2;
                    score += 320.0;
                    evidence.Add("hierarchy:presentation_id");
                }
            }

            if (request.LeaderActorId.HasValue)
            {
                var leaderNumbers = snapshot.Numbers
                    .Where(item => item.Value == request.LeaderActorId.Value).Take(2).ToArray();
                if (leaderNumbers.Length > 0)
                {
                    identityEvidence++;
                    score += 150.0;
                    evidence.AddRange(leaderNumbers.Select(item => "leader_actor_id:" + item.Path));
                }
            }
            if (request.OriginWorldEntityId.HasValue)
            {
                var originNumbers = snapshot.Numbers
                    .Where(item => item.Value == request.OriginWorldEntityId.Value).Take(2).ToArray();
                if (originNumbers.Length > 0)
                {
                    identityEvidence++;
                    score += 150.0;
                    evidence.AddRange(originNumbers.Select(item => "origin_entity_id:" + item.Path));
                }
            }

            if (semanticHint)
            {
                score += 90.0;
                evidence.Add("semantic:fight-entry");
            }
            if (snapshot.VisualHint) score += 30.0;
            if (planar <= 20.0) score += 100.0;
            else if (planar <= 45.0) score += 75.0;
            else if (planar <= 90.0) score += 40.0;
            else score += 10.0;

            score += 20.0;

            // Fail closed: proximity and a suggestive object name alone are not
            // proof. Require an exact live fight/leader/origin identity match,
            // and either fight-entry semantics or a second independent identity.
            if (identityEvidence < 1 || (!semanticHint && identityEvidence < 2 && !candidateCellEvidence)) continue;
            if (score < 250.0) continue;

            candidates.Add(new FightEntryRuntimeMatch
            {
                Hierarchy = snapshot.Hierarchy,
                ComponentType = snapshot.ComponentType,
                WorldX = snapshot.WorldPosition.x,
                WorldY = snapshot.WorldPosition.y,
                WorldZ = snapshot.WorldPosition.z,
                LaunchCellPlanarDistance = planar,
                Score = score,
                Confidence = Math.Max(0.0, Math.Min(0.99, score / 500.0)),
                OnScreen = true,
                Evidence = evidence.Distinct().Take(24).ToArray()
            });
        }

        var ranked = candidates
            .GroupBy(item => item.Hierarchy ?? "")
            .Select(group => group.OrderByDescending(item => item.Score).First())
            .OrderByDescending(item => item.Score)
            .ThenBy(item => item.LaunchCellPlanarDistance)
            .ToList();
        var best = ranked.FirstOrDefault();
        var runnerUp = ranked.Skip(1).FirstOrDefault();
        var uniqueEnough = best != null && (runnerUp == null || best.Score - runnerUp.Score >= 25.0);
        if (!uniqueEnough) best = null;

        diagnostics = new
        {
            status = best == null ? "FIGHT_ENTRY_NOT_PROVEN" : "FIGHT_ENTRY_PROVEN",
            strategy = "protocol_identity_plus_candidate_cell_anchors",
            launch_cell_id = request.LaunchCellId,
            presentation_id = request.PresentationId,
            candidate_cell_ids = request.CandidateCellIds,
            join_anchor_cell_id = request.JoinAnchorCellId,
            candidate_cell_anchors = anchorCells.Select(anchor => new { cell_id = anchor.CellId, hierarchy = anchor.Hierarchy, world = Vector(anchor.World) }).ToArray(),
            launch_cell_hierarchy = optionalLaunchCellResolved ? optionalLaunchCellHierarchy : null,
            launch_cell_world = optionalLaunchCellResolved ? Vector(optionalLaunchCellWorld) : null,
            launch_cell_diagnostics = launchDiagnostics,
            fight_instance_id = request.FightInstanceId,
            leader_actor_id = request.LeaderActorId,
            origin_world_entity_id = request.OriginWorldEntityId,
            scanned_component_count = scan.Components.Count,
            candidate_count = ranked.Count,
            candidates = ranked.Take(12).Select(item => new
            {
                hierarchy = item.Hierarchy,
                component_type = item.ComponentType,
                score = item.Score,
                confidence = item.Confidence,
                launch_cell_planar_distance = item.LaunchCellPlanarDistance,
                evidence = item.Evidence
            }).ToArray(),
            nearby_probes = nearbyProbes
                .OrderByDescending(item => item.SemanticHint)
                .ThenBy(item => item.NearestCellPlanarDistance)
                .Take(24)
                .Select(item => new
                {
                    hierarchy = item.Hierarchy,
                    component_type = item.ComponentType,
                    nearest_cell_id = item.NearestCellId,
                    planar_distance = item.NearestCellPlanarDistance,
                    semantic_hint = item.SemanticHint,
                    numeric_members = item.NumericMembers,
                    component_hints = item.ComponentHints
                }).ToArray()
        };
        return best;
    }

    public ActorRuntimeMatch ResolveActorAnchor(
        RuntimeObservation observation,
        long entityId,
        int expectedCellId,
        Camera camera,
        out object diagnostics)
    {
        diagnostics = null;
        if (observation == null)
        {
            diagnostics = new { status = "NO_OBSERVATION" };
            return null;
        }
        if (entityId == 0 || expectedCellId < 0 || expectedCellId >= 560)
        {
            diagnostics = new
            {
                status = "ENTITY_RESOLUTION_REQUEST_INVALID",
                entity_id = entityId,
                expected_cell_id = expectedCellId
            };
            return null;
        }

        var actor = (observation.Actors ?? new List<ObservationActor>())
            .FirstOrDefault(item => item != null
                                    && item.EntityId == entityId
                                    && item.CellId == expectedCellId);
        if (actor == null)
        {
            diagnostics = new
            {
                status = "CANONICAL_ENTITY_CELL_NOT_OBSERVED",
                entity_id = entityId,
                expected_cell_id = expectedCellId
            };
            return null;
        }

        TryFindExactCellAnchor(expectedCellId, out var exactCellWorld, out var exactCellHierarchy, out var exactCellDiagnostics);

        // Prefer a unique exact active entity root before any reflective scene
        // scan.  AutomaticMapAdapter independently checks the returned world
        // position against the authoritative runtime grid, so this fast path
        // remains fail-closed even when Dofus changes visual child structure.
        var exactMatches = FindExactActorAnchors(observation, camera, out var exactDiagnostics)
            .Where(match => match.EntityId == entityId && match.CellId == expectedCellId)
            .ToList();
        if (exactMatches.Count == 1)
        {
            diagnostics = new
            {
                status = "ENTITY_ANCHOR_PROVEN",
                strategy = "canonical_entity_plus_unique_exact_signed_entity_root_plus_runtime_grid",
                entity_id = entityId,
                expected_cell_id = expectedCellId,
                exact_named = exactDiagnostics,
                exact_cell = exactCellDiagnostics,
                exact_cell_hierarchy = exactCellHierarchy,
                identity_candidate_count = 1,
                refined_candidate_count = 1,
                selected = exactMatches[0],
                candidates = exactMatches.ToArray()
            };
            return exactMatches[0];
        }

        var scan = SnapshotRuntime(camera);
        var ranked = scan.Components
            .Select(snapshot => Score(snapshot, actor, camera))
            .Where(candidate => candidate != null)
            .GroupBy(candidate => candidate.Hierarchy ?? "")
            .Select(group => group.OrderByDescending(candidate => candidate.Score).First())
            .OrderByDescending(candidate => candidate.Score)
            .Take(12)
            .ToList();

        // Preserve any exact-name candidates as high-confidence hints when
        // uniqueness could not establish the fast path.
        foreach (var exact in exactMatches)
        {
            if (ranked.Any(item => string.Equals(item.Hierarchy, exact.Hierarchy, StringComparison.Ordinal))) continue;
            ranked.Insert(0, exact);
        }

        var refined = new List<ActorRuntimeMatch>();
        foreach (var identity in ranked)
        {
            var candidate = RefineActorToCellVisual(
                identity,
                actor,
                scan.VisualTransforms,
                exactCellWorld,
                exactCellHierarchy,
                camera);
            if (candidate != null) refined.Add(candidate);
        }

        var ordered = refined
            .GroupBy(item => item.Hierarchy ?? "")
            .Select(group => group.OrderByDescending(item => item.Score).First())
            .OrderByDescending(item => item.Score)
            .ToList();
        var best = ordered.FirstOrDefault();
        var runner = ordered.Skip(1).FirstOrDefault();
        var unique = best != null && (runner == null || best.Score - runner.Score >= 18.0);
        if (!unique) best = null;

        diagnostics = new
        {
            status = best == null ? "ENTITY_ANCHOR_NOT_PROVEN" : "ENTITY_ANCHOR_PROVEN",
            strategy = string.IsNullOrWhiteSpace(exactCellHierarchy)
                ? "canonical_entity_plus_runtime_identity_subtree_plus_runtime_grid"
                : "canonical_entity_plus_runtime_identity_subtree_plus_exact_cell_visual",
            entity_id = entityId,
            expected_cell_id = expectedCellId,
            exact_named = exactDiagnostics,
            exact_cell = exactCellDiagnostics,
            exact_cell_hierarchy = exactCellHierarchy,
            scanned_components = scan.Components.Count,
            scanned_transforms = scan.TraversedGameObjects,
            reflected_components = scan.ReflectedComponents,
            identity_candidate_count = ranked.Count,
            refined_candidate_count = ordered.Count,
            selected = best,
            candidates = ordered.Take(12).ToArray()
        };
        return best;
    }

    private static ActorRuntimeMatch RefineActorToCellVisual(
        ActorRuntimeMatch identity,
        ObservationActor actor,
        IReadOnlyList<VisualTransformSnapshot> visualTransforms,
        Vector3 exactCellWorld,
        string exactCellHierarchy,
        Camera camera)
    {
        if (identity == null || actor == null) return null;
        var identityHierarchy = identity.Hierarchy ?? "";
        var cellKnown = !string.IsNullOrWhiteSpace(exactCellHierarchy) && IsFinite(exactCellWorld);
        var candidates = new List<(VisualTransformSnapshot Visual, double Distance, double Score)>();
        foreach (var visual in visualTransforms ?? Array.Empty<VisualTransformSnapshot>())
        {
            if (visual == null || visual.UiHint) continue;
            // Identity refinement is allowed only inside the already-proven
            // entity subtree.  Ancestors such as `/entities` are shared by many
            // actors and therefore cannot be a physical interaction anchor.
            if (!HierarchyAtOrBelowIdentity(identityHierarchy, visual.Hierarchy)) continue;
            var distance = cellKnown ? PlanarDistance(visual.WorldPosition, exactCellWorld) : double.NaN;
            if (cellKnown && distance > 35.0) continue;
            var score = identity.Score;
            if (visual.VisualHint) score += 30.0;
            if (visual.OnScreen) score += 20.0;
            if (cellKnown)
            {
                score += Math.Max(0.0, 70.0 - distance * 2.0);
                if (distance <= 5.0) score += 35.0;
            }
            if ((visual.Hierarchy ?? "").Contains("#bounds:", StringComparison.Ordinal)) score += 8.0;
            candidates.Add((visual, distance, score));
        }

        var selected = candidates
            .OrderByDescending(item => item.Score)
            .ThenBy(item => double.IsNaN(item.Distance) ? double.MaxValue : item.Distance)
            .FirstOrDefault();
        if (selected.Visual == null)
        {
            if (!cellKnown) return identity;
            var identityDistance = PlanarDistance(identity.WorldPosition, exactCellWorld);
            if (identityDistance > 20.0) return null;
            identity.Score += Math.Max(0.0, 45.0 - identityDistance);
            identity.Confidence = Math.Max(identity.Confidence, identityDistance <= 5.0 ? 0.96 : 0.82);
            identity.MatchedMembers = identity.MatchedMembers
                .Concat(new[] { $"exact_cell_visual_distance:{identityDistance:F3}" })
                .Distinct().Take(30).ToArray();
            return identity;
        }

        var visualPoint = selected.Visual;
        var screen = default(Vector3);
        var onScreen = visualPoint.OnScreen;
        if (camera != null && TryProject(camera, visualPoint.WorldPosition, out var projected))
        {
            screen = projected;
            onScreen = true;
        }
        return new ActorRuntimeMatch
        {
            ActorId = actor.ActorId,
            EntityId = actor.EntityId,
            CellId = actor.CellId,
            CellFloor = actor.CellFloor,
            IsPlayerControlled = actor.IsPlayerControlled,
            Side = actor.Side,
            ActorType = actor.ActorType,
            Hierarchy = visualPoint.Hierarchy,
            ComponentType = "R5.172_ENTITY_VISUAL_RESOLVER",
            WorldX = visualPoint.WorldX,
            WorldY = visualPoint.WorldY,
            WorldZ = visualPoint.WorldZ,
            Score = selected.Score,
            Confidence = Math.Max(
                identity.Confidence,
                cellKnown ? (selected.Distance <= 5.0 ? 0.98 : 0.88) : 0.90),
            OnScreen = onScreen,
            ScreenX = screen.x,
            ScreenY = screen.y,
            MatchedMembers = identity.MatchedMembers
                .Concat(
                    cellKnown
                        ? new[]
                        {
                            "resolver:runtime_identity",
                            "resolver:identity_subtree_visual",
                            "resolver:exact_cell_visual",
                            $"resolver:cell_distance:{selected.Distance:F3}"
                        }
                        : new[]
                        {
                            "resolver:runtime_identity",
                            "resolver:identity_subtree_visual",
                            "resolver:exact_cell_visual_unavailable"
                        })
                .Distinct().Take(30).ToArray(),
            ComponentHints = visualPoint.ComponentHints?.Take(30).ToArray() ?? Array.Empty<string>()
        };
    }

    private static bool HierarchyAtOrBelowIdentity(string identityHierarchy, string visualHierarchy)
    {
        if (string.IsNullOrWhiteSpace(identityHierarchy) || string.IsNullOrWhiteSpace(visualHierarchy)) return false;
        var identityBase = identityHierarchy.Split('#')[0];
        var visualBase = visualHierarchy.Split('#')[0];
        return string.Equals(identityBase, visualBase, StringComparison.Ordinal)
               || visualBase.StartsWith(identityBase + "/", StringComparison.Ordinal);
    }

    private static bool IsEntityIdentityRootHierarchy(string hierarchy)
    {
        if (string.IsNullOrWhiteSpace(hierarchy)) return false;
        var clean = hierarchy.Split('#')[0].TrimEnd('/');
        var slash = clean.LastIndexOf('/');
        var leaf = slash >= 0 ? clean.Substring(slash + 1) : clean;
        if (leaf.StartsWith("entity_character_", StringComparison.Ordinal)) return true;
        if (!leaf.StartsWith("Entity ", StringComparison.Ordinal)) return false;
        var token = leaf.Substring("Entity ".Length).Trim();
        return long.TryParse(token, out _);
    }

    private static double PlanarDistance(Vector3 left, Vector3 right)
    {
        var dx = (double)left.x - right.x;
        var dy = (double)left.y - right.y;
        return Math.Sqrt(dx * dx + dy * dy);
    }

    public List<ActorRuntimeMatch> MatchActors(
        RuntimeObservation observation,
        Camera camera,
        out object diagnostics,
        out List<VisualTransformSnapshot> visualTransforms)
    {
        var scan = SnapshotRuntime(camera);
        var snapshots = scan.Components;
        visualTransforms = scan.VisualTransforms;
        var matches = new List<ActorRuntimeMatch>();
        var actorDiagnostics = new List<object>();
        foreach (var actor in observation.Actors ?? new List<ObservationActor>())
        {
            if (!actor.CellId.HasValue || actor.CellId < 0 || actor.CellId > 559) continue;
            var ranked = snapshots
                .Select(snapshot => Score(snapshot, actor, camera))
                .Where(candidate => candidate != null)
                .GroupBy(candidate => candidate.Hierarchy)
                .Select(group => group.OrderByDescending(candidate => candidate.Score).First())
                .OrderByDescending(candidate => candidate.Score)
                .Take(5)
                .ToList();
            var winner = ranked.FirstOrDefault();
            if (winner != null)
            {
                TryFindExactCellAnchor(actor.CellId.Value, out var exactCellWorld, out var exactCellHierarchy, out _);
                winner = RefineActorToCellVisual(
                    winner, actor, scan.VisualTransforms, exactCellWorld, exactCellHierarchy, camera);
                var runnerUp = ranked.Skip(1).FirstOrDefault();
                if (winner != null && runnerUp != null && runnerUp.Score >= winner.Score * 0.92)
                    winner.Confidence *= 0.70;
                if (winner != null && winner.Confidence >= 0.55) matches.Add(winner);
            }
            actorDiagnostics.Add(new
            {
                actor_id = actor.ActorId,
                entity_id = actor.EntityId,
                cell_id = actor.CellId,
                selected = winner,
                top_candidates = ranked
            });
        }
        diagnostics = new
        {
            scanned_components = snapshots.Count,
            scanned_transforms = scan.TraversedGameObjects,
            visual_transform_count = visualTransforms.Count,
            resource_fallback_objects = scan.ResourceFallbackObjects,
            reflected_components = scan.ReflectedComponents,
            loaded_scenes = scan.Scenes,
            camera = camera == null ? null : new
            {
                name = camera.name,
                pixel_width = camera.pixelWidth,
                pixel_height = camera.pixelHeight,
                position = Vector(camera.transform.position)
            },
            actor_count = observation.Actors?.Count ?? 0,
            matched_actor_count = matches.Count,
            actors = actorDiagnostics,
            transform_preview = visualTransforms
                .OrderByDescending(item => TransformPreviewScore(item))
                .Take(30)
                .Select(item => new
                {
                    scene = item.SceneName,
                    hierarchy = item.Hierarchy,
                    depth = item.Depth,
                    world = Vector(item.WorldPosition),
                    screen = new { x = item.ScreenX, y = item.ScreenY },
                    visual_hint = item.VisualHint,
                    ui_hint = item.UiHint,
                    component_hints = item.ComponentHints.Take(12).ToArray()
                })
                .ToArray()
        };
        return matches;
    }

    public object DiscoverySnapshot(RuntimeObservation observation)
    {
        var camera = SelectGameplayCamera();
        var cameras = new List<object>();
        foreach (var candidate in Camera.allCameras)
        {
            if (candidate == null) continue;
            cameras.Add(new
            {
                name = candidate.name,
                type = candidate.GetType().FullName,
                enabled = candidate.enabled,
                depth = candidate.depth,
                pixel_width = candidate.pixelWidth,
                pixel_height = candidate.pixelHeight,
                position = Vector(candidate.transform.position)
            });
        }
        var scan = SnapshotRuntime(camera);
        var snapshots = scan.Components;
        var targetValues = new HashSet<long>();
        if (observation?.MapId is long mapId) targetValues.Add(mapId);
        foreach (var actor in observation?.Actors ?? new List<ObservationActor>())
        {
            if (actor.ActorId.HasValue) targetValues.Add(actor.ActorId.Value);
            if (actor.EntityId.HasValue) targetValues.Add(actor.EntityId.Value);
            if (actor.CellId.HasValue) targetValues.Add(actor.CellId.Value);
        }
        var exactMatches = new List<object>();
        foreach (var snapshot in snapshots)
        {
            foreach (var number in snapshot.Numbers)
            {
                if (!targetValues.Contains(number.Value)) continue;
                exactMatches.Add(new
                {
                    scene = snapshot.SceneName,
                    hierarchy = snapshot.Hierarchy,
                    component_type = snapshot.ComponentType,
                    member = number.Path,
                    value = number.Value,
                    position = Vector(snapshot.WorldPosition),
                    visual_hint = snapshot.VisualHint,
                    ui_hint = snapshot.UiHint
                });
                if (exactMatches.Count >= 5000) break;
            }
            if (exactMatches.Count >= 5000) break;
        }
        var typeCounts = snapshots
            .GroupBy(snapshot => snapshot.ComponentType)
            .Select(group => new { type = group.Key, count = group.Count() })
            .OrderByDescending(item => item.count)
            .Take(1000)
            .ToArray();
        return new
        {
            generated_at_utc = DateTime.UtcNow.ToString("O"),
            observation,
            cameras,
            loaded_scenes = scan.Scenes,
            traversed_game_object_count = scan.TraversedGameObjects,
            scanned_component_count = snapshots.Count,
            visible_transform_count = scan.VisualTransforms.Count,
            resource_fallback_objects = scan.ResourceFallbackObjects,
            reflected_components = scan.ReflectedComponents,
            component_type_counts = typeCounts,
            exact_observed_value_matches = exactMatches,
            transform_preview = scan.VisualTransforms
                .OrderByDescending(item => TransformPreviewScore(item))
                .Take(250)
                .ToArray()
        };
    }

    private RuntimeSceneScan SnapshotRuntime(Camera camera)
    {
        var scan = new RuntimeSceneScan();
        var seenInstanceIds = new HashSet<int>();
        var sceneCount = SceneManager.sceneCount;
        for (var index = 0; index < sceneCount; index++)
        {
            Scene scene;
            try { scene = SceneManager.GetSceneAt(index); }
            catch { continue; }
            if (!scene.IsValid() || !scene.isLoaded) continue;
            var rootCount = 0;
            try { rootCount = scene.rootCount; }
            catch { }
            scan.Scenes.Add(new
            {
                name = scene.name,
                handle = scene.handle,
                build_index = scene.buildIndex,
                root_count = rootCount,
                is_active = scene == SceneManager.GetActiveScene()
            });
            try
            {
                foreach (var root in scene.GetRootGameObjects())
                {
                    if (root == null) continue;
                    Traverse(root.transform, scene.name, scan, seenInstanceIds, 0);
                    if (scan.TraversedGameObjects >= MaxGameObjects || scan.Components.Count >= MaxComponents) break;
                }
            }
            catch { }
            if (scan.TraversedGameObjects >= MaxGameObjects || scan.Components.Count >= MaxComponents) break;
        }

        // Unity keeps some runtime objects in the DontDestroyOnLoad scene or in
        // additive scenes that are not reliably reported as the active scene by
        // every IL2CPP build. This fallback closes that gap and is de-duplicated
        // by the Transform instance id.
        if (scan.TraversedGameObjects < MaxGameObjects && scan.VisualTransforms.Count < MaxVisualTransforms)
        {
            try
            {
                foreach (var transform in Resources.FindObjectsOfTypeAll<Transform>())
                {
                    if (transform == null || scan.TraversedGameObjects >= MaxGameObjects) break;
                    int instanceId;
                    try { instanceId = transform.GetInstanceID(); }
                    catch { continue; }
                    if (seenInstanceIds.Contains(instanceId)) continue;
                    var sceneName = "resource_runtime";
                    try
                    {
                        var objectScene = transform.gameObject.scene;
                        if (objectScene.IsValid() && !string.IsNullOrWhiteSpace(objectScene.name)) sceneName = objectScene.name;
                    }
                    catch { }
                    CaptureTransform(transform, sceneName, scan, seenInstanceIds, HierarchyDepth(transform));
                    scan.ResourceFallbackObjects++;
                }
            }
            catch { }
        }

        // Projection must happen after capture because the selected camera can
        // live in a different additive scene than the actor objects.
        if (camera != null)
        {
            var projected = new List<VisualTransformSnapshot>();
            foreach (var candidate in scan.VisualTransforms)
            {
                if (!TryProject(camera, candidate.WorldPosition, out var point)) continue;
                candidate.ScreenX = point.x;
                candidate.ScreenY = point.y;
                candidate.OnScreen = true;
                projected.Add(candidate);
                if (projected.Count >= MaxVisualTransforms) break;
            }
            scan.VisualTransforms = projected;
        }
        else
        {
            scan.VisualTransforms.Clear();
        }
        return scan;
    }

    private static void Traverse(
        Transform transform,
        string sceneName,
        RuntimeSceneScan scan,
        ISet<int> seenInstanceIds,
        int depth)
    {
        if (transform == null || depth > 80 || scan.TraversedGameObjects >= MaxGameObjects || scan.Components.Count >= MaxComponents) return;
        CaptureTransform(transform, sceneName, scan, seenInstanceIds, depth);
        for (var index = 0; index < transform.childCount; index++)
        {
            Transform child;
            try { child = transform.GetChild(index); }
            catch { continue; }
            Traverse(child, sceneName, scan, seenInstanceIds, depth + 1);
            if (scan.TraversedGameObjects >= MaxGameObjects || scan.Components.Count >= MaxComponents) break;
        }
    }

    private static void CaptureTransform(
        Transform transform,
        string sceneName,
        RuntimeSceneScan scan,
        ISet<int> seenInstanceIds,
        int depth)
    {
        if (transform == null || scan.TraversedGameObjects >= MaxGameObjects) return;
        int instanceId;
        try { instanceId = transform.GetInstanceID(); }
        catch { return; }
        if (!seenInstanceIds.Add(instanceId)) return;
        scan.TraversedGameObjects++;

        GameObject gameObject;
        try { gameObject = transform.gameObject; }
        catch { return; }
        if (gameObject == null) return;

        var components = new List<Component>();
        try
        {
            foreach (var component in gameObject.GetComponents<Component>())
                if (component != null) components.Add(component);
        }
        catch { }
        var hints = components
            .Where(component => component != null)
            .Select(component => component.GetType().FullName ?? component.GetType().Name)
            .Take(100)
            .ToArray();
        var joinedHints = string.Join(" ", hints).ToLowerInvariant();
        var visual = joinedHints.Contains("renderer") || joinedHints.Contains("animator")
                     || joinedHints.Contains("sprite") || joinedHints.Contains("mesh")
                     || joinedHints.Contains("graphic") || joinedHints.Contains("skeleton");
        var hierarchy = HierarchyPath(transform, sceneName);
        var ui = IsUiHint(transform, hierarchy, joinedHints);
        bool active;
        Vector3 world;
        try
        {
            active = gameObject.activeInHierarchy;
            world = transform.position;
        }
        catch { return; }

        foreach (var component in components)
        {
            if (component == null || scan.Components.Count >= MaxComponents) continue;
            var componentType = component.GetType().FullName ?? component.GetType().Name;
            if (IsInfrastructureType(componentType)) continue;
            scan.Components.Add(new ComponentSnapshot
            {
                Component = component,
                SceneName = sceneName,
                Hierarchy = hierarchy,
                Depth = depth,
                ComponentType = componentType,
                ComponentHints = hints,
                Active = active,
                VisualHint = visual,
                UiHint = ui,
                WorldPosition = world,
                Numbers = active && ShouldInspectNumericMembers(componentType) && scan.ReflectedComponents < MaxReflectedComponents
                    ? ReadNumericMembersCounted(component, scan)
                    : new List<NumericMember>()
            });
        }

        // Motion correlation intentionally sees every active runtime Transform,
        // not only GameObjects with Renderer/Animator components. Dofus places
        // actor state, visual children and renderers on different hierarchy
        // levels, and the moving root often has no visual component itself.
        if (active && scan.VisualTransforms.Count < MaxVisualTransforms && IsFinite(world))
        {
            scan.VisualTransforms.Add(new VisualTransformSnapshot
            {
                SceneName = sceneName,
                Hierarchy = hierarchy,
                Depth = depth,
                WorldX = world.x,
                WorldY = world.y,
                WorldZ = world.z,
                VisualHint = visual,
                UiHint = ui,
                OnScreen = false,
                ComponentHints = hints
            });

            // A renderer's bounds center can move even when its owning Transform
            // remains fixed (for example a skinned or batched visual). Capture it
            // as a separately tracked path so motion fallback still sees it.
            foreach (var component in components)
            {
                if (scan.VisualTransforms.Count >= MaxVisualTransforms) break;
                if (component is not Renderer renderer) continue;
                Vector3 center;
                try { center = renderer.bounds.center; }
                catch { continue; }
                if (!IsFinite(center) || Vector3.Distance(center, world) <= 0.01f) continue;
                scan.VisualTransforms.Add(new VisualTransformSnapshot
                {
                    SceneName = sceneName,
                    Hierarchy = hierarchy + "#bounds:" + (component.GetType().FullName ?? component.GetType().Name),
                    Depth = depth,
                    WorldX = center.x,
                    WorldY = center.y,
                    WorldZ = center.z,
                    VisualHint = true,
                    UiHint = ui,
                    OnScreen = false,
                    ComponentHints = hints
                });
            }
        }
    }

    private static ActorRuntimeMatch Score(ComponentSnapshot snapshot, ObservationActor actor, Camera camera)
    {
        // Entity interaction is an action authority, not a forensic inventory.
        // Resources.FindObjectsOfTypeAll also exposes inactive objects retained
        // from additive/previous scenes; accepting those can click a stale actor
        // merely because its historical ID still exists. Only an active runtime
        // component may establish identity for a physical interaction.
        if (snapshot == null || !snapshot.Active) return null;
        var matches = new List<string>();
        var entityMatches = actor.EntityId.HasValue
            ? snapshot.Numbers.Where(number => number.Value == actor.EntityId.Value).ToList()
            : new List<NumericMember>();
        // In Dofus Unity IL2CPP builds, gameplay components may surface only as
        // generic UnityEngine.Component wrappers, so numeric reflection can be
        // empty even though the actor's stable entity ID is present verbatim in
        // the root GameObject name (for example entity_character_477764256037).
        // Match only the leaf name, not ancestors, so visual children do not
        // create ambiguous duplicate candidates for the same actor.
        var hierarchyEntityMatch = actor.EntityId.HasValue
                                   && actor.EntityId.Value != 0
                                   && LeafContainsIdentifier(snapshot.Hierarchy, actor.EntityId.Value);
        var cellMatches = snapshot.Numbers.Where(number => number.Value == actor.CellId.Value).ToList();
        var actorMatches = actor.ActorId.HasValue
            ? snapshot.Numbers.Where(number => number.Value == actor.ActorId.Value).ToList()
            : new List<NumericMember>();
        var staticMatches = actor.ActorStaticId.HasValue
            ? snapshot.Numbers.Where(number => number.Value == actor.ActorStaticId.Value).ToList()
            : new List<NumericMember>();
        if (!hierarchyEntityMatch && entityMatches.Count == 0 && (cellMatches.Count == 0 || actorMatches.Count == 0)) return null;

        var score = entityMatches.Count > 0 ? 100.0 : 0.0;
        if (hierarchyEntityMatch) score += 180.0;
        score += Math.Min(2, cellMatches.Count) * 28.0;
        score += Math.Min(2, actorMatches.Count) * 14.0;
        score += Math.Min(1, staticMatches.Count) * 5.0;
        matches.AddRange(entityMatches.Select(item => $"entity:{item.Path}"));
        if (hierarchyEntityMatch) matches.Add("hierarchy:entity_id_leaf");
        matches.AddRange(cellMatches.Select(item => $"cell:{item.Path}"));
        matches.AddRange(actorMatches.Select(item => $"actor:{item.Path}"));
        matches.AddRange(staticMatches.Select(item => $"static:{item.Path}"));

        if (snapshot.Active) score += 4;
        if (snapshot.VisualHint) score += 14;
        if (snapshot.UiHint) score -= 25;
        var lower = (snapshot.Hierarchy + " " + snapshot.ComponentType).ToLowerInvariant();
        if (lower.Contains("actor") || lower.Contains("fighter") || lower.Contains("character")
            || lower.Contains("entity") || lower.Contains("monster")) score += 8;
        if (lower.Contains("portrait") || lower.Contains("timeline") || lower.Contains("tooltip")) score -= 25;

        var onScreen = false;
        var screenPoint = default(Vector3);
        if (camera != null)
        {
            try
            {
                onScreen = TryProject(camera, snapshot.WorldPosition, out screenPoint);
                if (onScreen) score += 12;
                else score -= 6;
            }
            catch { }
        }
        if (score < 70) return null;
        var confidence = Math.Max(0.0, Math.Min(0.99, (score - 55.0) / 100.0));
        return new ActorRuntimeMatch
        {
            ActorId = actor.ActorId,
            EntityId = actor.EntityId,
            CellId = actor.CellId,
            CellFloor = actor.CellFloor,
            IsPlayerControlled = actor.IsPlayerControlled,
            Side = actor.Side,
            ActorType = actor.ActorType,
            Hierarchy = snapshot.Hierarchy,
            ComponentType = snapshot.ComponentType,
            WorldX = snapshot.WorldPosition.x,
            WorldY = snapshot.WorldPosition.y,
            WorldZ = snapshot.WorldPosition.z,
            Score = score,
            Confidence = confidence,
            OnScreen = onScreen,
            ScreenX = screenPoint.x,
            ScreenY = screenPoint.y,
            MatchedMembers = matches.Distinct().Take(30).ToArray(),
            ComponentHints = snapshot.ComponentHints.Take(30).ToArray()
        };
    }



    private static bool LeafContainsIdentifier(string hierarchy, long identifier)
    {
        if (identifier == 0 || string.IsNullOrWhiteSpace(hierarchy)) return false;
        var end = hierarchy.LastIndexOf('#');
        if (end < 0) end = hierarchy.Length;
        var slash = hierarchy.LastIndexOf('/', Math.Max(0, end - 1));
        var start = slash >= 0 ? slash + 1 : 0;
        if (end <= start) return false;
        var leaf = hierarchy.Substring(start, end - start);
        var token = identifier.ToString();
        var searchFrom = 0;
        while (searchFrom <= leaf.Length - token.Length)
        {
            var index = leaf.IndexOf(token, searchFrom, StringComparison.Ordinal);
            if (index < 0) return false;
            var beforeIsDigit = index > 0 && char.IsDigit(leaf[index - 1]);
            // Signed entity IDs are distinct namespaces: a positive 20003 must
            // never match the leaf token -20003. Negative world-group IDs are
            // first-class identities and include their sign in `token`.
            var positiveInsideNegative = identifier > 0 && index > 0 && leaf[index - 1] == '-';
            var afterIndex = index + token.Length;
            var afterIsDigit = afterIndex < leaf.Length && char.IsDigit(leaf[afterIndex]);
            if (!beforeIsDigit && !positiveInsideNegative && !afterIsDigit) return true;
            searchFrom = index + 1;
        }
        return false;
    }

    private static List<NumericMember> ReadNumericMembersCounted(object root, RuntimeSceneScan scan)
    {
        scan.ReflectedComponents++;
        return ReadNumericMembers(root);
    }

    private static List<NumericMember> ReadNumericMembers(object root)
    {
        var result = new List<NumericMember>();
        var visited = new HashSet<object>(ReferenceEqualityComparer.Instance);
        ReadObject(root, root.GetType().Name, 0, visited, result);
        return result;
    }

    private static void ReadObject(object value, string path, int depth, ISet<object> visited, ICollection<NumericMember> result)
    {
        if (value == null || depth > MaxNestedDepth || result.Count >= MaxMembersPerObject) return;
        if (!value.GetType().IsValueType && !visited.Add(value)) return;
        var type = value.GetType();
        foreach (var field in SafeFields(type))
        {
            if (result.Count >= MaxMembersPerObject) break;
            object member;
            try { member = field.GetValue(value); }
            catch { continue; }
            RecordOrDescend(member, $"{path}.{field.Name}", depth, visited, result);
        }
        foreach (var property in SafeProperties(type))
        {
            if (result.Count >= MaxMembersPerObject) break;
            object member;
            try { member = property.GetValue(value, null); }
            catch { continue; }
            RecordOrDescend(member, $"{path}.{property.Name}", depth, visited, result);
        }
    }

    private static void RecordOrDescend(object member, string path, int depth, ISet<object> visited, ICollection<NumericMember> result)
    {
        if (TryLong(member, out var numeric))
        {
            result.Add(new NumericMember { Path = path, Value = numeric });
            return;
        }
        if (depth >= MaxNestedDepth || member == null) return;
        var type = member.GetType();
        var name = type.FullName ?? type.Name;
        if (name.StartsWith("UnityEngine.") || name.StartsWith("System.") || name.StartsWith("Il2CppSystem.")) return;
        if (name.Contains("Dictionary") || name.Contains("List") || name.Contains("Array")) return;
        ReadObject(member, path, depth + 1, visited, result);
    }

    private static IEnumerable<FieldInfo> SafeFields(Type type)
    {
        lock (ReflectionCacheLock)
        {
            if (FieldCache.TryGetValue(type, out var cached)) return cached;
            try
            {
                cached = type.GetFields(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic)
                    .Where(field => !field.IsStatic)
                    .Take(120)
                    .ToArray();
            }
            catch { cached = Array.Empty<FieldInfo>(); }
            FieldCache[type] = cached;
            return cached;
        }
    }

    private static IEnumerable<PropertyInfo> SafeProperties(Type type)
    {
        lock (ReflectionCacheLock)
        {
            if (PropertyCache.TryGetValue(type, out var cached)) return cached;
            try
            {
                cached = type.GetProperties(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic)
                    .Where(property => property.CanRead && property.GetIndexParameters().Length == 0)
                    .Where(property => property.Name is not ("gameObject" or "transform" or "name" or "tag"))
                    .Where(property => IsSimpleType(property.PropertyType) || IsSafeNestedType(property.PropertyType))
                    .Take(60)
                    .ToArray();
            }
            catch { cached = Array.Empty<PropertyInfo>(); }
            PropertyCache[type] = cached;
            return cached;
        }
    }

    private static bool TryLong(object value, out long result)
    {
        result = 0;
        if (value == null || value is bool || value is float || value is double || value is decimal) return false;
        if (value is byte b) { result = b; return true; }
        if (value is sbyte sb) { result = sb; return true; }
        if (value is short s) { result = s; return true; }
        if (value is ushort us) { result = us; return true; }
        if (value is int i) { result = i; return true; }
        if (value is uint ui) { result = ui; return true; }
        if (value is long l) { result = l; return true; }
        if (value is ulong ul && ul <= long.MaxValue) { result = (long)ul; return true; }
        if (value.GetType().IsEnum)
        {
            try { result = Convert.ToInt64(value); return true; }
            catch { return false; }
        }
        var typeName = value.GetType().FullName ?? "";
        if ((typeName.Contains("Int32") || typeName.Contains("Int64") || typeName.Contains("UInt32") || typeName.Contains("UInt64"))
            && long.TryParse(value.ToString(), out result)) return true;
        return false;
    }

    private static bool IsSimpleType(Type type) =>
        type.IsPrimitive || type.IsEnum || type == typeof(string) || type == typeof(decimal);

    private static bool IsSafeNestedType(Type type)
    {
        var name = type.FullName ?? type.Name;
        return !name.StartsWith("UnityEngine.")
               && !name.StartsWith("System.")
               && !name.StartsWith("Il2CppSystem.")
               && !name.StartsWith("BepInEx.")
               && !name.StartsWith("Il2CppInterop.")
               && !name.StartsWith("TMPro.");
    }

    private static bool ShouldInspectNumericMembers(string typeName) =>
        !typeName.StartsWith("UnityEngine.")
        && !typeName.StartsWith("System.")
        && !typeName.StartsWith("Il2CppSystem.")
        && !typeName.StartsWith("BepInEx.")
        && !typeName.StartsWith("Il2CppInterop.")
        && !typeName.StartsWith("TMPro.")
        && !typeName.StartsWith("DofusCoordinateBridge.");

    private static bool IsInfrastructureType(string typeName) =>
        typeName.StartsWith("UnityEngine.Transform")
        || typeName.StartsWith("UnityEngine.Camera")
        || typeName.StartsWith("DofusCoordinateBridge.");

    private static bool IsUiHint(Transform transform, string hierarchy, string joinedHints)
    {
        var lower = hierarchy.ToLowerInvariant();
        if (lower.Contains("tooltip") || lower.Contains("timeline") || lower.Contains("chat")
            || lower.Contains("button") || lower.Contains("popup") || lower.Contains("menu")
            || lower.Contains("window") || lower.Contains("hud") || lower.Contains("overlay")) return true;
        if (joinedHints.Contains("tmpro") || joinedHints.Contains("unityengine.ui")) return true;
        try
        {
            if (transform is RectTransform && joinedHints.Contains("canvasrenderer")) return true;
        }
        catch { }
        return false;
    }

    private static bool TryProject(Camera camera, Vector3 worldPosition, out Vector3 point)
    {
        point = default;
        if (camera == null || !IsFinite(worldPosition)) return false;
        try { point = camera.WorldToScreenPoint(worldPosition); }
        catch { return false; }
        if (!IsFinite(point) || point.z <= 0) return false;
        var width = Math.Max(1, camera.pixelWidth);
        var height = Math.Max(1, camera.pixelHeight);
        const float margin = 96.0f;
        return point.x >= -margin && point.y >= -margin
               && point.x <= width + margin && point.y <= height + margin;
    }

    private static double TransformPreviewScore(VisualTransformSnapshot item)
    {
        var score = item.VisualHint ? 30.0 : 0.0;
        if (item.UiHint) score -= 30.0;
        score += Math.Max(0, 15 - item.Depth);
        var lower = (item.Hierarchy + " " + string.Join(" ", item.ComponentHints ?? Array.Empty<string>())).ToLowerInvariant();
        if (lower.Contains("actor") || lower.Contains("fighter") || lower.Contains("character")
            || lower.Contains("entity") || lower.Contains("player") || lower.Contains("monster")) score += 40;
        return score;
    }

    private static string HierarchyPath(Transform transform, string sceneName)
    {
        var parts = new Stack<string>();
        Transform current = transform;
        while (current != null)
        {
            parts.Push(current.name ?? "unnamed");
            current = current.parent;
        }
        var instanceId = 0;
        try { instanceId = transform.GetInstanceID(); }
        catch { }
        var prefix = string.IsNullOrWhiteSpace(sceneName) ? "scene" : sceneName;
        return prefix + ":/" + string.Join("/", parts) + "#" + instanceId;
    }

    private static int HierarchyDepth(Transform transform)
    {
        var depth = 0;
        Transform current = transform;
        while (current != null && depth < 100)
        {
            depth++;
            current = current.parent;
        }
        return Math.Max(0, depth - 1);
    }

    private static bool IsFinite(Vector3 value) =>
        !float.IsNaN(value.x) && !float.IsInfinity(value.x)
        && !float.IsNaN(value.y) && !float.IsInfinity(value.y)
        && !float.IsNaN(value.z) && !float.IsInfinity(value.z)
        && Math.Abs(value.x) < 1000000 && Math.Abs(value.y) < 1000000 && Math.Abs(value.z) < 1000000;

    private static object Vector(Vector3 value) => new { x = value.x, y = value.y, z = value.z };

    private sealed class ReferenceEqualityComparer : IEqualityComparer<object>
    {
        public static readonly ReferenceEqualityComparer Instance = new();
        public new bool Equals(object left, object right) => ReferenceEquals(left, right);
        public int GetHashCode(object value) => System.Runtime.CompilerServices.RuntimeHelpers.GetHashCode(value);
    }
}
