use thiserror::Error;

use crate::bencode::BencodeError;

pub type Result<T> = std::result::Result<T, Error>;

/// Error unico del proyecto. Los errores que en Python eran clases de excepcion
/// separadas (BencodeError, TrackerError, PeerError...) se convierten aqui.
#[derive(Debug, Error)]
pub enum Error {
    #[error("{0}")]
    Msg(String),
    #[error(transparent)]
    Io(#[from] std::io::Error),
    #[error(transparent)]
    Bencode(#[from] BencodeError),
    #[error(transparent)]
    Json(#[from] serde_json::Error),
    #[error(transparent)]
    Http(#[from] reqwest::Error),
    #[error(transparent)]
    Url(#[from] url::ParseError),
}

impl Error {
    pub fn msg(message: impl Into<String>) -> Self {
        Error::Msg(message.into())
    }
}
