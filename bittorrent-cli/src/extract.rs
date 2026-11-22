//! Extrae enlaces magnet de una pagina web o de un HTML guardado.
//!
//! Port de `extract_magnets.py`, incluyendo la carga de cookies en formato
//! Netscape y el mismo tratamiento especial del error HTTP 403.

use std::collections::HashSet;
use std::path::Path;
use std::sync::OnceLock;
use std::time::Duration;

use regex::Regex;
use reqwest::cookie::Jar;

const MAX_PAGE_SIZE: usize = 5 * 1024 * 1024;

const USER_AGENT: &str = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) \
AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36";

/// Error de `fetch_page` conservando el estado HTTP cuando lo hubo.
#[derive(Debug)]
pub struct PageError {
    pub status: Option<u16>,
    pub message: String,
}

impl PageError {
    fn new(message: impl Into<String>) -> Self {
        PageError {
            status: None,
            message: message.into(),
        }
    }
}

impl std::fmt::Display for PageError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter.write_str(&self.message)
    }
}

impl std::error::Error for PageError {}

/// Devuelve enlaces magnet unicos, decodificando entidades HTML.
pub fn extract_magnets(page_html: &str) -> Vec<String> {
    static PATTERN: OnceLock<Regex> = OnceLock::new();
    let pattern = PATTERN.get_or_init(|| {
        Regex::new(r#"(?i)magnet:\?[^"'`<>\s]+"#).expect("expresion magnet valida")
    });

    let mut magnets = Vec::new();
    let mut seen: HashSet<String> = HashSet::new();
    for found in pattern.find_iter(page_html) {
        let decoded = html_escape::decode_html_entities(found.as_str()).into_owned();
        let magnet = decoded
            .trim_end_matches([')', ',', '.', ';', ']', '}'])
            .to_string();
        if !magnet.to_lowercase().starts_with("magnet:?xt=") {
            continue;
        }
        if seen.insert(magnet.clone()) {
            magnets.push(magnet);
        }
    }
    magnets
}

/// Descarga una pagina aplicando cabeceras de navegador y cookies opcionales.
pub async fn fetch_page(
    url: &str,
    timeout: f64,
    cookie_file: Option<&Path>,
) -> Result<String, PageError> {
    let parsed = url::Url::parse(url)
        .map_err(|_| PageError::new("La URL debe empezar por http:// o https://"))?;
    if !matches!(parsed.scheme(), "http" | "https") || parsed.host_str().is_none() {
        return Err(PageError::new("La URL debe empezar por http:// o https://"));
    }

    let mut headers = reqwest::header::HeaderMap::new();
    headers.insert(
        reqwest::header::USER_AGENT,
        reqwest::header::HeaderValue::from_static(USER_AGENT),
    );
    headers.insert(
        reqwest::header::ACCEPT,
        reqwest::header::HeaderValue::from_static("text/html,application/xhtml+xml,*/*;q=0.8"),
    );
    headers.insert(
        reqwest::header::ACCEPT_LANGUAGE,
        reqwest::header::HeaderValue::from_static("es-ES,es;q=0.9,en;q=0.8"),
    );
    headers.insert(
        reqwest::header::ACCEPT_ENCODING,
        reqwest::header::HeaderValue::from_static("identity"),
    );
    headers.insert(
        reqwest::header::HeaderName::from_static("upgrade-insecure-requests"),
        reqwest::header::HeaderValue::from_static("1"),
    );

    let mut builder = reqwest::Client::builder()
        .default_headers(headers)
        .timeout(Duration::from_secs_f64(timeout.max(0.001)));
    if let Some(cookie_file) = cookie_file {
        let jar = load_cookies(cookie_file, &parsed).map_err(PageError::new)?;
        builder = builder.cookie_provider(std::sync::Arc::new(jar));
    }
    let client = builder
        .build()
        .map_err(|error| PageError::new(error.to_string()))?;

    let response = client
        .get(parsed.clone())
        .send()
        .await
        .map_err(|error| PageError::new(error.to_string()))?;
    let status = response.status();
    if status == reqwest::StatusCode::FORBIDDEN {
        return Err(PageError {
            status: Some(403),
            message: "HTTP Error 403: Forbidden".to_string(),
        });
    }
    if !status.is_success() {
        return Err(PageError {
            status: Some(status.as_u16()),
            message: format!(
                "HTTP Error {}: {}",
                status.as_u16(),
                status.canonical_reason().unwrap_or_default()
            ),
        });
    }
    if let Some(length) = response.content_length() {
        if length > MAX_PAGE_SIZE as u64 {
            return Err(PageError::new("La página supera el límite de 5 MB"));
        }
    }
    let page = response
        .text()
        .await
        .map_err(|error| PageError::new(error.to_string()))?;
    if page.len() > MAX_PAGE_SIZE {
        return Err(PageError::new("La página supera el límite de 5 MB"));
    }
    Ok(page)
}

fn load_cookies(cookie_file: &Path, url: &url::Url) -> Result<Jar, String> {
    let raw = std::fs::read_to_string(cookie_file)
        .map_err(|error| format!("No se pudo leer el archivo de cookies: {error}"))?;
    let jar = Jar::default();
    for line in raw.lines() {
        let line = line.trim_end_matches('\r');
        if line.is_empty() {
            continue;
        }
        let line = if let Some(rest) = line.strip_prefix("#HttpOnly_") {
            rest
        } else if line.starts_with('#') {
            continue;
        } else {
            line
        };
        let fields: Vec<&str> = line.split('\t').collect();
        if fields.len() != 7 {
            continue;
        }
        let (domain, flag, path, secure, _expires, name, value) = (
            fields[0], fields[1], fields[2], fields[3], fields[4], fields[5], fields[6],
        );
        let mut domain = domain.to_string();
        if flag.eq_ignore_ascii_case("true") && !domain.starts_with('.') {
            domain.insert(0, '.');
        }
        let mut cookie = format!("{name}={value}; Domain={domain}; Path={path}");
        if secure.eq_ignore_ascii_case("true") {
            cookie.push_str("; Secure");
        }
        jar.add_cookie_str(&cookie, url);
    }
    Ok(jar)
}

#[cfg(test)]
mod tests {
    use super::extract_magnets;

    #[test]
    fn extracts_unique_valid_magnets() {
        let page = r#"
            <a href="magnet:?xt=urn:btih:AAA&amp;dn=One">x</a>
            magnet:?xt=urn:btih:BBB).
            magnet:?xt=urn:btih:AAA
            magnet:?dn=nombre
            <b>MAGNET:?XT=urn:btih:CCC</b>
        "#;
        let magnets = extract_magnets(page);
        assert_eq!(
            magnets,
            vec![
                "magnet:?xt=urn:btih:AAA&dn=One".to_string(),
                "magnet:?xt=urn:btih:BBB".to_string(),
                "magnet:?xt=urn:btih:AAA".to_string(),
                "MAGNET:?XT=urn:btih:CCC".to_string(),
            ]
        );
    }

    #[test]
    fn returns_empty_when_no_magnets() {
        assert!(extract_magnets("<html>nothing</html>").is_empty());
    }
}
