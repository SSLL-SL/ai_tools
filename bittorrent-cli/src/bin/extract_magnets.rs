//! Extrae enlaces magnet de una pagina web o de un HTML guardado.

use std::path::Path;

use clap::{CommandFactory, Parser};

use bittorrent_cli::extract::{extract_magnets, fetch_page};

#[derive(Parser)]
#[command(
    name = "extract-magnets",
    about = "Extrae enlaces magnet de una página web o de un HTML guardado."
)]
struct Args {
    /// URL HTTP o HTTPS de la página
    url: Option<String>,
    /// extrae los magnets de una copia HTML guardada
    #[arg(long = "html-file", value_name = "ARCHIVO")]
    html_file: Option<String>,
    /// archivo de cookies exportado en formato Netscape
    #[arg(long = "cookies", value_name = "COOKIES.TXT")]
    cookies: Option<String>,
}

#[tokio::main]
async fn main() {
    let args = Args::parse();

    if args.url.is_some() == args.html_file.is_some() {
        Args::command()
            .error(
                clap::error::ErrorKind::ValueValidation,
                "indica una URL o usa --html-file ARCHIVO",
            )
            .exit();
    }
    if args.cookies.is_some() && args.html_file.is_some() {
        Args::command()
            .error(
                clap::error::ErrorKind::ValueValidation,
                "--cookies solo se puede usar con una URL",
            )
            .exit();
    }

    let page = if let Some(html_file) = &args.html_file {
        match std::fs::read(html_file) {
            Ok(bytes) => String::from_utf8_lossy(&bytes).into_owned(),
            Err(error) => {
                eprintln!("Error: {error}");
                std::process::exit(1);
            }
        }
    } else {
        let url = args.url.as_deref().unwrap();
        let cookie_file = args.cookies.as_deref().map(Path::new);
        match fetch_page(url, 20.0, cookie_file).await {
            Ok(page) => page,
            Err(error) => {
                if error.status == Some(403) {
                    let message = if args.cookies.is_some() {
                        "El servidor sigue rechazando la petición (HTTP 403), incluso con las cookies indicadas."
                    } else {
                        "El servidor rechazó la petición (HTTP 403). Si la página abre en tu navegador, \
prueba con --cookies COOKIES.TXT o guarda la página y usa --html-file ARCHIVO."
                    };
                    eprintln!("Error: {message}");
                } else {
                    eprintln!("Error: {error}");
                }
                std::process::exit(1);
            }
        }
    };

    let magnets = extract_magnets(&page);
    if magnets.is_empty() {
        println!("No se encontraron enlaces magnet.");
        return;
    }
    println!("{}", magnets.join("\n"));
}
