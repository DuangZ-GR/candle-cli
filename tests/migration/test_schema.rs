use candle_cli::migration::{
    ensure_compatible_schema, ApiTraceRecord, DiagnosticCategory, DiagnosticRecord, Framework,
    RecordKind, TraceComparisonResult, SCHEMA_VERSION,
};

const API_TRACE_FIXTURE: &str = include_str!("../fixtures/migration/api_trace_v1.json");
const DIAGNOSTIC_FIXTURE: &str = include_str!("../fixtures/migration/diagnostic_v1.json");

#[test]
fn api_trace_fixture_deserializes_validates_and_round_trips() {
    let record: ApiTraceRecord = serde_json::from_str(API_TRACE_FIXTURE).unwrap();

    record.validate().unwrap();
    assert_eq!(record.schema_version, SCHEMA_VERSION);
    assert_eq!(record.record_kind, RecordKind::ApiTrace);
    assert_eq!(record.framework, Framework::PyTorch);
    assert_eq!(record.api, "torch.sum");
    assert_eq!(record.arguments[0].value.shape, vec![Some(32), Some(128)]);

    let encoded = serde_json::to_string(&record).unwrap();
    let decoded: ApiTraceRecord = serde_json::from_str(&encoded).unwrap();
    assert_eq!(decoded, record);
}

#[test]
fn diagnostic_fixture_deserializes_validates_and_round_trips() {
    let record: DiagnosticRecord = serde_json::from_str(DIAGNOSTIC_FIXTURE).unwrap();

    record.validate().unwrap();
    assert_eq!(record.record_kind, RecordKind::Diagnostic);
    assert_eq!(record.category, DiagnosticCategory::DtypeMismatch);
    assert_eq!(record.evidence.len(), 1);

    let encoded = serde_json::to_string(&record).unwrap();
    let decoded: DiagnosticRecord = serde_json::from_str(&encoded).unwrap();
    assert_eq!(decoded, record);
}

#[test]
fn compatible_minor_schema_versions_are_accepted() {
    ensure_compatible_schema("1.9").unwrap();
}

#[test]
fn incompatible_major_schema_versions_are_rejected() {
    let error = ensure_compatible_schema("2.0").unwrap_err();
    assert!(error
        .to_string()
        .contains("unsupported schema major version 2"));
}

#[test]
fn malformed_schema_versions_are_rejected() {
    assert!(ensure_compatible_schema("1").is_err());
    assert!(ensure_compatible_schema("one.zero").is_err());
    assert!(ensure_compatible_schema("1.x").is_err());
}

#[test]
fn unknown_enum_values_degrade_to_unknown() {
    let fixture = API_TRACE_FIXTURE.replace("\"pytorch\"", "\"future_framework\"");
    let record: ApiTraceRecord = serde_json::from_str(&fixture).unwrap();

    assert_eq!(record.framework, Framework::Unknown);
    record.validate().unwrap();
}

#[test]
fn negative_shape_dimensions_are_rejected() {
    let fixture = API_TRACE_FIXTURE.replace("[32, 128]", "[32, -1]");
    let record: ApiTraceRecord = serde_json::from_str(&fixture).unwrap();

    let error = record.validate().unwrap_err();
    assert!(error
        .to_string()
        .contains("use null for unknown dimensions"));
}

#[test]
fn trace_cannot_contain_both_output_and_error() {
    let mut value: serde_json::Value = serde_json::from_str(API_TRACE_FIXTURE).unwrap();
    value["error"] = serde_json::json!({
        "error_type": "TypeError",
        "message": "unexpected dtype"
    });
    let record: ApiTraceRecord = serde_json::from_value(value).unwrap();

    let error = record.validate().unwrap_err();
    assert!(error.to_string().contains("both output and error"));
}

#[test]
fn trace_must_contain_output_or_error() {
    let mut value: serde_json::Value = serde_json::from_str(API_TRACE_FIXTURE).unwrap();
    value.as_object_mut().unwrap().remove("output");
    let record: ApiTraceRecord = serde_json::from_value(value).unwrap();

    let error = record.validate().unwrap_err();
    assert!(error.to_string().contains("either output or error"));
}

#[test]
fn diagnostic_confidence_must_be_a_probability() {
    let fixture = DIAGNOSTIC_FIXTURE.replace("0.97", "1.01");
    let record: DiagnosticRecord = serde_json::from_str(&fixture).unwrap();

    let error = record.validate().unwrap_err();
    assert!(error.to_string().contains("between 0 and 1"));
}

#[test]
fn diagnostic_requires_evidence() {
    let mut value: serde_json::Value = serde_json::from_str(DIAGNOSTIC_FIXTURE).unwrap();
    value["evidence"] = serde_json::json!([]);
    let record: DiagnosticRecord = serde_json::from_value(value).unwrap();

    let error = record.validate().unwrap_err();
    assert!(error.to_string().contains("at least one evidence"));
}

#[test]
fn verified_diagnostic_requires_diff_validation_evidence() {
    let mut value: serde_json::Value = serde_json::from_str(DIAGNOSTIC_FIXTURE).unwrap();
    value["verified"] = serde_json::json!(true);
    let record: DiagnosticRecord = serde_json::from_value(value).unwrap();

    let error = record.validate().unwrap_err();
    assert!(error.to_string().contains("diff_validation"));
}

#[test]
fn equivalent_trace_comparison_validates() {
    let comparison: TraceComparisonResult = serde_json::from_value(serde_json::json!({
        "schema_version": SCHEMA_VERSION,
        "record_kind": "trace_comparison",
        "source_count": 2,
        "target_count": 2,
        "aligned_count": 2,
        "equivalent": true,
        "diagnostic": null
    }))
    .unwrap();

    comparison.validate().unwrap();
    assert_eq!(comparison.record_kind, RecordKind::TraceComparison);
}

#[test]
fn divergent_trace_comparison_requires_a_diagnostic() {
    let comparison: TraceComparisonResult = serde_json::from_value(serde_json::json!({
        "schema_version": SCHEMA_VERSION,
        "record_kind": "trace_comparison",
        "source_count": 1,
        "target_count": 1,
        "aligned_count": 1,
        "equivalent": false,
        "diagnostic": null
    }))
    .unwrap();

    let error = comparison.validate().unwrap_err();
    assert!(error.to_string().contains("must include it"));
}
