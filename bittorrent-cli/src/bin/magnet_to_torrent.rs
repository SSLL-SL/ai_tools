//! Obtiene el .torrent desde un magnet sin descargar los archivos del torrent.

use std::path::Path;

use clap::{CommandFactory, Parser};

use bittorrent_cli::aria2::convert_magnet;

#[derive(Parser)]
#[command(
    name = "magnet-to-torrent",
    about = "Obtiene el .torrent desde un magnet sin descargar los archivos del torrent."
)]
struct Args {
    /// enlace magnet
    magnet: String,
    /// ruta del archivo .torrent (por defecto, el nombre generado por aria2c)
    #[arg(short = 'o', long = "output")]
    output: Option<String>,
    /// tiempo máximo para obtener los metadatos en segundos (por defecto: 300)
    #[arg(long = "timeout", default_value_t = 300.0)]
    timeout: f64,
}

#[tokio::main]
async fn main() {
    let args = Args::parse();

    if args.timeout <= 0.0 {
        Args::command()
            .error(
                clap::error::ErrorKind::ValueValidation,
                "--timeout debe ser mayor que cero",
            )
            .exit();
    }

    let output = args.output.as_deref().map(Path::new);
    match convert_magnet(&args.magnet, output, args.timeout).await {
        Ok(path) => println!("Guardado: {}", path.display()),
        Err(error) => {
            eprintln!("Error: {error}");
            std::process::exit(1);
        }
    }
}
