import React, { useState, useEffect, useRef } from 'react';
import { api } from '../api';

export const AIChat = ({ sessionId, userId, onBack }) => {
    const [messages, setMessages] = useState([
        { role: 'system', content: 'Привіт! Я ваш AI-помічник. Я можу допомогти вам заповнити договір. Просто напишіть мені дані або запитайте щось.' }
    ]);
    const [input, setInput] = useState('');
    const [isSending, setIsSending] = useState(false);
    const messagesEndRef = useRef(null);

    const scrollToBottom = () => {
        messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
    };

    useEffect(() => {
        scrollToBottom();
    }, [messages]);

    const handleSend = async () => {
        if (!input.trim()) return;

        const userMsg = { role: 'user', content: input };
        setMessages(prev => [...prev, userMsg]);
        setInput('');
        setIsSending(true);

        try {
            const res = await api.chat(sessionId, userMsg.content, userId);
            setMessages(prev => [...prev, { role: 'assistant', content: res.reply }]);
        } catch (e) {
            console.error("Chat failed", e);
            setMessages(prev => [...prev, { role: 'system', content: 'Вибачте, сталася помилка. Спробуйте ще раз.' }]);
        } finally {
            setIsSending(false);
        }
    };

    return (
        <div className="chat-container">
            <div className="chat-header">
                <button className="back-button-small" onClick={onBack}>← Назад</button>
                <span className="chat-title">AI Помічник</span>
            </div>

            <div className="chat-messages">
                {messages.map((m, idx) => (
                    <div key={`${m.role}-${idx}-${m.content.slice(0,10)}`} className={`chat-message ${m.role}`}>
                        <div className="message-bubble">
                            {m.content}
                        </div>
                    </div>
                ))}
                {isSending && (
                    <div className="chat-message assistant">
                        <div className="message-bubble typing">
                            <span>.</span><span>.</span><span>.</span>
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
                    onChange={e => setInput(e.target.value)}
                    onKeyDown={e => e.key === 'Enter' && !e.shiftKey && handleSend()}
                    placeholder="Напишіть повідомлення..."
                    disabled={isSending}
                />
                <button className="send-button" onClick={handleSend} disabled={isSending || !input.trim()}>
                    ➤
                </button>
            </div>
        </div>
    );
};
