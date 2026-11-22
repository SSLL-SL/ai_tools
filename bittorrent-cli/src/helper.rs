//! Puente HTTP local para que la extension de Chrome obtenga .torrent desde magnets.
//!
//! Port de `torrent_helper.py`. Reproduce los mismos endpoints, comprobaciones
//! de CORS/Origin, limites de tamano y estructura de los trabajos de descarga.

use std::collections::HashMap;
use std::sync::{Arc, Mutex as StdMutex};
use std::time::{SystemTime, UNIX_EPOCH};

use axum::body::{to_bytes, Body};
use axum::extract::{Request, State};
use axum::http::{header, HeaderMap, HeaderName, HeaderValue, Method, StatusCode};
use axum::response::{IntoResponse, Response};
use axum::Router;
use serde_json::{json, Value as JsonValue};

use crate::aria2::{convert_magnet, download_magnet, validate_magnet, ConvertError};
use crate::client::Progress;
use crate::error::Result;

const MAX_REQUEST_SIZE: usize = 32 * 1024;
const MAX_TORRENT_SIZE: usize = 16 * 1024 * 1024;

#[derive(Clone, serde::Serialize)]
struct Job {
    status: String,
    phase: String,
    progress: f64,
    downloaded: u64,
    total: u64,
    peers: usize,
    speed: f64,
    updated: f64,
    #[serde(skip_serializing_if = "Option::is_none")]
    destination: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    error: Option<String>,
}

struct HelperState {
    extension_origin: String,
    jobs: StdMutex<HashMap<String, Job>>,
}

/// Arranca el helper en 127.0.0.1:`port` validando el origen de la extension.
pub async fn serve(port: u16, extension_id: &str) -> Result<()> {
    let state = Arc::new(HelperState {
        extension_origin: format!("chrome-extension://{extension_id}"),
        jobs: StdMutex::new(HashMap::new()),
    });
    let app = Router::new()
        .fallback(handle)
        .with_state(state)
        .layer(axum::extract::DefaultBodyLimit::disable());

    let address = std::net::SocketAddr::from(([127, 0, 0, 1], port));
    let listener = tokio::net::TcpListener::bind(address).await?;
    println!("Helper listo en http://127.0.0.1:{port} (Ctrl+C para salir)");
    axum::serve(listener, app)
        .with_graceful_shutdown(shutdown_signal())
        .await?;
    println!("\nHelper detenido.");
    Ok(())
}

async fn shutdown_signal() {
    let _ = tokio::signal::ctrl_c().await;
}

async fn handle(State(state): State<Arc<HelperState>>, request: Request) -> Response {
    let (parts, body) = request.into_parts();
    let method = parts.method;
    let path = parts.uri.path().to_string();
    let allowed = parts
        .headers
        .get(header::ORIGIN)
        .and_then(|value| value.to_str().ok())
        == Some(state.extension_origin.as_str());

    match method {
        Method::OPTIONS => {
            if !allowed {
                return empty(StatusCode::FORBIDDEN);
            }
            if !is_known_path(&path) {
                return empty(StatusCode::NOT_FOUND);
            }
            let mut response = StatusCode::NO_CONTENT.into_response();
            let headers = response.headers_mut();
            add_cors(headers, &state.extension_origin);
            headers.insert(
                header::ACCESS_CONTROL_MAX_AGE,
                HeaderValue::from_static("600"),
            );
            response
        }
        Method::GET => json_error(
            StatusCode::METHOD_NOT_ALLOWED,
            "Usa POST /download/status para consultar la descarga.",
            allowed,
            &state,
        ),
        Method::POST => post(&state, &path, &parts.headers, body, allowed).await,
        _ => empty(StatusCode::NOT_IMPLEMENTED),
    }
}

async fn post(
    state: &Arc<HelperState>,
    path: &str,
    headers: &HeaderMap,
    body: Body,
    allowed: bool,
) -> Response {
    if !allowed {
        return empty(StatusCode::FORBIDDEN);
    }
    if !is_known_path(path) {
        return json_error(StatusCode::NOT_FOUND, "Ruta no encontrada.", true, state);
    }

    let length = match headers.get(header::CONTENT_LENGTH) {
        Some(value) => match value
            .to_str()
            .ok()
            .and_then(|value| value.trim().parse::<i64>().ok())
        {
            Some(length) => length,
            None => {
                return json_error(
                    StatusCode::BAD_REQUEST,
                    "Longitud de solicitud no válida.",
                    true,
                    state,
                )
            }
        },
        None => 0,
    };
    if length <= 0 || length > MAX_REQUEST_SIZE as i64 {
        return json_error(
            StatusCode::PAYLOAD_TOO_LARGE,
            "La solicitud está vacía o es demasiado grande.",
            true,
            state,
        );
    }

    let bytes = match to_bytes(body, MAX_REQUEST_SIZE).await {
        Ok(bytes) => bytes,
        Err(_) => {
            return json_error(
                StatusCode::PAYLOAD_TOO_LARGE,
                "La solicitud está vacía o es demasiado grande.",
                true,
                state,
            )
        }
    };
    let payload: JsonValue = match serde_json::from_slice(&bytes) {
        Ok(payload) => payload,
        Err(_) => {
            return json_error(
                StatusCode::BAD_REQUEST,
                "Envía una solicitud JSON válida.",
                true,
                state,
            )
        }
    };
    if !payload.is_object() {
        return json_error(
            StatusCode::BAD_REQUEST,
            "Envía un objeto JSON.",
            true,
            state,
        );
    }

    if path == "/download/status" {
        let job_id = payload.get("job_id").and_then(|value| value.as_str());
        let valid = job_id
            .map(|value| {
                value.len() == 32
                    && value
                        .bytes()
                        .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
            })
            .unwrap_or(false);
        if !valid {
            return json_error(
                StatusCode::BAD_REQUEST,
                "ID de descarga no válido.",
                true,
                state,
            );
        }
        let job_id = job_id.unwrap();
        let job = state.jobs.lock().unwrap().get(job_id).cloned();
        return match job {
            Some(job) => json_response(
                StatusCode::OK,
                serde_json::to_value(job).unwrap(),
                true,
                state,
            ),
            None => json_error(
                StatusCode::NOT_FOUND,
                "Descarga no encontrada.",
                true,
                state,
            ),
        };
    }

    let magnet = match payload.get("magnet").and_then(|value| value.as_str()) {
        Some(magnet) => magnet,
        None => {
            return json_error(
                StatusCode::BAD_REQUEST,
                "Falta el enlace magnet.",
                true,
                state,
            )
        }
    };
    let magnet = match validate_magnet(magnet) {
        Ok(magnet) => magnet,
        Err(error) => return convert_error_response(error, state),
    };

    if path == "/download" {
        let now = now_secs();
        let job_id = {
            let mut jobs = state.jobs.lock().unwrap();
            jobs.retain(|_, job| {
                !((job.status == "completed" || job.status == "failed")
                    && now - job.updated > 3600.0)
            });
            let job_id = hex::encode(rand::random::<[u8; 16]>());
            jobs.insert(
                job_id.clone(),
                Job {
                    status: "downloading".to_string(),
                    phase: "metadata".to_string(),
                    progress: 0.0,
                    downloaded: 0,
                    total: 0,
                    peers: 0,
                    speed: 0.0,
                    updated: now,
                    destination: None,
                    error: None,
                },
            );
            job_id
        };
        let state_clone = state.clone();
        let job_clone = job_id.clone();
        let magnet_clone = magnet.clone();
        tokio::spawn(async move {
            run_download_job(state_clone, job_clone, magnet_clone).await;
        });
        return json_response(
            StatusCode::ACCEPTED,
            json!({ "job_id": job_id, "status": "downloading" }),
            true,
            state,
        );
    }

    convert(&magnet, state).await
}

async fn convert(magnet: &str, state: &Arc<HelperState>) -> Response {
    let directory = std::env::temp_dir().join(format!(
        "magnet-extension-{}",
        hex::encode(rand::random::<[u8; 8]>())
    ));
    if let Err(error) = std::fs::create_dir_all(&directory) {
        return json_error(
            StatusCode::INTERNAL_SERVER_ERROR,
            &error.to_string(),
            true,
            state,
        );
    }
    let destination = directory.join("metadata.torrent");

    let result = convert_magnet(magnet, Some(&destination), 300.0).await;
    let response = match result {
        Ok(path) => match std::fs::read(&path) {
            Ok(data) if !data.is_empty() && data.len() <= MAX_TORRENT_SIZE => {
                let mut response = Response::new(Body::from(data));
                *response.status_mut() = StatusCode::OK;
                let headers = response.headers_mut();
                headers.insert(
                    header::CONTENT_TYPE,
                    HeaderValue::from_static("application/x-bittorrent"),
                );
                add_cors(headers, &state.extension_origin);
                response
            }
            Ok(_) => json_error(
                StatusCode::BAD_REQUEST,
                "El archivo .torrent está vacío o supera el límite de tamaño.",
                true,
                state,
            ),
            Err(error) => json_error(
                StatusCode::INTERNAL_SERVER_ERROR,
                &error.to_string(),
                true,
                state,
            ),
        },
        Err(error) => convert_error_response(error, state),
    };
    let _ = std::fs::remove_dir_all(&directory);
    response
}

fn convert_error_response(error: ConvertError, state: &HelperState) -> Response {
    match error {
        ConvertError::Invalid(message) => {
            json_error(StatusCode::BAD_REQUEST, &message, true, state)
        }
        ConvertError::Runtime(message) => {
            json_error(StatusCode::BAD_GATEWAY, &message, true, state)
        }
        ConvertError::Os(message) => {
            json_error(StatusCode::INTERNAL_SERVER_ERROR, &message, true, state)
        }
    }
}

async fn run_download_job(state: Arc<HelperState>, job_id: String, magnet: String) {
    let progress_state = state.clone();
    let progress_job = job_id.clone();
    let update = move |progress: Progress| {
        let mut jobs = progress_state.jobs.lock().unwrap();
        if let Some(job) = jobs.get_mut(&progress_job) {
            job.progress = progress.progress;
            job.downloaded = progress.downloaded;
            job.total = progress.total;
            job.peers = progress.peers;
            job.speed = progress.speed;
            job.phase = if progress.total == 0 {
                "metadata".to_string()
            } else {
                "download".to_string()
            };
            job.updated = now_secs();
        }
    };

    match download_magnet(&magnet, update).await {
        Ok(()) => {
            let destination = std::path::absolute("descargas")
                .map(|path| path.to_string_lossy().into_owned())
                .unwrap_or_else(|_| "descargas".to_string());
            {
                let mut jobs = state.jobs.lock().unwrap();
                if let Some(job) = jobs.get_mut(&job_id) {
                    job.status = "completed".to_string();
                    job.destination = Some(destination.clone());
                    job.updated = now_secs();
                }
            }
            println!("Descarga {job_id} completada en {destination}");
        }
        Err(error) => {
            let message = error.to_string();
            {
                let mut jobs = state.jobs.lock().unwrap();
                if let Some(job) = jobs.get_mut(&job_id) {
                    job.status = "failed".to_string();
                    job.error = Some(message.clone());
                    job.updated = now_secs();
                }
            }
            println!("Descarga {job_id} fallida: {message}");
        }
    }
}

fn is_known_path(path: &str) -> bool {
    matches!(path, "/convert" | "/download" | "/download/status")
}

fn now_secs() -> f64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_secs_f64())
        .unwrap_or(0.0)
}

fn empty(status: StatusCode) -> Response {
    let mut response = StatusCode::default().into_response();
    *response.status_mut() = status;
    response
}

fn json_error(status: StatusCode, message: &str, cors: bool, state: &HelperState) -> Response {
    json_response(status, json!({ "error": message }), cors, state)
}

fn json_response(
    status: StatusCode,
    payload: JsonValue,
    cors: bool,
    state: &HelperState,
) -> Response {
    let body = serde_json::to_vec(&payload).unwrap_or_default();
    let length = body.len();
    let mut response = Response::new(Body::from(body));
    *response.status_mut() = status;
    let headers = response.headers_mut();
    headers.insert(
        header::CONTENT_TYPE,
        HeaderValue::from_static("application/json; charset=utf-8"),
    );
    if let Ok(value) = HeaderValue::from_str(&length.to_string()) {
        headers.insert(header::CONTENT_LENGTH, value);
    }
    headers.insert(header::CACHE_CONTROL, HeaderValue::from_static("no-store"));
    if cors {
        add_cors(headers, &state.extension_origin);
    }
    response
}

fn add_cors(headers: &mut HeaderMap, origin: &str) {
    if let Ok(value) = HeaderValue::from_str(origin) {
        headers.insert(header::ACCESS_CONTROL_ALLOW_ORIGIN, value);
    }
    headers.insert(
        header::ACCESS_CONTROL_ALLOW_METHODS,
        HeaderValue::from_static("GET, POST, OPTIONS"),
    );
    headers.insert(
        header::ACCESS_CONTROL_ALLOW_HEADERS,
        HeaderValue::from_static("Content-Type"),
    );
    headers.insert(
        HeaderName::from_static("access-control-allow-private-network"),
        HeaderValue::from_static("true"),
    );
    headers.insert(header::VARY, HeaderValue::from_static("Origin"));
}
