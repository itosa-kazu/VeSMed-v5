"""可运行的动态临床架构比较原型。

本包只验证形式语义与工程不变量，不作临床有效性声明。
"""

from .contract import (
    ArchitectureCandidate,
    CapabilityResult,
    ClockSet,
    InfoState,
    QueryKind,
    QuerySpec,
    ResultStatus,
    Scope,
    SemanticRole,
    SourceArtifact,
    Track,
)

__all__ = [
    "ArchitectureCandidate",
    "CapabilityResult",
    "ClockSet",
    "InfoState",
    "QueryKind",
    "QuerySpec",
    "ResultStatus",
    "Scope",
    "SemanticRole",
    "SourceArtifact",
    "Track",
]
