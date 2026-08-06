use std::collections::BTreeMap;
use std::fmt::{Display, Formatter};

use serde::{Deserialize, Serialize};
use serde_json::Value;

pub const SCHEMA_VERSION: &str = "1.0";
const SUPPORTED_SCHEMA_MAJOR: u64 = 1;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SchemaError {
    message: String,
}

impl SchemaError {
    fn new(message: impl Into<String>) -> Self {
        Self {
            message: message.into(),
        }
    }
}

impl Display for SchemaError {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> std::fmt::Result {
        formatter.write_str(&self.message)
    }
}

impl std::error::Error for SchemaError {}

pub fn ensure_compatible_schema(version: &str) -> Result<(), SchemaError> {
    let (major, minor) = version
        .split_once('.')
        .ok_or_else(|| SchemaError::new(format!("invalid schema version: {version}")))?;
    let major = major
        .parse::<u64>()
        .map_err(|_| SchemaError::new(format!("invalid schema major version: {version}")))?;
    minor
        .parse::<u64>()
        .map_err(|_| SchemaError::new(format!("invalid schema minor version: {version}")))?;

    if major != SUPPORTED_SCHEMA_MAJOR {
        return Err(SchemaError::new(format!(
            "unsupported schema major version {major}; supported major version is {SUPPORTED_SCHEMA_MAJOR}"
        )));
    }
    Ok(())
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum RecordKind {
    ApiTrace,
    Diagnostic,
    ScanReport,
    TraceComparison,
    MsprobeImportReport,
    RewritePlan,
    RewriteApplyReport,
    RewriteRollbackReport,
    MigrationRunReport,
    #[serde(other)]
    Unknown,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct MigrationRunStep {
    pub name: String,
    pub status: String,
    pub duration_ms: f64,
    pub details: Value,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct MigrationRunSummary {
    pub files_discovered: u64,
    pub files_scanned: u64,
    pub finding_count: u64,
    pub scan_issue_count: u64,
    pub mapping_counts: BTreeMap<String, u64>,
    pub files_changed: u64,
    pub edit_count: u64,
    pub rewrite_issue_count: u64,
    pub validation_status: String,
    pub trace_equivalent: Option<bool>,
    pub first_divergence_category: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct MigrationRunArtifacts {
    pub transaction_manifest: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct MigrationRunError {
    pub stage: String,
    #[serde(rename = "type")]
    pub error_type: String,
    pub message: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub rollback_error: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct MigrationRunReport {
    pub schema_version: String,
    pub record_kind: RecordKind,
    pub run_id: String,
    pub project_root: String,
    #[serde(rename = "mode")]
    pub mode_name: String,
    pub status: String,
    pub verified: bool,
    pub started_at: String,
    pub duration_ms: f64,
    pub steps: Vec<MigrationRunStep>,
    pub summary: MigrationRunSummary,
    pub artifacts: MigrationRunArtifacts,
    pub error: Option<MigrationRunError>,
}

impl MigrationRunReport {
    pub fn validate(&self) -> Result<(), SchemaError> {
        ensure_compatible_schema(&self.schema_version)?;
        if self.record_kind != RecordKind::MigrationRunReport {
            return Err(SchemaError::new(
                "record_kind must be migration_run_report",
            ));
        }
        validate_non_empty("migration run_id", &self.run_id)?;
        validate_non_empty("migration project_root", &self.project_root)?;
        validate_non_empty("migration started_at", &self.started_at)?;
        if !matches!(self.mode_name.as_str(), "preview" | "apply") {
            return Err(SchemaError::new(
                "migration mode must be preview or apply",
            ));
        }
        if !matches!(
            self.status.as_str(),
            "previewed" | "verified" | "divergent" | "rolled_back" | "failed"
        ) {
            return Err(SchemaError::new(
                "migration run has an invalid terminal status",
            ));
        }
        if !self.duration_ms.is_finite() || self.duration_ms < 0.0 {
            return Err(SchemaError::new(
                "migration duration_ms must be finite and non-negative",
            ));
        }
        if self.steps.is_empty() {
            return Err(SchemaError::new(
                "migration run must contain at least one step",
            ));
        }
        let mut step_names = std::collections::BTreeSet::new();
        for step in &self.steps {
            validate_non_empty("migration step name", &step.name)?;
            validate_non_empty("migration step status", &step.status)?;
            if !step.duration_ms.is_finite() || step.duration_ms < 0.0 {
                return Err(SchemaError::new(
                    "migration step duration must be finite and non-negative",
                ));
            }
            if !step_names.insert(&step.name) {
                return Err(SchemaError::new(
                    "migration step names must be unique",
                ));
            }
        }
        if self.summary.files_scanned > self.summary.files_discovered {
            return Err(SchemaError::new(
                "migration files_scanned must not exceed files_discovered",
            ));
        }
        validate_non_empty(
            "migration validation_status",
            &self.summary.validation_status,
        )?;
        if self.summary.trace_equivalent != Some(false)
            && self.summary.first_divergence_category.is_some()
        {
            return Err(SchemaError::new(
                "first divergence requires trace_equivalent=false",
            ));
        }
        if self.status == "verified" && (!self.verified || self.mode_name != "apply") {
            return Err(SchemaError::new(
                "verified migration status requires verified apply mode",
            ));
        }
        if self.verified && self.summary.validation_status != "passed" {
            return Err(SchemaError::new(
                "verified migration requires passed validation",
            ));
        }
        let failed = matches!(self.status.as_str(), "divergent" | "rolled_back" | "failed");
        if failed != self.error.is_some() {
            return Err(SchemaError::new(
                "migration failure status and error must agree",
            ));
        }
        if let Some(error) = &self.error {
            validate_non_empty("migration error stage", &error.stage)?;
            validate_non_empty("migration error type", &error.error_type)?;
            validate_non_empty("migration error message", &error.message)?;
        }
        if self.mode_name == "preview" && self.artifacts.transaction_manifest.is_some() {
            return Err(SchemaError::new(
                "preview migration must not contain a transaction manifest",
            ));
        }
        Ok(())
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ScanCallKind {
    Function,
    TensorMethod,
    Dynamic,
    #[serde(other)]
    Unknown,
}

impl ScanCallKind {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Function => "function",
            Self::TensorMethod => "tensor_method",
            Self::Dynamic => "dynamic",
            Self::Unknown => "unknown",
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum RiskLevel {
    Unclassified,
    Low,
    Medium,
    High,
    Critical,
    #[serde(other)]
    Unknown,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum MappingStatus {
    Exact,
    Difference,
    Unsupported,
    Unknown,
}

impl MappingStatus {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Exact => "exact",
            Self::Difference => "difference",
            Self::Unsupported => "unsupported",
            Self::Unknown => "unknown",
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct MappingResolution {
    pub source_api: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub target_api: Option<String>,
    pub status: MappingStatus,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub differences: Vec<String>,
    pub notes: String,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub evidence_urls: Vec<String>,
    pub source_framework_version: String,
    pub target_framework_version: String,
    pub knowledge_version: String,
}

impl RiskLevel {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Unclassified => "unclassified",
            Self::Low => "low",
            Self::Medium => "medium",
            Self::High => "high",
            Self::Critical => "critical",
            Self::Unknown => "unknown",
        }
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ScanFinding {
    pub finding_id: String,
    pub api: String,
    pub location: SourceLocation,
    pub call_kind: ScanCallKind,
    pub confidence: f64,
    pub risk_level: RiskLevel,
    pub mapping: MappingResolution,
    pub expression: String,
    pub positional_argument_count: u32,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub keyword_arguments: Vec<String>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ScanIssue {
    pub file: String,
    pub kind: String,
    pub message: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub line: Option<u32>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub column: Option<u32>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ScanSummary {
    pub finding_count: u64,
    pub unique_api_count: u64,
    pub direct_call_count: u64,
    pub tensor_method_count: u64,
    pub dynamic_call_count: u64,
    pub issue_count: u64,
    #[serde(default, skip_serializing_if = "BTreeMap::is_empty")]
    pub api_counts: BTreeMap<String, u64>,
    pub mapping_counts: BTreeMap<String, u64>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ScanReport {
    pub schema_version: String,
    pub record_kind: RecordKind,
    pub root: String,
    pub files_discovered: u64,
    pub files_scanned: u64,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub findings: Vec<ScanFinding>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub issues: Vec<ScanIssue>,
    pub summary: ScanSummary,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct TraceComparisonResult {
    pub schema_version: String,
    pub record_kind: RecordKind,
    pub source_count: u64,
    pub target_count: u64,
    pub aligned_count: u64,
    pub equivalent: bool,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub diagnostic: Option<DiagnosticRecord>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct MsprobeImportIssue {
    pub key: String,
    pub reason: String,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct MsprobeImportReport {
    pub schema_version: String,
    pub record_kind: RecordKind,
    pub framework: Framework,
    pub framework_version: String,
    pub run_id: String,
    pub input: String,
    pub output: String,
    pub records_imported: u64,
    pub records_skipped: u64,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub skipped: Vec<MsprobeImportIssue>,
}

impl MsprobeImportReport {
    pub fn validate(&self) -> Result<(), SchemaError> {
        ensure_compatible_schema(&self.schema_version)?;
        if self.record_kind != RecordKind::MsprobeImportReport {
            return Err(SchemaError::new(
                "record_kind must be msprobe_import_report",
            ));
        }
        if !matches!(self.framework, Framework::PyTorch | Framework::MindSpore) {
            return Err(SchemaError::new(
                "msprobe import framework must be pytorch or mindspore",
            ));
        }
        validate_non_empty("framework_version", &self.framework_version)?;
        validate_non_empty("run_id", &self.run_id)?;
        validate_non_empty("input", &self.input)?;
        validate_non_empty("output", &self.output)?;
        if self.records_imported == 0 {
            return Err(SchemaError::new(
                "msprobe import must contain at least one imported record",
            ));
        }
        if self.records_skipped != self.skipped.len() as u64 {
            return Err(SchemaError::new(
                "records_skipped must match the skipped issue count",
            ));
        }
        for issue in &self.skipped {
            validate_non_empty("skipped key", &issue.key)?;
            validate_non_empty("skipped reason", &issue.reason)?;
        }
        Ok(())
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct RewriteEdit {
    pub start: u64,
    pub end: u64,
    pub replacement: String,
    pub source_api: String,
    pub target_api: String,
    pub mapping_status: MappingStatus,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct RewriteFile {
    pub file: String,
    pub original_sha256: String,
    pub patched_sha256: String,
    pub encoding: String,
    pub edits: Vec<RewriteEdit>,
    pub diff: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct RewriteIssue {
    pub file: String,
    pub kind: String,
    pub message: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct RewritePlanReport {
    pub schema_version: String,
    pub record_kind: RecordKind,
    pub root: String,
    pub files_changed: u64,
    pub edit_count: u64,
    pub mapping_counts: BTreeMap<String, u64>,
    pub files: Vec<RewriteFile>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub issues: Vec<RewriteIssue>,
}

impl RewritePlanReport {
    pub fn validate(&self) -> Result<(), SchemaError> {
        ensure_compatible_schema(&self.schema_version)?;
        if self.record_kind != RecordKind::RewritePlan {
            return Err(SchemaError::new("record_kind must be rewrite_plan"));
        }
        validate_non_empty("rewrite root", &self.root)?;
        if self.files_changed != self.files.len() as u64 {
            return Err(SchemaError::new("files_changed must match files"));
        }
        let mut edit_count = 0;
        let mut mapping_counts = BTreeMap::from([
            ("exact".to_string(), 0_u64),
            ("difference".to_string(), 0_u64),
        ]);
        for file in &self.files {
            validate_non_empty("rewrite file", &file.file)?;
            validate_sha256("original_sha256", &file.original_sha256)?;
            validate_sha256("patched_sha256", &file.patched_sha256)?;
            if file.original_sha256 == file.patched_sha256 {
                return Err(SchemaError::new(
                    "rewrite original and patched hashes must differ",
                ));
            }
            validate_non_empty("rewrite encoding", &file.encoding)?;
            validate_non_empty("rewrite diff", &file.diff)?;
            if file.edits.is_empty() {
                return Err(SchemaError::new("rewrite file must contain edits"));
            }
            let mut previous_end = 0;
            for (index, edit) in file.edits.iter().enumerate() {
                if edit.end < edit.start {
                    return Err(SchemaError::new("rewrite edit end precedes start"));
                }
                if index > 0 && edit.start < previous_end {
                    return Err(SchemaError::new("rewrite edits overlap"));
                }
                previous_end = edit.end;
                validate_non_empty("rewrite replacement", &edit.replacement)?;
                validate_non_empty("rewrite source_api", &edit.source_api)?;
                validate_non_empty("rewrite target_api", &edit.target_api)?;
                let status = edit.mapping_status.as_str();
                if !matches!(
                    edit.mapping_status,
                    MappingStatus::Exact | MappingStatus::Difference
                ) {
                    return Err(SchemaError::new(
                        "rewrite mapping_status must be exact or difference",
                    ));
                }
                if edit.source_api != "<import>" {
                    *mapping_counts.entry(status.to_string()).or_insert(0) += 1;
                }
                edit_count += 1;
            }
        }
        if self.edit_count != edit_count {
            return Err(SchemaError::new("edit_count must match file edits"));
        }
        if self.mapping_counts != mapping_counts {
            return Err(SchemaError::new("mapping_counts must match rewrite edits"));
        }
        for issue in &self.issues {
            validate_non_empty("rewrite issue file", &issue.file)?;
            validate_non_empty("rewrite issue kind", &issue.kind)?;
            validate_non_empty("rewrite issue message", &issue.message)?;
        }
        Ok(())
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct RewriteApplyReport {
    pub schema_version: String,
    pub record_kind: RecordKind,
    pub transaction_id: String,
    pub files_changed: u64,
    pub manifest: String,
    pub status: String,
    pub verified: bool,
    pub validation: RewriteValidationReport,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct RewriteValidationReport {
    pub status: String,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub command: Vec<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub return_code: Option<i32>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub duration_ms: Option<f64>,
    #[serde(default, skip_serializing_if = "String::is_empty")]
    pub stdout: String,
    #[serde(default, skip_serializing_if = "String::is_empty")]
    pub stderr: String,
    #[serde(default)]
    pub stdout_truncated: bool,
    #[serde(default)]
    pub stderr_truncated: bool,
}

impl RewriteApplyReport {
    pub fn validate(&self) -> Result<(), SchemaError> {
        ensure_compatible_schema(&self.schema_version)?;
        if self.record_kind != RecordKind::RewriteApplyReport {
            return Err(SchemaError::new("record_kind must be rewrite_apply_report"));
        }
        validate_non_empty("transaction_id", &self.transaction_id)?;
        validate_non_empty("rewrite manifest", &self.manifest)?;
        if self.files_changed == 0 {
            return Err(SchemaError::new(
                "rewrite apply must change at least one file",
            ));
        }
        if self.status != "applied" {
            return Err(SchemaError::new("rewrite apply status must be applied"));
        }
        let expected_validation_status = if self.verified { "passed" } else { "not_run" };
        if self.validation.status != expected_validation_status {
            return Err(SchemaError::new(
                "rewrite verified flag does not match validation status",
            ));
        }
        if self.verified {
            if self.validation.command.is_empty()
                || self.validation.return_code != Some(0)
                || self
                    .validation
                    .duration_ms
                    .is_none_or(|duration| !duration.is_finite() || duration < 0.0)
            {
                return Err(SchemaError::new(
                    "verified rewrite requires a successful validation command",
                ));
            }
        }
        Ok(())
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct RewriteRollbackReport {
    pub schema_version: String,
    pub record_kind: RecordKind,
    pub transaction_id: String,
    pub files_restored: u64,
    pub status: String,
}

impl RewriteRollbackReport {
    pub fn validate(&self) -> Result<(), SchemaError> {
        ensure_compatible_schema(&self.schema_version)?;
        if self.record_kind != RecordKind::RewriteRollbackReport {
            return Err(SchemaError::new(
                "record_kind must be rewrite_rollback_report",
            ));
        }
        validate_non_empty("transaction_id", &self.transaction_id)?;
        if self.files_restored == 0 {
            return Err(SchemaError::new(
                "rewrite rollback must restore at least one file",
            ));
        }
        if self.status != "rolled_back" {
            return Err(SchemaError::new(
                "rewrite rollback status must be rolled_back",
            ));
        }
        Ok(())
    }
}

impl TraceComparisonResult {
    pub fn validate(&self) -> Result<(), SchemaError> {
        ensure_compatible_schema(&self.schema_version)?;
        if self.record_kind != RecordKind::TraceComparison {
            return Err(SchemaError::new("record_kind must be trace_comparison"));
        }
        if self.source_count == 0 || self.target_count == 0 {
            return Err(SchemaError::new(
                "trace comparison requires non-empty source and target traces",
            ));
        }
        if self.aligned_count > self.source_count || self.aligned_count > self.target_count {
            return Err(SchemaError::new(
                "aligned_count must not exceed either trace count",
            ));
        }
        if self.equivalent == self.diagnostic.is_some() {
            return Err(SchemaError::new(
                "equivalent comparison must omit diagnostic; divergent comparison must include it",
            ));
        }
        if let Some(diagnostic) = &self.diagnostic {
            diagnostic.validate()?;
            if !diagnostic.verified {
                return Err(SchemaError::new(
                    "trace comparison diagnostic must be verified",
                ));
            }
        }
        Ok(())
    }
}

impl ScanReport {
    pub fn validate(&self) -> Result<(), SchemaError> {
        ensure_compatible_schema(&self.schema_version)?;
        if self.record_kind != RecordKind::ScanReport {
            return Err(SchemaError::new("record_kind must be scan_report"));
        }
        validate_non_empty("root", &self.root)?;
        if self.files_scanned > self.files_discovered {
            return Err(SchemaError::new(
                "files_scanned must not exceed files_discovered",
            ));
        }

        let mut api_counts = BTreeMap::new();
        let mut direct_call_count = 0;
        let mut tensor_method_count = 0;
        let mut dynamic_call_count = 0;
        let mut mapping_counts = BTreeMap::new();
        for finding in &self.findings {
            validate_non_empty("finding_id", &finding.finding_id)?;
            validate_non_empty("api", &finding.api)?;
            validate_non_empty("expression", &finding.expression)?;
            finding.location.validate()?;
            finding
                .mapping
                .validate_for_finding(&finding.api, finding.risk_level)?;
            if !finding.confidence.is_finite() || !(0.0..=1.0).contains(&finding.confidence) {
                return Err(SchemaError::new(
                    "scan finding confidence must be a finite value between 0 and 1",
                ));
            }
            *api_counts.entry(finding.api.clone()).or_insert(0) += 1;
            *mapping_counts
                .entry(finding.mapping.status.as_str().to_string())
                .or_insert(0) += 1;
            match finding.call_kind {
                ScanCallKind::Function => direct_call_count += 1,
                ScanCallKind::TensorMethod => tensor_method_count += 1,
                ScanCallKind::Dynamic => dynamic_call_count += 1,
                ScanCallKind::Unknown => {}
            }
        }
        for issue in &self.issues {
            validate_non_empty("issue file", &issue.file)?;
            validate_non_empty("issue kind", &issue.kind)?;
            validate_non_empty("issue message", &issue.message)?;
            if issue.line.is_none() && issue.column.is_some() {
                return Err(SchemaError::new(
                    "scan issue column requires a corresponding line",
                ));
            }
        }

        let expected = ScanSummary {
            finding_count: self.findings.len() as u64,
            unique_api_count: api_counts.len() as u64,
            direct_call_count,
            tensor_method_count,
            dynamic_call_count,
            issue_count: self.issues.len() as u64,
            api_counts,
            mapping_counts,
        };
        if self.summary != expected {
            return Err(SchemaError::new(
                "scan summary does not match findings and issues",
            ));
        }
        Ok(())
    }
}

impl MappingResolution {
    pub fn validate(&self) -> Result<(), SchemaError> {
        validate_non_empty("mapping source_api", &self.source_api)?;
        validate_non_empty("mapping notes", &self.notes)?;
        validate_non_empty(
            "mapping source_framework_version",
            &self.source_framework_version,
        )?;
        validate_non_empty(
            "mapping target_framework_version",
            &self.target_framework_version,
        )?;
        validate_non_empty("mapping knowledge_version", &self.knowledge_version)?;
        match self.status {
            MappingStatus::Exact | MappingStatus::Difference => {
                if self
                    .target_api
                    .as_deref()
                    .is_none_or(|api| !api.starts_with("mindspore"))
                {
                    return Err(SchemaError::new(
                        "known mapping must contain a MindSpore target_api",
                    ));
                }
                if self.evidence_urls.is_empty() {
                    return Err(SchemaError::new("known mapping must contain evidence_urls"));
                }
            }
            MappingStatus::Unsupported | MappingStatus::Unknown => {
                if self.target_api.is_some() {
                    return Err(SchemaError::new(
                        "unsupported or unknown mapping must not contain target_api",
                    ));
                }
            }
        }
        if self.status == MappingStatus::Exact && !self.differences.is_empty() {
            return Err(SchemaError::new(
                "exact mapping must not contain differences",
            ));
        }
        if self.status == MappingStatus::Difference && self.differences.is_empty() {
            return Err(SchemaError::new(
                "difference mapping must contain differences",
            ));
        }
        Ok(())
    }

    fn validate_for_finding(
        &self,
        finding_api: &str,
        risk_level: RiskLevel,
    ) -> Result<(), SchemaError> {
        self.validate()?;
        if self.source_api != finding_api {
            return Err(SchemaError::new(
                "mapping source_api must match the scan finding api",
            ));
        }
        let expected_risk = match self.status {
            MappingStatus::Exact => RiskLevel::Low,
            MappingStatus::Difference => RiskLevel::Medium,
            MappingStatus::Unsupported | MappingStatus::Unknown => RiskLevel::High,
        };
        if risk_level != expected_risk {
            return Err(SchemaError::new(
                "scan finding risk_level does not match mapping status",
            ));
        }
        Ok(())
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum Framework {
    #[serde(rename = "pytorch")]
    PyTorch,
    #[serde(rename = "mindspore")]
    MindSpore,
    #[serde(rename = "framework_neutral")]
    FrameworkNeutral,
    #[serde(other)]
    Unknown,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ExecutionMode {
    Eager,
    PyNative,
    Graph,
    StaticAnalysis,
    #[serde(other)]
    Unknown,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct SourceLocation {
    pub file: String,
    pub line: u32,
    pub column: u32,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub end_line: Option<u32>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub end_column: Option<u32>,
}

impl SourceLocation {
    pub fn validate(&self) -> Result<(), SchemaError> {
        if self.file.trim().is_empty() {
            return Err(SchemaError::new("source location file must not be empty"));
        }
        if self.line == 0 {
            return Err(SchemaError::new("source location line is one-based"));
        }
        if let Some(end_line) = self.end_line {
            if end_line < self.line {
                return Err(SchemaError::new(
                    "source location end_line must not precede line",
                ));
            }
            if end_line == self.line
                && self
                    .end_column
                    .is_some_and(|end_column| end_column < self.column)
            {
                return Err(SchemaError::new(
                    "source location end_column must not precede column on the same line",
                ));
            }
        }
        if self.end_line.is_some() != self.end_column.is_some() {
            return Err(SchemaError::new(
                "source location end_line and end_column must be provided together",
            ));
        }
        Ok(())
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ValueKind {
    Tensor,
    Scalar,
    Boolean,
    String,
    Sequence,
    Mapping,
    None,
    #[serde(other)]
    Unknown,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, Default)]
pub struct NumericSummary {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub min: Option<f64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub max: Option<f64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub mean: Option<f64>,
    #[serde(default)]
    pub nan_count: u64,
    #[serde(default)]
    pub inf_count: u64,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ValueSummary {
    pub kind: ValueKind,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub dtype: Option<String>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub shape: Vec<Option<i64>>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub numeric: Option<NumericSummary>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub preview: Option<Value>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub children: Vec<ValueSummary>,
}

impl ValueSummary {
    pub fn validate(&self) -> Result<(), SchemaError> {
        if self.shape.iter().flatten().any(|dimension| *dimension < 0) {
            return Err(SchemaError::new(
                "shape dimensions must be non-negative; use null for unknown dimensions",
            ));
        }
        if self
            .dtype
            .as_deref()
            .is_some_and(|dtype| dtype.trim().is_empty())
        {
            return Err(SchemaError::new("dtype must not be an empty string"));
        }
        for child in &self.children {
            child.validate()?;
        }
        Ok(())
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ApiArgument {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub name: Option<String>,
    pub position: u32,
    pub value: ValueSummary,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct RuntimeError {
    pub error_type: String,
    pub message: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub traceback: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ApiTraceRecord {
    pub schema_version: String,
    pub record_kind: RecordKind,
    pub run_id: String,
    pub framework: Framework,
    pub framework_version: String,
    pub execution_mode: ExecutionMode,
    pub location: SourceLocation,
    pub api: String,
    pub call_index: u64,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub arguments: Vec<ApiArgument>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub output: Option<ValueSummary>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub error: Option<RuntimeError>,
    #[serde(default, skip_serializing_if = "BTreeMap::is_empty")]
    pub metadata: BTreeMap<String, Value>,
}

impl ApiTraceRecord {
    pub fn validate(&self) -> Result<(), SchemaError> {
        ensure_compatible_schema(&self.schema_version)?;
        if self.record_kind != RecordKind::ApiTrace {
            return Err(SchemaError::new("record_kind must be api_trace"));
        }
        validate_non_empty("run_id", &self.run_id)?;
        validate_non_empty("framework_version", &self.framework_version)?;
        validate_non_empty("api", &self.api)?;
        self.location.validate()?;
        for argument in &self.arguments {
            argument.value.validate()?;
        }
        if let Some(output) = &self.output {
            output.validate()?;
        }
        match (&self.output, &self.error) {
            (Some(_), Some(_)) => {
                return Err(SchemaError::new(
                    "api trace must not contain both output and error",
                ));
            }
            (None, None) => {
                return Err(SchemaError::new(
                    "api trace must contain either output or error",
                ));
            }
            _ => {}
        }
        if let Some(error) = &self.error {
            validate_non_empty("error_type", &error.error_type)?;
            validate_non_empty("error message", &error.message)?;
        }
        Ok(())
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum DiagnosticCategory {
    MissingOperator,
    UnmappedApi,
    ParameterMismatch,
    DefaultValueMismatch,
    DtypeMismatch,
    ShapeMismatch,
    ReturnStructureMismatch,
    ValueMismatch,
    GradientMismatch,
    RandomnessMismatch,
    GraphCompileFailure,
    DeviceUnsupported,
    RuntimeError,
    NeedsManualReview,
    #[serde(other)]
    Unknown,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Severity {
    Info,
    Low,
    Medium,
    High,
    Critical,
    #[serde(other)]
    Unknown,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum EvidenceKind {
    StaticAnalysis,
    RuntimeTrace,
    MappingKnowledge,
    ExecutionError,
    Documentation,
    DiffValidation,
    #[serde(other)]
    Unknown,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct DiagnosticEvidence {
    pub kind: EvidenceKind,
    pub message: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub location: Option<SourceLocation>,
    #[serde(default, skip_serializing_if = "BTreeMap::is_empty")]
    pub data: BTreeMap<String, Value>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct DiagnosticRecord {
    pub schema_version: String,
    pub record_kind: RecordKind,
    pub diagnostic_id: String,
    pub run_id: String,
    pub category: DiagnosticCategory,
    pub severity: Severity,
    pub confidence: f64,
    pub summary: String,
    pub explanation: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub location: Option<SourceLocation>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub source_api: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub target_api: Option<String>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub evidence: Vec<DiagnosticEvidence>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub suggested_action: Option<String>,
    #[serde(default)]
    pub verified: bool,
    #[serde(default, skip_serializing_if = "BTreeMap::is_empty")]
    pub metadata: BTreeMap<String, Value>,
}

impl DiagnosticRecord {
    pub fn validate(&self) -> Result<(), SchemaError> {
        ensure_compatible_schema(&self.schema_version)?;
        if self.record_kind != RecordKind::Diagnostic {
            return Err(SchemaError::new("record_kind must be diagnostic"));
        }
        validate_non_empty("diagnostic_id", &self.diagnostic_id)?;
        validate_non_empty("run_id", &self.run_id)?;
        validate_non_empty("summary", &self.summary)?;
        validate_non_empty("explanation", &self.explanation)?;
        if !self.confidence.is_finite() || !(0.0..=1.0).contains(&self.confidence) {
            return Err(SchemaError::new(
                "diagnostic confidence must be a finite value between 0 and 1",
            ));
        }
        if let Some(location) = &self.location {
            location.validate()?;
        }
        if self.evidence.is_empty() {
            return Err(SchemaError::new(
                "diagnostic must contain at least one evidence item",
            ));
        }
        for evidence in &self.evidence {
            validate_non_empty("evidence message", &evidence.message)?;
            if let Some(location) = &evidence.location {
                location.validate()?;
            }
        }
        if self.verified
            && !self
                .evidence
                .iter()
                .any(|evidence| evidence.kind == EvidenceKind::DiffValidation)
        {
            return Err(SchemaError::new(
                "verified diagnostic must contain diff_validation evidence",
            ));
        }
        Ok(())
    }
}

fn validate_non_empty(field: &str, value: &str) -> Result<(), SchemaError> {
    if value.trim().is_empty() {
        return Err(SchemaError::new(format!("{field} must not be empty")));
    }
    Ok(())
}

fn validate_sha256(field: &str, value: &str) -> Result<(), SchemaError> {
    if value.len() != 64 || !value.bytes().all(|byte| byte.is_ascii_hexdigit()) {
        return Err(SchemaError::new(format!(
            "{field} must be a 64-character hexadecimal SHA-256"
        )));
    }
    Ok(())
}
