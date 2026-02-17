import React, { useState, useRef, useEffect } from "react";
import {
  Input,
  Button,
  Space,
  Alert,
  Spin,
  Empty,
  Card,
  Avatar,
  Tooltip,
} from "antd";
import {
  SendOutlined,
  RobotOutlined,
  UserOutlined,
  WarningOutlined,
} from "@ant-design/icons";
import { useChat } from "../hooks/useChat";
import "./ChatInterface.css";

export interface ChatInterfaceProps {
  sessionId: string;
  conversationSummary?: string;
  title?: string;
  onStateChange?: (state: any) => void;
}

/**
 * ChatInterface component for interactive conversation with the LLM
 * Displays message history and provides input for new messages
 */
export function ChatInterface({
  sessionId,
  conversationSummary,
  title = "Ask Follow-Up Questions",
  onStateChange,
}: ChatInterfaceProps) {
  const [inputValue, setInputValue] = useState("");
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const { messages, loading, error, tokenWarning, sessionHandoff, sendMessage, clearMessages } =
    useChat(sessionId, conversationSummary);

  // Scroll to bottom when new messages arrive
  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  // Notify parent of state changes
  useEffect(() => {
    if (onStateChange) {
      onStateChange({ tokenWarning, sessionHandoff, messageCount: messages.length });
    }
  }, [messages, tokenWarning, sessionHandoff, onStateChange]);

  const handleSendMessage = async () => {
    if (!inputValue.trim()) return;

    const message = inputValue;
    setInputValue("");

    try {
      await sendMessage(message);
    } catch (err) {
      console.error("Failed to send message:", err);
    }
  };

  const handleKeyPress = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter" && !e.shiftKey && !loading) {
      e.preventDefault();
      handleSendMessage();
    }
  };

  return (
    <Card
      className="chat-interface"
      title={
        <span>
          <RobotOutlined style={{ marginRight: "8px" }} />
          {title}
        </span>
      }
      extra={
        messages.length > 0 && (
          <Button type="text" size="small" onClick={clearMessages}>
            Clear
          </Button>
        )
      }
    >
      {/* Warnings */}
      {error && (
        <Alert
          message="Error"
          description={error}
          type="error"
          showIcon
          closable
          style={{ marginBottom: "16px" }}
        />
      )}

      {tokenWarning && (
        <Alert
          message="Token Budget Warning"
          description="You're using more than 50% of your token budget. Session may handoff to new conversation soon."
          type="warning"
          icon={<WarningOutlined />}
          showIcon
          style={{ marginBottom: "16px" }}
        />
      )}

      {sessionHandoff && (
        <Alert
          message="Session Handoff"
          description="Your session exceeded token budget and has been handed off to a new conversation with context summary."
          type="info"
          showIcon
          style={{ marginBottom: "16px" }}
        />
      )}

      {/* Message History */}
      <div className="chat-messages">
        {messages.length === 0 ? (
          <Empty
            description="No messages yet"
            style={{ marginTop: "40px", marginBottom: "40px" }}
          />
        ) : (
          messages.map((message) => (
            <div
              key={message.id}
              className={`chat-message chat-message-${message.role}`}
            >
              <div className="chat-message-header">
                <Avatar
                  icon={
                    message.role === "user" ? (
                      <UserOutlined />
                    ) : (
                      <RobotOutlined />
                    )
                  }
                  style={{
                    backgroundColor:
                      message.role === "user" ? "#1890ff" : "#52c41a",
                  }}
                />
                <span className="chat-message-role">
                  {message.role === "user" ? "You" : "Assistant"}
                </span>
                <Tooltip title={message.timestamp.toLocaleTimeString()}>
                  <span className="chat-message-time">
                    {message.timestamp.toLocaleTimeString([], {
                      hour: "2-digit",
                      minute: "2-digit",
                    })}
                  </span>
                </Tooltip>
              </div>
              <div className="chat-message-content">{message.content}</div>
            </div>
          ))
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Input Area */}
      <div className="chat-input-area" style={{ marginTop: "16px" }}>
        <Space.Compact style={{ width: "100%" }}>
          <Input
            placeholder="Ask a follow-up question..."
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            onKeyPress={handleKeyPress}
            disabled={loading}
            autoFocus
          />
          <Spin spinning={loading} style={{ marginLeft: "8px" }}>
            <Button
              type="primary"
              icon={<SendOutlined />}
              onClick={handleSendMessage}
              disabled={!inputValue.trim() || loading}
            >
              Send
            </Button>
          </Spin>
        </Space.Compact>
      </div>

      {/* Helper Text */}
      <div style={{ marginTop: "12px", fontSize: "12px", color: "#999" }}>
        Tip: Press Shift+Enter for new line, Enter to send
      </div>
    </Card>
  );
}
