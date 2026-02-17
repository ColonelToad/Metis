import { invoke } from "@tauri-apps/api/core";
import { useState, useCallback } from "react";

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: Date;
}

export interface ChatResponse {
  message: string;
  session_id: string;
  token_warning: boolean;
  session_handoff: boolean;
}

export interface UseChatState {
  messages: ChatMessage[];
  loading: boolean;
  error: string | null;
  tokenWarning: boolean;
  sessionHandoff: boolean;
}

/**
 * Hook for managing chat interactions with the LLM
 * Maintains conversation history and handles message sending
 */
export function useChat(
  sessionId: string,
  conversationSummary?: string
) {
  const [state, setState] = useState<UseChatState>({
    messages: [],
    loading: false,
    error: null,
    tokenWarning: false,
    sessionHandoff: false,
  });

  const addMessage = useCallback((role: "user" | "assistant", content: string) => {
    setState((prev) => ({
      ...prev,
      messages: [
        ...prev.messages,
        {
          id: `${Date.now()}-${Math.random()}`,
          role,
          content,
          timestamp: new Date(),
        },
      ],
    }));
  }, []);

  const sendMessage = useCallback(
    async (userMessage: string) => {
      // Add user message to local state
      addMessage("user", userMessage);

      setState((prev) => ({
        ...prev,
        loading: true,
        error: null,
      }));

      try {
        // Call backend chat command
        const response = await invoke<ChatResponse>("chat_with_llm", {
          session_id: sessionId,
          user_message: userMessage,
          conversation_summary: conversationSummary,
        });

        // Add assistant response
        addMessage("assistant", response.message);

        // Update token tracking flags
        setState((prev) => ({
          ...prev,
          loading: false,
          tokenWarning: response.token_warning,
          sessionHandoff: response.session_handoff,
        }));

        return response.message;
      } catch (err) {
        const errorMessage =
          err instanceof Error ? err.message : String(err);

        setState((prev) => ({
          ...prev,
          loading: false,
          error: errorMessage,
        }));

        throw err;
      }
    },
    [sessionId, conversationSummary, addMessage]
  );

  const clearMessages = useCallback(() => {
    setState((prev) => ({
      ...prev,
      messages: [],
      error: null,
    }));
  }, []);

  return {
    ...state,
    sendMessage,
    clearMessages,
  };
}
