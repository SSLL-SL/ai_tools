//! Conexion con un peer: handshake, mensajes y estado de la extension.

use std::collections::{HashMap, HashSet, VecDeque};
use std::sync::{Arc, Mutex as StdMutex};
use std::time::Duration;

use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::tcp::{OwnedReadHalf, OwnedWriteHalf};
use tokio::net::TcpStream;
use tokio::sync::Mutex as AsyncMutex;

use crate::bencode::{dict, encode, Value};
use crate::error::{Error, Result};

pub const CHOKE: u8 = 0;
pub const UNCHOKE: u8 = 1;
pub const INTERESTED: u8 = 2;
pub const NOT_INTERESTED: u8 = 3;
pub const HAVE: u8 = 4;
pub const BITFIELD: u8 = 5;
pub const REQUEST: u8 = 6;
pub const PIECE: u8 = 7;
pub const CANCEL: u8 = 8;
pub const EXTENDED: u8 = 20;

pub const PEX_LOCAL_ID: u8 = 1;
pub const METADATA_LOCAL_ID: u8 = 2;

pub type PeerRef = Arc<Peer>;

pub enum Incoming {
    KeepAlive,
    Message(u8, Vec<u8>),
}

pub struct PeerState {
    pub connected: bool,
    pub peer_choking: bool,
    pub am_choking: bool,
    pub supports_extensions: bool,
    pub bitfield: Vec<u8>,
    pub bitfield_sent: bool,
    pub assigned_piece: Option<usize>,
    pub outstanding: HashSet<(usize, usize)>,
    pub remote_extensions: HashMap<Vec<u8>, u8>,
    pub pex_address: Option<(String, u16)>,
    pub pex_announced: HashSet<(String, u16)>,
    pub metadata_size: Option<usize>,
    pub metadata_queue: VecDeque<usize>,
    pub metadata_outstanding: HashSet<usize>,
    pub pending_bitfield: Option<Vec<u8>>,
    pub pending_have: HashSet<usize>,
}

impl Default for PeerState {
    fn default() -> Self {
        PeerState {
            connected: false,
            peer_choking: true,
            am_choking: true,
            supports_extensions: false,
            bitfield: Vec::new(),
            bitfield_sent: false,
            assigned_piece: None,
            outstanding: HashSet::new(),
            remote_extensions: HashMap::new(),
            pex_address: None,
            pex_announced: HashSet::new(),
            metadata_size: None,
            metadata_queue: VecDeque::new(),
            metadata_outstanding: HashSet::new(),
            pending_bitfield: None,
            pending_have: HashSet::new(),
        }
    }
}

pub struct Peer {
    pub peer_id: [u8; 20],
    pub info_hash: [u8; 20],
    pub ip: String,
    pub port: u16,
    state: StdMutex<PeerState>,
    writer: AsyncMutex<Option<OwnedWriteHalf>>,
    reader: StdMutex<Option<OwnedReadHalf>>,
}

impl Peer {
    pub fn new(peer_id: [u8; 20], info_hash: [u8; 20], ip: String, port: u16) -> PeerRef {
        let pex_address = Some((ip.clone(), port));
        let state = PeerState {
            pex_address,
            ..PeerState::default()
        };
        Arc::new(Peer {
            peer_id,
            info_hash,
            ip,
            port,
            state: StdMutex::new(state),
            writer: AsyncMutex::new(None),
            reader: StdMutex::new(None),
        })
    }

    fn lock(&self) -> std::sync::MutexGuard<'_, PeerState> {
        self.state.lock().unwrap_or_else(|error| error.into_inner())
    }

    pub fn is_connected(&self) -> bool {
        self.lock().connected
    }

    pub fn set_connected(&self, value: bool) {
        self.lock().connected = value;
    }

    pub fn peer_choking(&self) -> bool {
        self.lock().peer_choking
    }

    pub fn set_peer_choking(&self, value: bool) {
        self.lock().peer_choking = value;
    }

    pub fn am_choking(&self) -> bool {
        self.lock().am_choking
    }

    pub fn set_am_choking(&self, value: bool) {
        self.lock().am_choking = value;
    }

    pub fn supports_extensions(&self) -> bool {
        self.lock().supports_extensions
    }

    pub fn set_supports_extensions(&self, value: bool) {
        self.lock().supports_extensions = value;
    }

    pub fn assigned_piece(&self) -> Option<usize> {
        self.lock().assigned_piece
    }

    pub fn set_assigned_piece(&self, value: Option<usize>) {
        self.lock().assigned_piece = value;
    }

    pub fn bitfield_sent(&self) -> bool {
        self.lock().bitfield_sent
    }

    pub fn set_bitfield_sent(&self, value: bool) {
        self.lock().bitfield_sent = value;
    }

    pub fn pex_address(&self) -> Option<(String, u16)> {
        self.lock().pex_address.clone()
    }

    pub fn clear_pex_address(&self) {
        self.lock().pex_address = None;
    }

    pub fn has_piece(&self, index: usize) -> bool {
        let state = self.lock();
        let (byte_index, bit_index) = (index / 8, index % 8);
        byte_index < state.bitfield.len() && state.bitfield[byte_index] & (0x80 >> bit_index) != 0
    }

    pub fn bitfield_copy(&self) -> Vec<u8> {
        self.lock().bitfield.clone()
    }

    pub fn update_bitfield(&self, bitfield: &[u8], piece_count: usize) -> Result<()> {
        let expected_length = piece_count.div_ceil(8);
        if bitfield.len() != expected_length {
            return Err(Error::msg("Peer sent a bitfield of the wrong length"));
        }
        self.lock().bitfield = bitfield.to_vec();
        Ok(())
    }

    pub fn set_have(&self, index: usize, piece_count: usize) -> Result<()> {
        if index >= piece_count {
            return Err(Error::msg("Peer sent an out-of-range HAVE message"));
        }
        let mut state = self.lock();
        if state.bitfield.is_empty() {
            state.bitfield = vec![0u8; piece_count.div_ceil(8)];
        }
        state.bitfield[index / 8] |= 0x80 >> (index % 8);
        Ok(())
    }

    pub fn set_pending_bitfield(&self, data: Vec<u8>) {
        self.lock().pending_bitfield = Some(data);
    }

    pub fn take_pending_bitfield(&self) -> Option<Vec<u8>> {
        self.lock().pending_bitfield.take()
    }

    pub fn add_pending_have(&self, index: usize) {
        self.lock().pending_have.insert(index);
    }

    pub fn take_pending_have(&self) -> HashSet<usize> {
        std::mem::take(&mut self.lock().pending_have)
    }

    pub fn outstanding_snapshot(&self) -> HashSet<(usize, usize)> {
        self.lock().outstanding.clone()
    }

    pub fn outstanding_remove(&self, key: &(usize, usize)) -> bool {
        self.lock().outstanding.remove(key)
    }

    pub fn clear_outstanding(&self) {
        self.lock().outstanding.clear();
    }

    pub fn remote_extension(&self, name: &[u8]) -> Option<u8> {
        self.lock().remote_extensions.get(name).copied()
    }

    pub fn set_remote_extension(&self, name: &[u8], id: u8) {
        self.lock().remote_extensions.insert(name.to_vec(), id);
    }

    pub fn pex_announced_contains(&self, address: &(String, u16)) -> bool {
        self.lock().pex_announced.contains(address)
    }

    pub fn add_pex_announced(&self, addresses: &[(String, u16)]) {
        let mut state = self.lock();
        for address in addresses {
            state.pex_announced.insert(address.clone());
        }
    }

    pub fn metadata_size(&self) -> Option<usize> {
        self.lock().metadata_size
    }

    pub fn set_metadata_size(&self, value: Option<usize>) {
        self.lock().metadata_size = value;
    }

    pub fn metadata_queue_snapshot(&self) -> Vec<usize> {
        self.lock().metadata_queue.iter().copied().collect()
    }

    pub fn push_metadata_queue(&self, piece: usize) {
        let mut state = self.lock();
        if !state.metadata_queue.contains(&piece) {
            state.metadata_queue.push_back(piece);
        }
    }

    pub fn pop_metadata_queue(&self) -> Option<usize> {
        self.lock().metadata_queue.pop_front()
    }

    pub fn clear_metadata_queue(&self) {
        self.lock().metadata_queue.clear();
    }

    pub fn metadata_outstanding_len(&self) -> usize {
        self.lock().metadata_outstanding.len()
    }

    pub fn add_metadata_outstanding(&self, piece: usize) {
        self.lock().metadata_outstanding.insert(piece);
    }

    pub fn discard_metadata_outstanding(&self, piece: usize) {
        self.lock().metadata_outstanding.remove(&piece);
    }

    pub fn clear_metadata_outstanding(&self) {
        self.lock().metadata_outstanding.clear();
    }

    pub fn take_reader(&self) -> Option<OwnedReadHalf> {
        self.reader
            .lock()
            .unwrap_or_else(|error| error.into_inner())
            .take()
    }

    async fn attach_io(&self, reader: OwnedReadHalf, writer: OwnedWriteHalf) {
        *self.writer.lock().await = Some(writer);
        *self
            .reader
            .lock()
            .unwrap_or_else(|error| error.into_inner()) = Some(reader);
        self.set_connected(true);
    }

    pub async fn connect(&self) -> Result<()> {
        let stream = tokio::time::timeout(
            Duration::from_secs(10),
            TcpStream::connect((self.ip.as_str(), self.port)),
        )
        .await
        .map_err(|_| {
            Error::msg(format!(
                "Connection to {}:{} failed: timeout",
                self.ip, self.port
            ))
        })??;
        let (mut reader, mut writer) = stream.into_split();

        let handshake = async {
            let mut reserved = [0u8; 8];
            reserved[5] |= 0x10; // BEP 10: extension protocol.
            let mut request = Vec::with_capacity(68);
            request.extend_from_slice(b"\x13BitTorrent protocol");
            request.extend_from_slice(&reserved);
            request.extend_from_slice(&self.info_hash);
            request.extend_from_slice(&self.peer_id);
            writer.write_all(&request).await?;
            writer.flush().await?;

            let mut response = [0u8; 68];
            reader.read_exact(&mut response).await?;
            if response[0] != 19 || &response[1..20] != b"BitTorrent protocol" {
                return Err(Error::msg("Peer returned an invalid handshake"));
            }
            if &response[28..48] != self.info_hash.as_slice() {
                return Err(Error::msg("Peer returned a different info hash"));
            }
            if &response[48..68] == self.peer_id.as_slice() {
                return Err(Error::msg("Peer returned our own peer ID"));
            }
            Ok::<[u8; 68], Error>(response)
        };

        let response = match tokio::time::timeout(Duration::from_secs(10), handshake).await {
            Ok(Ok(response)) => response,
            Ok(Err(error)) => return Err(error),
            Err(_) => {
                return Err(Error::msg(format!(
                    "Connection to {}:{} failed: timeout",
                    self.ip, self.port
                )))
            }
        };
        self.set_supports_extensions(response[25] & 0x10 != 0);
        self.attach_io(reader, writer).await;
        Ok(())
    }

    /// Completa el handshake de una conexion entrante ya aceptada.
    pub async fn accept(&self, stream: TcpStream) -> Result<()> {
        let (mut reader, mut writer) = stream.into_split();

        let mut handshake = [0u8; 68];
        reader.read_exact(&mut handshake).await?;
        if handshake[0] != 19 || &handshake[1..20] != b"BitTorrent protocol" {
            return Err(Error::msg("Peer returned an invalid handshake"));
        }
        if &handshake[28..48] != self.info_hash.as_slice() {
            return Err(Error::msg("Peer returned a different info hash"));
        }
        if &handshake[48..68] == self.peer_id.as_slice() {
            return Err(Error::msg("Peer returned our own peer ID"));
        }

        let mut reserved = [0u8; 8];
        reserved[5] |= 0x10;
        let mut response = Vec::with_capacity(68);
        response.extend_from_slice(b"\x13BitTorrent protocol");
        response.extend_from_slice(&reserved);
        response.extend_from_slice(&self.info_hash);
        response.extend_from_slice(&self.peer_id);
        writer.write_all(&response).await?;
        writer.flush().await?;

        self.set_supports_extensions(handshake[25] & 0x10 != 0);
        self.attach_io(reader, writer).await;
        Ok(())
    }

    pub async fn send_message(&self, message_id: u8, payload: &[u8]) -> Result<()> {
        if !self.is_connected() {
            return Ok(());
        }
        let mut guard = self.writer.lock().await;
        let writer = match guard.as_mut() {
            Some(writer) => writer,
            None => return Ok(()),
        };
        let length = (payload.len() as u32) + 1;
        writer.write_all(&length.to_be_bytes()).await?;
        writer.write_all(&[message_id]).await?;
        if !payload.is_empty() {
            writer.write_all(payload).await?;
        }
        writer.flush().await?;
        Ok(())
    }

    pub async fn write_raw(&self, data: &[u8]) -> Result<()> {
        let mut guard = self.writer.lock().await;
        if let Some(writer) = guard.as_mut() {
            writer.write_all(data).await?;
            writer.flush().await?;
        }
        Ok(())
    }

    pub async fn send_interested(&self) -> Result<()> {
        self.send_message(INTERESTED, &[]).await
    }

    pub async fn send_extension_handshake(&self, metadata_size: Option<usize>) -> Result<()> {
        let mut fields: Vec<(&[u8], Value)> = vec![
            (
                b"m",
                dict(vec![
                    (b"ut_pex", Value::Int(PEX_LOCAL_ID as i64)),
                    (b"ut_metadata", Value::Int(METADATA_LOCAL_ID as i64)),
                ]),
            ),
            (b"reqq", Value::Int(128)),
            (b"v", Value::Bytes(b"PythonTorrent 0.1".to_vec())),
        ];
        if let Some(size) = metadata_size {
            fields.push((b"metadata_size", Value::Int(size as i64)));
        }
        let handshake = encode(&dict(fields));
        let mut payload = vec![0u8];
        payload.extend_from_slice(&handshake);
        self.send_message(EXTENDED, &payload).await
    }

    pub async fn send_extended(&self, extension_id: u8, payload: &[u8]) -> Result<()> {
        if extension_id == 0 {
            return Err(Error::msg("Extension ID must be between 1 and 255"));
        }
        let mut message = vec![extension_id];
        message.extend_from_slice(payload);
        self.send_message(EXTENDED, &message).await
    }

    pub async fn send_request(
        &self,
        piece_index: usize,
        begin: usize,
        length: usize,
    ) -> Result<()> {
        let mut payload = Vec::with_capacity(12);
        payload.extend_from_slice(&(piece_index as u32).to_be_bytes());
        payload.extend_from_slice(&(begin as u32).to_be_bytes());
        payload.extend_from_slice(&(length as u32).to_be_bytes());
        self.send_message(REQUEST, &payload).await?;
        self.lock().outstanding.insert((piece_index, begin));
        Ok(())
    }

    pub async fn close(&self) {
        self.set_connected(false);
        let writer = self.writer.lock().await.take();
        if let Some(mut writer) = writer {
            let _ = writer.shutdown().await;
        }
    }
}

pub async fn read_message(reader: &mut OwnedReadHalf) -> std::io::Result<Option<Incoming>> {
    let mut length_buffer = [0u8; 4];
    if let Err(error) = reader.read_exact(&mut length_buffer).await {
        if error.kind() == std::io::ErrorKind::UnexpectedEof {
            return Ok(None);
        }
        return Err(error);
    }
    let length = u32::from_be_bytes(length_buffer) as usize;
    if length == 0 {
        return Ok(Some(Incoming::KeepAlive));
    }
    if length > 4 * 1024 * 1024 {
        return Err(std::io::Error::new(
            std::io::ErrorKind::InvalidData,
            format!("Peer message too large: {length} bytes"),
        ));
    }
    let mut message = vec![0u8; length];
    reader.read_exact(&mut message).await?;
    let message_id = message[0];
    let payload = message.split_off(1);
    Ok(Some(Incoming::Message(message_id, payload)))
}
