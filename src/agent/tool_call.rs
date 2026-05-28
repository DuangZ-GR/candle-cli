use crate::model::types::ToolCallIntent;
use serde_json::Value;
use std::fmt;

const OPEN_TAG: &str = "<tool_call>";
const CLOSE_TAG: &str = "</tool_call>";

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ToolCallParseError {
    MissingCloseTag,
    InvalidJson(String),
    MissingStringField(&'static str),
    InputMustBeObject,
    OuterMustBeObject,
}

impl fmt::Display for ToolCallParseError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::MissingCloseTag => write!(f, "tool call block is missing </tool_call>"),
            Self::InvalidJson(msg) => write!(f, "tool call JSON is invalid: {msg}"),
            Self::MissingStringField(field) => {
                write!(f, "tool call is missing string field: {field}")
            }
            Self::InputMustBeObject => write!(f, "tool call field 'input' must be an object"),
            Self::OuterMustBeObject => write!(f, "tool call JSON must be an object"),
        }
    }
}

impl std::error::Error for ToolCallParseError {}

pub fn parse_tool_call(text: &str) -> Result<Option<ToolCallIntent>, ToolCallParseError> {
    let Some(start) = text.find(OPEN_TAG) else {
        return Ok(None);
    };

    let json_start = start + OPEN_TAG.len();
    let Some(relative_end) = text[json_start..].find(CLOSE_TAG) else {
        return Err(ToolCallParseError::MissingCloseTag);
    };
    let json_end = json_start + relative_end;
    let raw_json = text[json_start..json_end].trim();

    let value: Value = serde_json::from_str(raw_json)
        .map_err(|err| ToolCallParseError::InvalidJson(err.to_string()))?;
    let object = value
        .as_object()
        .ok_or(ToolCallParseError::OuterMustBeObject)?;

    let id = object
        .get("id")
        .and_then(Value::as_str)
        .ok_or(ToolCallParseError::MissingStringField("id"))?
        .to_string();
    let name = object
        .get("name")
        .and_then(Value::as_str)
        .ok_or(ToolCallParseError::MissingStringField("name"))?
        .to_string();
    let input = object
        .get("input")
        .ok_or(ToolCallParseError::InputMustBeObject)?;

    if !input.is_object() {
        return Err(ToolCallParseError::InputMustBeObject);
    }

    Ok(Some(ToolCallIntent {
        id,
        name,
        input_json: input.to_string(),
    }))
}
