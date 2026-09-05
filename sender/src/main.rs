// zpet hook binary — self-healing sender: reads the hook payload from stdin
// and forwards it to the daemon via UDP. If the daemon is down, starts it
// first (so ANY hook event resurrects the pet). Always exits 0 — a non-zero
// exit would make ZCode treat the hook as failed, and exit 2 would BLOCK the
// tool call. The mode argument ("send"/"spawn") is accepted for compatibility
// and behaves identically.
#![windows_subsystem = "windows"]

use std::io::Read;
use std::net::UdpSocket;
use std::path::PathBuf;
use std::process::Command;
use std::thread::sleep;
use std::time::Duration;

const PORT: u16 = 57891;
const SEP: u8 = 0x1F;

fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let state = args.get(1).cloned().unwrap_or_default();

    let mut payload = Vec::new();
    let _ = std::io::stdin().take(48 * 1024).read_to_end(&mut payload);

    // daemon holds the port with an exclusive bind, so a successful plain
    // bind here means no daemon is running
    let attempts: usize = if UdpSocket::bind(("127.0.0.1", PORT)).is_ok() {
        spawn_daemon();
        4 // daemon boot takes a moment; re-send until its socket is up
    } else {
        1
    };
    for i in 0..attempts {
        let _ = send(&state, &payload);
        if i + 1 < attempts {
            sleep(Duration::from_millis(500));
        }
    }
}

fn send(state: &str, payload: &[u8]) -> std::io::Result<()> {
    let mut msg = state.as_bytes().to_vec();
    msg.push(SEP);
    msg.extend_from_slice(payload);
    let sock = UdpSocket::bind("127.0.0.1:0")?;
    sock.send_to(&msg, ("127.0.0.1", PORT))?;
    Ok(())
}

fn spawn_daemon() {
    use std::os::windows::process::CommandExt;
    let Some(bin_dir) = std::env::current_exe().ok().and_then(|p| p.parent().map(PathBuf::from)) else {
        return;
    };
    let daemon = bin_dir.join("zpetd").join("zpetd.exe");
    if !daemon.exists() {
        return;
    }
    const DETACHED: u32 = 0x0000_0008 | 0x0000_0200; // DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    const BREAKAWAY: u32 = 0x0100_0000; // CREATE_BREAKAWAY_FROM_JOB
    let make = |flags: u32| Command::new(&daemon)
        .creation_flags(flags)
        .stdin(std::process::Stdio::null())
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::null())
        .spawn();
    if make(DETACHED | BREAKAWAY).is_err() {
        let _ = make(DETACHED);
    }
}
