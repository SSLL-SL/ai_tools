//! Motor de descarga: peers, trackers, DHT, PEX y metadatos por magnet.
//!
//! Traduce a tokio el `BitTorrentClient` de asyncio del original. El estado
//! compartido vive detras de un unico `Mutex` de `std` que nunca se mantiene a
//! traves de un `await`; cuando hace falta enviar mensajes se copian los datos
//! necesarios y se suelta el cerrojo antes de tocar la red.

use std::collections::{BTreeMap, HashMap, HashSet};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, AtomicU32, Ordering};
use std::sync::{Arc, Mutex as StdMutex};
use std::time::{Duration, Instant};

use futures::future::join_all;
use rand::distributions::Alphanumeric;
use rand::Rng;
use sha1::{Digest, Sha1};
use tokio::net::tcp::OwnedReadHalf;
use tokio::net::{TcpListener, TcpStream};
use tokio::task::JoinHandle;

use crate::bencode::{decode, decode_complete, dict, encode, Value};
use crate::dht::DhtClient;
use crate::error::{Error, Result};
use crate::magnet::parse_magnet_uri;
use crate::peer::{
    read_message, Incoming, Peer, PeerRef, BITFIELD, CHOKE, EXTENDED, HAVE, INTERESTED,
    METADATA_LOCAL_ID, PEX_LOCAL_ID, PIECE, REQUEST, UNCHOKE,
};
use crate::pex::{encode_pex, parse_pex, PeerAddr};
use crate::resume::ResumeStore;
use crate::storage::PieceStorage;
use crate::torrent::{parse_info_bytes, parse_torrent_file, Torrent, TorrentInfo};
use crate::tracker::TrackerClient;

const BLOCK_SIZE: usize = 16 * 1024;
const METADATA_BLOCK_SIZE: usize = 16 * 1024;
const MAX_METADATA_SIZE: usize = 16 * 1024 * 1024;
const MAX_METADATA_IN_FLIGHT: usize = 8;
const METADATA_REQUEST_TIMEOUT: Duration = Duration::from_secs(15);
const MAX_IN_FLIGHT: usize = 16;
const MAX_PEERS: usize = 40;

/// Instantanea del progreso de la descarga (equivale al dict de Python).
#[derive(Debug, Clone, Copy, Default, serde::Serialize)]
pub struct Progress {
    pub progress: f64,
    pub downloaded: u64,
    pub total: u64,
    pub peers: usize,
    pub speed: f64,
}

struct PieceAssembly {
    data: Vec<u8>,
    block_lengths: BTreeMap<usize, usize>,
    received: HashSet<usize>,
}

#[derive(Default)]
struct MetadataState {
    size: Option<usize>,
    chunks: HashMap<usize, Vec<u8>>,
    sources: HashMap<usize, PeerRef>,
    requested: HashMap<usize, PeerRef>,
    deadlines: HashMap<usize, Instant>,
}

struct ClientState {
    torrent: Option<Torrent>,
    storage: Option<PieceStorage>,
    resume_store: Option<ResumeStore>,
    info_hash: Option<[u8; 20]>,
    tracker_urls: Vec<String>,
    display_name: String,
    peers: Vec<PeerRef>,
    connecting: HashSet<(String, u16)>,
    pieces: HashMap<usize, PieceAssembly>,
    assigned: HashMap<usize, PeerRef>,
    downloaded: u64,
    uploaded: u64,
    download_started: Option<Instant>,
    metadata: MetadataState,
}

/// Cliente BitTorrent de consola (port de `btclient.client.BitTorrentClient`).
#[derive(Clone)]
pub struct BitTorrentClient {
    inner: Arc<ClientInner>,
}

struct ClientInner {
    save_path: PathBuf,
    peer_id: [u8; 20],
    port: AtomicU32,
    running: AtomicBool,
    state: StdMutex<ClientState>,
    peer_tasks: StdMutex<Vec<JoinHandle<()>>>,
    server_task: StdMutex<Option<JoinHandle<()>>>,
}

impl BitTorrentClient {
    pub fn new(save_path: impl Into<PathBuf>, port: u16) -> Self {
        BitTorrentClient {
            inner: Arc::new(ClientInner::new(save_path.into(), port)),
        }
    }

    pub async fn download(&self, source: &str) -> Result<()> {
        self.inner.download(source).await
    }

    pub fn get_progress(&self) -> Progress {
        self.inner.get_progress()
    }

    /// Solicita el fin de la descarga (equivale a poner `running = False`).
    pub fn stop(&self) {
        self.inner.running.store(false, Ordering::SeqCst);
    }

    pub fn is_running(&self) -> bool {
        self.inner.running.load(Ordering::SeqCst)
    }
}

impl ClientInner {
    fn new(save_path: PathBuf, port: u16) -> Self {
        let mut peer_id = [0u8; 20];
        peer_id[..8].copy_from_slice(b"-PC0001-");
        let suffix: Vec<u8> = rand::thread_rng()
            .sample_iter(&Alphanumeric)
            .take(12)
            .collect();
        peer_id[8..].copy_from_slice(&suffix);
        ClientInner {
            save_path,
            peer_id,
            port: AtomicU32::new(port as u32),
            running: AtomicBool::new(false),
            state: StdMutex::new(ClientState {
                torrent: None,
                storage: None,
                resume_store: None,
                info_hash: None,
                tracker_urls: Vec::new(),
                display_name: String::new(),
                peers: Vec::new(),
                connecting: HashSet::new(),
                pieces: HashMap::new(),
                assigned: HashMap::new(),
                downloaded: 0,
                uploaded: 0,
                download_started: None,
                metadata: MetadataState::default(),
            }),
            peer_tasks: StdMutex::new(Vec::new()),
            server_task: StdMutex::new(None),
        }
    }

    fn lock(&self) -> std::sync::MutexGuard<'_, ClientState> {
        self.state.lock().unwrap_or_else(|error| error.into_inner())
    }

    fn running(&self) -> bool {
        self.running.load(Ordering::SeqCst)
    }

    fn is_complete(&self) -> bool {
        self.lock()
            .torrent
            .as_ref()
            .map(|torrent| torrent.is_complete())
            .unwrap_or(false)
    }

    fn metadata_size_for_handshake(&self) -> Option<usize> {
        self.lock()
            .torrent
            .as_ref()
            .map(|torrent| torrent.info.raw_info.len())
    }

    pub fn get_progress(&self) -> Progress {
        let state = self.lock();
        match state.torrent.as_ref() {
            None => Progress::default(),
            Some(torrent) => {
                let elapsed = state
                    .download_started
                    .map(|started| started.elapsed().as_secs_f64())
                    .unwrap_or(0.001)
                    .max(0.001);
                let peers = state
                    .peers
                    .iter()
                    .filter(|peer| peer.is_connected())
                    .count();
                Progress {
                    progress: torrent.progress(),
                    downloaded: state.downloaded,
                    total: torrent.info.total_size(),
                    peers,
                    speed: state.downloaded as f64 / elapsed,
                }
            }
        }
    }

    async fn download(self: &Arc<Self>, source: &str) -> Result<()> {
        let is_magnet = source.to_lowercase().starts_with("magnet:");
        if is_magnet {
            let magnet = parse_magnet_uri(source)?;
            let mut state = self.lock();
            state.info_hash = Some(magnet.info_hash);
            state.tracker_urls = magnet.trackers.clone();
            state.display_name = magnet.display_name.clone();
            drop(state);
            log::info!(
                "Resolving magnet metadata for {} ({})",
                magnet.display_name,
                hex::encode(magnet.info_hash)
            );
        } else {
            let info = parse_torrent_file(Path::new(source))?;
            let (name, total, pieces, hash) = (
                info.name.clone(),
                info.total_size(),
                info.num_pieces(),
                info.info_hash,
            );
            let mut state = self.lock();
            state.tracker_urls = info.trackers.clone();
            state.install_metadata(info, &self.save_path)?;
            state.info_hash = Some(hash);
            drop(state);
            log::info!("Starting {name} ({total} bytes; {pieces} pieces)");
        }

        {
            let mut state = self.lock();
            state.download_started = Some(Instant::now());
        }
        self.running.store(true, Ordering::SeqCst);

        if let Err(error) = self.start_listener().await {
            self.running.store(false, Ordering::SeqCst);
            self.cleanup().await;
            return Err(error);
        }
        let tracker_urls = self.lock().tracker_urls.clone();

        let mut background: Vec<JoinHandle<()>> = Vec::new();
        {
            let inner = self.clone();
            background.push(tokio::spawn(async move { inner.dht_loop().await }));
        }
        {
            let inner = self.clone();
            background.push(tokio::spawn(async move { inner.metadata_sweeper().await }));
        }
        if !tracker_urls.is_empty() {
            let inner = self.clone();
            background.push(tokio::spawn(async move { inner.tracker_loop().await }));
        } else {
            log::info!("No trackers in source; discovering peers through DHT");
        }

        while self.running() && !self.is_complete() {
            tokio::time::sleep(Duration::from_millis(200)).await;
        }

        self.running.store(false, Ordering::SeqCst);
        for handle in background {
            handle.abort();
        }
        self.cleanup().await;
        Ok(())
    }

    async fn cleanup(&self) {
        let tasks: Vec<JoinHandle<()>> = std::mem::take(&mut *self.peer_tasks.lock().unwrap());
        for handle in tasks {
            handle.abort();
        }
        if let Some(handle) = self.server_task.lock().unwrap().take() {
            handle.abort();
        }
        let peers = self.lock().peers.clone();
        for peer in peers {
            peer.close().await;
        }
        self.persist_resume();
        self.lock().storage.take();
    }

    async fn start_listener(self: &Arc<Self>) -> Result<()> {
        let port = self.port.load(Ordering::SeqCst) as u16;
        let listener = match TcpListener::bind(("0.0.0.0", port)).await {
            Ok(listener) => listener,
            Err(error) => {
                if port == 0 {
                    return Err(error.into());
                }
                log::warn!("Could not bind peer port {port} ({error}); using an ephemeral port");
                TcpListener::bind(("0.0.0.0", 0)).await?
            }
        };
        let actual = listener.local_addr()?.port();
        self.port.store(actual as u32, Ordering::SeqCst);
        log::info!("Listening for peer connections on port {actual}");

        let inner = self.clone();
        let handle = tokio::spawn(async move {
            loop {
                match listener.accept().await {
                    Ok((stream, address)) => {
                        let inner = inner.clone();
                        tokio::spawn(async move { inner.accept_peer(stream, address).await });
                    }
                    Err(_) => {
                        if !inner.running() {
                            break;
                        }
                    }
                }
            }
        });
        *self.server_task.lock().unwrap() = Some(handle);
        Ok(())
    }

    async fn accept_peer(self: &Arc<Self>, stream: TcpStream, address: std::net::SocketAddr) {
        let (peer_id, info_hash) = {
            let state = self.lock();
            match state.info_hash {
                Some(hash) => (self.peer_id, hash),
                None => return,
            }
        };
        let peer = Peer::new(peer_id, info_hash, address.ip().to_string(), address.port());
        match tokio::time::timeout(Duration::from_secs(10), peer.accept(stream)).await {
            Ok(Ok(())) => {}
            _ => {
                peer.close().await;
                return;
            }
        }
        if peer.supports_extensions() {
            let _ = peer
                .send_extension_handshake(self.metadata_size_for_handshake())
                .await;
        }
        peer.clear_pex_address();

        let bitfield = {
            let state = self.lock();
            state
                .torrent
                .as_ref()
                .filter(|torrent| torrent.any_have())
                .map(|torrent| torrent.bitfield.clone())
        };
        if let Some(bitfield) = bitfield {
            let _ = peer.send_message(BITFIELD, &bitfield).await;
            peer.set_bitfield_sent(true);
        }

        self.lock().peers.push(peer.clone());
        self.spawn_peer_task(peer);
    }

    fn spawn_peer_task(self: &Arc<Self>, peer: PeerRef) {
        let inner = self.clone();
        let handle = tokio::spawn(async move { inner.handle_peer(peer).await });
        let mut tasks = self.peer_tasks.lock().unwrap();
        tasks.retain(|handle| !handle.is_finished());
        tasks.push(handle);
    }

    async fn tracker_loop(self: &Arc<Self>) {
        let urls = {
            let state = self.lock();
            dedup(&state.tracker_urls)
        };
        if urls.is_empty() {
            return;
        }
        let mut started: HashSet<String> = HashSet::new();

        while self.running() && !self.is_complete() {
            let (info_hash, peer_id) = {
                let state = self.lock();
                match state.info_hash {
                    Some(hash) => (hash, self.peer_id),
                    None => return,
                }
            };
            let (uploaded, downloaded, left) = {
                let state = self.lock();
                let total = state
                    .torrent
                    .as_ref()
                    .map(|torrent| torrent.info.total_size())
                    .unwrap_or(0);
                let left = if state.torrent.is_some() {
                    total.saturating_sub(state.downloaded)
                } else {
                    1
                };
                (state.uploaded, state.downloaded, left)
            };
            let port = self.port.load(Ordering::SeqCst) as u16;
            let tracker = TrackerClient::new(info_hash, peer_id, port);

            let mut requests = Vec::with_capacity(urls.len());
            for url in &urls {
                let event = if started.contains(url) { "" } else { "started" };
                requests.push(tracker.announce(url, uploaded, downloaded, left, event));
            }
            let results = join_all(requests).await;

            let mut next_interval = 300u64;
            let mut peers: Vec<PeerAddr> = Vec::new();
            for (url, result) in urls.iter().zip(results) {
                match result {
                    Ok(response) => {
                        started.insert(url.clone());
                        next_interval = next_interval.min(response.interval);
                        log::info!("Tracker {url} returned {} peers", response.peers.len());
                        peers.extend(response.peers);
                    }
                    Err(error) => log::warn!("Tracker {url} failed: {error}"),
                }
            }
            self.connect_to_peers(peers).await;
            tokio::time::sleep(Duration::from_secs(next_interval.clamp(15, 300))).await;
        }
    }

    async fn dht_loop(self: &Arc<Self>) {
        let (info_hash, port) = {
            let state = self.lock();
            match state.info_hash {
                Some(hash) => (hash, self.port.load(Ordering::SeqCst) as u16),
                None => return,
            }
        };
        let dht = match DhtClient::start(port, port).await {
            Ok(dht) => dht,
            Err(error) => {
                log::warn!("DHT discovery unavailable: {error}");
                return;
            }
        };
        while self.running() && !self.is_complete() {
            let peers = dht.find_peers(&info_hash).await;
            log::info!("DHT lookup returned {} peers", peers.len());
            self.connect_to_peers(peers.into_iter().collect()).await;
            tokio::time::sleep(Duration::from_secs(300)).await;
        }
    }

    async fn metadata_sweeper(self: &Arc<Self>) {
        loop {
            tokio::time::sleep(Duration::from_secs(1)).await;
            if !self.running() {
                break;
            }
            let expired: Vec<(usize, PeerRef)> = {
                let now = Instant::now();
                let mut state = self.lock();
                let pieces: Vec<usize> = state
                    .metadata
                    .deadlines
                    .iter()
                    .filter(|(_, deadline)| **deadline <= now)
                    .map(|(piece, _)| *piece)
                    .collect();
                let mut out = Vec::new();
                for piece in pieces {
                    state.metadata.deadlines.remove(&piece);
                    if let Some(owner) = state.metadata.requested.remove(&piece) {
                        owner.discard_metadata_outstanding(piece);
                        out.push((piece, owner));
                    }
                }
                out
            };
            for (piece, owner) in expired {
                self.assign_metadata_piece(piece, &owner, true).await;
            }
        }
    }

    async fn connect_to_peers(self: &Arc<Self>, addresses: Vec<(String, u16)>) {
        let mut unique: Vec<(String, u16)> = Vec::new();
        {
            let mut state = self.lock();
            let current: HashSet<(String, u16)> = state
                .peers
                .iter()
                .filter(|peer| peer.is_connected())
                .map(|peer| (peer.ip.clone(), peer.port))
                .collect();
            let capacity = MAX_PEERS.saturating_sub(current.len());
            for (ip, port) in addresses {
                if port == 0 || ip.is_empty() {
                    continue;
                }
                let address = (ip, port);
                if current.contains(&address)
                    || state.connecting.contains(&address)
                    || unique.contains(&address)
                {
                    continue;
                }
                unique.push(address);
                if unique.len() >= capacity {
                    break;
                }
            }
            for address in &unique {
                state.connecting.insert(address.clone());
            }
        }

        if unique.is_empty() {
            return;
        }
        let results = join_all(unique.iter().map(|(ip, port)| self.connect_one(ip, *port))).await;
        let announced: Vec<PeerAddr> = results
            .into_iter()
            .flatten()
            .map(|peer| (peer.ip.clone(), peer.port))
            .collect();
        self.broadcast_pex(announced, None, Vec::new()).await;
    }

    async fn connect_one(self: &Arc<Self>, ip: &str, port: u16) -> Option<PeerRef> {
        let (peer_id, info_hash) = {
            let state = self.lock();
            match state.info_hash {
                Some(hash) => (self.peer_id, hash),
                None => return None,
            }
        };
        let peer = Peer::new(peer_id, info_hash, ip.to_string(), port);
        let result = peer.connect().await;
        match result {
            Ok(()) => {
                if peer.supports_extensions() {
                    let _ = peer
                        .send_extension_handshake(self.metadata_size_for_handshake())
                        .await;
                }
                let bitfield = {
                    let state = self.lock();
                    state
                        .torrent
                        .as_ref()
                        .filter(|torrent| torrent.any_have())
                        .map(|torrent| torrent.bitfield.clone())
                };
                if let Some(bitfield) = bitfield {
                    let _ = peer.send_message(BITFIELD, &bitfield).await;
                    peer.set_bitfield_sent(true);
                }
                let _ = peer.send_interested().await;
                self.lock().peers.push(peer.clone());
                self.spawn_peer_task(peer.clone());
                Some(peer)
            }
            Err(error) => {
                log::debug!("Peer {ip}:{port} rejected connection: {error}");
                peer.close().await;
                None
            }
        }
    }

    async fn handle_peer(self: Arc<Self>, peer: PeerRef) {
        let mut reader: OwnedReadHalf = match peer.take_reader() {
            Some(reader) => reader,
            None => {
                peer.close().await;
                return;
            }
        };
        if let Err(error) = self.peer_loop(&peer, &mut reader).await {
            log::debug!("Peer {}:{} ended: {error}", peer.ip, peer.port);
        }
        self.release_peer_piece(&peer);
        self.release_metadata_peer(&peer).await;
        if let Some(address) = peer.pex_address() {
            self.broadcast_pex(Vec::new(), Some(&peer), vec![address])
                .await;
        }
        peer.close().await;
        self.lock().peers.retain(|known| !Arc::ptr_eq(known, &peer));
    }

    async fn peer_loop(self: &Arc<Self>, peer: &PeerRef, reader: &mut OwnedReadHalf) -> Result<()> {
        while self.running() && peer.is_connected() {
            match read_message(reader).await {
                Ok(None) => break,
                Ok(Some(Incoming::KeepAlive)) => continue,
                Ok(Some(Incoming::Message(message_id, payload))) => match message_id {
                    CHOKE => {
                        peer.set_peer_choking(true);
                        self.release_peer_piece(peer);
                    }
                    UNCHOKE => {
                        peer.set_peer_choking(false);
                        self.assign_piece(peer).await;
                    }
                    INTERESTED => {
                        if peer.am_choking() {
                            peer.set_am_choking(false);
                            peer.send_message(UNCHOKE, &[]).await?;
                        }
                    }
                    HAVE => {
                        if payload.len() != 4 {
                            return Err(Error::msg("Malformed HAVE message"));
                        }
                        let index = u32::from_be_bytes(payload[..4].try_into().unwrap()) as usize;
                        self.on_have(peer, index).await?;
                    }
                    BITFIELD => {
                        self.on_bitfield(peer, &payload).await?;
                    }
                    PIECE => {
                        self.receive_block(peer, &payload).await?;
                    }
                    REQUEST => {
                        self.serve_request(peer, &payload).await?;
                    }
                    EXTENDED => {
                        self.handle_extension(peer, &payload).await?;
                    }
                    _ => {}
                },
                Err(error) => return Err(error.into()),
            }
        }
        Ok(())
    }

    async fn on_have(&self, peer: &PeerRef, index: usize) -> Result<()> {
        let piece_count = {
            let state = self.lock();
            state
                .torrent
                .as_ref()
                .map(|torrent| torrent.info.num_pieces())
        };
        match piece_count {
            None => peer.add_pending_have(index),
            Some(count) => {
                peer.set_have(index, count)?;
                if !peer.peer_choking() && peer.assigned_piece().is_none() {
                    self.assign_piece(peer).await;
                }
            }
        }
        Ok(())
    }

    async fn on_bitfield(&self, peer: &PeerRef, payload: &[u8]) -> Result<()> {
        let piece_count = {
            let state = self.lock();
            state
                .torrent
                .as_ref()
                .map(|torrent| torrent.info.num_pieces())
        };
        match piece_count {
            None => peer.set_pending_bitfield(payload.to_vec()),
            Some(count) => {
                peer.update_bitfield(payload, count)?;
                if !peer.peer_choking() {
                    self.assign_piece(peer).await;
                }
            }
        }
        Ok(())
    }

    async fn assign_piece(&self, peer: &PeerRef) {
        if peer.peer_choking() || peer.assigned_piece().is_some() || !peer.is_connected() {
            return;
        }
        let peers = self.lock().peers.clone();
        let (piece_index, piece_length) = {
            let mut state = self.lock();
            let num_pieces = match state.torrent.as_ref() {
                Some(torrent) => torrent.info.num_pieces(),
                None => return,
            };
            let mut candidates: Vec<usize> = Vec::new();
            for index in 0..num_pieces {
                let has = state
                    .torrent
                    .as_ref()
                    .map(|torrent| torrent.has_piece(index))
                    .unwrap_or(false);
                if !has && !state.assigned.contains_key(&index) && peer.has_piece(index) {
                    candidates.push(index);
                }
            }
            if candidates.is_empty() {
                return;
            }
            let piece_index = *candidates
                .iter()
                .min_by_key(|index| {
                    peers
                        .iter()
                        .filter(|other| other.is_connected() && other.has_piece(**index))
                        .count()
                })
                .unwrap();
            let piece_length = match state
                .torrent
                .as_ref()
                .and_then(|torrent| torrent.info.get_piece_length(piece_index))
            {
                Some(length) => length,
                None => return,
            };
            let mut blocks = BTreeMap::new();
            let mut offset = 0u64;
            while offset < piece_length {
                blocks.insert(
                    offset as usize,
                    (BLOCK_SIZE as u64).min(piece_length - offset) as usize,
                );
                offset += BLOCK_SIZE as u64;
            }
            let assembly = state
                .pieces
                .entry(piece_index)
                .or_insert_with(|| PieceAssembly {
                    data: vec![0u8; piece_length as usize],
                    block_lengths: blocks.clone(),
                    received: HashSet::new(),
                });
            if assembly.block_lengths.is_empty() {
                assembly.block_lengths = blocks.clone();
            }
            state.assigned.insert(piece_index, peer.clone());
            (piece_index, piece_length)
        };
        let _ = piece_length;
        peer.set_assigned_piece(Some(piece_index));
        self.fill_request_window(peer).await;
    }

    async fn fill_request_window(&self, peer: &PeerRef) {
        let piece_index = match peer.assigned_piece() {
            Some(index) => index,
            None => return,
        };
        if peer.peer_choking() || !peer.is_connected() {
            return;
        }
        let outstanding = peer.outstanding_snapshot();
        let pending: Vec<(usize, usize)> = {
            let state = self.lock();
            match state.pieces.get(&piece_index) {
                Some(assembly) => assembly
                    .block_lengths
                    .iter()
                    .filter(|(offset, _)| {
                        !assembly.received.contains(offset)
                            && !outstanding.contains(&(piece_index, **offset))
                    })
                    .map(|(offset, length)| (*offset, *length))
                    .collect(),
                None => return,
            }
        };
        let slots = MAX_IN_FLIGHT.saturating_sub(outstanding.len());
        for (offset, length) in pending.into_iter().take(slots) {
            if peer
                .send_request(piece_index, offset, length)
                .await
                .is_err()
            {
                break;
            }
        }
    }

    async fn receive_block(&self, peer: &PeerRef, payload: &[u8]) -> Result<()> {
        if payload.len() < 8 {
            return Err(Error::msg("Malformed PIECE message"));
        }
        let piece_index = u32::from_be_bytes(payload[..4].try_into().unwrap()) as usize;
        let begin = u32::from_be_bytes(payload[4..8].try_into().unwrap()) as usize;
        let block = &payload[8..];
        if !peer.outstanding_remove(&(piece_index, begin)) {
            return Ok(());
        }
        if peer.assigned_piece() != Some(piece_index) {
            return Ok(());
        }

        let piece_data: Option<Vec<u8>> = {
            let mut state = self.lock();
            let complete = {
                let assembly = match state.pieces.get_mut(&piece_index) {
                    Some(assembly) => assembly,
                    None => return Ok(()),
                };
                if !assembly.block_lengths.contains_key(&begin) {
                    return Ok(());
                }
                let expected = assembly.block_lengths[&begin];
                if block.len() != expected || assembly.received.contains(&begin) {
                    return Ok(());
                }
                assembly.data[begin..begin + block.len()].copy_from_slice(block);
                assembly.received.insert(begin);
                assembly.received.len() == assembly.block_lengths.len()
            };
            state.downloaded += block.len() as u64;
            if !complete {
                None
            } else {
                state
                    .pieces
                    .get(&piece_index)
                    .map(|assembly| assembly.data.clone())
            }
        };

        let piece_data = match piece_data {
            Some(data) => data,
            None => {
                self.fill_request_window(peer).await;
                return Ok(());
            }
        };

        let verified = {
            let mut state = self.lock();
            let verified = state
                .torrent
                .as_ref()
                .map(|torrent| torrent.verify_piece(piece_index, &piece_data))
                .unwrap_or(false);
            if verified {
                if let Some(storage) = state.storage.as_mut() {
                    storage.write_piece(piece_index, &piece_data)?;
                }
                if let Some(torrent) = state.torrent.as_mut() {
                    torrent.set_have(piece_index);
                }
                if let (Some(resume), Some(torrent)) =
                    (state.resume_store.as_ref(), state.torrent.as_ref())
                {
                    if let Err(error) = resume.save(&torrent.bitfield) {
                        log::warn!("Could not save resume checkpoint: {error}");
                    }
                }
            } else {
                log::warn!("Piece {piece_index} failed SHA-1 verification; retrying");
                state.downloaded = state.downloaded.saturating_sub(piece_data.len() as u64);
            }
            state.assigned.remove(&piece_index);
            state.pieces.remove(&piece_index);
            verified
        };

        if verified {
            let peers = self.lock().peers.clone();
            let message = (piece_index as u32).to_be_bytes();
            for other in peers {
                if other.is_connected() {
                    let _ = other.send_message(HAVE, &message).await;
                }
            }
        }
        peer.set_assigned_piece(None);
        self.assign_piece(peer).await;
        Ok(())
    }

    fn release_peer_piece(&self, peer: &PeerRef) {
        let mut state = self.lock();
        if let Some(piece_index) = peer.assigned_piece() {
            let owned = state
                .assigned
                .get(&piece_index)
                .map(|owner| Arc::ptr_eq(owner, peer))
                .unwrap_or(false);
            if owned {
                state.assigned.remove(&piece_index);
                state.pieces.remove(&piece_index);
            }
            peer.set_assigned_piece(None);
        }
        peer.clear_outstanding();
    }

    async fn serve_request(&self, peer: &PeerRef, payload: &[u8]) -> Result<()> {
        if payload.len() != 12 || peer.am_choking() {
            return Ok(());
        }
        let piece_index = u32::from_be_bytes(payload[..4].try_into().unwrap()) as usize;
        let begin = u32::from_be_bytes(payload[4..8].try_into().unwrap()) as usize;
        let length = u32::from_be_bytes(payload[8..12].try_into().unwrap()) as usize;
        if length == 0 || length > BLOCK_SIZE {
            return Ok(());
        }

        let data = {
            let mut state = self.lock();
            let piece_length = match state
                .torrent
                .as_ref()
                .and_then(|torrent| torrent.info.get_piece_length(piece_index))
            {
                Some(length)
                    if state
                        .torrent
                        .as_ref()
                        .map(|t| t.has_piece(piece_index))
                        .unwrap_or(false) =>
                {
                    length
                }
                _ => return Ok(()),
            };
            if begin as u64 + length as u64 > piece_length {
                return Ok(());
            }
            let storage = match state.storage.as_mut() {
                Some(storage) => storage,
                None => return Ok(()),
            };
            let data = storage.read_piece(piece_index)?;
            state.uploaded += length as u64;
            data
        };

        let mut message = Vec::with_capacity(8 + length);
        message.extend_from_slice(&(piece_index as u32).to_be_bytes());
        message.extend_from_slice(&(begin as u32).to_be_bytes());
        message.extend_from_slice(&data[begin..begin + length]);
        peer.send_message(PIECE, &message).await?;
        Ok(())
    }

    async fn handle_extension(self: &Arc<Self>, peer: &PeerRef, payload: &[u8]) -> Result<()> {
        if payload.is_empty() {
            return Ok(());
        }
        let extension_id = payload[0];
        let body = &payload[1..];

        if extension_id == 0 {
            let handshake = match decode_complete(body) {
                Ok(handshake) => handshake,
                Err(_) => return Ok(()),
            };
            if !handshake.is_dict() {
                return Ok(());
            }
            let extensions = match handshake.get(b"m").and_then(|value| value.as_dict()) {
                Some(extensions) => extensions,
                None => return Ok(()),
            };
            if let Some(pex_id) = extensions
                .get(b"ut_pex".as_slice())
                .and_then(|value| value.as_int())
            {
                if (1..256).contains(&pex_id) {
                    peer.set_remote_extension(b"ut_pex", pex_id as u8);
                    let addresses: Vec<PeerAddr> = self
                        .lock()
                        .peers
                        .iter()
                        .filter(|known| !Arc::ptr_eq(known, peer) && known.is_connected())
                        .filter_map(|known| known.pex_address())
                        .collect();
                    self.send_pex(peer, &addresses, &[]).await;
                }
            }
            if let Some(metadata_id) = extensions
                .get(b"ut_metadata".as_slice())
                .and_then(|value| value.as_int())
            {
                if (1..256).contains(&metadata_id) {
                    peer.set_remote_extension(b"ut_metadata", metadata_id as u8);
                    let size = handshake.get_int(b"metadata_size");
                    let (installed, current_size) = {
                        let state = self.lock();
                        (state.torrent.is_some(), state.metadata.size)
                    };
                    if !installed {
                        if let Some(size) = size {
                            if size > 0
                                && size as usize <= MAX_METADATA_SIZE
                                && (current_size.is_none() || current_size == Some(size as usize))
                            {
                                self.lock().metadata.size = Some(size as usize);
                                peer.set_metadata_size(Some(size as usize));
                                self.queue_metadata(peer).await;
                            }
                        }
                    }
                }
            }
            return Ok(());
        }

        if extension_id == METADATA_LOCAL_ID {
            self.handle_metadata_message(peer, body).await?;
        } else if extension_id == PEX_LOCAL_ID {
            let message = match decode_complete(body) {
                Ok(message) => message,
                Err(_) => return Ok(()),
            };
            if !message.is_dict() {
                return Ok(());
            }
            let (added, dropped) = parse_pex(&message);
            if !added.is_empty() {
                self.connect_to_peers(added.into_iter().collect()).await;
            }
            if !dropped.is_empty() {
                self.broadcast_pex(Vec::new(), Some(peer), dropped.into_iter().collect())
                    .await;
            }
        }
        Ok(())
    }

    async fn queue_metadata(&self, peer: &PeerRef) {
        let (size, torrent_installed) = {
            let state = self.lock();
            (state.metadata.size, state.torrent.is_some())
        };
        let size = match size {
            Some(size) if !torrent_installed => size,
            _ => return,
        };
        if !peer.is_connected() || peer.metadata_size() != Some(size) {
            return;
        }
        let piece_count = size.div_ceil(METADATA_BLOCK_SIZE);
        for piece in 0..piece_count {
            let skip = {
                let state = self.lock();
                state.metadata.chunks.contains_key(&piece)
                    || state.metadata.requested.contains_key(&piece)
            };
            if skip {
                continue;
            }
            peer.push_metadata_queue(piece);
        }
        self.fill_metadata_window(peer).await;
    }

    async fn fill_metadata_window(&self, peer: &PeerRef) {
        let metadata_id = match peer.remote_extension(b"ut_metadata") {
            Some(id) => id,
            None => return,
        };
        loop {
            if self.lock().torrent.is_some() || !peer.is_connected() {
                return;
            }
            if peer.metadata_outstanding_len() >= MAX_METADATA_IN_FLIGHT {
                return;
            }
            let piece = match peer.pop_metadata_queue() {
                Some(piece) => piece,
                None => return,
            };
            {
                let mut state = self.lock();
                if state.metadata.chunks.contains_key(&piece)
                    || state.metadata.requested.contains_key(&piece)
                {
                    continue;
                }
                state.metadata.requested.insert(piece, peer.clone());
                state
                    .metadata
                    .deadlines
                    .insert(piece, Instant::now() + METADATA_REQUEST_TIMEOUT);
            }
            peer.add_metadata_outstanding(piece);
            let request = encode(&dict(vec![
                (b"msg_type", Value::Int(0)),
                (b"piece", Value::Int(piece as i64)),
            ]));
            if peer.send_extended(metadata_id, &request).await.is_err() {
                return;
            }
        }
    }

    async fn handle_metadata_message(&self, peer: &PeerRef, body: &[u8]) -> Result<()> {
        let (header, header_end) = match decode(body, 0) {
            Ok(decoded) => decoded,
            Err(_) => return Ok(()),
        };
        if !header.is_dict() {
            return Ok(());
        }
        let message_type = header.get_int(b"msg_type");
        let piece = match header.get_int(b"piece") {
            Some(piece) if piece >= 0 => piece as usize,
            _ => return Ok(()),
        };

        if message_type == Some(0) {
            self.serve_metadata_request(peer, piece).await;
            return Ok(());
        }
        if message_type == Some(2) {
            let owner = self.lock().metadata.requested.get(&piece).cloned();
            if let Some(owner) = owner {
                if Arc::ptr_eq(&owner, peer) {
                    {
                        let mut state = self.lock();
                        state.metadata.requested.remove(&piece);
                        state.metadata.deadlines.remove(&piece);
                    }
                    peer.discard_metadata_outstanding(piece);
                    self.assign_metadata_piece(piece, peer, false).await;
                }
            }
            return Ok(());
        }
        if message_type != Some(1) {
            return Ok(());
        }

        let (torrent_installed, size, is_owner) = {
            let state = self.lock();
            let is_owner = state
                .metadata
                .requested
                .get(&piece)
                .map(|owner| Arc::ptr_eq(owner, peer))
                .unwrap_or(false);
            (state.torrent.is_some(), state.metadata.size, is_owner)
        };
        if torrent_installed || !is_owner {
            return Ok(());
        }
        let size = match size {
            Some(size) => size,
            None => return Ok(()),
        };
        if let Some(reported) = header.get_int(b"total_size") {
            if reported as usize != size {
                peer.close().await;
                return Ok(());
            }
        }

        let start = match piece.checked_mul(METADATA_BLOCK_SIZE) {
            Some(start) => start,
            None => return Ok(()),
        };
        let remaining = match size.checked_sub(start) {
            Some(remaining) => remaining,
            None => return Ok(()),
        };
        let expected = METADATA_BLOCK_SIZE.min(remaining);
        let data = &body[header_end..];
        if expected == 0 || data.len() != expected {
            peer.close().await;
            return Ok(());
        }

        let count = size.div_ceil(METADATA_BLOCK_SIZE);
        let raw_info: Option<Vec<u8>> = {
            let mut state = self.lock();
            state.metadata.requested.remove(&piece);
            state.metadata.deadlines.remove(&piece);
            peer.discard_metadata_outstanding(piece);
            state.metadata.chunks.insert(piece, data.to_vec());
            state.metadata.sources.insert(piece, peer.clone());
            if state.metadata.chunks.len() == count {
                let mut raw = Vec::with_capacity(size);
                for index in 0..count {
                    raw.extend_from_slice(&state.metadata.chunks[&index]);
                }
                Some(raw)
            } else {
                None
            }
        };

        let raw_info = match raw_info {
            Some(raw_info) => raw_info,
            None => {
                self.queue_metadata(peer).await;
                return Ok(());
            }
        };

        let expected_hash = self.lock().info_hash;
        let digest = Sha1::digest(&raw_info);
        if Some(digest.as_slice()) != expected_hash.as_ref().map(|hash| hash.as_slice()) {
            log::warn!("Magnet metadata failed info-hash verification");
            let bad_peers: Vec<PeerRef> = {
                let mut state = self.lock();
                let bad: Vec<PeerRef> = state.metadata.sources.values().cloned().collect();
                state.metadata.chunks.clear();
                state.metadata.sources.clear();
                state.metadata.requested.clear();
                state.metadata.deadlines.clear();
                for known in &state.peers {
                    known.clear_metadata_outstanding();
                    known.clear_metadata_queue();
                }
                bad
            };
            for bad in bad_peers {
                bad.close().await;
            }
            return Ok(());
        }

        let trackers = self.lock().tracker_urls.clone();
        let info = match parse_info_bytes(&raw_info, &trackers) {
            Ok(info) => info,
            Err(error) => {
                log::warn!("Invalid magnet metadata: {error}");
                peer.close().await;
                return Ok(());
            }
        };

        let install_result = {
            let mut state = self.lock();
            let result = state.install_metadata(info, &self.save_path);
            if result.is_ok() {
                state.metadata.chunks.clear();
                state.metadata.sources.clear();
                state.metadata.requested.clear();
                state.metadata.deadlines.clear();
            }
            result
        };
        if let Err(error) = install_result {
            log::warn!("Invalid magnet metadata: {error}");
            peer.close().await;
            return Ok(());
        }
        self.activate_metadata_for_peers().await;
        Ok(())
    }

    async fn assign_metadata_piece(&self, piece: usize, exclude: &PeerRef, retry_same: bool) {
        let size = match self.lock().metadata.size {
            Some(size) => size,
            None => return,
        };
        let candidates: Vec<PeerRef> = {
            let state = self.lock();
            let mut candidates: Vec<PeerRef> = state
                .peers
                .iter()
                .filter(|candidate| !Arc::ptr_eq(candidate, exclude))
                .cloned()
                .collect();
            if retry_same {
                candidates.extend(
                    state
                        .peers
                        .iter()
                        .filter(|candidate| Arc::ptr_eq(candidate, exclude))
                        .cloned(),
                );
            }
            candidates
        };
        for candidate in candidates {
            if !candidate.is_connected()
                || candidate.remote_extension(b"ut_metadata").is_none()
                || candidate.metadata_size() != Some(size)
            {
                continue;
            }
            if !candidate.metadata_queue_snapshot().contains(&piece) {
                candidate.push_metadata_queue(piece);
            }
            self.fill_metadata_window(&candidate).await;
            return;
        }
    }

    async fn release_metadata_peer(&self, peer: &PeerRef) {
        let requeue: Vec<PeerRef> = {
            let mut state = self.lock();
            let lost: Vec<usize> = state
                .metadata
                .requested
                .iter()
                .filter(|(_, owner)| Arc::ptr_eq(owner, peer))
                .map(|(piece, _)| *piece)
                .collect();
            for piece in lost {
                state.metadata.requested.remove(&piece);
                state.metadata.deadlines.remove(&piece);
            }
            let received: Vec<usize> = state
                .metadata
                .sources
                .iter()
                .filter(|(_, owner)| Arc::ptr_eq(owner, peer))
                .map(|(piece, _)| *piece)
                .collect();
            for piece in received {
                state.metadata.sources.remove(&piece);
                state.metadata.chunks.remove(&piece);
            }
            peer.clear_metadata_outstanding();
            peer.clear_metadata_queue();
            if state.torrent.is_none() {
                state
                    .peers
                    .iter()
                    .filter(|candidate| !Arc::ptr_eq(candidate, peer) && candidate.is_connected())
                    .cloned()
                    .collect()
            } else {
                Vec::new()
            }
        };
        for candidate in requeue {
            self.queue_metadata(&candidate).await;
        }
    }

    async fn serve_metadata_request(&self, peer: &PeerRef, piece: usize) {
        let extension_id = match peer.remote_extension(b"ut_metadata") {
            Some(id) => id,
            None => return,
        };
        let raw_info: Vec<u8> = self
            .lock()
            .torrent
            .as_ref()
            .map(|torrent| torrent.info.raw_info.clone())
            .unwrap_or_default();
        let start = piece.saturating_mul(METADATA_BLOCK_SIZE);
        let response = if raw_info.is_empty() || start >= raw_info.len() {
            encode(&dict(vec![
                (b"msg_type", Value::Int(2)),
                (b"piece", Value::Int(piece as i64)),
            ]))
        } else {
            let mut response = encode(&dict(vec![
                (b"msg_type", Value::Int(1)),
                (b"piece", Value::Int(piece as i64)),
                (b"total_size", Value::Int(raw_info.len() as i64)),
            ]));
            let end = (start + METADATA_BLOCK_SIZE).min(raw_info.len());
            response.extend_from_slice(&raw_info[start..end]);
            response
        };
        let _ = peer.send_extended(extension_id, &response).await;
    }

    async fn activate_metadata_for_peers(&self) {
        let (peers, num_pieces, raw_length, bitfield, any_have) = {
            let state = self.lock();
            match state.torrent.as_ref() {
                Some(torrent) => (
                    state.peers.clone(),
                    torrent.info.num_pieces(),
                    torrent.info.raw_info.len(),
                    torrent.bitfield.clone(),
                    torrent.any_have(),
                ),
                None => return,
            }
        };
        for peer in peers {
            if !peer.is_connected() {
                continue;
            }
            if peer.supports_extensions() {
                let _ = peer.send_extension_handshake(Some(raw_length)).await;
            }
            if let Some(pending) = peer.take_pending_bitfield() {
                if peer.update_bitfield(&pending, num_pieces).is_err() {
                    peer.close().await;
                    continue;
                }
            }
            let pending = peer.take_pending_have();
            let mut closed = false;
            for piece in pending {
                if peer.set_have(piece, num_pieces).is_err() {
                    peer.close().await;
                    closed = true;
                    break;
                }
            }
            if closed || !peer.is_connected() {
                continue;
            }
            if !peer.bitfield_sent() && any_have {
                let _ = peer.send_message(BITFIELD, &bitfield).await;
                peer.set_bitfield_sent(true);
            }
            if !peer.peer_choking() {
                self.assign_piece(&peer).await;
            }
        }
    }

    async fn send_pex(&self, peer: &PeerRef, addresses: &[PeerAddr], dropped: &[PeerAddr]) {
        if !peer.is_connected() {
            return;
        }
        let peer_id = match peer.remote_extension(b"ut_pex") {
            Some(id) => id,
            None => return,
        };
        let mut added: Vec<PeerAddr> = Vec::new();
        for address in addresses {
            if address.1 == 0 {
                continue;
            }
            if peer.pex_address().as_ref() == Some(address) || peer.pex_announced_contains(address)
            {
                continue;
            }
            added.push(address.clone());
            if added.len() == 50 {
                break;
            }
        }
        let dropped: Vec<PeerAddr> = dropped.iter().take(50).cloned().collect();
        if added.is_empty() && dropped.is_empty() {
            return;
        }
        let payload = encode_pex(&added, &dropped);
        if peer.send_extended(peer_id, &payload).await.is_ok() {
            peer.add_pex_announced(&added);
        } else {
            log::debug!("Could not send PEX update to {}:{}", peer.ip, peer.port);
        }
    }

    async fn broadcast_pex(
        &self,
        addresses: Vec<PeerAddr>,
        exclude: Option<&PeerRef>,
        dropped: Vec<PeerAddr>,
    ) {
        let addresses: Vec<PeerAddr> = addresses.into_iter().filter(|a| a.1 != 0).collect();
        let dropped: Vec<PeerAddr> = dropped.into_iter().filter(|a| a.1 != 0).collect();
        if addresses.is_empty() && dropped.is_empty() {
            return;
        }
        let peers = self.lock().peers.clone();
        for peer in peers {
            if let Some(exclude) = exclude {
                if Arc::ptr_eq(&peer, exclude) {
                    continue;
                }
            }
            if peer.is_connected() && peer.remote_extension(b"ut_pex").is_some() {
                self.send_pex(&peer, &addresses, &dropped).await;
            }
        }
    }

    fn persist_resume(&self) {
        let state = self.lock();
        if let (Some(resume), Some(torrent)) = (state.resume_store.as_ref(), state.torrent.as_ref())
        {
            if let Err(error) = resume.save(&torrent.bitfield) {
                log::warn!("Could not save resume checkpoint: {error}");
            }
        }
    }
}

impl ClientState {
    fn install_metadata(&mut self, info: TorrentInfo, save_path: &Path) -> Result<()> {
        if let Some(existing) = self.info_hash {
            if existing != info.info_hash {
                return Err(Error::msg(
                    "Los metadatos recibidos no coinciden con el info-hash del magnet",
                ));
            }
        }
        let storage = PieceStorage::new(&info, save_path)?;
        let resume = ResumeStore::new(save_path, &info)?;
        self.display_name = info.name.clone();
        self.info_hash = Some(info.info_hash);
        self.torrent = Some(Torrent::new(info));
        self.storage = Some(storage);
        self.resume_store = Some(resume);
        self.restore_resume();
        Ok(())
    }

    fn restore_resume(&mut self) {
        if self.resume_store.is_none() || self.storage.is_none() || self.torrent.is_none() {
            return;
        }
        let saved = match self.resume_store.as_ref().unwrap().load() {
            Some(bitfield) => bitfield,
            None => return,
        };
        let num_pieces = self.torrent.as_ref().unwrap().info.num_pieces();
        let mut restored = 0u64;
        for index in 0..num_pieces {
            if saved[index / 8] & (0x80 >> (index % 8)) == 0 {
                continue;
            }
            let data = match self.storage.as_mut().unwrap().read_piece(index) {
                Ok(data) => data,
                Err(error) => {
                    log::warn!("Could not read saved piece {index}; downloading it again: {error}");
                    continue;
                }
            };
            let torrent = self.torrent.as_mut().unwrap();
            if torrent.verify_piece(index, &data) {
                torrent.set_have(index);
                self.downloaded += data.len() as u64;
                restored += 1;
            } else {
                log::warn!("Saved piece {index} failed SHA-1 verification; downloading it again");
            }
        }
        let changed = self
            .torrent
            .as_ref()
            .map(|torrent| torrent.bitfield != saved)
            .unwrap_or(false);
        if changed {
            self.persist_resume_locked();
        }
        if restored > 0 {
            let progress = self
                .torrent
                .as_ref()
                .map(|torrent| torrent.progress() * 100.0)
                .unwrap_or(0.0);
            log::info!("Resumed {restored} verified pieces ({progress:.1}%)");
        }
    }

    fn persist_resume_locked(&self) {
        if let (Some(resume), Some(torrent)) = (self.resume_store.as_ref(), self.torrent.as_ref()) {
            if let Err(error) = resume.save(&torrent.bitfield) {
                log::warn!("Could not save resume checkpoint: {error}");
            }
        }
    }
}

fn dedup(values: &[String]) -> Vec<String> {
    let mut seen: HashSet<&str> = HashSet::new();
    let mut out = Vec::new();
    for value in values {
        if seen.insert(value.as_str()) {
            out.push(value.clone());
        }
    }
    out
}
