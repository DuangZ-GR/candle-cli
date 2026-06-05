use std::process::Command;

pub fn run(query: &str) -> Result<String, String> {
    // DuckDuckGo Lite first, then Sogou fallback.
    let urls: &[(&str, &str)] = &[
        ("https://lite.duckduckgo.com/lite/?q=", query),
        ("https://www.sogou.com/web?query=", query),
    ];

    for (base, q) in urls {
        let script = format!(
            "python3 -c \"
import re, urllib.request, urllib.parse, sys
query = '''{q}'''
url = '{base}' + urllib.parse.quote(query)
try:
    req = urllib.request.Request(url, headers={{'User-Agent': 'Mozilla/5.0'}})
    html = urllib.request.urlopen(req, timeout=8).read().decode('utf-8', errors='ignore')
    html = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL|re.IGNORECASE)
    html = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL|re.IGNORECASE)
    html = re.sub(r'<[^>]+>', '', html)
    html = html.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
    html = re.sub(r'&[a-zA-Z]+;', '', html)
    html = re.sub(r'[ \\t\\r]+', ' ', html)
    lines = [l.strip() for l in html.split('\\n') if l.strip()]
    lines = [l for l in lines if len(l) > 15 and not l.startswith('{{') and l.count(';') < 2]
    print('\\n'.join(lines[:50]))
except Exception as e:
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
        if text.lines().count() >= 2 {
            return Ok(text);
        }
    }

    Err("web_search: all backends returned empty or unreachable".to_string())
}
