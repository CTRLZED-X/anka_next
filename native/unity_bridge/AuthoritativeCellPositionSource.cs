using System.Reflection;
using System.Runtime.CompilerServices;
using UnityEngine;

namespace DofusCoordinateBridge;

public sealed class CellSourceValidationSample
{
    public long? ActorId { get; set; }
    public long? EntityId { get; set; }
    public int CellId { get; set; }
    public string ActorHierarchy { get; set; }
    public string Mode { get; set; }
    public float WorldError { get; set; }
    public float PlanarError { get; set; }
    public float VerticalError { get; set; }
    public int NearestCellId { get; set; }
    public bool AssociationCorrect { get; set; }
    public string ObservedAtUtc { get; set; }
}

/// <summary>
/// Resolves Dofus's live cell-id to Vector3 converter by semantic signature
/// instead of compiling against an obfuscated member name. The selected method
/// must return a nearly complete, distinct 560-cell position set. R5.172
/// certifies projection independently by matching exact rendered cell::<id>
/// anchors to this grid; actor placement validation remains diagnostic/legacy.
/// </summary>
public sealed class AuthoritativeCellPositionSource
{
    public const int CellCount = 560;
    public const string SourceType =
        "Core.Features.Roleplay.World.GridGenerator.CustomGridGenerator";
    public const string SourceMember =
        "runtime-discovered UnityEngine.Vector3 <method>(System.Int32)";
    public const string CurrentAccessor =
        "UnityEngine.Resources.FindObjectsOfTypeAll<Component>() filtered by exact/full/simple runtime type plus reflected static accessors";
    private const float MaximumPlanarValidationError = 5.0f;
    private const int RequiredDistinctCells = 2;
    private const int MinimumValidConverterPositions = 500;
    private const int MinimumDistinctConverterPositions = 500;
    private static Type _cachedGeneratorRuntimeType;

    private readonly Component _generator;
    private readonly MethodInfo _converterMethod;
    private readonly Func<int, Vector3> _converter;
    private readonly string _converterInvocationMode;
    private readonly int _converterValidPositions;
    private readonly int _converterDistinctPositions;
    private readonly Dictionary<string, CellSourceValidationSample> _acceptedSamples = new();
    private readonly List<CellSourceValidationSample> _recentSamples = new();
    private string _mode = "UNSELECTED";
    private string _lastError;
    private bool _structuralProjectionVerified;
    private string _structuralProjectionEvidence;

    private AuthoritativeCellPositionSource(
        Component generator,
        ConverterCandidate converter)
    {
        _generator = generator;
        _converterMethod = converter.Method;
        _converter = converter.Invoke;
        _converterInvocationMode = converter.InvocationMode;
        _converterValidPositions = converter.ValidPositions;
        _converterDistinctPositions = converter.DistinctPositions;
    }

    public bool Verified =>
        _acceptedSamples.Values.Select(sample => sample.CellId).Distinct().Count() >= RequiredDistinctCells
        && _acceptedSamples.Values.All(sample => sample.AssociationCorrect);

    public bool ProjectionVerified => Verified || _structuralProjectionVerified;

    public int DistinctValidatedCells =>
        _acceptedSamples.Values.Select(sample => sample.CellId).Distinct().Count();

    public int ValidatedActors =>
        _acceptedSamples.Values
            .Select(sample => sample.EntityId?.ToString() ?? sample.ActorId?.ToString())
            .Where(value => !string.IsNullOrWhiteSpace(value))
            .Distinct(StringComparer.Ordinal)
            .Count();

    public string Mode => _mode;
    public string LastError => _lastError;
    public string SelectedMember => _converterMethod == null
        ? SourceMember
        : MethodSignature(_converterMethod);
    public string ConverterInvocationMode => _converterInvocationMode;

    public int GeneratorInstanceId
    {
        get
        {
            try { return _generator == null ? 0 : _generator.GetInstanceID(); }
            catch { return 0; }
        }
    }

    public GameObject SourceObject
    {
        get
        {
            try { return _generator == null ? null : _generator.gameObject; }
            catch { return null; }
        }
    }

    public static bool TryDiscover(
        out AuthoritativeCellPositionSource source,
        out object diagnostics,
        out string error)
    {
        source = null;
        diagnostics = null;
        error = null;

        var candidates = DiscoverGeneratorCandidates(out var accessorDiagnostics, out var discoveryErrors);
        foreach (var discoveryError in discoveryErrors)
            error = Append(error, discoveryError);

        var inspected = new List<object>();
        AuthoritativeCellPositionSource best = null;
        var bestValid = -1;
        var bestDistinct = -1;
        var bestActive = false;

        foreach (var generator in candidates)
        {
            var converterCandidates = DiscoverConverterCandidates(generator);
            var accepted = converterCandidates
                .Where(candidate => candidate.Accepted)
                .OrderByDescending(candidate => candidate.ValidPositions)
                .ThenByDescending(candidate => candidate.DistinctPositions)
                .ThenBy(candidate => candidate.Signature, StringComparer.Ordinal)
                .FirstOrDefault();
            var active = Active(generator);

            inspected.Add(new
            {
                instance_id = InstanceId(generator),
                hierarchy = Hierarchy(generator),
                active,
                map_metadata = "OPTIONAL_NOT_REQUIRED",
                selected_converter = accepted?.Signature,
                selected_invocation_mode = accepted?.InvocationMode,
                valid_positions = accepted?.ValidPositions ?? 0,
                distinct_positions = accepted?.DistinctPositions ?? 0,
                converter_candidates = converterCandidates.Select(candidate => new
                {
                    signature = candidate.Signature,
                    invocation_mode = candidate.InvocationMode,
                    valid_positions = candidate.ValidPositions,
                    distinct_positions = candidate.DistinctPositions,
                    invocation_failures = candidate.InvocationFailures,
                    accepted = candidate.Accepted,
                    rejection = candidate.Rejection,
                    first_error = candidate.FirstError
                }).ToArray()
            });

            if (accepted == null) continue;
            var better = accepted.ValidPositions > bestValid
                         || (accepted.ValidPositions == bestValid
                             && accepted.DistinctPositions > bestDistinct)
                         || (accepted.ValidPositions == bestValid
                             && accepted.DistinctPositions == bestDistinct
                             && active && !bestActive);
            if (!better) continue;

            best = new AuthoritativeCellPositionSource(generator, accepted);
            bestValid = accepted.ValidPositions;
            bestDistinct = accepted.DistinctPositions;
            bestActive = active;
        }

        if (best != null && _cachedGeneratorRuntimeType == null)
        {
            try { _cachedGeneratorRuntimeType = best._generator.GetType(); }
            catch { }
        }

        diagnostics = new
        {
            source_type = SourceType,
            source_member_contract = SourceMember,
            current_accessor = CurrentAccessor,
            minimum_valid_positions = MinimumValidConverterPositions,
            minimum_distinct_positions = MinimumDistinctConverterPositions,
            generator_candidate_count = candidates.Count,
            accessor_discovery = accessorDiagnostics,
            candidates = inspected,
            selected = best == null
                ? null
                : new
                {
                    generator_instance_id = best.GeneratorInstanceId,
                    hierarchy = Hierarchy(best._generator),
                    runtime_type = best._generator?.GetType()?.FullName,
                    converter = best.SelectedMember,
                    invocation_mode = best.ConverterInvocationMode,
                    valid_positions = best._converterValidPositions,
                    distinct_positions = best._converterDistinctPositions
                }
        };

        if (best == null)
        {
            error = Append(
                error,
                "No live Dofus CustomGridGenerator exposed a trustworthy Vector3 converter with one Int32 parameter.");
            return false;
        }

        source = best;
        return true;
    }

    public void Validate(IEnumerable<ActorRuntimeMatch> actors)
    {
        _recentSamples.Clear();
        var reliable = (actors ?? Array.Empty<ActorRuntimeMatch>())
            .Where(actor => actor != null
                            && actor.CellId.HasValue
                            && actor.CellId.Value >= 0
                            && actor.CellId.Value < CellCount
                            && (actor.Confidence >= 0.80 || actor.IsPlayerControlled))
            .GroupBy(actor => actor.EntityId?.ToString() ?? actor.ActorId?.ToString() ?? actor.Hierarchy)
            .Select(group => group.OrderByDescending(actor => actor.Confidence).First())
            .ToList();
        if (reliable.Count == 0)
        {
            _lastError = "No exact actor placement is available to validate the Dofus cell-position source.";
            return;
        }

        _structuralProjectionVerified = false;
        _structuralProjectionEvidence = null;
        var direct = BuildPositions("DIRECT_DOFUS_WORLD");
        var transformed = BuildPositions("GENERATOR_TRANSFORM_POINT");
        var directSamples = ScoreMode(direct, "DIRECT_DOFUS_WORLD", reliable);
        var transformedSamples = ScoreMode(transformed, "GENERATOR_TRANSFORM_POINT", reliable);
        var directScore = ModeScore(directSamples);
        var transformedScore = ModeScore(transformedSamples);
        var selected = directScore <= transformedScore ? directSamples : transformedSamples;
        _mode = directScore <= transformedScore ? "DIRECT_DOFUS_WORLD" : "GENERATOR_TRANSFORM_POINT";
        _recentSamples.AddRange(selected);

        foreach (var sample in selected.Where(sample =>
                     sample.AssociationCorrect && sample.PlanarError <= MaximumPlanarValidationError))
        {
            var key = $"{sample.EntityId?.ToString() ?? sample.ActorId?.ToString() ?? sample.ActorHierarchy}:{sample.CellId}";
            _acceptedSamples[key] = sample;
        }

        var incorrect = selected.Where(sample => !sample.AssociationCorrect).ToList();
        if (incorrect.Count > 0)
        {
            _lastError =
                $"The Dofus source associated {incorrect.Count} actor placement(s) with another cell.";
            return;
        }
        var inaccurate = selected.Where(sample => sample.PlanarError > MaximumPlanarValidationError).ToList();
        if (inaccurate.Count > 0)
        {
            _lastError =
                $"The Dofus source exceeded the {MaximumPlanarValidationError:0.##} world-unit validation tolerance.";
            return;
        }
        if (!Verified)
        {
            _lastError =
                $"Validated {DistinctValidatedCells}/{RequiredDistinctCells} distinct actor cells. Another actor placement or movement is required.";
            return;
        }
        _lastError = null;
    }

    public bool SelectStructuralProjectionMode(string mode, string evidence)
    {
        if (mode != "DIRECT_DOFUS_WORLD" && mode != "GENERATOR_TRANSFORM_POINT")
        {
            _lastError = "Unsupported structural projection mode: " + mode;
            return false;
        }
        var positions = BuildPositions(mode);
        var finite = positions.Count(IsFinite);
        var distinct = positions
            .Where(IsFinite)
            .Select(position => $"{Round(position.x)}|{Round(position.y)}|{Round(position.z)}")
            .Distinct(StringComparer.Ordinal)
            .Count();
        if (finite < MinimumValidConverterPositions || distinct < MinimumDistinctConverterPositions)
        {
            _lastError = $"Structural projection mode {mode} exposed only {finite} finite and {distinct} distinct cells.";
            return false;
        }
        _mode = mode;
        _structuralProjectionVerified = true;
        _structuralProjectionEvidence = evidence;
        _lastError = null;
        return true;
    }

    public IReadOnlyList<Vector3> SnapshotPositionsForMode(string mode) => BuildPositions(mode);

    public bool TryGetWorldPosition(int cellId, out Vector3 world)
    {
        world = default;
        if (cellId < 0 || cellId >= CellCount || _generator == null || _converter == null || _mode == "UNSELECTED")
            return false;
        try
        {
            var raw = _converter(cellId);
            world = _mode == "GENERATOR_TRANSFORM_POINT"
                ? _generator.transform.TransformPoint(raw)
                : raw;
            return IsFinite(world);
        }
        catch (Exception exception)
        {
            _lastError = $"Dofus cell conversion failed for cell {cellId} using {SelectedMember}: {RootMessage(exception)}";
            return false;
        }
    }

    public IReadOnlyList<Vector3> SnapshotPositions()
    {
        var result = new List<Vector3>(CellCount);
        for (var cellId = 0; cellId < CellCount; cellId++)
        {
            result.Add(TryGetWorldPosition(cellId, out var world)
                ? world
                : new Vector3(float.NaN, float.NaN, float.NaN));
        }
        return result;
    }

    public string TransformSignature()
    {
        try
        {
            var transform = _generator.transform;
            var matrix = transform.localToWorldMatrix;
            return string.Join("|", new[]
            {
                GeneratorInstanceId.ToString(),
                SelectedMember,
                _mode,
                Round(matrix.m00), Round(matrix.m01), Round(matrix.m02), Round(matrix.m03),
                Round(matrix.m10), Round(matrix.m11), Round(matrix.m12), Round(matrix.m13),
                Round(matrix.m20), Round(matrix.m21), Round(matrix.m22), Round(matrix.m23)
            });
        }
        catch
        {
            return $"{GeneratorInstanceId}|{SelectedMember}|{_mode}|UNAVAILABLE";
        }
    }

    public object Summary() => new
    {
        type = SourceType,
        member_contract = SourceMember,
        selected_member = SelectedMember,
        converter_invocation_mode = _converterInvocationMode,
        converter_valid_positions = _converterValidPositions,
        converter_distinct_positions = _converterDistinctPositions,
        current_accessor = CurrentAccessor,
        generator_instance_id = GeneratorInstanceId,
        hierarchy = Hierarchy(_generator),
        mode = _mode,
        verified = Verified,
        projection_verified = ProjectionVerified,
        structural_projection_verified = _structuralProjectionVerified,
        structural_projection_evidence = _structuralProjectionEvidence,
        required_distinct_cells = RequiredDistinctCells,
        distinct_validated_cells = DistinctValidatedCells,
        validated_actors = ValidatedActors,
        maximum_planar_validation_error = MaximumPlanarValidationError,
        last_error = _lastError,
        recent_samples = _recentSamples.Take(40).ToArray(),
        accepted_samples = _acceptedSamples.Values.Take(100).ToArray()
    };

    private Vector3[] BuildPositions(string mode)
    {
        var result = new Vector3[CellCount];
        for (var cellId = 0; cellId < CellCount; cellId++)
        {
            try
            {
                var raw = _converter(cellId);
                result[cellId] = mode == "GENERATOR_TRANSFORM_POINT"
                    ? _generator.transform.TransformPoint(raw)
                    : raw;
            }
            catch
            {
                result[cellId] = new Vector3(float.NaN, float.NaN, float.NaN);
            }
        }
        return result;
    }

    private static List<Component> DiscoverGeneratorCandidates(
        out object diagnostics,
        out List<string> errors)
    {
        var candidates = new List<Component>();
        var resourceCount = 0;
        var scannedComponentCount = 0;
        var reflected = new List<object>();
        errors = new List<string>();

        var runtimeType = ResolveGeneratorRuntimeType(out var typeDiagnostics, out var typeError);
        if (!string.IsNullOrWhiteSpace(typeError)) errors.Add(typeError);

        // Always keep the scene/resource scan available.  Exact full-name
        // resolution is preferred, but game updates may move the generated
        // IL2CPP wrapper to another namespace/assembly.  In that case a
        // simple-name candidate is still only accepted after the existing
        // 560-cell semantic converter probe, so this fallback is fail-closed
        // rather than an assembly-name guess.
        try
        {
            foreach (var candidate in Resources.FindObjectsOfTypeAll<Component>())
            {
                if (candidate == null) continue;
                scannedComponentCount++;
                if (!MatchesGeneratorType(candidate, runtimeType)) continue;
                candidates.Add(candidate);
                resourceCount++;
            }
        }
        catch (Exception exception)
        {
            errors.Add("Grid resource scan failed: " + RootMessage(exception));
        }

        if (runtimeType != null)
        {
            try
            {
                foreach (var field in runtimeType.GetFields(BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic)
                             .Where(field => runtimeType.IsAssignableFrom(field.FieldType)))
                {
                    try
                    {
                        var value = field.GetValue(null) as Component;
                        if (value != null) candidates.Add(value);
                        reflected.Add(new
                        {
                            kind = "field",
                            name = field.Name,
                            signature = $"{field.FieldType.FullName} {field.Name}",
                            resolved = value != null,
                            error = (string)null
                        });
                    }
                    catch (Exception exception)
                    {
                        reflected.Add(new
                        {
                            kind = "field",
                            name = field.Name,
                            signature = $"{field.FieldType.FullName} {field.Name}",
                            resolved = false,
                            error = RootMessage(exception)
                        });
                    }
                }
            }
            catch (Exception exception)
            {
                errors.Add("Static grid-field discovery failed: " + RootMessage(exception));
            }

            try
            {
                foreach (var property in runtimeType.GetProperties(BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic)
                             .Where(property => property.GetIndexParameters().Length == 0
                                                && property.CanRead
                                                && runtimeType.IsAssignableFrom(property.PropertyType)))
                {
                    try
                    {
                        var value = property.GetValue(null) as Component;
                        if (value != null) candidates.Add(value);
                        reflected.Add(new
                        {
                            kind = "property",
                            name = property.Name,
                            signature = $"{property.PropertyType.FullName} {property.Name}",
                            resolved = value != null,
                            error = (string)null
                        });
                    }
                    catch (Exception exception)
                    {
                        reflected.Add(new
                        {
                            kind = "property",
                            name = property.Name,
                            signature = $"{property.PropertyType.FullName} {property.Name}",
                            resolved = false,
                            error = RootMessage(exception)
                        });
                    }
                }
            }
            catch (Exception exception)
            {
                errors.Add("Static grid-property discovery failed: " + RootMessage(exception));
            }
        }

        var unique = candidates
            .Where(candidate => candidate != null)
            .GroupBy(CandidateKey)
            .Select(group => group.First())
            .ToList();

        diagnostics = new
        {
            compile_time_dofus_dependency = false,
            runtime_type = typeDiagnostics,
            resource_components_scanned = scannedComponentCount,
            resource_scan_count = resourceCount,
            reflected_static_accessors = reflected,
            unique_candidate_count = unique.Count,
            errors = errors.ToArray()
        };
        return unique;
    }

    private static Type ResolveGeneratorRuntimeType(out object diagnostics, out string error)
    {
        error = null;
        if (_cachedGeneratorRuntimeType != null)
        {
            diagnostics = new
            {
                resolved = true,
                source_type = SourceType,
                assembly = _cachedGeneratorRuntimeType.Assembly.FullName,
                cached = true
            };
            return _cachedGeneratorRuntimeType;
        }
        var inspected = new List<string>();
        foreach (var assembly in AppDomain.CurrentDomain.GetAssemblies())
        {
            try
            {
                inspected.Add(assembly.GetName().Name ?? assembly.FullName ?? "UNKNOWN");
                var type = assembly.GetType(SourceType, throwOnError: false, ignoreCase: false);
                if (type == null) continue;
                _cachedGeneratorRuntimeType = type;
                diagnostics = new
                {
                    resolved = true,
                    source_type = SourceType,
                    assembly = assembly.FullName,
                    scanned_assemblies = inspected.Count,
                    cached = false
                };
                return type;
            }
            catch (Exception exception)
            {
                error = Append(error, "Assembly type scan failed: " + RootMessage(exception));
            }
        }
        diagnostics = new
        {
            resolved = false,
            source_type = SourceType,
            scanned_assemblies = inspected.Count,
            assemblies = inspected.Take(128).ToArray()
        };
        error = Append(error, $"Runtime type {SourceType} was not found in loaded IL2CPP interop assemblies.");
        return null;
    }

    private static bool MatchesGeneratorType(Component candidate, Type runtimeType)
    {
        try
        {
            if (runtimeType != null && runtimeType.IsInstanceOfType(candidate)) return true;
            var type = candidate.GetType();
            return string.Equals(type.FullName, SourceType, StringComparison.Ordinal)
                   || string.Equals(type.Name, "CustomGridGenerator", StringComparison.Ordinal);
        }
        catch
        {
            return false;
        }
    }

    private static List<ConverterCandidate> DiscoverConverterCandidates(Component generator)
    {
        var type = generator?.GetType();
        if (type == null)
        {
            return new List<ConverterCandidate>
            {
                ConverterCandidate.DiscoveryFailure("Generator runtime type is unavailable.")
            };
        }
        MethodInfo[] methods;
        try
        {
            methods = type.GetMethods(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
        }
        catch (Exception exception)
        {
            return new List<ConverterCandidate>
            {
                ConverterCandidate.DiscoveryFailure("Method enumeration failed: " + RootMessage(exception))
            };
        }

        var matching = methods
            .Where(method => !method.IsStatic
                             && !method.ContainsGenericParameters
                             && method.ReturnType == typeof(Vector3))
            .Select(method => new { Method = method, Parameters = method.GetParameters() })
            .Where(item => item.Parameters.Length == 1 && IsInt32(item.Parameters[0].ParameterType))
            .Select(item => item.Method)
            .Distinct(MethodInfoIdentityComparer.Instance)
            .OrderBy(method => method.Name, StringComparer.Ordinal)
            .ThenBy(MethodSignature, StringComparer.Ordinal)
            .ToList();

        if (matching.Count == 0)
        {
            return new List<ConverterCandidate>
            {
                ConverterCandidate.DiscoveryFailure(
                    "No instance method returned UnityEngine.Vector3 with one Int32 parameter.")
            };
        }

        return matching.Select(method => ProbeConverter(generator, method)).ToList();
    }

    private static ConverterCandidate ProbeConverter(Component generator, MethodInfo method)
    {
        var candidate = new ConverterCandidate
        {
            Method = method,
            Signature = MethodSignature(method)
        };

        try
        {
            candidate.Invoke = CreateInvoker(generator, method, out var invocationMode);
            candidate.InvocationMode = invocationMode;
        }
        catch (Exception exception)
        {
            candidate.Rejection = "INVOKER_CREATION_FAILED";
            candidate.FirstError = RootMessage(exception);
            return candidate;
        }

        var keys = new HashSet<string>(StringComparer.Ordinal);
        for (var cellId = 0; cellId < CellCount; cellId++)
        {
            try
            {
                var point = candidate.Invoke(cellId);
                if (!IsFinite(point)) continue;
                candidate.ValidPositions++;
                keys.Add($"{Round(point.x)}:{Round(point.y)}:{Round(point.z)}");
            }
            catch (Exception exception)
            {
                candidate.InvocationFailures++;
                candidate.FirstError ??= RootMessage(exception);
            }
        }
        candidate.DistinctPositions = keys.Count;

        if (candidate.ValidPositions < MinimumValidConverterPositions)
        {
            candidate.Rejection =
                $"VALID_POSITION_COUNT_{candidate.ValidPositions}_BELOW_{MinimumValidConverterPositions}";
        }
        else if (candidate.DistinctPositions < MinimumDistinctConverterPositions)
        {
            candidate.Rejection =
                $"DISTINCT_POSITION_COUNT_{candidate.DistinctPositions}_BELOW_{MinimumDistinctConverterPositions}";
        }

        return candidate;
    }

    private static Func<int, Vector3> CreateInvoker(
        Component generator,
        MethodInfo method,
        out string invocationMode)
    {
        var parameter = method.GetParameters()[0].ParameterType;
        if (parameter == typeof(int))
        {
            try
            {
                var typed = (Func<int, Vector3>)method.CreateDelegate(typeof(Func<int, Vector3>), generator);
                invocationMode = "CACHED_DELEGATE";
                return typed;
            }
            catch
            {
                // Generated IL2CPP wrappers do not all support CreateDelegate.
                // Reflection remains safe because it invokes the same generated wrapper.
            }
        }

        invocationMode = "CACHED_METHODINFO_INVOKE";
        return cellId =>
        {
            var value = method.Invoke(generator, new object[] { cellId });
            if (value is Vector3 point) return point;
            throw new InvalidOperationException(
                $"{MethodSignature(method)} returned {value?.GetType().FullName ?? "null"} instead of UnityEngine.Vector3.");
        };
    }

    private static List<CellSourceValidationSample> ScoreMode(
        IReadOnlyList<Vector3> positions,
        string mode,
        IReadOnlyList<ActorRuntimeMatch> actors)
    {
        var samples = new List<CellSourceValidationSample>();
        foreach (var actor in actors)
        {
            var cellId = actor.CellId.Value;
            var expected = positions[cellId];
            if (!IsFinite(expected)) continue;
            var observed = actor.WorldPosition;
            var nearestCell = NearestCell(positions, observed);
            var dx = expected.x - observed.x;
            var dy = expected.y - observed.y;
            var dz = expected.z - observed.z;
            samples.Add(new CellSourceValidationSample
            {
                ActorId = actor.ActorId,
                EntityId = actor.EntityId,
                CellId = cellId,
                ActorHierarchy = actor.Hierarchy,
                Mode = mode,
                WorldError = (float)Math.Sqrt(dx * dx + dy * dy + dz * dz),
                PlanarError = (float)Math.Sqrt(dx * dx + dy * dy),
                VerticalError = Math.Abs(dz),
                NearestCellId = nearestCell,
                AssociationCorrect = nearestCell == cellId,
                ObservedAtUtc = DateTime.UtcNow.ToString("O")
            });
        }
        return samples;
    }

    private static double ModeScore(IReadOnlyList<CellSourceValidationSample> samples)
    {
        if (samples.Count == 0) return double.PositiveInfinity;
        var mismatches = samples.Count(sample => !sample.AssociationCorrect);
        return mismatches * 1000000.0 + samples.Average(sample => sample.PlanarError);
    }

    private static int NearestCell(IReadOnlyList<Vector3> positions, Vector3 observed)
    {
        var selected = -1;
        var selectedDistance = double.PositiveInfinity;
        for (var cellId = 0; cellId < positions.Count; cellId++)
        {
            var candidate = positions[cellId];
            if (!IsFinite(candidate)) continue;
            var dx = candidate.x - observed.x;
            var dy = candidate.y - observed.y;
            var distance = dx * dx + dy * dy;
            if (distance >= selectedDistance) continue;
            selectedDistance = distance;
            selected = cellId;
        }
        return selected;
    }

    private static bool IsFinite(Vector3 value) =>
        !float.IsNaN(value.x) && !float.IsInfinity(value.x)
        && !float.IsNaN(value.y) && !float.IsInfinity(value.y)
        && !float.IsNaN(value.z) && !float.IsInfinity(value.z)
        && Math.Abs(value.x) < 1000000
        && Math.Abs(value.y) < 1000000
        && Math.Abs(value.z) < 1000000;

    private static bool IsInt32(Type type) =>
        type == typeof(int)
        || string.Equals(type.FullName, "System.Int32", StringComparison.Ordinal)
        || string.Equals(type.Name, "Int32", StringComparison.Ordinal);

    private static string Round(float value) => Math.Round(value, 4).ToString("R");

    private static string MethodSignature(MethodInfo method)
    {
        if (method == null) return SourceMember;
        var parameters = string.Join(
            ", ",
            method.GetParameters().Select(parameter => parameter.ParameterType.FullName ?? parameter.ParameterType.Name));
        return $"{method.ReturnType.FullName ?? method.ReturnType.Name} "
               + $"{method.DeclaringType?.FullName ?? SourceType}.{method.Name}({parameters})";
    }

    private static string CandidateKey(Component generator)
    {
        var instanceId = InstanceId(generator);
        return instanceId != 0
            ? "UNITY:" + instanceId
            : "MANAGED:" + RuntimeHelpers.GetHashCode(generator);
    }

    private static int InstanceId(Component generator)
    {
        try { return generator == null ? 0 : generator.GetInstanceID(); }
        catch { return 0; }
    }

    private static string Hierarchy(Component generator)
    {
        try
        {
            if (generator == null) return null;
            var parts = new List<string>();
            var current = generator.transform;
            while (current != null && parts.Count < 64)
            {
                parts.Add(current.name);
                current = current.parent;
            }
            parts.Reverse();
            return string.Join("/", parts);
        }
        catch
        {
            return null;
        }
    }

    private static bool Active(Component generator)
    {
        try { return generator != null && generator.gameObject.activeInHierarchy; }
        catch { return false; }
    }

    private static string RootMessage(Exception exception)
    {
        while (exception is TargetInvocationException && exception.InnerException != null)
            exception = exception.InnerException;
        return exception.Message;
    }

    private static string Append(string current, string addition) =>
        string.IsNullOrWhiteSpace(current) ? addition : current + " " + addition;

    private sealed class ConverterCandidate
    {
        public MethodInfo Method { get; set; }
        public Func<int, Vector3> Invoke { get; set; }
        public string Signature { get; set; }
        public string InvocationMode { get; set; }
        public int ValidPositions { get; set; }
        public int DistinctPositions { get; set; }
        public int InvocationFailures { get; set; }
        public string Rejection { get; set; }
        public string FirstError { get; set; }
        public bool Accepted => Method != null
                                && Invoke != null
                                && ValidPositions >= MinimumValidConverterPositions
                                && DistinctPositions >= MinimumDistinctConverterPositions
                                && string.IsNullOrWhiteSpace(Rejection);

        public static ConverterCandidate DiscoveryFailure(string error) => new()
        {
            Signature = "UNRESOLVED",
            InvocationMode = "UNAVAILABLE",
            Rejection = "DISCOVERY_FAILED",
            FirstError = error
        };
    }

    private sealed class MethodInfoIdentityComparer : IEqualityComparer<MethodInfo>
    {
        public static readonly MethodInfoIdentityComparer Instance = new();

        public bool Equals(MethodInfo left, MethodInfo right)
        {
            if (ReferenceEquals(left, right)) return true;
            if (left == null || right == null) return false;
            try
            {
                return left.Module == right.Module && left.MetadataToken == right.MetadataToken;
            }
            catch
            {
                return string.Equals(MethodSignature(left), MethodSignature(right), StringComparison.Ordinal);
            }
        }

        public int GetHashCode(MethodInfo method)
        {
            if (method == null) return 0;
            try
            {
                return HashCode.Combine(method.Module, method.MetadataToken);
            }
            catch
            {
                return StringComparer.Ordinal.GetHashCode(MethodSignature(method));
            }
        }
    }
}
