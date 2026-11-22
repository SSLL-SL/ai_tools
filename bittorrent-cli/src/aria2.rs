//! Obtiene el archivo .torrent asociado a un magnet usando aria2c.
//!
//! Port de `magnet_to_torrent.py` (y parte de lo que el original hacia en
//! `btclient.client` para la descarga completa desde el helper).

use std::path::{Path, PathBuf};
use std::process::Stdio;
use std::time::Duration;

use tokio::process::Command;

use crate::client::{BitTorrentClient, Progress};
use crate::error::Result;

const INVALID_MAGNET: &str = "Indica un magnet válido que incluya el parámetro xt.";

/// Errores tipados para poder mapearlos a los codigos HTTP del helper, como
/// hacian `ValueError`/`RuntimeError`/`OSError` en Python.
#[derive(Debug)]
pub enum ConvertError {
    /// Equivale a `ValueError`: entrada o destino invalido (HTTP 400).
    Invalid(String),
    /// Equivale a `RuntimeError`: fallo al ejecutar aria2c (HTTP 502).
    Runtime(String),
    /// Equivale a `OSError`: fallo de sistema de ficheros (HTTP 500).
    Os(String),
}

impl std::fmt::Display for ConvertError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            ConvertError::Invalid(message)
            | ConvertError::Runtime(message)
            | ConvertError::Os(message) => formatter.write_str(message),
        }
    }
}

impl std::error::Error for ConvertError {}

impl From<ConvertError> for crate::Error {
    fn from(error: ConvertError) -> Self {
        crate::Error::msg(error.to_string())
    }
}

/// Valida que el texto sea un enlace magnet con parametro `xt`.
pub fn validate_magnet(value: &str) -> std::result::Result<String, ConvertError> {
    let magnet = value.trim().to_string();
    let parsed =
        url::Url::parse(&magnet).map_err(|_| ConvertError::Invalid(INVALID_MAGNET.into()))?;
    if parsed.scheme().to_lowercase() != "magnet" {
        return Err(ConvertError::Invalid(INVALID_MAGNET.into()));
    }
    let has_xt = parsed.query_pairs().any(|(key, _)| key == "xt");
    if !has_xt {
        return Err(ConvertError::Invalid(INVALID_MAGNET.into()));
    }
    Ok(magnet)
}

/// Descarga el torrent de un magnet con el cliente propio, informando progreso.
pub async fn download_magnet<F>(magnet: &str, mut progress: F) -> Result<()>
where
    F: FnMut(Progress),
{
    let magnet = validate_magnet(magnet)?;
    let client = BitTorrentClient::new("./descargas", 0);
    let mut download = Box::pin(client.download(&magnet));
    let outcome = loop {
        progress(client.get_progress());
        tokio::select! {
            result = &mut download => break result,
            _ = tokio::time::sleep(Duration::from_secs(1)) => {}
        }
    };
    progress(client.get_progress());
    outcome
}

struct TempDir {
    path: PathBuf,
}

impl TempDir {
    fn create(prefix: &str) -> std::io::Result<Self> {
        let path = std::env::temp_dir().join(format!(
            "{prefix}{}",
            hex::encode(rand::random::<[u8; 8]>())
        ));
        std::fs::create_dir_all(&path)?;
        Ok(TempDir { path })
    }
}

impl Drop for TempDir {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.path);
    }
}

fn expand_user(value: &str) -> PathBuf {
    if let Some(rest) = value.strip_prefix("~/") {
        if let Some(home) = std::env::var_os("HOME").or_else(|| std::env::var_os("USERPROFILE")) {
            return PathBuf::from(home).join(rest);
        }
    }
    if value == "~" {
        if let Some(home) = std::env::var_os("HOME").or_else(|| std::env::var_os("USERPROFILE")) {
            return PathBuf::from(home);
        }
    }
    PathBuf::from(value)
}

/// Busca un ejecutable en `PATH` (equivalente a `shutil.which`).
pub fn which(program: &str) -> Option<PathBuf> {
    let path = std::env::var_os("PATH")?;
    let extensions: Vec<String> = if cfg!(windows) {
        std::env::var("PATHEXT")
            .unwrap_or_else(|_| ".COM;.EXE;.BAT;.CMD".to_string())
            .split(';')
            .filter(|extension| !extension.is_empty())
            .map(|extension| extension.to_string())
            .collect()
    } else {
        vec![String::new()]
    };
    for directory in std::env::split_paths(&path) {
        for extension in &extensions {
            let candidate = directory.join(format!("{program}{extension}"));
            if candidate.is_file() {
                return Some(candidate);
            }
        }
    }
    None
}

fn format_number(value: f64) -> String {
    if value.is_finite() && value.fract() == 0.0 && value.abs() < 1e15 {
        format!("{}", value as i64)
    } else {
        format!("{value}")
    }
}

/// Convierte un magnet en `.torrent` ejecutando aria2c (equivalente a `convert_magnet`).
pub async fn convert_magnet(
    magnet: &str,
    output: Option<&Path>,
    timeout: f64,
) -> std::result::Result<PathBuf, ConvertError> {
    let magnet = validate_magnet(magnet)?;

    let aria2c = which("aria2c").ok_or_else(|| {
        ConvertError::Runtime(
            "No se encontró aria2c. Instálalo, por ejemplo con «brew install aria2», y vuelve a intentarlo.".into(),
        )
    })?;

    let mut destination: Option<PathBuf> = None;
    if let Some(output) = output {
        let mut candidate = expand_user(&output.to_string_lossy());
        let extension = candidate
            .extension()
            .map(|value| value.to_string_lossy().to_lowercase())
            .unwrap_or_default();
        if extension != "torrent" {
            let name = candidate
                .file_name()
                .map(|value| value.to_string_lossy().into_owned())
                .unwrap_or_default();
            candidate = candidate.with_file_name(format!("{name}.torrent"));
        }
        if !candidate.is_absolute() {
            candidate = std::env::current_dir()
                .map(|directory| directory.join(&candidate))
                .unwrap_or(candidate);
        }
        if let Some(parent) = candidate.parent() {
            if !parent.is_dir() {
                return Err(ConvertError::Invalid(format!(
                    "No existe la carpeta de destino: {}",
                    parent.display()
                )));
            }
        }
        if candidate.exists() {
            return Err(ConvertError::Invalid(format!(
                "El archivo ya existe: {}",
                candidate.display()
            )));
        }
        destination = Some(candidate);
    }

    let temp = TempDir::create("magnet-to-torrent-")
        .map_err(|error| ConvertError::Os(error.to_string()))?;
    let dir = temp.path.clone();

    let mut command = Command::new(&aria2c);
    command
        .arg("--bt-metadata-only=true")
        .arg("--bt-save-metadata=true")
        .arg("--seed-time=0")
        .arg("--summary-interval=0")
        .arg("--console-log-level=warn")
        .arg("--bt-tracker-connect-timeout=10")
        .arg("--bt-tracker-timeout=15")
        .arg(format!("--dir={}", dir.display()))
        .arg(magnet)
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());

    let output_result = tokio::time::timeout(
        Duration::from_secs_f64(timeout.max(0.001)),
        command.output(),
    )
    .await;

    let result = match output_result {
        Ok(Ok(result)) => result,
        Ok(Err(error)) => return Err(ConvertError::Os(error.to_string())),
        Err(_) => {
            return Err(ConvertError::Runtime(format!(
                "Se agotó el tiempo de espera ({} s).",
                format_number(timeout)
            )))
        }
    };

    if !result.status.success() {
        let stderr = String::from_utf8_lossy(&result.stderr);
        let stdout = String::from_utf8_lossy(&result.stdout);
        let raw = if !stderr.trim().is_empty() {
            stderr
        } else {
            stdout
        };
        let details = raw.trim();
        let suffix = if details.is_empty() {
            String::new()
        } else {
            let lines: Vec<&str> = details.lines().collect();
            let start = lines.len().saturating_sub(8);
            format!("\n{}", lines[start..].join("\n"))
        };
        return Err(ConvertError::Runtime(format!(
            "aria2c no pudo obtener los metadatos.{suffix}"
        )));
    }

    let mut torrent_files: Vec<PathBuf> = std::fs::read_dir(&dir)
        .map_err(|error| ConvertError::Os(error.to_string()))?
        .filter_map(|entry| entry.ok())
        .map(|entry| entry.path())
        .filter(|path| {
            path.is_file()
                && path
                    .extension()
                    .map(|value| value.to_string_lossy().to_lowercase() == "torrent")
                    .unwrap_or(false)
        })
        .collect();
    torrent_files.sort();
    let source = match torrent_files.into_iter().next() {
        Some(source) => source,
        None => {
            return Err(ConvertError::Runtime(
                "aria2c terminó, pero no generó ningún archivo .torrent.".into(),
            ))
        }
    };

    let destination = match destination {
        Some(destination) => destination,
        None => {
            let name = source
                .file_name()
                .map(|value| value.to_string_lossy().into_owned())
                .unwrap_or_else(|| "metadata.torrent".to_string());
            std::env::current_dir()
                .map(|directory| directory.join(&name))
                .unwrap_or_else(|_| PathBuf::from(name))
        }
    };
    if destination.exists() {
        return Err(ConvertError::Invalid(format!(
            "El archivo ya existe: {}",
            destination.display()
        )));
    }

    std::fs::copy(&source, &destination).map_err(|error| ConvertError::Os(error.to_string()))?;
    Ok(destination)
}

#[cfg(test)]
mod tests {
    use super::{format_number, validate_magnet};

    #[test]
    fn accepts_magnets_with_xt() {
        assert!(validate_magnet("magnet:?xt=urn:btih:ABC").is_ok());
        assert!(validate_magnet("  magnet:?xt=urn:btih:ABC&dn=x  ").is_ok());
    }

    #[test]
    fn rejects_magnets_without_xt() {
        assert!(validate_magnet("http://example.com").is_err());
        assert!(validate_magnet("magnet:?dn=nombre").is_err());
    }

    #[test]
    fn formats_numbers_like_python_g() {
        assert_eq!(format_number(300.0), "300");
        assert_eq!(format_number(12.5), "12.5");
    }
}
