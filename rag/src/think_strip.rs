/// Strip a DeepSeek-R1-style `<think>...</think>` reasoning block from raw
/// model output.
///
/// Returns `Some(text)` with the think block removed if one was present and
/// properly closed, or `Some(text)` unchanged if there was no think block at
/// all. Returns `None` if a `<think>` tag was opened but the output was
/// truncated before the matching `</think>` — in that case there's no
/// reliable way to separate "reasoning" from "answer," so callers should
/// treat it as "no usable content" rather than exposing the raw, unclosed
/// reasoning text as if it were the answer.
///
/// This replaces two previously separate, behaviorally different
/// implementations (a regex-based strip in `explanation_parser.rs` that
/// didn't handle the truncated case, and a hand-rolled version in
/// `reasoning_chain.rs` that did). This version keeps the more complete
/// (truncation-aware) behavior and is shared by both call sites.
pub fn strip_think_block(raw: &str) -> Option<String> {
    if let Some(end_idx) = raw.rfind("</think>") {
        Some(raw[end_idx + "</think>".len()..].trim().to_string())
    } else if raw.contains("<think>") {
        None
    } else {
        Some(raw.trim().to_string())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn strips_closed_think_block() {
        let raw = "<think>reasoning here</think>the actual answer";
        assert_eq!(strip_think_block(raw), Some("the actual answer".to_string()));
    }

    #[test]
    fn passes_through_text_with_no_think_block() {
        let raw = "just the answer, no think tags";
        assert_eq!(strip_think_block(raw), Some(raw.to_string()));
    }

    #[test]
    fn returns_none_for_truncated_think_block() {
        let raw = "<think>reasoning that never finished because generation was cut off";
        assert_eq!(strip_think_block(raw), None);
    }
}
