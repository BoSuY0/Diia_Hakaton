import React, { useEffect, useState } from 'react';
import { api } from '../api';

export const ContractDetails = ({ sessionId, clientId, onBack, onEdit }) => {
    const [info, setInfo] = useState(null);
    const [isLoading, setIsLoading] = useState(true);
    const [isSigning, setIsSigning] = useState(false);
    const [activeTab, setActiveTab] = useState('info');
    const [history, setHistory] = useState(null);
    const [historyLoading, setHistoryLoading] = useState(false);
    const [historyError, setHistoryError] = useState(null);

    const load = async () => {
        try {
            setIsLoading(true);
            const res = await api.getContract(sessionId, clientId);
            setInfo(res.data);
        } catch (e) {
            console.error("Failed to load contract info", e);
        } finally {
            setIsLoading(false);
        }
    };

    const loadHistory = async () => {
        try {
            setHistoryLoading(true);
            setHistoryError(null);
            const data = await api.getHistory(sessionId, clientId);
            setHistory(data);
        } catch (e) {
            const detail = e?.response?.data?.detail;
            const msg = typeof detail === 'string' ? detail : detail?.message || e.message || 'Не вдалося отримати історію';
            setHistoryError(msg);
        } finally {
            setHistoryLoading(false);
        }
    };

    useEffect(() => {
        setHistory(null);
        setHistoryError(null);
        setActiveTab('info');
        load();
        const interval = setInterval(load, 5000);
        return () => clearInterval(interval);
    }, [sessionId]);

    useEffect(() => {
        if (activeTab === 'history' && !history && !historyLoading) {
            loadHistory();
        }
    }, [activeTab, history, historyLoading]);

    const formatTimestamp = (ts) => {
        try {
            return new Date(ts).toLocaleString('uk-UA');
        } catch (e) {
            return ts;
        }
    };

    const handleSign = async () => {
        try {
            setIsSigning(true);
            await api.signContract(sessionId, clientId);
            await load(); // Reload to update status
            await loadHistory();
            alert("Підписано успішно!");
        } catch (e) {
            console.error("Sign failed", e);
            const status = e.response?.status;
            const detail = e.response?.data?.detail;
            let friendly = typeof detail === 'string' ? detail : detail?.message || detail;
            if (status === 400) {
                friendly = "Договір ще не готовий до підпису. Перевірте обов'язкові поля.";
            } else if (status === 403) {
                friendly = "Ви не маєте права підписувати цей договір для поточної ролі.";
            } else if (status === 409) {
                friendly = "Договір змінився — перезберіть його перед підписом.";
            }
            alert(`Помилка підпису: ${friendly || e.message || "Не вдалося підписати"}`);
        } finally {
            setIsSigning(false);
        }
    };

    const renderHistory = () => {
        if (historyLoading) return <div>Завантаження історії...</div>;
        if (historyError) return <div className="info-text" style={{ color: '#DC2626' }}>Помилка: {historyError}</div>;
        if (!history) return <div className="info-text">Історія поки відсутня.</div>;

        const signEvents = [...(history.sign_history || [])].sort(
            (a, b) => new Date(b.timestamp) - new Date(a.timestamp)
        );

        const fieldEvents = Object.entries(history.all_data || {})
            .flatMap(([key, entry]) =>
                (entry.history || []).map(evt => ({ ...evt, key }))
            )
            .sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp))
            .slice(0, 12);

        return (
            <div className="history-grid">
                <div className="history-card">
                    <h3 className="card-title" style={{ marginBottom: 12 }}>Підписання</h3>
                    {signEvents.length === 0 ? (
                        <p className="info-text">Підписів ще немає.</p>
                    ) : signEvents.map((evt, idx) => (
                        <div key={`${evt.timestamp}-${idx}`} className="history-row">
                            <div className="history-meta">
                                <span className="history-pill">{(evt.roles || []).join(', ') || 'роль'}</span>
                                <span className="history-timestamp">{formatTimestamp(evt.timestamp)}</span>
                            </div>
                            <div className="history-detail">
                                Клієнт: {evt.client_id || 'N/A'} • Стан: {evt.state}
                            </div>
                        </div>
                    ))}
                </div>

                <div className="history-card">
                    <h3 className="card-title" style={{ marginBottom: 12 }}>Зміни полів</h3>
                    {fieldEvents.length === 0 ? (
                        <p className="info-text">Історію змін полів ще не зафіксовано.</p>
                    ) : fieldEvents.map((evt, idx) => (
                        <div key={`${evt.key}-${idx}`} className="history-row">
                            <div className="history-meta">
                                <span className="history-pill">{evt.role || '—'}</span>
                                <span className="history-timestamp">{formatTimestamp(evt.timestamp)}</span>
                            </div>
                            <div className="history-detail">
                                <strong>{evt.key}</strong>: {evt.value || '(порожньо)'} {evt.valid === false ? '⚠️' : '✅'}
                            </div>
                        </div>
                    ))}
                </div>
            </div>
        );
    };

    if (isLoading && !info) return <div>Loading...</div>;
    if (!info) return <div>Failed to load info</div>;

    // Determine my role based on server-side mapping (does not expose other users)
    const myRole = info.client_roles && info.client_roles.length > 0 ? info.client_roles[0] : null;

    const mySignature = myRole ? info.signatures?.[myRole] : false;
    const isFullySigned = info.is_signed;
    const canEdit = !isFullySigned && onEdit;  // Можна редагувати якщо не повністю підписано

    return (
        <div className="contract-details">
            <h2 className="card-title" style={{ marginBottom: 24 }}>Деталі договору</h2>
            <div className="details-card">
                <div className="tab-row">
                    <button
                        className={`tab-button ${activeTab === 'info' ? 'active' : ''}`}
                        onClick={() => setActiveTab('info')}
                    >
                        Статус
                    </button>
                    <button
                        className={`tab-button ${activeTab === 'history' ? 'active' : ''}`}
                        onClick={() => setActiveTab('history')}
                    >
                        Історія
                    </button>
                </div>

                {activeTab === 'history' ? (
                    renderHistory()
                ) : (
                    <>
                        <div className="detail-row">
                            <span className="detail-label">ID сесії</span>
                            <span className="detail-value" style={{ fontFamily: 'monospace' }}>{info.session_id}</span>
                        </div>
                        <div className="detail-row">
                            <span className="detail-label">Статус</span>
                            <span className={`status-badge ${info.status}`}>
                                {info.is_signed ? "Підписано" : info.status.replace('_', ' ')}
                            </span>
                        </div>

                        <div className="signatures-section">
                            <h3 className="card-title" style={{ fontSize: 16, marginBottom: 16 }}>Підписи сторін</h3>
                            {info.signatures && Object.keys(info.signatures).map((role) => {
                              const signed = info.signatures?.[role];
                              return (
                                <div key={role} className="signature-row">
                                  <span className="role-name">{role}</span>
                                  <span className={`signature-status ${signed ? 'signed' : 'pending'}`}>
                                    {signed ? "✅ Підписано" : "⏳ Очікується"}
                                  </span>
                                </div>
                              );
                            })}
                        </div>

                        <div className="actions-row" style={{ marginTop: 24, display: 'flex', gap: 12, flexDirection: 'column' }}>
                            {info.preview_url && (
                                <button className="btn-secondary" onClick={() => window.open(api.API_URL + info.preview_url, '_blank')} style={{ border: '1px solid #E5E7EB', borderRadius: 16, padding: 12 }}>
                                    👁️ Переглянути чернетку
                                </button>
                            )}

                            {/* Кнопка редагування - показується якщо договір НЕ повністю підписаний */}
                            {canEdit && (
                                <button className="btn-secondary" onClick={onEdit} style={{ border: '1px solid #3B82F6', color: '#3B82F6', borderRadius: 16, padding: 12 }}>
                                    ✏️ Редагувати договір
                                </button>
                            )}

                            {!mySignature && myRole && (
                                <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                                    <button
                                        className="btn-primary"
                                        onClick={handleSign}
                                        disabled={isSigning || (!info.can_build_contract && !info.document_ready)}
                                        title={(!info.can_build_contract && !info.document_ready) ? "Договір ще не готовий (очікується заповнення всіх полів)" : ""}
                                    >
                                        {isSigning ? "Підписання..." : "✍️ Підписати (КЕП/Дія.Підпис)"}
                                    </button>
                                    {(!info.can_build_contract && !info.document_ready) && (
                                        <p className="info-text" style={{ color: '#F59E0B', fontSize: '0.85em', textAlign: 'center' }}>
                                            ⚠️ Підписання стане доступним після заповнення всіх полів усіма сторонами.
                                        </p>
                                    )}
                                </div>
                            )}

                            {isFullySigned && info.document_url && (
                                <button className="btn-primary" onClick={() => window.open(api.API_URL + info.document_url, '_blank')} style={{ background: '#059669' }}>
                                    ⬇️ Завантажити оригінал (.docx)
                                </button>
                            )}

                            {!isFullySigned && (
                                <p className="info-text" style={{ color: '#6B7280', fontSize: '0.9em', textAlign: 'center', marginTop: 8 }}>
                                    Очікується підпис усіх сторін для завантаження оригіналу.
                                </p>
                            )}
                        </div>
                    </>
                )}
            </div>
            <button className="btn-secondary" onClick={onBack} style={{ marginTop: 24 }}>
                ← Назад
            </button>
        </div>
    );
};
