// Compatibility metadata for Dofus IL2CPP interop builds.
//
// Some generated Il2Cppmscorlib versions expose compiler-services nullable
// attribute types without the constructors expected by the modern Roslyn
// compiler.  Source-local definitions take precedence during this plugin
// build and prevent CS0656 while remaining harmless runtime metadata.
#pragma warning disable 0436
using System;

namespace System.Runtime.CompilerServices
{
    [AttributeUsage(
        AttributeTargets.Class |
        AttributeTargets.Event |
        AttributeTargets.Field |
        AttributeTargets.GenericParameter |
        AttributeTargets.Module |
        AttributeTargets.Parameter |
        AttributeTargets.Property |
        AttributeTargets.ReturnValue |
        AttributeTargets.Struct,
        AllowMultiple = false,
        Inherited = false)]
    internal sealed class NullableAttribute : Attribute
    {
        public readonly byte[] NullableFlags;

        public NullableAttribute(byte flag)
        {
            NullableFlags = new[] { flag };
        }

        public NullableAttribute(byte[] flags)
        {
            NullableFlags = flags ?? Array.Empty<byte>();
        }
    }

    [AttributeUsage(
        AttributeTargets.Class |
        AttributeTargets.Delegate |
        AttributeTargets.Interface |
        AttributeTargets.Method |
        AttributeTargets.Module |
        AttributeTargets.Struct,
        AllowMultiple = false,
        Inherited = false)]
    internal sealed class NullableContextAttribute : Attribute
    {
        public readonly byte Flag;

        public NullableContextAttribute(byte flag)
        {
            Flag = flag;
        }
    }

    [AttributeUsage(
        AttributeTargets.Class |
        AttributeTargets.Delegate |
        AttributeTargets.Interface |
        AttributeTargets.Method |
        AttributeTargets.Module |
        AttributeTargets.Struct,
        AllowMultiple = false,
        Inherited = false)]
    internal sealed class NullablePublicOnlyAttribute : Attribute
    {
        public readonly bool IncludesInternals;

        public NullablePublicOnlyAttribute(bool includesInternals)
        {
            IncludesInternals = includesInternals;
        }
    }
}
#pragma warning restore 0436
