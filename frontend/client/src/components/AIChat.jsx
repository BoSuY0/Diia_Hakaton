import React, { useState, useEffect, useRef } from "react";
import { api } from "../api";

const SUGGESTED_QUESTIONS = [
  "Привіт! Допоможи, будь ласка, заповнити договір NDA",
];

export const AIChat = ({ sessionId, userId, onBack }) => {
  const [messages, setMessages] = useState([
    {
      role: "system",
      content:
        "Вітаю! Я ваш AI-асистент. З яким договором можу допомогти сьогодні?",
    },
  ]);
  const [input, setInput] = useState("");
  const [isSending, setIsSending] = useState(false);
  const [showSuggestions, setShowSuggestions] = useState(true);
  const messagesEndRef = useRef(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  const handleSend = async (messageText) => {
    const textToSend = messageText || input.trim();
    if (!textToSend) return;

    const userMsg = { role: "user", content: textToSend };
    setMessages((prev) => [...prev, userMsg]);
    setInput("");
    setIsSending(true);
    setShowSuggestions(false);

    try {
      const res = await api.chat(sessionId, userMsg.content, userId);
      const assistantMsg = { role: "assistant", content: res.reply };
      setMessages((prev) => [...prev, assistantMsg]);
    } catch (e) {
      console.error("Chat failed", e);
      setMessages((prev) => [
        ...prev,
        {
          role: "system",
          content: "Вибачте, сталася помилка. Спробуйте ще раз.",
        },
      ]);
    } finally {
      setIsSending(false);
    }
  };

  const handleSuggestionClick = (question) => {
    handleSend(question);
  };

  return (
    <div className="chat-container">
      <div className="chat-header">
        <button className="back-button-small" onClick={onBack}>
          ← Назад
        </button>
        <span className="chat-title">AI Помічник</span>
      </div>

      <div className="chat-messages">
        {messages.map((m, idx) => (
          <div
            key={`${m.role}-${idx}-${
              typeof m.content === "string" ? m.content.slice(0, 10) : ""
            }`}
          >
            <div className={`chat-message ${m.role}`}>
              <div className="message-bubble">{m.content}</div>
            </div>
          </div>
        ))}

        {showSuggestions && messages.length === 1 && (
          <div className="suggested-questions">
            {SUGGESTED_QUESTIONS.map((question, idx) => (
              <button
                key={idx}
                className="suggestion-button"
                onClick={() => handleSuggestionClick(question)}
                disabled={isSending}
              >
                {question}
              </button>
            ))}
          </div>
        )}

        {isSending && (
          <div className="chat-message assistant">
            <div className="message-bubble typing">
              <span>.</span>
              <span>.</span>
              <span>.</span>
            </div>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      <div className="chat-input-area">
        <input
          type="text"
          className="chat-input"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && handleSend()}
          placeholder="Напишіть повідомлення..."
          disabled={isSending}
        />
        <button
          className="send-button"
          onClick={() => handleSend()}
          disabled={isSending || !input.trim()}
        >
          ➤
        </button>
      </div>
    </div>
  );
};
