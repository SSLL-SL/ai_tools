//! Servicio local requerido por la extension de Chrome para descargar desde magnets.

use clap::{CommandFactory, Parser};

use bittorrent_cli::helper;

#[derive(Parser)]
#[command(
    name = "torrent-helper",
    about = "Inicia el servicio local requerido por la extensión para descargar desde magnets."
)]
struct Args {
    /// ID de la extensión mostrado en chrome://extensions
    #[arg(long = "extension-id")]
    extension_id: String,
    /// puerto local (por defecto: 8765)
    #[arg(long = "port", default_value_t = 8765)]
    port: u16,
}

fn valid_extension_id(value: &str) -> bool {
    value.len() == 32 && value.bytes().all(|byte| (b'a'..=b'p').contains(&byte))
}

#[tokio::main]
async fn main() {
    let args = Args::parse();

    if !valid_extension_id(&args.extension_id) {
        Args::command()
            .error(
                clap::error::ErrorKind::ValueValidation,
                "--extension-id debe ser el ID de 32 letras mostrado por Chrome",
            )
            .exit();
    }
    if !(1..=65535).contains(&args.port) {
        Args::command()
            .error(
                clap::error::ErrorKind::ValueValidation,
                "--port debe estar entre 1 y 65535",
            )
            .exit();
    }

    if let Err(error) = helper::serve(args.port, &args.extension_id).await {
        eprintln!("Error: {error}");
        std::process::exit(1);
    }
}
