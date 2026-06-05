use std::process::Command;

pub fn run(query: &str) -> Result<String, String> {
    let encoded = query.replace(' ', "+");
    let url = format!("https://lite.duckduckgo.com/lite/?q={encoded}");

    let script = format!(
        "curl -sL --max-time 10 '{url}' 2>/dev/null | \
         sed 's/<[^>]*>//g' | \
         sed 's/&amp;/&/g; s/&lt;/</g; s/&gt;/>/g; s/&quot;/\"/g' | \
         sed '/^$/d' | \
         head -50"
    );

    let output = Command::new("sh")
        .arg("-lc")
        .arg(&script)
        .output()
        .map_err(|e| e.to_string())?;

    if !output.status.success() {
        return Err(format!("web_search failed: curl exited with error"));
    }

    let text = String::from_utf8_lossy(&output.stdout).trim().to_string();
    if text.is_empty() {
        return Err("web_search returned no results".to_string());
    }
    Ok(text)
}
