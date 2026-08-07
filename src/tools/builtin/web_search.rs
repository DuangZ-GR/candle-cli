use std::process::Command;

const SEARCH_SCRIPT: &str = r#"
import re, urllib.request, urllib.parse, sys
base, query = sys.argv[1], sys.argv[2]
url = base + urllib.parse.quote(query)
try:
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    html = urllib.request.urlopen(req, timeout=8).read().decode('utf-8', errors='ignore')
    html = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL|re.IGNORECASE)
    html = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL|re.IGNORECASE)
    html = re.sub(r'<[^>]+>', '', html)
    html = html.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
    html = re.sub(r'&[a-zA-Z]+;', '', html)
    html = re.sub(r'[ \t\r]+', ' ', html)
    lines = [line.strip() for line in html.split('\n') if line.strip()]
    lines = [line for line in lines if len(line) > 15 and not line.startswith('{') and line.count(';') < 2]
    print('\n'.join(lines[:50]))
except Exception:
    sys.exit(1)
"#;

pub fn run(query: &str) -> Result<String, String> {
    // DuckDuckGo Lite first, then Sogou fallback.
    let urls: &[(&str, &str)] = &[
        ("https://lite.duckduckgo.com/lite/?q=", query),
        ("https://www.sogou.com/web?query=", query),
    ];

    for (base, q) in urls {
        let output = python_command(base, q)
            .output()
            .map_err(|error| format!("web_search: failed to start Python: {error}"))?;

        if !output.status.success() {
            continue;
        }

        let text = String::from_utf8_lossy(&output.stdout).trim().to_string();
        if text.lines().count() >= 2 {
            return Ok(text);
        }
    }

    Err("web_search: all backends returned empty or unreachable".to_string())
}

fn python_command(base: &str, query: &str) -> Command {
    let python = std::env::var("CANDLE_CLI_PYTHON").unwrap_or_else(|_| {
        if cfg!(windows) {
            "python".to_string()
        } else {
            "python3".to_string()
        }
    });
    let mut command = Command::new(python);
    // The query is a process argument, never interpolated into Python or shell source.
    command.args(["-c", SEARCH_SCRIPT, base, query]);
    command
}

pub(crate) fn query_is_passed_as_opaque_argument(query: &str) -> bool {
    let command = python_command("https://example.invalid/?q=", query);
    let args: Vec<_> = command.get_args().collect();
    args.len() == 4
        && args.last().and_then(|value| value.to_str()) == Some(query)
        && !SEARCH_SCRIPT.contains(query)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn hostile_query_is_passed_as_opaque_argument() {
        let hostile = "'''; __import__('os').system('touch escaped'); # $(whoami)";
        assert!(query_is_passed_as_opaque_argument(hostile));
    }
}
