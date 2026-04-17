pub fn parse_slash_command(input: &str) -> Option<String> {
    input.strip_prefix('/').map(|value| value.trim().to_string())
}
