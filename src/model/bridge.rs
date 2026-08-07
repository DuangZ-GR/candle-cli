use crate::model::runtime::CandleTargetRuntime;
use crate::model::types::{
    RuntimeCapabilities, RuntimeHealth, TokenUsage, ToolCallIntent, TurnRequest, TurnResult,
};
use serde_json::Value;
use std::io::{BufRead, BufReader, Write};
use std::process::{Child, Command, Stdio};

type BridgeProcess = (Child, Box<dyn Write + Send>, Box<dyn BufRead + Send>);

pub struct LocalBridgeRuntime {
    command: String,
    child: Option<BridgeProcess>,
}

impl LocalBridgeRuntime {
    pub fn new(command: String) -> Self {
        Self {
            command,
            child: None,
        }
    }

    fn command_parts(&self) -> Result<(String, Vec<String>), String> {
        let mut parts = self.command.split_whitespace();
        let program = parts
            .next()
            .ok_or_else(|| "bridge command is empty".to_string())?
            .to_string();
        let args = parts.map(|value| value.to_string()).collect();
        Ok((program, args))
    }

    fn ensure_worker(&mut self) -> Result<(), String> {
        if self.child.is_some() {
            return Ok(());
        }
        let (program, args) = self.command_parts()?;
        let mut child = Command::new(program)
            .args(args)
            .env("PYTHONUTF8", "1")
            .env("PYTHONIOENCODING", "utf-8")
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .spawn()
            .map_err(|e| e.to_string())?;
        let stdin: Box<dyn Write + Send> =
            Box::new(child.stdin.take().ok_or("stdin unavailable".to_string())?);
        let stdout: Box<dyn BufRead + Send> = Box::new(BufReader::new(
            child
                .stdout
                .take()
                .ok_or("stdout unavailable".to_string())?,
        ));
        self.child = Some((child, stdin, stdout));
        Ok(())
    }
}

impl CandleTargetRuntime for LocalBridgeRuntime {
    fn generate_turn(&mut self, request: TurnRequest) -> Result<TurnResult, String> {
        self.ensure_worker()?;
        let (_child, stdin, reader) = self.child.as_mut().unwrap();

        writeln!(
            stdin,
            "{}",
            serde_json::json!({
                "type": "generate_turn",
                "request": {
                    "system_prompt": request.system_prompt,
                    "messages_json": request.messages_json,
                    "tools_json": request.tools_json,
                    "timeout_ms": request.timeout_ms,
                    "deadline_unix_ms": request.deadline_unix_ms,
                }
            })
        )
        .map_err(|_| "failed to send generate_turn".to_string())?;

        let mut line = String::new();
        reader
            .read_line(&mut line)
            .map_err(|_| "failed to read generate_turn response".to_string())?;

        let value: Value = serde_json::from_str(line.trim()).map_err(|e| e.to_string())?;
        if !value.get("ok").and_then(|v| v.as_bool()).unwrap_or(false) {
            return Err(value
                .get("error")
                .and_then(|v| v.as_str())
                .unwrap_or("bridge worker error")
                .to_string());
        }

        let result = value
            .get("result")
            .ok_or_else(|| "missing result".to_string())?;
        let final_text = result
            .get("final_text")
            .and_then(|v| v.as_str())
            .ok_or_else(|| "missing final_text".to_string())?
            .to_string();

        let tool_calls = result
            .get("tool_calls")
            .and_then(|v| v.as_array())
            .map(|items| {
                items
                    .iter()
                    .map(|item| ToolCallIntent {
                        id: item
                            .get("id")
                            .and_then(|v| v.as_str())
                            .unwrap_or_default()
                            .to_string(),
                        name: item
                            .get("name")
                            .and_then(|v| v.as_str())
                            .unwrap_or_default()
                            .to_string(),
                        input_json: item
                            .get("input_json")
                            .and_then(|v| v.as_str())
                            .unwrap_or_default()
                            .to_string(),
                    })
                    .collect::<Vec<_>>()
            })
            .unwrap_or_default();

        let usage = result
            .get("usage")
            .and_then(parse_token_usage)
            .unwrap_or_else(TokenUsage::unreported_request);

        Ok(TurnResult {
            final_text,
            tool_calls,
            usage,
        })
    }

    fn healthcheck(&self) -> RuntimeHealth {
        let (program, args) = match self.command_parts() {
            Ok(parts) => parts,
            Err(message) => return RuntimeHealth { ok: false, message },
        };
        let mut child = match Command::new(program)
            .args(args)
            .env("PYTHONUTF8", "1")
            .env("PYTHONIOENCODING", "utf-8")
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .spawn()
        {
            Ok(child) => child,
            Err(error) => {
                return RuntimeHealth {
                    ok: false,
                    message: error.to_string(),
                }
            }
        };
        let Some(mut stdin) = child.stdin.take() else {
            return RuntimeHealth {
                ok: false,
                message: "stdin unavailable".into(),
            };
        };
        let Some(stdout) = child.stdout.take() else {
            return RuntimeHealth {
                ok: false,
                message: "stdout unavailable".into(),
            };
        };
        let _ = writeln!(stdin, "{}", serde_json::json!({ "type": "healthcheck" }));
        let _ = writeln!(stdin, "{}", serde_json::json!({ "type": "shutdown" }));
        let mut line = String::new();
        let mut reader = BufReader::new(stdout);
        if reader.read_line(&mut line).is_err() {
            return RuntimeHealth {
                ok: false,
                message: "failed to read healthcheck".into(),
            };
        }
        let _ = child.wait();
        match serde_json::from_str::<Value>(line.trim()) {
            Ok(value) => RuntimeHealth {
                ok: value.get("ok").and_then(|v| v.as_bool()).unwrap_or(false),
                message: value
                    .get("message")
                    .and_then(|v| v.as_str())
                    .unwrap_or("invalid")
                    .to_string(),
            },
            Err(error) => RuntimeHealth {
                ok: false,
                message: error.to_string(),
            },
        }
    }

    fn capabilities(&self) -> RuntimeCapabilities {
        RuntimeCapabilities {
            supports_tools: true,
            supports_streaming: true,
        }
    }
}

fn parse_token_usage(value: &Value) -> Option<TokenUsage> {
    let usage = value.as_object()?;
    let retry_count = usage
        .get("retry_count")
        .and_then(Value::as_u64)
        .unwrap_or_default();
    let provider_latency_ms = usage
        .get("provider_latency_ms")
        .and_then(Value::as_u64)
        .unwrap_or_default();
    let Some(prompt_tokens) = usage.get("prompt_tokens").and_then(Value::as_u64) else {
        return (usage.contains_key("retry_count") || usage.contains_key("provider_latency_ms"))
            .then_some(TokenUsage {
                request_count: 1,
                retry_count,
                provider_latency_ms,
                ..TokenUsage::default()
            });
    };
    let completion_tokens = usage.get("completion_tokens")?.as_u64()?;
    let total_tokens = usage.get("total_tokens")?.as_u64()?;
    if total_tokens != prompt_tokens.checked_add(completion_tokens)? {
        return None;
    }

    let mut cached_prompt_tokens = usage.get("cached_prompt_tokens").and_then(Value::as_u64);
    let mut cache_miss_prompt_tokens = usage
        .get("cache_miss_prompt_tokens")
        .and_then(Value::as_u64);
    if cached_prompt_tokens.is_some_and(|cached| cached > prompt_tokens)
        || matches!(
            (cached_prompt_tokens, cache_miss_prompt_tokens),
            (Some(cached), Some(missed)) if cached.checked_add(missed) != Some(prompt_tokens)
        )
    {
        cached_prompt_tokens = None;
        cache_miss_prompt_tokens = None;
    }

    Some(TokenUsage {
        request_count: 1,
        retry_count,
        provider_latency_ms,
        usage_reported_request_count: 1,
        prompt_tokens,
        completion_tokens,
        total_tokens,
        cache_metrics_reported_request_count: u64::from(cached_prompt_tokens.is_some()),
        cached_prompt_tokens: cached_prompt_tokens.unwrap_or_default(),
        cache_miss_prompt_tokens,
    })
}

impl Drop for LocalBridgeRuntime {
    fn drop(&mut self) {
        if let Some((mut child, ref mut stdin, _)) = self.child.take() {
            let _ = writeln!(stdin, "{}", serde_json::json!({ "type": "shutdown" }));
            let _ = child.wait();
        }
    }
}

#[cfg(test)]
mod tests {
    use super::parse_token_usage;

    #[test]
    fn invalid_usage_degrades_to_unreported_instead_of_breaking_generation() {
        let invalid_total = serde_json::json!({
            "prompt_tokens": 10,
            "completion_tokens": 2,
            "total_tokens": 99
        });
        assert_eq!(parse_token_usage(&invalid_total), None);

        let invalid_cache = serde_json::json!({
            "prompt_tokens": 10,
            "completion_tokens": 2,
            "total_tokens": 12,
            "cached_prompt_tokens": 11
        });
        let usage = parse_token_usage(&invalid_cache).unwrap();
        assert!(usage.usage_complete());
        assert!(!usage.cache_metrics_complete());
        assert_eq!(usage.provider_cache_hit_rate(), None);
    }

    #[test]
    fn request_telemetry_survives_when_provider_omits_token_usage() {
        let telemetry = serde_json::json!({
            "retry_count": 2,
            "provider_latency_ms": 3210
        });

        let usage = parse_token_usage(&telemetry).unwrap();

        assert_eq!(usage.request_count, 1);
        assert_eq!(usage.retry_count, 2);
        assert_eq!(usage.provider_latency_ms, 3210);
        assert!(!usage.usage_complete());
        assert_eq!(usage.provider_cache_hit_rate(), None);
    }
}
