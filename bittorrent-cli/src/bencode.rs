//! Implementacion estricta de bencode usada por los metadatos y los trackers.
//!
//! Se escribe a mano (en lugar de usar un crate generico) porque se necesita
//! conservar los bytes exactos del diccionario `info` para verificar el
//! info-hash SHA-1, y validar orden/duplicados de claves como hace el original.

use std::collections::BTreeMap;

use thiserror::Error;

#[derive(Debug, Clone, PartialEq, Eq, Error)]
#[error("{0}")]
pub struct BencodeError(pub String);

impl BencodeError {
    pub fn new(message: impl Into<String>) -> Self {
        BencodeError(message.into())
    }
}

pub type BResult<T> = std::result::Result<T, BencodeError>;

#[derive(Debug, Clone, PartialEq)]
pub enum Value {
    Int(i64),
    Bytes(Vec<u8>),
    List(Vec<Value>),
    Dict(BTreeMap<Vec<u8>, Value>),
}

impl Value {
    pub fn as_int(&self) -> Option<i64> {
        match self {
            Value::Int(value) => Some(*value),
            _ => None,
        }
    }

    pub fn as_bytes(&self) -> Option<&[u8]> {
        match self {
            Value::Bytes(value) => Some(value),
            _ => None,
        }
    }

    pub fn as_list(&self) -> Option<&Vec<Value>> {
        match self {
            Value::List(value) => Some(value),
            _ => None,
        }
    }

    pub fn as_dict(&self) -> Option<&BTreeMap<Vec<u8>, Value>> {
        match self {
            Value::Dict(value) => Some(value),
            _ => None,
        }
    }

    pub fn get(&self, key: &[u8]) -> Option<&Value> {
        self.as_dict().and_then(|dict| dict.get(key))
    }

    pub fn get_bytes(&self, key: &[u8]) -> Option<&[u8]> {
        self.get(key).and_then(|value| value.as_bytes())
    }

    pub fn get_int(&self, key: &[u8]) -> Option<i64> {
        self.get(key).and_then(|value| value.as_int())
    }

    pub fn is_dict(&self) -> bool {
        matches!(self, Value::Dict(_))
    }
}

impl From<i64> for Value {
    fn from(value: i64) -> Self {
        Value::Int(value)
    }
}

impl From<u64> for Value {
    fn from(value: u64) -> Self {
        Value::Int(value as i64)
    }
}

impl From<usize> for Value {
    fn from(value: usize) -> Self {
        Value::Int(value as i64)
    }
}

impl From<i32> for Value {
    fn from(value: i32) -> Self {
        Value::Int(value as i64)
    }
}

impl From<u16> for Value {
    fn from(value: u16) -> Self {
        Value::Int(value as i64)
    }
}

impl From<Vec<u8>> for Value {
    fn from(value: Vec<u8>) -> Self {
        Value::Bytes(value)
    }
}

impl From<&[u8]> for Value {
    fn from(value: &[u8]) -> Self {
        Value::Bytes(value.to_vec())
    }
}

impl From<&str> for Value {
    fn from(value: &str) -> Self {
        Value::Bytes(value.as_bytes().to_vec())
    }
}

/// Construye un diccionario bencode a partir de pares clave/valor.
pub fn dict(entries: Vec<(&[u8], Value)>) -> Value {
    let mut map = BTreeMap::new();
    for (key, value) in entries {
        map.insert(key.to_vec(), value);
    }
    Value::Dict(map)
}

fn decode_integer(data: &[u8], pos: usize) -> BResult<(Value, usize)> {
    let end = match data[pos + 1..].iter().position(|&byte| byte == b'e') {
        Some(offset) => pos + 1 + offset,
        None => return Err(BencodeError::new("Unterminated integer")),
    };
    let raw = &data[pos + 1..end];
    let digits = if raw.first() == Some(&b'-') {
        &raw[1..]
    } else {
        raw
    };
    if digits.is_empty()
        || !digits.iter().all(|byte| byte.is_ascii_digit())
        || (digits.len() > 1 && digits[0] == b'0')
    {
        return Err(BencodeError::new("Invalid bencoded integer"));
    }
    let text =
        std::str::from_utf8(raw).map_err(|_| BencodeError::new("Invalid bencoded integer"))?;
    let value: i64 = text
        .parse()
        .map_err(|_| BencodeError::new("Invalid bencoded integer"))?;
    Ok((Value::Int(value), end + 1))
}

fn decode_list(data: &[u8], pos: usize) -> BResult<(Value, usize)> {
    let mut result = Vec::new();
    let mut cursor = pos + 1;
    loop {
        if cursor >= data.len() {
            return Err(BencodeError::new("Unterminated list"));
        }
        if data[cursor] == b'e' {
            return Ok((Value::List(result), cursor + 1));
        }
        let (item, next) = decode(data, cursor)?;
        result.push(item);
        cursor = next;
    }
}

fn decode_dict(data: &[u8], pos: usize) -> BResult<(Value, usize)> {
    let mut result: BTreeMap<Vec<u8>, Value> = BTreeMap::new();
    let mut cursor = pos + 1;
    let mut previous_key: Option<Vec<u8>> = None;
    loop {
        if cursor >= data.len() {
            return Err(BencodeError::new("Unterminated dictionary"));
        }
        if data[cursor] == b'e' {
            return Ok((Value::Dict(result), cursor + 1));
        }
        let (key, next) = decode(data, cursor)?;
        let key = match key {
            Value::Bytes(bytes) => bytes,
            _ => return Err(BencodeError::new("Dictionary keys must be byte strings")),
        };
        if result.contains_key(&key) {
            return Err(BencodeError::new("Duplicate dictionary key"));
        }
        if let Some(previous) = &previous_key {
            if key < *previous {
                return Err(BencodeError::new("Dictionary keys are not sorted"));
            }
        }
        previous_key = Some(key.clone());
        let (value, next) = decode(data, next)?;
        result.insert(key, value);
        cursor = next;
    }
}

fn decode_bytes(data: &[u8], pos: usize) -> BResult<(Value, usize)> {
    let colon = match data[pos..].iter().position(|&byte| byte == b':') {
        Some(offset) => pos + offset,
        None => return Err(BencodeError::new("Byte string has no length separator")),
    };
    let raw_length = &data[pos..colon];
    if raw_length.is_empty() || (raw_length.len() > 1 && raw_length[0] == b'0') {
        return Err(BencodeError::new("Invalid byte string length"));
    }
    let length: usize = std::str::from_utf8(raw_length)
        .ok()
        .and_then(|text| text.parse().ok())
        .ok_or_else(|| BencodeError::new("Invalid byte string length"))?;
    let start = colon + 1;
    let end = start + length;
    if end > data.len() {
        return Err(BencodeError::new("Byte string extends beyond end of data"));
    }
    Ok((Value::Bytes(data[start..end].to_vec()), end))
}

pub fn decode(data: &[u8], pos: usize) -> BResult<(Value, usize)> {
    if pos >= data.len() {
        return Err(BencodeError::new("Unexpected end of data"));
    }
    match data[pos] {
        b'i' => decode_integer(data, pos),
        b'l' => decode_list(data, pos),
        b'd' => decode_dict(data, pos),
        marker if marker.is_ascii_digit() => decode_bytes(data, pos),
        _ => Err(BencodeError::new(format!(
            "Invalid bencode marker at offset {pos}"
        ))),
    }
}

pub fn decode_complete(data: &[u8]) -> BResult<Value> {
    let (value, end) = decode(data, 0)?;
    if end != data.len() {
        return Err(BencodeError::new("Trailing data after bencoded value"));
    }
    Ok(value)
}

/// Decodifica un diccionario .torrent y devuelve tambien los bytes exactos de `info`.
pub fn decode_torrent(data: &[u8]) -> BResult<(Value, Vec<u8>)> {
    if !data.starts_with(b"d") {
        if data.is_empty() {
            return Err(BencodeError::new("El archivo .torrent esta vacio"));
        }
        let sample: Vec<u8> = data[..data.len().min(80)]
            .iter()
            .copied()
            .skip_while(|byte| {
                matches!(
                    byte,
                    b'\xef' | b'\xbb' | b'\xbf' | b'\r' | b'\n' | b'\t' | b' '
                )
            })
            .map(|byte| byte.to_ascii_lowercase())
            .collect();
        if sample.starts_with(b"<!doctype html")
            || sample.starts_with(b"<html")
            || sample.starts_with(b"<?xml")
        {
            return Err(BencodeError::new(
                "El archivo parece ser una pagina HTML/XML, no un .torrent; \
                 comprueba que descargaste el archivo torrent y no una pagina web",
            ));
        }
        if sample.starts_with(b"magnet:") {
            return Err(BencodeError::new(
                "El archivo contiene un enlace magnet, no metadatos .torrent",
            ));
        }
        let preview = if data.len() > 24 { &data[..24] } else { data };
        return Err(BencodeError::new(format!(
            "El archivo no parece un .torrent bencode valido (bytes iniciales: {preview:?})"
        )));
    }

    let mut result: BTreeMap<Vec<u8>, Value> = BTreeMap::new();
    let mut raw_info: Option<Vec<u8>> = None;
    let mut cursor = 1;
    let mut previous_key: Option<Vec<u8>> = None;
    loop {
        if cursor >= data.len() {
            return Err(BencodeError::new("Unterminated torrent dictionary"));
        }
        if data[cursor] == b'e' {
            cursor += 1;
            break;
        }
        let (key, next) = decode(data, cursor)?;
        let key = match key {
            Value::Bytes(bytes) => bytes,
            _ => return Err(BencodeError::new("Dictionary keys must be byte strings")),
        };
        if result.contains_key(&key) {
            return Err(BencodeError::new("Duplicate dictionary key"));
        }
        if let Some(previous) = &previous_key {
            if key < *previous {
                return Err(BencodeError::new("Dictionary keys are not sorted"));
            }
        }
        previous_key = Some(key.clone());

        let value_start = next;
        let (value, value_end) = decode(data, next)?;
        if key == b"info" {
            raw_info = Some(data[value_start..value_end].to_vec());
        }
        result.insert(key, value);
        cursor = value_end;
    }

    if cursor != data.len() {
        return Err(BencodeError::new("Trailing data after torrent dictionary"));
    }
    let info = result.get(b"info".as_slice()).cloned();
    let raw_info = match (raw_info, info) {
        (Some(raw), Some(Value::Dict(_))) => raw,
        _ => return Err(BencodeError::new("Torrent has no info dictionary")),
    };
    Ok((Value::Dict(result), raw_info))
}

pub fn encode(value: &Value) -> Vec<u8> {
    let mut out = Vec::new();
    encode_into(value, &mut out);
    out
}

fn encode_into(value: &Value, out: &mut Vec<u8>) {
    match value {
        Value::Int(number) => {
            out.push(b'i');
            out.extend_from_slice(number.to_string().as_bytes());
            out.push(b'e');
        }
        Value::Bytes(bytes) => {
            out.extend_from_slice(bytes.len().to_string().as_bytes());
            out.push(b':');
            out.extend_from_slice(bytes);
        }
        Value::List(items) => {
            out.push(b'l');
            for item in items {
                encode_into(item, out);
            }
            out.push(b'e');
        }
        Value::Dict(entries) => {
            out.push(b'd');
            for (key, item) in entries {
                out.extend_from_slice(key.len().to_string().as_bytes());
                out.push(b':');
                out.extend_from_slice(key);
                encode_into(item, out);
            }
            out.push(b'e');
        }
    }
}
