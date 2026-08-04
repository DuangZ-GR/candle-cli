import json
from pathlib import Path

import pytest

from migration.schema import (
    ApiTraceRecord,
    DiagnosticCategory,
    DiagnosticRecord,
    Framework,
    RecordKind,
    SchemaError,
    ensure_compatible_schema,
)

FIXTURES = Path(__file__).parents[1] / "tests" / "fixtures" / "migration"
MACHINE_SCHEMA = Path(__file__).parents[1] / "schemas" / "migration-v1.schema.json"


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_machine_schema_is_valid_json_and_declares_both_record_types():
    schema = json.loads(MACHINE_SCHEMA.read_text(encoding="utf-8"))

    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert "apiTrace" in schema["$defs"]
    assert "diagnostic" in schema["$defs"]


def test_api_trace_fixture_validates_and_round_trips():
    source = load_fixture("api_trace_v1.json")
    record = ApiTraceRecord.from_dict(source)

    record.validate()
    assert record.record_kind == RecordKind.API_TRACE
    assert record.framework == Framework.PYTORCH
    assert record.arguments[0].value.shape == [32, 128]

    decoded = ApiTraceRecord.from_dict(record.to_dict())
    decoded.validate()
    assert decoded == record


def test_diagnostic_fixture_validates_and_round_trips():
    source = load_fixture("diagnostic_v1.json")
    record = DiagnosticRecord.from_dict(source)

    record.validate()
    assert record.record_kind == RecordKind.DIAGNOSTIC
    assert record.category == DiagnosticCategory.DTYPE_MISMATCH

    decoded = DiagnosticRecord.from_dict(record.to_dict())
    decoded.validate()
    assert decoded == record


def test_schema_major_version_is_enforced():
    ensure_compatible_schema("1.8")
    with pytest.raises(SchemaError, match="unsupported schema major version 2"):
        ensure_compatible_schema("2.0")


@pytest.mark.parametrize("version", ["1", "one.zero", "1.x", "1.0.0"])
def test_malformed_schema_version_is_rejected(version):
    with pytest.raises(SchemaError, match="invalid schema version"):
        ensure_compatible_schema(version)


def test_unknown_enum_value_degrades_to_unknown():
    source = load_fixture("api_trace_v1.json")
    source["framework"] = "future_framework"

    record = ApiTraceRecord.from_dict(source)

    assert record.framework == Framework.UNKNOWN
    record.validate()


def test_negative_shape_dimension_is_rejected():
    source = load_fixture("api_trace_v1.json")
    source["arguments"][0]["value"]["shape"] = [32, -1]
    record = ApiTraceRecord.from_dict(source)

    with pytest.raises(SchemaError, match="use null for unknown dimensions"):
        record.validate()


def test_trace_cannot_contain_output_and_error():
    source = load_fixture("api_trace_v1.json")
    source["error"] = {"error_type": "TypeError", "message": "unexpected dtype"}
    record = ApiTraceRecord.from_dict(source)

    with pytest.raises(SchemaError, match="both output and error"):
        record.validate()


def test_trace_must_contain_output_or_error():
    source = load_fixture("api_trace_v1.json")
    del source["output"]
    record = ApiTraceRecord.from_dict(source)

    with pytest.raises(SchemaError, match="either output or error"):
        record.validate()


def test_diagnostic_confidence_must_be_a_probability():
    source = load_fixture("diagnostic_v1.json")
    source["confidence"] = 1.01
    record = DiagnosticRecord.from_dict(source)

    with pytest.raises(SchemaError, match="between 0 and 1"):
        record.validate()


def test_diagnostic_requires_evidence():
    source = load_fixture("diagnostic_v1.json")
    source["evidence"] = []
    record = DiagnosticRecord.from_dict(source)

    with pytest.raises(SchemaError, match="at least one evidence"):
        record.validate()


def test_verified_diagnostic_requires_diff_validation_evidence():
    source = load_fixture("diagnostic_v1.json")
    source["verified"] = True
    record = DiagnosticRecord.from_dict(source)

    with pytest.raises(SchemaError, match="diff_validation"):
        record.validate()
