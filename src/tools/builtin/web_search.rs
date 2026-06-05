use std::process::Command;

pub fn run(query: &str) -> Result<String, String> {
    let encoded = query.replace(' ', "+");

    // Try DuckDuckGo Lite first (works outside China), then Sogou (works inside China).
    for (name, url) in [
        (
            "DuckDuckGo",
            format!("https://lite.duckduckgo.com/lite/?q={encoded}"),
        ),
        (
            "Sogou",
            format!("https://www.sogou.com/web?query={encoded}"),
        ),
    ] {
        let script = format!(
            "curl -sL --connect-timeout 5 --max-time 10 '{url}' \
             -H 'User-Agent: Mozilla/5.0' 2>/dev/null | \
             sed 's/<script[^>]*>.*<\\/script>//g' | \
             sed 's/<style[^>]*>.*<\\/style>//g' | \
             sed 's/<[^>]*>//g' | \
             sed 's/&amp;/&/g; s/&lt;/</g; s/&gt;/>/g; s/&quot;/\"/g' | \
             sed 's/&[a-zA-Z]\\+;//g' | \
             sed '/^$/d' | \
             head -60"
        );

        let output = Command::new("sh")
            .arg("-lc")
            .arg(&script)
            .output()
            .map_err(|e| e.to_string())?;

        if !output.status.success() {
            continue;
        }

        let text = String::from_utf8_lossy(&output.stdout).trim().to_string();
        if !text.is_empty() && text.len() > 10 {
            return Ok(text);
        }
        // Fall through to next backend
        let _ = name;
    }

    Err("web_search: all backends unreachable".to_string())
}
