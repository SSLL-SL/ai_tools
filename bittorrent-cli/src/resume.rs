//! Puntos de control de descarga por torrent, a prueba de fallos.

use std::io::Write;
use std::path::{Path, PathBuf};

use base64::engine::general_purpose::STANDARD;
use base64::Engine;

use crate::error::{Error, Result};
use crate::torrent::TorrentInfo;

const MAX_RESUME_SIZE: u64 = 16 * 1024 * 1024;

pub struct ResumeStore {
    directory: PathBuf,
    path: PathBuf,
    info_hash: [u8; 20],
    piece_length: u64,
    total_size: u64,
    num_pieces: usize,
}

impl ResumeStore {
    const VERSION: u64 = 1;

    pub fn new(save_path: &Path, info: &TorrentInfo) -> Result<Self> {
        let directory = std::path::absolute(save_path)?.join(".btclient");
        let path = directory.join(format!("{}.resume.json", hex::encode(info.info_hash)));
        Ok(ResumeStore {
            directory,
            path,
            info_hash: info.info_hash,
            piece_length: info.piece_length,
            total_size: info.total_size(),
            num_pieces: info.num_pieces(),
        })
    }

    /// Devuelve el bitfield guardado o `None` si no hay un checkpoint valido.
    pub fn load(&self) -> Option<Vec<u8>> {
        let metadata = std::fs::metadata(&self.path).ok()?;
        if metadata.len() > MAX_RESUME_SIZE {
            return None;
        }
        let raw = std::fs::read(&self.path).ok()?;
        if raw.len() as u64 > MAX_RESUME_SIZE {
            return None;
        }
        let document: serde_json::Value = serde_json::from_slice(&raw).ok()?;
        let object = document.as_object()?;

        if object.get("version")?.as_u64()? != Self::VERSION {
            return None;
        }
        if object.get("info_hash")?.as_str()? != hex::encode(self.info_hash) {
            return None;
        }
        if object.get("piece_length")?.as_u64()? != self.piece_length {
            return None;
        }
        if object.get("total_size")?.as_u64()? != self.total_size {
            return None;
        }
        if object.get("num_pieces")?.as_u64()? != self.num_pieces as u64 {
            return None;
        }

        let bitfield = STANDARD.decode(object.get("bitfield")?.as_str()?).ok()?;
        let expected_length = self.num_pieces.div_ceil(8);
        if bitfield.len() != expected_length {
            return None;
        }
        if !self.num_pieces.is_multiple_of(8) && !bitfield.is_empty() {
            let unused_mask = (1u16 << (8 - self.num_pieces % 8)) - 1;
            if bitfield[bitfield.len() - 1] as u16 & unused_mask != 0 {
                return None;
            }
        }
        Some(bitfield)
    }

    pub fn save(&self, bitfield: &[u8]) -> Result<()> {
        let expected_length = self.num_pieces.div_ceil(8);
        if bitfield.len() != expected_length {
            return Err(Error::msg("Resume bitfield has an unexpected length"));
        }
        std::fs::create_dir_all(&self.directory)?;

        let mut document: serde_json::Map<String, serde_json::Value> = serde_json::Map::new();
        document.insert("version".into(), Self::VERSION.into());
        document.insert("info_hash".into(), hex::encode(self.info_hash).into());
        document.insert("piece_length".into(), self.piece_length.into());
        document.insert("total_size".into(), self.total_size.into());
        document.insert("num_pieces".into(), (self.num_pieces as u64).into());
        document.insert("bitfield".into(), STANDARD.encode(bitfield).into());

        let mut payload = serde_json::to_vec(&serde_json::Value::Object(document))?;
        payload.push(b'\n');

        let temporary_path = self.directory.join(format!(
            ".resume-{}",
            hex::encode(rand::random::<[u8; 8]>())
        ));
        {
            let mut file = std::fs::File::create(&temporary_path)?;
            file.write_all(&payload)?;
            file.flush()?;
            file.sync_all()?;
        }
        if let Err(error) = std::fs::rename(&temporary_path, &self.path) {
            let _ = std::fs::remove_file(&temporary_path);
            return Err(error.into());
        }
        Ok(())
    }
}
