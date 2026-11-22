//! Metadatos del torrent: parseo, verificacion de piezas y mapa de ficheros.

use sha1::{Digest, Sha1};

use crate::bencode::{decode_torrent, BencodeError};
use crate::error::Result;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct FileInfo {
    pub path: String,
    pub length: u64,
}

#[derive(Debug, Clone)]
pub struct TorrentInfo {
    pub name: String,
    pub piece_length: u64,
    pub pieces: Vec<[u8; 20]>,
    pub files: Vec<FileInfo>,
    pub info_hash: [u8; 20],
    pub trackers: Vec<String>,
    pub multi_file: bool,
    pub raw_info: Vec<u8>,
}

impl TorrentInfo {
    pub fn total_size(&self) -> u64 {
        self.files.iter().map(|file| file.length).sum()
    }

    pub fn num_pieces(&self) -> usize {
        self.pieces.len()
    }

    pub fn is_multi_file(&self) -> bool {
        self.multi_file
    }

    /// Longitud de la pieza `index`, o `None` si esta fuera de rango.
    pub fn get_piece_length(&self, index: usize) -> Option<u64> {
        if index >= self.num_pieces() {
            return None;
        }
        if index == self.num_pieces() - 1 {
            Some(self.total_size() - index as u64 * self.piece_length)
        } else {
            Some(self.piece_length)
        }
    }
}

pub struct Torrent {
    pub info: TorrentInfo,
    pub bitfield: Vec<u8>,
    pub have: Vec<bool>,
}

impl Torrent {
    pub fn new(info: TorrentInfo) -> Self {
        let bitfield = vec![0u8; info.num_pieces().div_ceil(8)];
        let have = vec![false; info.num_pieces()];
        Torrent {
            info,
            bitfield,
            have,
        }
    }

    pub fn set_have(&mut self, index: usize) -> bool {
        if index >= self.info.num_pieces() {
            return false;
        }
        self.bitfield[index / 8] |= 0x80 >> (index % 8);
        self.have[index] = true;
        true
    }

    pub fn has_piece(&self, index: usize) -> bool {
        self.have.get(index).copied().unwrap_or(false)
    }

    pub fn is_complete(&self) -> bool {
        !self.have.is_empty() && self.have.iter().all(|have| *have)
    }

    pub fn any_have(&self) -> bool {
        self.have.iter().any(|have| *have)
    }

    pub fn progress(&self) -> f64 {
        if self.have.is_empty() {
            1.0
        } else {
            self.have.iter().filter(|have| **have).count() as f64 / self.have.len() as f64
        }
    }

    pub fn get_missing_pieces(&self) -> Vec<usize> {
        self.have
            .iter()
            .enumerate()
            .filter(|(_, have)| !**have)
            .map(|(index, _)| index)
            .collect()
    }

    pub fn verify_piece(&self, index: usize, data: &[u8]) -> bool {
        match self.info.get_piece_length(index) {
            Some(expected) if data.len() as u64 == expected => {
                let digest = Sha1::digest(data);
                digest.as_slice() == self.info.pieces[index].as_slice()
            }
            _ => false,
        }
    }
}

fn text(value: &[u8], field: &str) -> Result<String> {
    std::str::from_utf8(value)
        .map(|value| value.to_string())
        .map_err(|_| {
            BencodeError::new(format!("Torrent field {field:?} is not valid UTF-8")).into()
        })
}

fn missing_fields() -> crate::error::Error {
    BencodeError::new("Torrent info dictionary is missing required fields").into()
}

fn invalid_files() -> crate::error::Error {
    BencodeError::new("Torrent contains invalid file metadata").into()
}

fn safe_relative_path(parts: &[Vec<u8>]) -> Result<String> {
    let mut decoded = Vec::with_capacity(parts.len());
    for part in parts {
        decoded.push(text(part, "path")?);
    }
    if decoded.is_empty()
        || decoded.iter().any(|part| {
            part.is_empty()
                || part == "."
                || part == ".."
                || part.contains('/')
                || part.contains('\\')
        })
    {
        return Err(BencodeError::new("Torrent contains an unsafe file path").into());
    }
    Ok(decoded.join("/"))
}

pub fn parse_torrent_bytes(data: &[u8]) -> Result<TorrentInfo> {
    let (decoded, raw_info) = decode_torrent(data)?;
    let info = decoded
        .get(b"info")
        .and_then(|value| value.as_dict())
        .ok_or_else(missing_fields)?;

    let name_bytes = info
        .get(b"name".as_slice())
        .and_then(|value| value.as_bytes())
        .ok_or_else(missing_fields)?
        .to_vec();
    let name = text(&name_bytes, "name")?;
    safe_relative_path(std::slice::from_ref(&name_bytes))?;

    let piece_length = info
        .get(b"piece length".as_slice())
        .and_then(|value| value.as_int())
        .ok_or_else(missing_fields)?;
    let pieces_raw = info
        .get(b"pieces".as_slice())
        .and_then(|value| value.as_bytes())
        .ok_or_else(missing_fields)?
        .to_vec();

    if piece_length <= 0 {
        return Err(BencodeError::new("Invalid piece length").into());
    }
    if pieces_raw.len() % 20 != 0 {
        return Err(BencodeError::new("Invalid pieces hash string").into());
    }
    let pieces: Vec<[u8; 20]> = pieces_raw
        .chunks(20)
        .map(|chunk| {
            let mut hash = [0u8; 20];
            hash.copy_from_slice(chunk);
            hash
        })
        .collect();

    let multi_file = info.contains_key(b"files".as_slice());
    let mut raw_files: Vec<(String, i64)> = Vec::new();
    if multi_file {
        let entries = info
            .get(b"files".as_slice())
            .and_then(|value| value.as_list())
            .ok_or_else(invalid_files)?;
        for entry in entries {
            let entry = entry.as_dict().ok_or_else(invalid_files)?;
            let length = entry
                .get(b"length".as_slice())
                .and_then(|value| value.as_int())
                .ok_or_else(invalid_files)?;
            let path = entry
                .get(b"path".as_slice())
                .and_then(|value| value.as_list())
                .ok_or_else(invalid_files)?;
            let parts: Vec<Vec<u8>> = path
                .iter()
                .map(|part| part.as_bytes().map(|bytes| bytes.to_vec()))
                .collect::<Option<Vec<_>>>()
                .ok_or_else(invalid_files)?;
            raw_files.push((safe_relative_path(&parts)?, length));
        }
    } else {
        let length = info
            .get(b"length".as_slice())
            .and_then(|value| value.as_int())
            .ok_or_else(invalid_files)?;
        raw_files.push((
            safe_relative_path(std::slice::from_ref(&name_bytes))?,
            length,
        ));
    }

    if raw_files.iter().any(|(_, length)| *length < 0) {
        return Err(BencodeError::new("Torrent contains an invalid file length").into());
    }
    let total_size: u64 = raw_files.iter().map(|(_, length)| *length as u64).sum();
    let expected_pieces = total_size.div_ceil(piece_length as u64) as usize;
    if pieces.len() != expected_pieces {
        return Err(BencodeError::new(format!(
            "Torrent has {} piece hashes; expected {expected_pieces}",
            pieces.len()
        ))
        .into());
    }

    let mut trackers: Vec<String> = Vec::new();
    if let Some(announce) = decoded.get(b"announce").and_then(|value| value.as_bytes()) {
        trackers.push(text(announce, "announce")?);
    }
    if let Some(tiers) = decoded
        .get(b"announce-list")
        .and_then(|value| value.as_list())
    {
        for tier in tiers {
            if let Some(tier) = tier.as_list() {
                for tracker in tier {
                    if let Some(value) = tracker.as_bytes() {
                        let value = text(value, "announce-list")?;
                        if !trackers.contains(&value) {
                            trackers.push(value);
                        }
                    }
                }
            }
        }
    }

    let mut info_hash = [0u8; 20];
    info_hash.copy_from_slice(&Sha1::digest(&raw_info));

    let files = raw_files
        .into_iter()
        .map(|(path, length)| FileInfo {
            path,
            length: length as u64,
        })
        .collect();

    Ok(TorrentInfo {
        name,
        piece_length: piece_length as u64,
        pieces,
        files,
        info_hash,
        trackers,
        multi_file,
        raw_info,
    })
}

pub fn parse_torrent_file(path: &std::path::Path) -> Result<TorrentInfo> {
    let data = std::fs::read(path)?;
    parse_torrent_bytes(&data)
}

/// Parsea los bytes de metadatos de BEP 9 sin alterar su representacion hasheada.
pub fn parse_info_bytes(raw_info: &[u8], trackers: &[String]) -> Result<TorrentInfo> {
    let mut wrapped = Vec::with_capacity(raw_info.len() + 8);
    wrapped.extend_from_slice(b"d4:info");
    wrapped.extend_from_slice(raw_info);
    wrapped.push(b'e');
    let mut info = parse_torrent_bytes(&wrapped)?;
    if !trackers.is_empty() {
        let mut seen: Vec<String> = Vec::new();
        for tracker in trackers {
            if !seen.contains(tracker) {
                seen.push(tracker.clone());
            }
        }
        info.trackers = seen;
    }
    Ok(info)
}
