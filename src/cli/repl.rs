use std::io::{self, Write};

pub fn read_line(prompt: &str) -> io::Result<String> {
    let mut stdout = io::stdout();
    write!(stdout, "{}", prompt)?;
    stdout.flush()?;

    let mut buffer = String::new();
    io::stdin().read_line(&mut buffer)?;
    while matches!(buffer.chars().last(), Some('\n' | '\r')) {
        buffer.pop();
    }
    Ok(buffer)
}
