use axum::http::StatusCode;
use axum::response::{IntoResponse, Response};
use axum::Json;
use serde::{Deserialize, Serialize};
use thiserror::Error;

#[derive(Debug, Error)]
pub enum OrchestrationError {
    #[error("Job not found: {0}")]
    JobNotFound(String),

    #[error("Job already running")]
    JobAlreadyRunning,

    #[error("Python subprocess failed: {0}")]
    PythonError(String),

    #[error("TCP connection failed: {0}")]
    TcpError(String),

    #[error("Database error: {0}")]
    DatabaseError(String),

    #[error("Invalid request: {0}")]
    InvalidRequest(String),

    #[error("Internal server error: {0}")]
    InternalError(String),
}

#[derive(Serialize, Deserialize)]
pub struct ErrorResponse {
    pub error: String,
    pub details: Option<String>,
}

impl IntoResponse for OrchestrationError {
    fn into_response(self) -> Response {
        let (status, error_message, details) = match self {
            Self::JobNotFound(msg) => (
                StatusCode::NOT_FOUND,
                "Job not found".to_string(),
                Some(msg),
            ),
            Self::JobAlreadyRunning => (
                StatusCode::CONFLICT,
                "Pipeline already running".to_string(),
                Some("Another pipeline execution is in progress".to_string()),
            ),
            Self::PythonError(msg) => (
                StatusCode::INTERNAL_SERVER_ERROR,
                "Python execution failed".to_string(),
                Some(msg),
            ),
            Self::TcpError(msg) => (
                StatusCode::INTERNAL_SERVER_ERROR,
                "TCP connection error".to_string(),
                Some(msg),
            ),
            Self::DatabaseError(msg) => (
                StatusCode::INTERNAL_SERVER_ERROR,
                "Database error".to_string(),
                Some(msg),
            ),
            Self::InvalidRequest(msg) => (
                StatusCode::BAD_REQUEST,
                "Invalid request".to_string(),
                Some(msg),
            ),
            Self::InternalError(msg) => (
                StatusCode::INTERNAL_SERVER_ERROR,
                "Internal server error".to_string(),
                Some(msg),
            ),
        };

        let body = Json(ErrorResponse {
            error: error_message,
            details,
        });

        (status, body).into_response()
    }
}
