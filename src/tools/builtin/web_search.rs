use std::process::Command;

pub fn run(query: &str) -> Result<String, String> {
    let encoded = query.replace(' ', "+");

    // DuckDuckGo Lite first (simple HTML), then Sogou (works inside China).
    let urls: &[(&str, &str)] = &[
        (
            "https://lite.duckduckgo.com/lite/?q={query}",
            &encoded,
        ),
        (
            "https://www.sogou.com/web?query={query}",
            &encoded,
        ),
    ];

    for (template, q) in urls {
        let url = template.replace("{query}", q);

        // Use Python for proper multiline HTML cleaning.
        let script = format!(
            "python3 -c \"
import re, urllib.request, sys
try:
    req = urllib.request.Request('{url}', headers={{'User-Agent': 'Mozilla/5.0'}})
    html = urllib.request.urlopen(req, timeout=8).read().decode('utf-8', errors='ignore')
    # Remove script and style blocks (DOTALL makes . match newlines)
    html = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL|re.IGNORECASE)
    html = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL|re.IGNORECASE)
    # Remove HTML tags
    html = re.sub(r'<[^>]+>', '', html)
    # Decode common entities
    html = html.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
    html = html.replace('&quot;', '\\\"').replace('&#x27;', \\\"'\\\")
    html = re.sub(r'&[a-zA-Z]+;', '', html)
    # Collapse whitespace
    html = re.sub(r'[ \\t\\r]+', ' ', html)
    lines = [l.strip() for l in html.split('\\n') if l.strip()]
    # Skip short noise lines and JS fragments
    lines = [l for l in lines if len(l) > 15 and not l.startswith('{{') and l.count(';') < 2]
    print('\\n'.join(lines[:50]))
except Exception as e:
    print('', file=sys.stderr)
    sys.exit(1)
\" 2>/dev/null"
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
        // Require at least some meaningful content
        if text.lines().count() >= 2 {
            return Ok(text);
        }
    }

    Err("web_search: all backends returned empty or unreachable".to_string())
}
