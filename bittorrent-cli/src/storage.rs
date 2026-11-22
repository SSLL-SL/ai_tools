//! Mapea el flujo contiguo de bytes del torrent a sus ficheros de destino.

use std::fs::{File, OpenOptions};
use std::io::{Read, Seek, SeekFrom, Write};
use std::path::{Path, PathBuf};

use crate::error::{Error, Result};
use crate::torrent::TorrentInfo;

pub struct PieceStorage {
    info: TorrentInfo,
    base: PathBuf,
    segments: Vec<(u64, u64, File)>,
}

impl PieceStorage {
    pub fn new(info: &TorrentInfo, save_path: &Path) -> Result<Self> {
        let root = std::path::absolute(save_path)?;
        let base = if info.is_multi_file() {
            root.join(&info.name)
        } else {
            root
        };
        std::fs::create_dir_all(&base)?;

        let mut segments = Vec::with_capacity(info.files.len());
        let mut offset = 0u64;
        for entry in &info.files {
            let mut full = base.clone();
            for part in entry.path.split('/') {
                full.push(part);
            }
            if !full.starts_with(&base) {
                return Err(Error::msg("Torrent path escapes destination directory"));
            }
            if let Some(parent) = full.parent() {
                std::fs::create_dir_all(parent)?;
            }
            let file = OpenOptions::new()
                .read(true)
                .write(true)
                .create(true)
                .truncate(false)
                .open(&full)?;
            file.set_len(entry.length)?;
            segments.push((offset, offset + entry.length, file));
            offset += entry.length;
        }

        Ok(PieceStorage {
            info: info.clone(),
            base,
            segments,
        })
    }

    pub fn base(&self) -> &Path {
        &self.base
    }

    fn write_at(&mut self, offset: u64, data: &[u8]) -> Result<()> {
        let end = offset + data.len() as u64;
        let mut cursor = offset;
        for (segment_start, segment_end, file) in &mut self.segments {
            if *segment_end <= cursor || *segment_start >= end {
                continue;
            }
            let start = cursor.max(*segment_start);
            let stop = end.min(*segment_end);
            if stop > start {
                file.seek(SeekFrom::Start(start - *segment_start))?;
                file.write_all(&data[(start - offset) as usize..(stop - offset) as usize])?;
                cursor = stop;
            }
            if cursor >= end {
                break;
            }
        }
        if cursor != end {
            return Err(Error::msg(
                "Torrent piece could not be mapped to destination files",
            ));
        }
        Ok(())
    }

    pub fn write_piece(&mut self, piece_index: usize, data: &[u8]) -> Result<()> {
        let expected = self
            .info
            .get_piece_length(piece_index)
            .ok_or_else(|| Error::msg("Piece index out of range"))?;
        if data.len() as u64 != expected {
            return Err(Error::msg(format!(
                "Piece {piece_index} has {} bytes; expected {expected}",
                data.len()
            )));
        }
        self.write_at(piece_index as u64 * self.info.piece_length, data)?;
        for (_, _, file) in &mut self.segments {
            file.flush()?;
        }
        Ok(())
    }

    pub fn read_piece(&mut self, piece_index: usize) -> Result<Vec<u8>> {
        let offset = piece_index as u64 * self.info.piece_length;
        let length = self
            .info
            .get_piece_length(piece_index)
            .ok_or_else(|| Error::msg("Piece index out of range"))?;
        let end = offset + length;

        let mut reader = PieceReader {
            segments: &mut self.segments,
            cursor: offset,
            end,
            chunks: Vec::new(),
        };
        reader.collect()?;
        let mut data = Vec::with_capacity(length as usize);
        for chunk in reader.chunks {
            data.extend_from_slice(&chunk);
        }
        if data.len() as u64 != length {
            return Err(Error::msg(format!(
                "Piece {piece_index} is not fully present on disk"
            )));
        }
        Ok(data)
    }

    pub fn close(&mut self) {
        // Los ficheros se cierran al soltarse; no hay nada que hacer.
    }
}

struct PieceReader<'a> {
    segments: &'a mut Vec<(u64, u64, File)>,
    cursor: u64,
    end: u64,
    chunks: Vec<Vec<u8>>,
}

impl PieceReader<'_> {
    fn collect(&mut self) -> Result<()> {
        for (segment_start, segment_end, file) in self.segments.iter_mut() {
            if *segment_end <= self.cursor || *segment_start >= self.end {
                continue;
            }
            let start = self.cursor.max(*segment_start);
            let stop = self.end.min(*segment_end);
            file.seek(SeekFrom::Start(start - *segment_start))?;
            let mut buffer = vec![0u8; (stop - start) as usize];
            file.read_exact(&mut buffer)?;
            self.chunks.push(buffer);
            self.cursor = stop;
            if self.cursor >= self.end {
                break;
            }
        }
        Ok(())
    }
}
