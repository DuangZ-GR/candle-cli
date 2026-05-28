use std::io::{self, Write};

pub fn confirm_dangerous_action(tool_name: &str, input_json: &str) -> bool {
    if let Ok(value) = std::env::var("CANDLE_CLI_PERMISSION_RESPONSE") {
        return matches!(
            value.trim().to_ascii_lowercase().as_str(),
            "y" | "yes" | "allow"
        );
    }

    let mut stdout = io::stdout();
    let mut stdin = String::new();

    for attempt in 0..2 {
        let _ = writeln!(stdout, "Allow tool call?");
        let _ = writeln!(stdout, "- tool: {tool_name}");
        let _ = writeln!(stdout, "- input: {input_json}");
        let _ = writeln!(stdout, "[y] allow");
        let _ = writeln!(stdout, "[n] deny");
        let _ = stdout.flush();

        stdin.clear();
        match io::stdin().read_line(&mut stdin) {
            Ok(0) => return false,
            Ok(_) => match stdin.trim().to_ascii_lowercase().as_str() {
                "y" | "yes" | "allow" => return true,
                "n" | "no" | "deny" | "" => return false,
                _ if attempt == 0 => continue,
                _ => return false,
            },
            Err(_) => return false,
        }
    }

    false
}
