use crate::model::types::ToolCallIntent;
use serde_json::Value;
use std::fmt;

const OPEN_TAG: &str = "<tool_call>";
const CLOSE_TAG: &str = "</tool_call>";
const FALLBACK_ID: &str = "call-fallback";
const KNOWN_TOOLS: &[&str] = &["pwd", "read", "glob", "grep", "edit", "shell"];

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
    if let Some(start) = text.find(OPEN_TAG) {
        let json_start = start + OPEN_TAG.len();
        let Some(relative_end) = text[json_start..].find(CLOSE_TAG) else {
            return Err(ToolCallParseError::MissingCloseTag);
        };
        let json_end = json_start + relative_end;
        let raw_json = text[json_start..json_end].trim();
        return parse_wrapped_json(raw_json);
    }

    parse_fallback_function_call(text)
}

fn parse_wrapped_json(raw_json: &str) -> Result<Option<ToolCallIntent>, ToolCallParseError> {
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

fn parse_fallback_function_call(text: &str) -> Result<Option<ToolCallIntent>, ToolCallParseError> {
    let trimmed = text.trim();
    let Some(open_paren) = trimmed.find('(') else {
        return Ok(None);
    };
    if !trimmed.ends_with(')') {
        return Ok(None);
    }

    let tool_name = trimmed[..open_paren].trim();
    if !KNOWN_TOOLS.contains(&tool_name) {
        return Ok(None);
    }

    let raw_input = trimmed[open_paren + 1..trimmed.len() - 1].trim();
    let value: Value = serde_json::from_str(raw_input)
        .map_err(|err| ToolCallParseError::InvalidJson(err.to_string()))?;
    if !value.is_object() {
        return Err(ToolCallParseError::InputMustBeObject);
    }

    Ok(Some(ToolCallIntent {
        id: FALLBACK_ID.to_string(),
        name: tool_name.to_string(),
        input_json: value.to_string(),
    }))
}
