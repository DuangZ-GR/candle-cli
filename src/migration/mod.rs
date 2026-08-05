pub mod schema;

pub use schema::{
    ensure_compatible_schema, ApiArgument, ApiTraceRecord, DiagnosticCategory, DiagnosticEvidence,
    DiagnosticRecord, EvidenceKind, ExecutionMode, Framework, MappingResolution, MappingStatus,
    NumericSummary, RecordKind, RiskLevel, RuntimeError, ScanCallKind, ScanFinding, ScanIssue,
    ScanReport, ScanSummary, SchemaError, Severity, SourceLocation, ValueKind, ValueSummary,
    SCHEMA_VERSION,
};
