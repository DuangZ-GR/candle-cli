use clap::Parser;

#[derive(Parser, Debug)]
#[command(name = "candle-cli")]
struct Args {}

fn main() {
    let _ = Args::parse();
}
