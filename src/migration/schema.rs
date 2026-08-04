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
    #[serde(other)]
    Unknown,
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
