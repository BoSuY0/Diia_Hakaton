import React, { useEffect, useState } from 'react';
import { api } from '../api';

export const Dashboard = ({ userId, onSelectSession, onBack }) => {
    const [sessions, setSessions] = useState([]);
    const [isLoading, setIsLoading] = useState(true);

    useEffect(() => {
        const load = async () => {
            try {
                const data = await api.getMySessions(userId);
                setSessions(data);
            } catch (e) {
                console.error("Failed to load sessions", e);
            } finally {
                setIsLoading(false);
            }
        };
        load();
    }, [userId]);

    if (isLoading) return <div>Loading...</div>;

    return (
        <div className="dashboard">
            <h2 className="card-title" style={{ marginBottom: 24 }}>Мої договори</h2>
            {sessions.length === 0 ? (
                <div className="card" style={{ textAlign: 'center', padding: 40 }}>
                    <p style={{ color: '#6B7280' }}>У вас поки немає договорів.</p>
                </div>
            ) : (
                <div className="session-list">
                    {sessions.map(s => (
                        <div key={s.session_id} className="session-card" onClick={() => onSelectSession(s.session_id)}>
                            <div className="session-header">
                                <div>
                                    <div className="session-title">{s.title || "Без назви"}</div>
                                    <div className="session-id">ID: {s.session_id?.substring(0, 8) || 'N/A'}</div>
                                </div>
                                <div className={`status-badge ${s.state}`}>
                                    {s.is_signed ? "Підписано" : (s.state || 'draft').replace('_', ' ')}
                                </div>
                            </div>
                            <div className="session-meta">
                                <span>📅 {new Date(s.updated_at).toLocaleDateString('uk-UA', { day: 'numeric', month: 'long', hour: '2-digit', minute: '2-digit' })}</span>
                            </div>
                        </div>
                    ))}
                </div>
            )}
            <button className="btn-secondary" onClick={onBack} style={{ marginTop: 20 }}>
                ← Назад
            </button>
        </div>
    );
};
