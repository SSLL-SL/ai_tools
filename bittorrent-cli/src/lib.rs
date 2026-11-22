//! Cliente BitTorrent de consola (port a Rust de rutracker-magnet-tools).

pub mod aria2;
pub mod bencode;
pub mod client;
pub mod dht;
pub mod error;
pub mod extract;
pub mod helper;
pub mod magnet;
pub mod peer;
pub mod pex;
pub mod resume;
pub mod storage;
pub mod torrent;
pub mod tracker;

pub use client::{BitTorrentClient, Progress};
pub use error::{Error, Result};
