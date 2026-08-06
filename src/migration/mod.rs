pub mod schema;

pub use schema::{
    ensure_compatible_schema, ApiArgument, ApiTraceRecord, DiagnosticCategory, DiagnosticEvidence,
    DiagnosticRecord, EvidenceKind, ExecutionMode, Framework, MappingResolution, MappingStatus,
    MigrationRunArtifacts, MigrationRunError, MigrationRunReport, MigrationRunStep,
    MigrationRunSummary, MsprobeImportIssue, MsprobeImportReport, NumericSummary, RecordKind,
    RewriteApplyReport, RewriteEdit, RewriteFile, RewriteIssue, RewritePlanReport,
    RewriteRollbackReport, RewriteValidationReport, RiskLevel, RuntimeError, ScanCallKind,
    ScanFinding, ScanIssue, ScanReport, ScanSummary, SchemaError, Severity, SourceLocation,
    TraceComparisonResult, ValueKind, ValueSummary, SCHEMA_VERSION,
};
