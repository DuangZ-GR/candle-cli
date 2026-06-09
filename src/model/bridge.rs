use crate::model::runtime::CandleTargetRuntime;
use crate::model::types::{
    RuntimeCapabilities, RuntimeHealth, ToolCallIntent, TurnRequest, TurnResult,
};
use serde_json::Value;
use std::io::{BufRead, BufReader, Write};
use std::process::{Child, Command, Stdio};

pub struct LocalBridgeRuntime {
    command: String,
    child: Option<(Child, Box<dyn Write + Send>, Box<dyn BufRead + Send>)>,
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
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .spawn()
            .map_err(|e| e.to_string())?;
        let stdin: Box<dyn Write + Send> =
            Box::new(child.stdin.take().ok_or("stdin unavailable".to_string())?);
        let stdout: Box<dyn BufRead + Send> =
            Box::new(BufReader::new(child.stdout.take().ok_or("stdout unavailable".to_string())?));
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

        Ok(TurnResult {
            final_text,
            tool_calls,
        })
    }

    fn healthcheck(&self) -> RuntimeHealth {
        let (program, args) = match self.command_parts() {
            Ok(parts) => parts,
            Err(message) => return RuntimeHealth { ok: false, message },
        };
        let mut child = match Command::new(program)
            .args(args)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .spawn()
        {
            Ok(child) => child,
            Err(error) => return RuntimeHealth { ok: false, message: error.to_string() },
        };
        let Some(mut stdin) = child.stdin.take() else {
            return RuntimeHealth { ok: false, message: "stdin unavailable".into() };
        };
        let Some(stdout) = child.stdout.take() else {
            return RuntimeHealth { ok: false, message: "stdout unavailable".into() };
        };
        let _ = writeln!(stdin, "{}", serde_json::json!({ "type": "healthcheck" }));
        let _ = writeln!(stdin, "{}", serde_json::json!({ "type": "shutdown" }));
        let mut line = String::new();
        let mut reader = BufReader::new(stdout);
        if reader.read_line(&mut line).is_err() {
            return RuntimeHealth { ok: false, message: "failed to read healthcheck".into() };
        }
        let _ = child.wait();
        match serde_json::from_str::<Value>(line.trim()) {
            Ok(value) => RuntimeHealth {
                ok: value.get("ok").and_then(|v| v.as_bool()).unwrap_or(false),
                message: value.get("message").and_then(|v| v.as_str()).unwrap_or("invalid").to_string(),
            },
            Err(error) => RuntimeHealth { ok: false, message: error.to_string() },
        }
    }

    fn capabilities(&self) -> RuntimeCapabilities {
        RuntimeCapabilities {
            supports_tools: true,
            supports_streaming: true,
        }
    }
}

impl Drop for LocalBridgeRuntime {
    fn drop(&mut self) {
        if let Some((mut child, ref mut stdin, _)) = self.child.take() {
            let _ = writeln!(stdin, "{}", serde_json::json!({ "type": "shutdown" }));
            let _ = child.wait();
        }
    }
}
