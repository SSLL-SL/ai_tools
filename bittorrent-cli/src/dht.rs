//! Implementacion minima del DHT Mainline de BitTorrent (BEP 5) para IPv4.

use std::collections::{BTreeMap, HashMap, HashSet};
use std::net::{IpAddr, Ipv4Addr, SocketAddr};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::{Duration, Instant};

use hmac::{Hmac, Mac};
use rand::RngCore;
use sha1::Sha1;
use tokio::net::UdpSocket;
use tokio::sync::{oneshot, Mutex};
use tokio::task::JoinHandle;

use crate::bencode::{decode_complete, dict, encode, Value};
use crate::error::{Error, Result};

type HmacSha1 = Hmac<Sha1>;

const BOOTSTRAP_NODES: &[(&str, u16)] = &[
    ("router.bittorrent.com", 6881),
    ("router.utorrent.com", 6881),
    ("dht.transmissionbt.com", 6881),
];
const MAX_ROUTING_NODES: usize = 512;
const MAX_LOOKUP_NODES: usize = 32;
const ALPHA: usize = 8;

pub struct DhtClient {
    inner: Arc<DhtInner>,
    task: JoinHandle<()>,
}

impl DhtClient {
    pub async fn start(peer_port: u16, bind_port: u16) -> Result<Self> {
        let socket = match UdpSocket::bind(("0.0.0.0", bind_port)).await {
            Ok(socket) => socket,
            Err(error) => {
                if bind_port == 0 {
                    return Err(error.into());
                }
                log::warn!("Could not bind DHT UDP port {bind_port}; using an ephemeral port");
                UdpSocket::bind(("0.0.0.0", 0)).await?
            }
        };
        let socket = Arc::new(socket);

        let mut node_id = [0u8; 20];
        rand::thread_rng().fill_bytes(&mut node_id);
        let mut token_secret = [0u8; 32];
        rand::thread_rng().fill_bytes(&mut token_secret);

        let inner = Arc::new(DhtInner {
            node_id,
            peer_port,
            token_secret,
            socket: socket.clone(),
            pending: Mutex::new(HashMap::new()),
            nodes: Mutex::new(HashMap::new()),
            peer_store: Mutex::new(HashMap::new()),
            closed: AtomicBool::new(false),
        });

        let task_inner = inner.clone();
        let task = tokio::spawn(async move { task_inner.run().await });
        Ok(DhtClient { inner, task })
    }

    pub async fn find_peers(&self, info_hash: &[u8; 20]) -> HashSet<(String, u16)> {
        self.inner.find_peers(info_hash).await
    }

    pub fn close(&self) {
        self.inner.closed.store(true, Ordering::SeqCst);
        self.task.abort();
    }
}

impl Drop for DhtClient {
    fn drop(&mut self) {
        self.inner.closed.store(true, Ordering::SeqCst);
        self.task.abort();
    }
}

type PendingReply = Result<(Value, SocketAddr)>;
type PendingRequests = HashMap<Vec<u8>, oneshot::Sender<PendingReply>>;
type PeerStore = HashMap<Vec<u8>, HashMap<(String, u16), Instant>>;

struct DhtInner {
    node_id: [u8; 20],
    peer_port: u16,
    token_secret: [u8; 32],
    socket: Arc<UdpSocket>,
    pending: Mutex<PendingRequests>,
    nodes: Mutex<HashMap<(String, u16), [u8; 20]>>,
    peer_store: Mutex<PeerStore>,
    closed: AtomicBool,
}

impl DhtInner {
    async fn run(self: Arc<Self>) {
        let mut buffer = vec![0u8; 4097];
        while !self.closed.load(Ordering::SeqCst) {
            match self.socket.recv_from(&mut buffer).await {
                Ok((length, address)) => {
                    let data = buffer[..length].to_vec();
                    self.handle_datagram(data, address).await;
                }
                Err(_) => {
                    if self.closed.load(Ordering::SeqCst) {
                        break;
                    }
                }
            }
        }
    }

    async fn handle_datagram(&self, data: Vec<u8>, address: SocketAddr) {
        if data.len() > 4096 {
            return;
        }
        let message = match decode_complete(&data) {
            Ok(message) => message,
            Err(_) => return,
        };
        if !message.is_dict() {
            return;
        }
        let kind = message.get_bytes(b"y").map(|value| value.to_vec());
        let transaction = match message.get_bytes(b"t") {
            Some(transaction) => transaction.to_vec(),
            None => return,
        };

        match kind.as_deref() {
            Some(b"r") => {
                if let Some(sender) = self.pending.lock().await.remove(&transaction) {
                    if let Some(result) = message.get(b"r").cloned() {
                        let _ = sender.send(Ok((result, address)));
                    }
                }
            }
            Some(b"e") => {
                if let Some(sender) = self.pending.lock().await.remove(&transaction) {
                    let _ = sender.send(Err(Error::msg(format!(
                        "DHT error: {:?}",
                        message.get(b"e")
                    ))));
                }
            }
            Some(b"q") => {
                self.answer_query(&message, address).await;
            }
            _ => {}
        }
    }

    async fn query(
        &self,
        address: SocketAddr,
        query: &[u8],
        arguments: Value,
        timeout: Duration,
    ) -> Option<(Value, SocketAddr)> {
        if self.closed.load(Ordering::SeqCst) {
            return None;
        }
        let mut transaction = [0u8; 2];
        {
            let pending = self.pending.lock().await;
            for _ in 0..5 {
                let mut candidate = [0u8; 2];
                rand::thread_rng().fill_bytes(&mut candidate);
                if !pending.contains_key(&candidate.to_vec()) {
                    transaction = candidate;
                    break;
                }
            }
        }

        let (sender, receiver) = oneshot::channel();
        self.pending
            .lock()
            .await
            .insert(transaction.to_vec(), sender);

        let packet = encode(&dict(vec![
            (b"t", Value::Bytes(transaction.to_vec())),
            (b"y", Value::Bytes(b"q".to_vec())),
            (b"q", Value::Bytes(query.to_vec())),
            (b"a", arguments),
        ]));

        let result = match self.socket.send_to(&packet, address).await {
            Ok(_) => match tokio::time::timeout(timeout, receiver).await {
                Ok(Ok(Ok(value))) => Some(value),
                _ => None,
            },
            Err(_) => None,
        };
        self.pending.lock().await.remove(&transaction.to_vec());
        result
    }

    async fn answer_query(&self, message: &Value, address: SocketAddr) {
        let transaction = message.get_bytes(b"t").unwrap_or(b"").to_vec();
        let query = message.get_bytes(b"q").map(|value| value.to_vec());
        let arguments = message.get(b"a").and_then(|value| value.as_dict());
        let arguments = match arguments {
            Some(arguments) => arguments,
            None => {
                self.send_error(&transaction, address, 203, b"Invalid arguments")
                    .await;
                return;
            }
        };

        let remote_id = arguments
            .get(b"id".as_slice())
            .and_then(|value| value.as_bytes());
        let remote_id = match remote_id {
            Some(id) if id.len() == 20 => id.to_vec(),
            _ => {
                self.send_error(&transaction, address, 203, b"Invalid node ID")
                    .await;
                return;
            }
        };
        self.add_node(&remote_id, &address.ip().to_string(), address.port())
            .await;

        let mut result: BTreeMap<Vec<u8>, Value> = BTreeMap::new();
        result.insert(b"id".to_vec(), Value::Bytes(self.node_id.to_vec()));

        match query.as_deref() {
            Some(b"ping") => {}
            Some(b"find_node") => {
                let target = arguments
                    .get(b"target".as_slice())
                    .and_then(|value| value.as_bytes());
                match target {
                    Some(target) if target.len() == 20 => {
                        result.insert(
                            b"nodes".to_vec(),
                            Value::Bytes(self.closest_nodes(target, Some(address)).await),
                        );
                    }
                    _ => {
                        self.send_error(&transaction, address, 203, b"Invalid target")
                            .await;
                        return;
                    }
                }
            }
            Some(b"get_peers") => {
                let target = arguments
                    .get(b"info_hash".as_slice())
                    .and_then(|value| value.as_bytes());
                match target {
                    Some(target) if target.len() == 20 => {
                        result.insert(
                            b"token".to_vec(),
                            Value::Bytes(self.make_token(&address.ip().to_string())),
                        );
                        let peers = self.stored_peers(target).await;
                        if peers.is_empty() {
                            result.insert(
                                b"nodes".to_vec(),
                                Value::Bytes(self.closest_nodes(target, Some(address)).await),
                            );
                        } else {
                            result.insert(
                                b"values".to_vec(),
                                Value::List(peers.into_iter().map(Value::Bytes).collect()),
                            );
                        }
                    }
                    _ => {
                        self.send_error(&transaction, address, 203, b"Invalid info_hash")
                            .await;
                        return;
                    }
                }
            }
            Some(b"announce_peer") => {
                let target = arguments
                    .get(b"info_hash".as_slice())
                    .and_then(|value| value.as_bytes());
                let token = arguments
                    .get(b"token".as_slice())
                    .and_then(|value| value.as_bytes());
                let (target, token) = match (target, token) {
                    (Some(target), Some(token)) if target.len() == 20 => (target, token),
                    _ => {
                        self.send_error(
                            &transaction,
                            address,
                            203,
                            b"Invalid announce_peer arguments",
                        )
                        .await;
                        return;
                    }
                };
                if token != self.make_token(&address.ip().to_string()) {
                    self.send_error(&transaction, address, 203, b"Invalid token")
                        .await;
                    return;
                }
                let implied_port = arguments
                    .get(b"implied_port".as_slice())
                    .and_then(|value| value.as_int())
                    .unwrap_or(0)
                    == 1;
                let peer_port = if implied_port {
                    Some(address.port())
                } else {
                    arguments
                        .get(b"port".as_slice())
                        .and_then(|value| value.as_int())
                        .filter(|port| *port > 0 && *port <= 65535)
                        .map(|port| port as u16)
                };
                let peer_port = match peer_port {
                    Some(port) => port,
                    None => {
                        self.send_error(&transaction, address, 203, b"Invalid peer port")
                            .await;
                        return;
                    }
                };
                let mut store = self.peer_store.lock().await;
                let entry = store.entry(target.to_vec()).or_default();
                entry.insert(
                    (address.ip().to_string(), peer_port),
                    Instant::now() + Duration::from_secs(1800),
                );
            }
            _ => {
                self.send_error(&transaction, address, 204, b"Method Unknown")
                    .await;
                return;
            }
        }

        if !self.closed.load(Ordering::SeqCst) {
            let packet = encode(&dict(vec![
                (b"t", Value::Bytes(transaction)),
                (b"y", Value::Bytes(b"r".to_vec())),
                (b"r", Value::Dict(result)),
            ]));
            let _ = self.socket.send_to(&packet, address).await;
        }
    }

    async fn send_error(&self, transaction: &[u8], address: SocketAddr, code: i64, text: &[u8]) {
        if self.closed.load(Ordering::SeqCst) {
            return;
        }
        let packet = encode(&dict(vec![
            (b"t", Value::Bytes(transaction.to_vec())),
            (b"y", Value::Bytes(b"e".to_vec())),
            (
                b"e",
                Value::List(vec![Value::Int(code), Value::Bytes(text.to_vec())]),
            ),
        ]));
        let _ = self.socket.send_to(&packet, address).await;
    }

    fn make_token(&self, ip: &str) -> Vec<u8> {
        let packed = match ip.parse::<IpAddr>() {
            Ok(IpAddr::V4(address)) => address.octets().to_vec(),
            Ok(IpAddr::V6(address)) => address.octets().to_vec(),
            Err(_) => return Vec::new(),
        };
        let mut mac = HmacSha1::new_from_slice(&self.token_secret).expect("clave HMAC valida");
        mac.update(&packed);
        mac.finalize().into_bytes().to_vec()
    }

    async fn add_node(&self, node_id: &[u8], ip: &str, port: u16) {
        if node_id.len() != 20 || port == 0 {
            return;
        }
        match ip.parse::<IpAddr>() {
            Ok(IpAddr::V4(_)) => {}
            _ => return,
        }
        let mut nodes = self.nodes.lock().await;
        if nodes.len() >= MAX_ROUTING_NODES {
            if let Some(key) = nodes.keys().next().cloned() {
                nodes.remove(&key);
            }
        }
        nodes.insert((ip.to_string(), port), to_array(node_id));
    }

    async fn closest_nodes(&self, target: &[u8], exclude: Option<SocketAddr>) -> Vec<u8> {
        let target = to_array(target);
        let nodes = self.nodes.lock().await;
        let mut entries: Vec<([u8; 20], String, u16)> = nodes
            .iter()
            .filter(|((ip, port), _)| match exclude {
                Some(address) => !(address.ip().to_string() == *ip && address.port() == *port),
                None => true,
            })
            .map(|((ip, port), id)| (*id, ip.clone(), *port))
            .collect();
        entries.sort_by_key(|(id, _, _)| xor_key(id, &target));
        entries.truncate(8);
        let mut out = Vec::new();
        for (id, ip, port) in entries {
            out.extend_from_slice(&compact_node(&id, &ip, port));
        }
        out
    }

    async fn stored_peers(&self, info_hash: &[u8]) -> Vec<Vec<u8>> {
        let mut store = self.peer_store.lock().await;
        let now = Instant::now();
        let mut values = Vec::new();
        if let Some(entry) = store.get_mut(info_hash) {
            entry.retain(|_, expiry| *expiry > now);
            for (ip, port) in entry.keys() {
                let packed = compact_peer(ip, *port);
                if !packed.is_empty() {
                    values.push(packed);
                }
                if values.len() >= 50 {
                    break;
                }
            }
        }
        values
    }

    async fn resolve_bootstrap(&self) -> Vec<SocketAddr> {
        let mut resolved = Vec::new();
        for (host, port) in BOOTSTRAP_NODES {
            match tokio::net::lookup_host((*host, *port)).await {
                Ok(addresses) => {
                    for address in addresses {
                        if address.is_ipv4() && !resolved.contains(&address) {
                            resolved.push(address);
                        }
                    }
                }
                Err(error) => log::debug!("Could not resolve DHT bootstrap {host}: {error}"),
            }
        }
        resolved
    }

    async fn find_peers(&self, info_hash: &[u8; 20]) -> HashSet<(String, u16)> {
        let bootstrap = self.resolve_bootstrap().await;
        if bootstrap.is_empty() {
            return HashSet::new();
        }

        let mut candidates: HashMap<SocketAddr, [u8; 20]> = HashMap::new();
        let timeout = Duration::from_millis(2500);

        let find_futures = bootstrap.iter().map(|address| {
            self.query(
                *address,
                b"find_node",
                dict(vec![
                    (b"id", Value::Bytes(self.node_id.to_vec())),
                    (b"target", Value::Bytes(info_hash.to_vec())),
                ]),
                timeout,
            )
        });
        for response in futures::future::join_all(find_futures)
            .await
            .into_iter()
            .flatten()
        {
            let (result, address) = response;
            if let Some(node_id) = result.get_bytes(b"id") {
                if node_id.len() == 20 {
                    self.add_node(node_id, &address.ip().to_string(), address.port())
                        .await;
                    candidates.insert(address, to_array(node_id));
                }
            }
            for (id, ip, port) in parse_nodes(result.get_bytes(b"nodes").unwrap_or(&[])) {
                self.add_node(&id, &ip, port).await;
                if let Some(address) = socket_addr(&ip, port) {
                    candidates.insert(address, id);
                }
            }
        }

        {
            let nodes = self.nodes.lock().await;
            for ((ip, port), id) in nodes.iter() {
                if let Some(address) = socket_addr(ip, *port) {
                    candidates.insert(address, *id);
                }
            }
        }

        let mut visited: HashSet<SocketAddr> = HashSet::new();
        let mut peers: HashSet<(String, u16)> = HashSet::new();
        let mut announced: HashSet<SocketAddr> = HashSet::new();
        let mut query_count = 0usize;

        while !candidates.is_empty() && query_count < MAX_LOOKUP_NODES {
            let mut batch: Vec<([u8; 20], SocketAddr)> = candidates
                .iter()
                .filter(|(address, _)| !visited.contains(address))
                .map(|(address, id)| (*id, *address))
                .collect();
            batch.sort_by_key(|(id, _)| xor_key(id, info_hash));
            batch.truncate(ALPHA);
            if batch.is_empty() {
                break;
            }
            for (_, address) in &batch {
                visited.insert(*address);
            }
            query_count += batch.len();

            let get_futures = batch.iter().map(|(_, address)| {
                self.query(
                    *address,
                    b"get_peers",
                    dict(vec![
                        (b"id", Value::Bytes(self.node_id.to_vec())),
                        (b"info_hash", Value::Bytes(info_hash.to_vec())),
                    ]),
                    timeout,
                )
            });
            let responses = futures::future::join_all(get_futures).await;

            let mut announce_tasks = Vec::new();
            for response in responses.into_iter().flatten() {
                let (result, address) = response;
                if let Some(node_id) = result.get_bytes(b"id") {
                    if node_id.len() == 20 {
                        self.add_node(node_id, &address.ip().to_string(), address.port())
                            .await;
                    }
                }
                peers.extend(parse_compact_peers(result.get(b"values")));
                if let Some(token) = result.get_bytes(b"token") {
                    if !announced.contains(&address) {
                        announced.insert(address);
                        announce_tasks.push((address, token.to_vec()));
                    }
                }
                for (id, ip, port) in parse_nodes(result.get_bytes(b"nodes").unwrap_or(&[])) {
                    self.add_node(&id, &ip, port).await;
                    if let Some(address) = socket_addr(&ip, port) {
                        candidates.insert(address, id);
                    }
                }
            }

            let announce_futures = announce_tasks.into_iter().map(|(address, token)| {
                self.query(
                    address,
                    b"announce_peer",
                    dict(vec![
                        (b"id", Value::Bytes(self.node_id.to_vec())),
                        (b"info_hash", Value::Bytes(info_hash.to_vec())),
                        (b"port", Value::Int(self.peer_port as i64)),
                        (b"token", Value::Bytes(token)),
                        (b"implied_port", Value::Int(0)),
                    ]),
                    timeout,
                )
            });
            let _ = futures::future::join_all(announce_futures).await;
        }

        peers
    }
}

fn to_array(value: &[u8]) -> [u8; 20] {
    let mut array = [0u8; 20];
    let length = value.len().min(20);
    array[..length].copy_from_slice(&value[..length]);
    array
}

fn xor_key(id: &[u8; 20], target: &[u8; 20]) -> [u8; 20] {
    let mut key = [0u8; 20];
    for index in 0..20 {
        key[index] = id[index] ^ target[index];
    }
    key
}

fn socket_addr(ip: &str, port: u16) -> Option<SocketAddr> {
    match ip.parse::<IpAddr>() {
        Ok(address) => Some(SocketAddr::new(address, port)),
        Err(_) => None,
    }
}

pub fn compact_node(node_id: &[u8], host: &str, port: u16) -> Vec<u8> {
    if node_id.len() != 20 || port == 0 {
        return Vec::new();
    }
    match host.parse::<Ipv4Addr>() {
        Ok(address) => {
            let mut out = Vec::with_capacity(26);
            out.extend_from_slice(node_id);
            out.extend_from_slice(&address.octets());
            out.extend_from_slice(&port.to_be_bytes());
            out
        }
        Err(_) => Vec::new(),
    }
}

fn compact_peer(host: &str, port: u16) -> Vec<u8> {
    match host.parse::<Ipv4Addr>() {
        Ok(address) if port != 0 => {
            let mut out = Vec::with_capacity(6);
            out.extend_from_slice(&address.octets());
            out.extend_from_slice(&port.to_be_bytes());
            out
        }
        _ => Vec::new(),
    }
}

fn parse_nodes(data: &[u8]) -> Vec<([u8; 20], String, u16)> {
    let mut result = Vec::new();
    if data.is_empty() || !data.len().is_multiple_of(26) {
        return result;
    }
    for chunk in data.chunks(26) {
        let mut node_id = [0u8; 20];
        node_id.copy_from_slice(&chunk[..20]);
        let mut octets = [0u8; 4];
        octets.copy_from_slice(&chunk[20..24]);
        let ip = Ipv4Addr::from(octets).to_string();
        let port = u16::from_be_bytes([chunk[24], chunk[25]]);
        if port != 0 {
            result.push((node_id, ip, port));
        }
    }
    result
}

fn parse_compact_peers(values: Option<&Value>) -> HashSet<(String, u16)> {
    let mut peers = HashSet::new();
    let values = match values.and_then(|value| value.as_list()) {
        Some(values) => values,
        None => return peers,
    };
    for value in values {
        let data = match value.as_bytes() {
            Some(data) => data,
            None => continue,
        };
        if data.len() == 6 {
            let mut octets = [0u8; 4];
            octets.copy_from_slice(&data[..4]);
            let port = u16::from_be_bytes([data[4], data[5]]);
            if port != 0 {
                peers.insert((Ipv4Addr::from(octets).to_string(), port));
            }
        } else if data.len() == 18 {
            let mut octets = [0u8; 16];
            octets.copy_from_slice(&data[..16]);
            let port = u16::from_be_bytes([data[16], data[17]]);
            if port != 0 {
                peers.insert((std::net::Ipv6Addr::from(octets).to_string(), port));
            }
        }
    }
    peers
}
