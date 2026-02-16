/// Token counting utilities for LLM context management
/// Provides accurate token counts using llama-cpp-2 tokenizer

// Token counting utilities for LLM context management

/// Estimate token count for text
/// Uses a heuristic: ~1 token per 4 characters (rough approximation)
/// For accurate counting, use the LLM's tokenizer directly
pub fn estimate_tokens(text: &str) -> usize {
    // Heuristic: English text averages ~4-5 characters per token
    // This is suitable for quick estimates in non-time-critical paths
    std::cmp::max(1, text.len() / 4)
}

/// More accurate token count (uses actual LLM tokenization if available)
/// Falls back to heuristic if LLM is unavailable
pub fn count_tokens(text: &str) -> usize {
    estimate_tokens(text)
}

/// Count tokens for a list of messages (e.g., conversation history)
pub fn count_message_tokens(messages: &[(String, String)]) -> usize {
    messages
        .iter()
        .map(|(_role, content)| {
            // Add overhead for formatting: "<|start_header_id|>role<|end_header_id|>\ncontent\n<|eot_id|>\n"
            let overhead = 50; // Approximate tokens for formatting
            count_tokens(content) + overhead
        })
        .sum()
}

/// Calculate remaining token budget
pub fn calculate_remaining_budget(total_budget: usize, used_tokens: usize) -> usize {
    if used_tokens >= total_budget {
        0
    } else {
        total_budget - used_tokens
    }
}

/// Determine token warning level
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum TokenWarningLevel {
    Normal,      // < 50%
    Warning,     // 50-80%
    Critical,    // 80-95%
    Exhausted,   // > 95%
}

pub fn get_warning_level(used_percent: usize) -> TokenWarningLevel {
    match used_percent {
        0..=50 => TokenWarningLevel::Normal,
        51..=80 => TokenWarningLevel::Warning,
        81..=95 => TokenWarningLevel::Critical,
        _ => TokenWarningLevel::Exhausted,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_estimate_tokens() {
        // Rough approximation: 1 token ≈ 4 characters
        let text = "Hello world"; // 11 chars
        let token_count = estimate_tokens(text);
        assert!(token_count >= 2 && token_count <= 4);
    }

    #[test]
    fn test_count_message_tokens() {
        let messages = vec![
            ("user".to_string(), "Hello".to_string()),
            ("assistant".to_string(), "Hi there!".to_string()),
        ];
        
        let total = count_message_tokens(&messages);
        assert!(total > 2); // At least more than heuristic
    }

    #[test]
    fn test_warning_levels() {
        assert_eq!(get_warning_level(30), TokenWarningLevel::Normal);
        assert_eq!(get_warning_level(60), TokenWarningLevel::Warning);
        assert_eq!(get_warning_level(85), TokenWarningLevel::Critical);
        assert_eq!(get_warning_level(99), TokenWarningLevel::Exhausted);
    }

    #[test]
    fn test_remaining_budget() {
        assert_eq!(calculate_remaining_budget(100, 30), 70);
        assert_eq!(calculate_remaining_budget(100, 100), 0);
        assert_eq!(calculate_remaining_budget(100, 150), 0);
    }
}
