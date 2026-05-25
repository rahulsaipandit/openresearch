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

# Interview Research schemas
from .interview import (
    InterviewPipelineInput, FitVerdict, CompanyProfile,
    QuestionSet, STARAnswer, AnswerSet, InterviewPrepBrief,
)

# Real Estate Research schemas
from .realestate import (
    RealEstatePipelineInput, RealEstateBrief, GeoResolution,
    MigrationSignal, MigrationSnapshot,
    LaborMarketSnapshot, IndustryShare,
    HousingMarketSnapshot, CostOfLivingSnapshot,
    DemandFactorsSnapshot, FloodRiskDetail, ClimateRiskSnapshot,
    RentalUnderwritingSnapshot, RegulatoryRiskSnapshot,
    NeighborhoodSnapshot, RentalAnalysis,
    AppraisalExtract, InspectionExtract, HOAExtract, TaxRecordExtract,
    LeaseExtract, FloodCertExtract, ListingExtract, CMAExtract, ZoningExtract,
    DocumentInsight, DocumentFactsBundle,
)

# Profile, tracker, and skills schemas
from .profile import MasterProfile, Experience, Education
from .tracker import ApplicationRecord, ApplicationTracker
from .skills import TrackedQuestion, ReviewResult, DueQuestion, SkillsBank

__all__ = [
    # stock
    "ValuationSummary", "SentimentSummary", "ResearchBrief", "StockPipelineInput",
    # board
    "OrgSnapshot", "TeamStatus", "OrgMetrics", "Project", "Risk", "Decision",
    "Initiative", "Conflict", "ActionItem", "BoardMemberView", "ConflictReport",
    "BoardBriefing", "BoardSessionInput",
    # interview
    "InterviewPipelineInput", "FitVerdict", "CompanyProfile",
    "QuestionSet", "STARAnswer", "AnswerSet", "InterviewPrepBrief",
    # profile / tracker / skills
    "MasterProfile", "Experience", "Education",
    "ApplicationRecord", "ApplicationTracker",
    "TrackedQuestion", "ReviewResult", "DueQuestion", "SkillsBank",
    # real estate
    "RealEstatePipelineInput", "RealEstateBrief", "GeoResolution",
    "MigrationSignal", "MigrationSnapshot",
    "LaborMarketSnapshot", "IndustryShare",
    "HousingMarketSnapshot", "CostOfLivingSnapshot",
    "DemandFactorsSnapshot", "FloodRiskDetail", "ClimateRiskSnapshot",
    "RentalUnderwritingSnapshot", "RegulatoryRiskSnapshot",
    "NeighborhoodSnapshot", "RentalAnalysis",
    "AppraisalExtract", "InspectionExtract", "HOAExtract", "TaxRecordExtract",
    "LeaseExtract", "FloodCertExtract", "ListingExtract", "CMAExtract", "ZoningExtract",
    "DocumentInsight", "DocumentFactsBundle",
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
