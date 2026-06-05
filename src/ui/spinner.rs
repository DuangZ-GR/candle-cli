use std::io::{self, Write};
use std::sync::mpsc;
use std::thread;
use std::time::{Duration, Instant};

pub struct Spinner {
    tx: Option<mpsc::Sender<()>>,
}

impl Spinner {
    pub fn start() -> Self {
        let (tx, rx) = mpsc::channel();
        let started = Instant::now();
        let frames = ['/', '-', '\\', '|'];
        let mut idx = 0usize;

        thread::spawn(move || {
            let mut stderr = io::stderr();
            loop {
                let elapsed = started.elapsed().as_secs();
                let frame = frames[idx % frames.len()];
                let _ = write!(
                    stderr,
                    "\r  {}  thinking... {}s ",
                    frame, elapsed
                );
                let _ = stderr.flush();
                idx += 1;

                // Check for stop signal with 250ms timeout
                if rx.recv_timeout(Duration::from_millis(250)).is_ok() {
                    // Clear the line
                    let _ = write!(stderr, "\r\x1b[K");
                    let _ = stderr.flush();
                    return;
                }
            }
        });

        Self { tx: Some(tx) }
    }

    pub fn stop(&mut self) {
        if let Some(tx) = self.tx.take() {
            let _ = tx.send(());
        }
    }
}

impl Drop for Spinner {
    fn drop(&mut self) {
        self.stop();
    }
}
