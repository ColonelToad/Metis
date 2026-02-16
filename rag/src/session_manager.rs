/// Session Manager for conversation context with sliding window support
/// Manages token budgets and graceful session handoffs

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use std::collections::VecDeque;
use uuid::Uuid;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Message {
    pub id: String,
    pub role: String, // "user", "assistant", "system"
    pub content: String,
    pub token_count: usize,
    pub timestamp: DateTime<Utc>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ConversationSession {
    pub session_id: String,
    pub messages: VecDeque<Message>,
    pub total_tokens: usize,
    pub created_at: DateTime<Utc>,
    pub last_activity: DateTime<Utc>,
    pub status: SessionStatus,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub enum SessionStatus {
    Active,
    ReadyForHandoff,
    Suspended,
    Archived,
}

pub struct SessionManager {
    active_session: ConversationSession,
    standby_session: Option<ConversationSession>,
    
    // Configuration thresholds
    context_window: usize,                    // Total token budget (e.g., 2048)
    warning_threshold_percent: usize,         // 50% = spawn standby
    handoff_threshold_percent: usize,         // 80% = switch to standby
    max_messages_per_session: usize,          // Prevent unbounded growth
    
    // Statistics
    total_sessions: usize,
    total_handoffs: usize,
}

impl SessionManager {
    pub fn new(context_window: usize) -> Self {
        Self {
            active_session: ConversationSession::new(),
            standby_session: None,
            context_window,
            warning_threshold_percent: 50,
            handoff_threshold_percent: 80,
            max_messages_per_session: 100,
            total_sessions: 1,
            total_handoffs: 0,
        }
    }

    /// Add a message to the active session
    /// Returns (should_warn, should_handoff) to signal UI events
    pub async fn add_message(
        &mut self,
        role: &str,
        content: &str,
        token_count: usize,
    ) -> Result<(bool, bool), String> {
        let message = Message {
            id: Uuid::new_v4().to_string(),
            role: role.to_string(),
            content: content.to_string(),
            token_count,
            timestamp: Utc::now(),
        };

        // Check if adding this message would exceed capacity
        let new_total = self.active_session.total_tokens + token_count;
        let warning_threshold = (self.context_window * self.warning_threshold_percent) / 100;
        let handoff_threshold = (self.context_window * self.handoff_threshold_percent) / 100;

        let mut should_warn = false;
        let mut should_handoff = false;

        // If we're approaching capacity
        if new_total > warning_threshold && self.standby_session.is_none() {
            should_warn = true;
            // Spawn standby session with context summary
            self.spawn_standby_session().await?;
        }

        // If we've exceeded handoff threshold and standby is ready
        if new_total > handoff_threshold && self.standby_session.is_some() {
            should_handoff = self.attempt_handoff().await?;
        }

        // Add message to active session
        self.active_session.messages.push_back(message);
        self.active_session.total_tokens = new_total;
        self.active_session.last_activity = Utc::now();

        // Trim old messages if session gets too large
        while self.active_session.messages.len() > self.max_messages_per_session {
            if let Some(removed) = self.active_session.messages.pop_front() {
                self.active_session.total_tokens = self.active_session.total_tokens
                    .saturating_sub(removed.token_count);
            }
        }

        Ok((should_warn, should_handoff))
    }

    /// Spawn standby session with compressed summary of current conversation
    async fn spawn_standby_session(&mut self) -> Result<(), String> {
        let summary =
            self.create_conversation_summary(&self.active_session, 300); // 300 token budget for summary
        let summary_tokens = summary.len() / 4; // Rough estimate: 1 token ≈ 4 chars

        let mut new_session = ConversationSession::new();
        new_session.messages.push_back(Message {
            id: Uuid::new_v4().to_string(),
            role: "system".to_string(),
            content: format!(
                "You are continuing a conversation. Previous context:\n\n{}",
                summary
            ),
            token_count: summary_tokens,
            timestamp: Utc::now(),
        });
        new_session.total_tokens = summary_tokens;
        new_session.status = SessionStatus::ReadyForHandoff;

        self.standby_session = Some(new_session);
        tracing::info!(
            "Standby session spawned with summary ({} tokens)",
            summary_tokens
        );

        Ok(())
    }

    /// Attempt handoff from active to standby session
    async fn attempt_handoff(&mut self) -> Result<bool, String> {
        if let Some(standby) = self.standby_session.take() {
            let old_session_id = self.active_session.session_id.clone();
            
            // Move standby to active
            self.active_session = standby;
            self.active_session.status = SessionStatus::Active;
            
            self.total_handoffs += 1;
            self.total_sessions += 1;

            tracing::info!(
                "Handoff completed: {} → {}",
                old_session_id,
                self.active_session.session_id
            );

            return Ok(true);
        }

        Ok(false)
    }

    /// Create a compressed summary of conversation
    /// Extracts: key decision points, recent context, open questions
    fn create_conversation_summary(&self, session: &ConversationSession, max_tokens: usize) -> String {
        let mut summary = String::new();
        let max_chars = max_tokens * 4; // Rough estimate

        // Recent context: last 5-10 messages
        let recent_count = std::cmp::min(10, session.messages.len());
        if recent_count > 0 {
            summary.push_str("## Recent Messages\n");
            for msg in session
                .messages
                .iter()
                .rev()
                .take(recent_count)
                .collect::<Vec<_>>()
                .iter()
                .rev()
            {
                summary.push_str(&format!("**{}**: {}\n", msg.role, &msg.content[..std::cmp::min(100, msg.content.len())]));
            }
            summary.push('\n');
        }

        // Statistics
        summary.push_str(&format!(
            "## Statistics\n- Total messages: {}\n- Total tokens: {}\n- Session duration: {:?}\n",
            session.messages.len(),
            session.total_tokens,
            session.last_activity.signed_duration_since(session.created_at)
        ));

        // Truncate if needed
        if summary.len() > max_chars {
            summary.truncate(max_chars);
            summary.push_str("\n[truncated]");
        }

        summary
    }

    /// Get current session statistics
    pub fn get_stats(&self) -> SessionStats {
        let active_percent = (self.active_session.total_tokens * 100) / self.context_window;
        
        SessionStats {
            active_session_id: self.active_session.session_id.clone(),
            active_tokens: self.active_session.total_tokens,
            context_window: self.context_window,
            token_percent: active_percent,
            message_count: self.active_session.messages.len(),
            has_standby: self.standby_session.is_some(),
            total_sessions_created: self.total_sessions,
            total_handoffs: self.total_handoffs,
        }
    }

    /// Reset to a fresh session
    pub fn reset(&mut self) {
        self.active_session = ConversationSession::new();
        self.standby_session = None;
        self.total_sessions += 1;
        tracing::info!("Session reset. Total sessions: {}", self.total_sessions);
    }

    /// Get the full conversation history from active session
    pub fn get_conversation_history(&self) -> Vec<Message> {
        self.active_session.messages.iter().cloned().collect()
    }
}

impl ConversationSession {
    pub fn new() -> Self {
        Self {
            session_id: Uuid::new_v4().to_string(),
            messages: VecDeque::new(),
            total_tokens: 0,
            created_at: Utc::now(),
            last_activity: Utc::now(),
            status: SessionStatus::Active,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SessionStats {
    pub active_session_id: String,
    pub active_tokens: usize,
    pub context_window: usize,
    pub token_percent: usize,
    pub message_count: usize,
    pub has_standby: bool,
    pub total_sessions_created: usize,
    pub total_handoffs: usize,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn test_session_creation() {
        let manager = SessionManager::new(2048);
        let stats = manager.get_stats();
        
        assert_eq!(stats.context_window, 2048);
        assert_eq!(stats.message_count, 0);
        assert_eq!(stats.has_standby, false);
    }

    #[tokio::test]
    async fn test_add_message() {
        let mut manager = SessionManager::new(2048);
        
        let (warn, handoff) = manager
            .add_message("user", "Hello", 10)
            .await
            .expect("Failed to add message");

        assert!(!warn);
        assert!(!handoff);
        
        let stats = manager.get_stats();
        assert_eq!(stats.message_count, 1);
        assert_eq!(stats.active_tokens, 10);
    }

    #[tokio::test]
    async fn test_warning_threshold() {
        let mut manager = SessionManager::new(200); // Small window
        
        // Fill to 45% - no warning
        let (warn1, _) = manager
            .add_message("user", "x", 90)  // 90 / 200 = 45%
            .await
            .expect("Failed");
        assert!(!warn1);

        // Add more to exceed 50% - should warn
        let (warn2, _) = manager
            .add_message("assistant", "y", 20)  // 110 / 200 = 55%
            .await
            .expect("Failed");
        assert!(warn2);

        let stats = manager.get_stats();
        assert!(stats.has_standby);
    }
}
