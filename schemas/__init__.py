# Legacy ML schemas (kept for backwards compatibility)
from .problem_spec import ProblemSpec, TaskType, EvalMetric, Constraint
from .data_health import (
    DataHealthReport, FeatureInsight, DataQualityFlag,
    CorrelationPair, Severity,
)
from .methods_catalog import MethodSpec, MethodsCatalog, ComplexityLevel
from .dataset_diagnostics import DatasetDiagnosticsReport
from .data_prep import DataPrepReport
from .execution_result import (
    ExecutionResult, ExecutionStatus, ModelArtifact,
    EvaluationReport, MethodScore, RiskFlag, FailedMethodSummary,
)

# Stock Research schemas
from .stock import (
    ValuationSummary, SentimentSummary, ResearchBrief, StockPipelineInput,
)

# Executive Board schemas
from .board import (
    OrgSnapshot, TeamStatus, OrgMetrics, Project, Risk, Decision,
    Initiative, Conflict, ActionItem, BoardMemberView, ConflictReport,
    BoardBriefing, BoardSessionInput,
)

__all__ = [
    # stock
    "ValuationSummary", "SentimentSummary", "ResearchBrief", "StockPipelineInput",
    # board
    "OrgSnapshot", "TeamStatus", "OrgMetrics", "Project", "Risk", "Decision",
    "Initiative", "Conflict", "ActionItem", "BoardMemberView", "ConflictReport",
    "BoardBriefing", "BoardSessionInput",
    # legacy ML
    "ProblemSpec", "TaskType", "EvalMetric", "Constraint",
    "DataHealthReport", "FeatureInsight", "DataQualityFlag",
    "CorrelationPair", "Severity",
    "MethodSpec", "MethodsCatalog", "ComplexityLevel",
    "DatasetDiagnosticsReport",
    "DataPrepReport",
    "ExecutionResult", "ExecutionStatus", "ModelArtifact",
    "EvaluationReport", "MethodScore", "RiskFlag", "FailedMethodSummary",
]
