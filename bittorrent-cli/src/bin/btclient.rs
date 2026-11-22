//! Cliente BitTorrent de consola (port de `main.py`).

use std::io::Write;
use std::path::Path;
use std::time::Duration;

use clap::Parser;

use bittorrent_cli::client::BitTorrentClient;
use bittorrent_cli::torrent::parse_torrent_file;

#[derive(Parser)]
#[command(
    name = "btclient",
    about = "Cliente BitTorrent de consola",
    disable_help_subcommand = true
)]
struct Args {
    /// Ruta al archivo .torrent o un enlace magnet
    source: String,
    /// Directorio de destino (default: actual)
    #[arg(short = 'o', long = "output", default_value = ".")]
    output: String,
    /// Listar contenido sin descargar
    #[arg(short = 'l', long = "list")]
    list: bool,
    /// Puerto anunciado a los peers (default: 6881)
    #[arg(long = "port", default_value_t = 6881)]
    port: u16,
    /// Mostrar mensajes de diagnóstico
    #[arg(long = "verbose")]
    verbose: bool,
}

fn format_size(size: f64) -> String {
    let units = ["B", "KB", "MB", "GB", "TB"];
    let mut size = size;
    for unit in units {
        if size < 1024.0 {
            return format!("{size:.1} {unit}");
        }
        size /= 1024.0;
    }
    format!("{size:.1} PB")
}

fn print_progress(progress: &bittorrent_cli::client::Progress) {
    let percent = progress.progress * 100.0;
    let bar_length: i64 = 30;
    let filled = (bar_length as f64 * percent / 100.0) as i64;
    let mut bar = "=".repeat(filled.max(0) as usize);
    if filled < bar_length {
        bar.push('>');
    }
    bar.push_str(&" ".repeat((bar_length - filled - 1).max(0) as usize));

    let downloaded = format_size(progress.downloaded as f64);
    let total = format_size(progress.total as f64);
    let speed = format!("{}/s", format_size(progress.speed));
    print!(
        "\r[{bar}] {percent:.1}% | {downloaded} / {total} | {speed} | Peers: {}",
        progress.peers
    );
    let _ = std::io::stdout().flush();
}

fn list_contents(torrent_path: &str) -> bittorrent_cli::Result<()> {
    let info = parse_torrent_file(Path::new(torrent_path))?;
    println!("Nombre: {}", info.name);
    println!("Tamaño total: {}", format_size(info.total_size() as f64));
    println!(
        "Piezas: {} ({} c/u)",
        info.num_pieces(),
        format_size(info.piece_length as f64)
    );
    let trackers = if info.trackers.is_empty() {
        "Ninguno".to_string()
    } else {
        info.trackers.join(", ")
    };
    println!("Trackers: {trackers}");
    println!("Archivos ({}):", info.files.len());
    for file in &info.files {
        println!("  {} ({})", file.path, format_size(file.length as f64));
    }
    Ok(())
}

async fn download(torrent_path: &str, output_dir: &str, port: u16) -> bittorrent_cli::Result<()> {
    std::fs::create_dir_all(output_dir)?;

    let client = BitTorrentClient::new(output_dir, port);

    let label = if torrent_path.to_lowercase().starts_with("magnet:") {
        "magnet link".to_string()
    } else {
        torrent_path.to_string()
    };
    println!("Descargando: {label}");
    println!("Destino: {output_dir}");
    println!("Presiona Ctrl+C para detener\n");

    let mut download = Box::pin(client.download(torrent_path));
    let mut interrupted = false;
    let mut completed = false;
    loop {
        print_progress(&client.get_progress());
        tokio::select! {
            result = &mut download => {
                result?;
                completed = true;
                break;
            }
            _ = tokio::time::sleep(Duration::from_secs(1)) => {}
            _ = tokio::signal::ctrl_c() => {
                println!("\n\nDeteniendo descarga...");
                client.stop();
                interrupted = true;
                break;
            }
        }
    }

    if interrupted {
        let _ = download.await;
        return Ok(());
    }
    if completed {
        print_progress(&client.get_progress());
        println!("\n\nDescarga completada!");
    }
    Ok(())
}

#[tokio::main]
async fn main() {
    let args = Args::parse();

    let is_magnet = args.source.to_lowercase().starts_with("magnet:");
    if args.list && is_magnet {
        eprintln!("Error: --list solo funciona con archivos .torrent");
        std::process::exit(1);
    }
    if !is_magnet && !Path::new(&args.source).is_file() {
        eprintln!("Error: No se encuentra el archivo '{}'", args.source);
        std::process::exit(1);
    }

    let mut builder = env_logger::Builder::new();
    builder.filter_level(if args.verbose {
        log::LevelFilter::Info
    } else {
        log::LevelFilter::Warn
    });
    builder.format(|buffer, record| writeln!(buffer, "{}: {}", record.level(), record.args()));
    let _ = builder.try_init();

    let result = if args.list {
        list_contents(&args.source)
    } else {
        download(&args.source, &args.output, args.port).await
    };

    if let Err(error) = result {
        eprintln!("Error: {error}");
        std::process::exit(1);
    }
}
