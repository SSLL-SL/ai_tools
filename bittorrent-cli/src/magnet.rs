//! Parseo de URIs magnet para BitTorrent v1 (intercambio de metadatos BEP 9).

use data_encoding::BASE32_NOPAD;

use crate::error::{Error, Result};

#[derive(Debug, Clone)]
pub struct MagnetInfo {
    pub info_hash: [u8; 20],
    pub display_name: String,
    pub trackers: Vec<String>,
}

fn is_hex_digest(value: &str) -> bool {
    value.len() == 40 && value.bytes().all(|byte| byte.is_ascii_hexdigit())
}

fn is_base32_digest(value: &str) -> bool {
    value.len() == 32
        && value.bytes().all(|byte| {
            byte.is_ascii_uppercase() || (b'2'..=b'7').contains(&byte) || byte.is_ascii_lowercase()
        })
}

pub fn parse_magnet_uri(uri: &str) -> Result<MagnetInfo> {
    if !uri.to_lowercase().starts_with("magnet:?") {
        return Err(Error::msg(
            "Enlace magnet invalido: debe comenzar por magnet:?",
        ));
    }

    let query = uri.split_once('?').map(|parts| parts.1).unwrap_or("");
    let pairs: Vec<(String, String)> = url::form_urlencoded::parse(query.as_bytes())
        .into_owned()
        .collect();

    let xt = pairs
        .iter()
        .filter(|(key, _)| key == "xt")
        .map(|(_, value)| value)
        .find(|value| value.to_lowercase().starts_with("urn:btih:"))
        .ok_or_else(|| Error::msg("El magnet debe incluir xt=urn:btih:<info-hash>"))?;

    let digest = xt
        .splitn(3, ':')
        .nth(2)
        .ok_or_else(|| Error::msg("El magnet debe incluir xt=urn:btih:<info-hash>"))?;

    let bytes = if is_hex_digest(digest) {
        hex::decode(digest)
            .map_err(|_| Error::msg("El info-hash del magnet debe ser BTIH hexadecimal o Base32"))?
    } else if is_base32_digest(digest) {
        BASE32_NOPAD
            .decode(digest.to_uppercase().as_bytes())
            .map_err(|_| Error::msg("El info-hash del magnet debe ser BTIH hexadecimal o Base32"))?
    } else {
        return Err(Error::msg(
            "El info-hash del magnet debe ser BTIH hexadecimal o Base32",
        ));
    };

    if bytes.len() != 20 {
        return Err(Error::msg("El info-hash BTIH debe ocupar 20 bytes"));
    }
    let mut info_hash = [0u8; 20];
    info_hash.copy_from_slice(&bytes);

    let mut trackers: Vec<String> = Vec::new();
    for (key, value) in &pairs {
        if key == "tr" && !value.is_empty() && !trackers.contains(value) {
            trackers.push(value.clone());
        }
    }

    let display_name = pairs
        .iter()
        .find(|(key, _)| key == "dn")
        .map(|(_, value)| value.clone())
        .unwrap_or_else(|| "Magnet torrent".to_string());

    Ok(MagnetInfo {
        info_hash,
        display_name,
        trackers,
    })
}
