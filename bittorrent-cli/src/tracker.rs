//! Anuncios a trackers HTTP(S) y UDP (BEP 15).

use std::net::{Ipv4Addr, Ipv6Addr};
use std::time::Duration;

use percent_encoding::{percent_encode, NON_ALPHANUMERIC};
use tokio::net::UdpSocket;
use url::Url;

use crate::bencode::{decode_complete, Value};
use crate::error::{Error, Result};

pub struct TrackerResponse {
    pub interval: u64,
    pub complete: i64,
    pub incomplete: i64,
    pub peers: Vec<(String, u16)>,
}

impl TrackerResponse {
    fn from_value(data: &Value) -> Result<Self> {
        if let Some(failure) = data.get_bytes(b"failure reason") {
            return Err(Error::msg(String::from_utf8_lossy(failure).into_owned()));
        }
        let interval = data.get_int(b"interval").unwrap_or(1800).max(30) as u64;
        let complete = data.get_int(b"complete").unwrap_or(0);
        let incomplete = data.get_int(b"incomplete").unwrap_or(0);
        let mut peers = parse_peers(data.get(b"peers"), 6, false);
        peers.extend(parse_peers(data.get(b"peers6"), 18, true));
        Ok(TrackerResponse {
            interval,
            complete,
            incomplete,
            peers,
        })
    }
}

fn parse_compact_peers(data: &[u8], stride: usize, ipv6: bool) -> Vec<(String, u16)> {
    let mut peers = Vec::new();
    if stride == 0 || !data.len().is_multiple_of(stride) {
        return peers;
    }
    let ip_size = if ipv6 { 16 } else { 4 };
    for chunk in data.chunks(stride) {
        let ip = if ipv6 {
            let mut octets = [0u8; 16];
            octets.copy_from_slice(&chunk[..16]);
            Ipv6Addr::from(octets).to_string()
        } else {
            let mut octets = [0u8; 4];
            octets.copy_from_slice(&chunk[..4]);
            Ipv4Addr::from(octets).to_string()
        };
        let port = u16::from_be_bytes([chunk[ip_size], chunk[ip_size + 1]]);
        if port != 0 {
            peers.push((ip, port));
        }
    }
    peers
}

fn parse_peers(value: Option<&Value>, stride: usize, ipv6: bool) -> Vec<(String, u16)> {
    match value {
        Some(Value::List(entries)) => {
            let mut peers = Vec::new();
            for entry in entries {
                if let (Some(ip), Some(port)) = (entry.get_bytes(b"ip"), entry.get_int(b"port")) {
                    if port > 0 && port <= 65535 {
                        peers.push((String::from_utf8_lossy(ip).into_owned(), port as u16));
                    }
                }
            }
            peers
        }
        Some(Value::Bytes(data)) => parse_compact_peers(data, stride, ipv6),
        _ => Vec::new(),
    }
}

fn encode_component(bytes: &[u8]) -> String {
    percent_encode(bytes, NON_ALPHANUMERIC).to_string()
}

pub struct TrackerClient {
    info_hash: [u8; 20],
    peer_id: [u8; 20],
    pub port: u16,
    timeout: Duration,
    client: reqwest::Client,
}

impl TrackerClient {
    pub fn new(info_hash: [u8; 20], peer_id: [u8; 20], port: u16) -> Self {
        TrackerClient {
            info_hash,
            peer_id,
            port,
            timeout: Duration::from_secs(15),
            client: reqwest::Client::new(),
        }
    }

    pub async fn announce(
        &self,
        tracker_url: &str,
        uploaded: u64,
        downloaded: u64,
        left: u64,
        event: &str,
    ) -> Result<TrackerResponse> {
        let parsed = Url::parse(tracker_url).map_err(|_| {
            Error::msg(format!(
                "Unsupported tracker scheme: {}",
                url_scheme(tracker_url)
            ))
        })?;
        match parsed.scheme() {
            "http" | "https" => {
                self.http_announce(&parsed, uploaded, downloaded, left, event)
                    .await
            }
            "udp" => {
                self.udp_announce(&parsed, uploaded, downloaded, left, event)
                    .await
            }
            other => Err(Error::msg(format!(
                "Unsupported tracker scheme: {}",
                if other.is_empty() { "(none)" } else { other }
            ))),
        }
    }

    async fn http_announce(
        &self,
        parsed: &Url,
        uploaded: u64,
        downloaded: u64,
        left: u64,
        event: &str,
    ) -> Result<TrackerResponse> {
        let mut params: Vec<String> = vec![
            format!("info_hash={}", encode_component(&self.info_hash)),
            format!("peer_id={}", encode_component(&self.peer_id)),
            format!("port={}", self.port),
            format!("uploaded={uploaded}"),
            format!("downloaded={downloaded}"),
            format!("left={left}"),
            "compact=1".to_string(),
            "numwant=50".to_string(),
        ];
        if !event.is_empty() {
            params.push(format!("event={event}"));
        }
        let base_query = parsed.query().unwrap_or("");
        let final_query = if base_query.is_empty() {
            params.join("&")
        } else {
            format!("{}&{}", base_query, params.join("&"))
        };
        let mut url = parsed.clone();
        url.set_query(Some(&final_query));

        let response = self
            .client
            .get(url)
            .header("User-Agent", "PythonTorrent/0.1")
            .timeout(self.timeout)
            .send()
            .await
            .map_err(|error| Error::msg(format!("HTTP tracker request failed: {error}")))?;
        let body = response
            .bytes()
            .await
            .map_err(|error| Error::msg(format!("HTTP tracker request failed: {error}")))?;
        let decoded = decode_complete(&body)
            .map_err(|error| Error::msg(format!("HTTP tracker request failed: {error}")))?;
        if !decoded.is_dict() {
            return Err(Error::msg("Tracker returned a non-dictionary response"));
        }
        TrackerResponse::from_value(&decoded)
    }

    async fn udp_announce(
        &self,
        parsed: &Url,
        uploaded: u64,
        downloaded: u64,
        left: u64,
        event: &str,
    ) -> Result<TrackerResponse> {
        let host = parsed
            .host_str()
            .ok_or_else(|| Error::msg("UDP tracker URL has no hostname"))?;
        let port = parsed.port().unwrap_or(80);
        let address = tokio::net::lookup_host((host, port))
            .await?
            .find(|candidate| candidate.is_ipv4())
            .ok_or_else(|| Error::msg("UDP tracker has no IPv4 address"))?;

        let socket = UdpSocket::bind(("0.0.0.0", 0)).await?;
        socket.connect(address).await?;

        let connection_id = self.udp_connect(&socket).await?;
        let transaction_id: u32 = rand::random();
        let event_code: u32 = match event {
            "completed" => 1,
            "started" => 2,
            "stopped" => 3,
            _ => 0,
        };
        let key: u32 = rand::random();

        let mut packet = Vec::with_capacity(98);
        packet.extend_from_slice(&connection_id.to_be_bytes());
        packet.extend_from_slice(&1u32.to_be_bytes());
        packet.extend_from_slice(&transaction_id.to_be_bytes());
        packet.extend_from_slice(&self.info_hash);
        packet.extend_from_slice(&self.peer_id);
        packet.extend_from_slice(&downloaded.to_be_bytes());
        packet.extend_from_slice(&left.to_be_bytes());
        packet.extend_from_slice(&uploaded.to_be_bytes());
        packet.extend_from_slice(&event_code.to_be_bytes());
        packet.extend_from_slice(&0u32.to_be_bytes());
        packet.extend_from_slice(&key.to_be_bytes());
        packet.extend_from_slice(&50i32.to_be_bytes());
        packet.extend_from_slice(&self.port.to_be_bytes());
        socket.send(&packet).await?;

        let mut buffer = [0u8; 65535];
        let length = tokio::time::timeout(self.timeout, socket.recv(&mut buffer))
            .await
            .map_err(|_| Error::msg("UDP tracker timed out"))??;
        let data = &buffer[..length];
        if data.len() < 8 {
            return Err(Error::msg("Truncated UDP tracker announce response"));
        }
        let action = u32::from_be_bytes([data[0], data[1], data[2], data[3]]);
        let response_tx = u32::from_be_bytes([data[4], data[5], data[6], data[7]]);
        if response_tx != transaction_id {
            return Err(Error::msg("UDP tracker transaction ID mismatch"));
        }
        if action == 3 {
            return Err(Error::msg(String::from_utf8_lossy(&data[8..]).into_owned()));
        }
        if action != 1 {
            return Err(Error::msg("Unexpected UDP tracker response"));
        }
        if data.len() < 20 {
            return Err(Error::msg("Truncated UDP tracker announce response"));
        }
        let interval = u32::from_be_bytes([data[8], data[9], data[10], data[11]]);
        let leechers = u32::from_be_bytes([data[12], data[13], data[14], data[15]]);
        let seeders = u32::from_be_bytes([data[16], data[17], data[18], data[19]]);
        let peers = parse_compact_peers(&data[20..], 6, false);

        Ok(TrackerResponse {
            interval: interval as u64,
            complete: seeders as i64,
            incomplete: leechers as i64,
            peers,
        })
    }

    async fn udp_connect(&self, socket: &UdpSocket) -> Result<u64> {
        let transaction_id: u32 = rand::random();
        let mut packet = Vec::with_capacity(16);
        packet.extend_from_slice(&0x41727101980u64.to_be_bytes());
        packet.extend_from_slice(&0u32.to_be_bytes());
        packet.extend_from_slice(&transaction_id.to_be_bytes());

        for attempt in 0..3u32 {
            socket.send(&packet).await?;
            let seconds = (1u64 << (attempt + 1)).min(self.timeout.as_secs().max(1));
            let mut buffer = [0u8; 2048];
            let length =
                match tokio::time::timeout(Duration::from_secs(seconds), socket.recv(&mut buffer))
                    .await
                {
                    Ok(Ok(length)) => length,
                    Ok(Err(error)) => return Err(error.into()),
                    Err(_) => continue,
                };
            let data = &buffer[..length];
            if data.len() < 8 {
                continue;
            }
            let action = u32::from_be_bytes([data[0], data[1], data[2], data[3]]);
            let response_tx = u32::from_be_bytes([data[4], data[5], data[6], data[7]]);
            if response_tx != transaction_id {
                continue;
            }
            if action == 3 {
                return Err(Error::msg(String::from_utf8_lossy(&data[8..]).into_owned()));
            }
            if action != 0 || data.len() != 16 {
                return Err(Error::msg("Invalid UDP tracker connect response"));
            }
            return Ok(u64::from_be_bytes(data[8..16].try_into().unwrap()));
        }
        Err(Error::msg("UDP tracker connect timed out"))
    }
}

fn url_scheme(url: &str) -> String {
    match Url::parse(url) {
        Ok(parsed) if !parsed.scheme().is_empty() => parsed.scheme().to_string(),
        _ => "(none)".to_string(),
    }
}
