/// Estimated token count for budget tracking.
/// Rough heuristic: 1 token ≈ 4 characters for English, 1 token ≈ 1.5 characters for CJK.
pub fn estimate_tokens(text: &str) -> usize {
    let chars = text.chars().count();
    let cjk = text.chars().filter(|c| c > &'\u{2e80}').count();
    // CJK chars are roughly 1 token each; Latin chars roughly 4/token
    let latin = chars - cjk;
    cjk + (latin / 4).max(1)
}

/// Estimate total tokens in a messages JSON string.
pub fn estimate_tokens_json(json: &str) -> usize {
    estimate_tokens(json)
}
