//! Direcciones compactas de peers usadas por el Peer Exchange (BEP 11).

use std::collections::HashSet;
use std::net::{IpAddr, Ipv4Addr, Ipv6Addr};

use crate::bencode::{dict, encode, Value};

pub type PeerAddr = (String, u16);

fn parse_compact(data: &[u8], stride: usize, ipv6: bool, out: &mut HashSet<PeerAddr>) {
    if stride == 0 || !data.len().is_multiple_of(stride) {
        return;
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
            out.insert((ip, port));
        }
    }
}

/// Devuelve las direcciones `(ip, puerto)` anadidas y eliminadas de un mensaje PEX.
pub fn parse_pex(message: &Value) -> (HashSet<PeerAddr>, HashSet<PeerAddr>) {
    let mut added = HashSet::new();
    if let Some(data) = message.get_bytes(b"added") {
        parse_compact(data, 6, false, &mut added);
    }
    if let Some(data) = message.get_bytes(b"added6") {
        parse_compact(data, 18, true, &mut added);
    }

    let mut dropped = HashSet::new();
    if let Some(data) = message.get_bytes(b"dropped") {
        parse_compact(data, 6, false, &mut dropped);
    }
    if let Some(data) = message.get_bytes(b"dropped6") {
        parse_compact(data, 18, true, &mut dropped);
    }

    (added, dropped)
}

pub fn encode_pex(added: &[PeerAddr], dropped: &[PeerAddr]) -> Vec<u8> {
    let mut added4: Vec<u8> = Vec::new();
    let mut added6: Vec<u8> = Vec::new();
    let mut dropped4: Vec<u8> = Vec::new();
    let mut dropped6: Vec<u8> = Vec::new();

    for (collection, target4, target6) in [
        (added, &mut added4, &mut added6),
        (dropped, &mut dropped4, &mut dropped6),
    ] {
        for (ip, port) in collection {
            if *port == 0 {
                continue;
            }
            match ip.parse::<IpAddr>() {
                Ok(IpAddr::V4(address)) => {
                    target4.extend_from_slice(&address.octets());
                    target4.extend_from_slice(&port.to_be_bytes());
                }
                Ok(IpAddr::V6(address)) => {
                    target6.extend_from_slice(&address.octets());
                    target6.extend_from_slice(&port.to_be_bytes());
                }
                Err(_) => {}
            }
        }
    }

    encode(&dict(vec![
        (b"added", Value::Bytes(added4)),
        (b"added6", Value::Bytes(added6)),
        (b"dropped", Value::Bytes(dropped4)),
        (b"dropped6", Value::Bytes(dropped6)),
    ]))
}
