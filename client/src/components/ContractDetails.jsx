import React, { useEffect, useState } from 'react';
import { api } from '../api';

export const ContractDetails = ({ sessionId, clientId, onBack, onEdit }) => {
    const [info, setInfo] = useState(null);
    const [isLoading, setIsLoading] = useState(true);
    const [isSigning, setIsSigning] = useState(false);

    const load = async () => {
        try {
            setIsLoading(true);
            const res = await api.getContract(sessionId);
            setInfo(res.data);
        } catch (e) {
            console.error("Failed to load contract info", e);
        } finally {
            setIsLoading(false);
        }
    };

    useEffect(() => {
        load();
        // Poll for updates every 5 seconds? Or use SSE?
        // For simplicity, poll.
        const interval = setInterval(load, 5000);
        return () => clearInterval(interval);
    }, [sessionId]);

    const handleSign = async () => {
        try {
            setIsSigning(true);
            await api.signContract(sessionId, clientId);
            await load(); // Reload to update status
            alert("Підписано успішно!");
        } catch (e) {
            console.error("Sign failed", e);
            const errorMsg = e.response?.data?.detail || e.message || "Failed to sign";
            alert(`Помилка підпису: ${errorMsg}`);
        } finally {
            setIsSigning(false);
        }
    };

    if (isLoading && !info) return <div>Loading...</div>;
    if (!info) return <div>Failed to load info</div>;

    // Determine my role
    let myRole = null;
    if (info.party_users) {
        for (const [role, uid] of Object.entries(info.party_users)) {
            if (uid === clientId) {
                myRole = role;
                break;
            }
        }
    }

    const mySignature = myRole ? info.signatures?.[myRole] : false;
    const isFullySigned = info.is_signed;
    const canEdit = !isFullySigned && onEdit;  // Можна редагувати якщо не повністю підписано

    return (
        <div className="contract-details">
            <h2 className="card-title" style={{ marginBottom: 24 }}>Деталі договору</h2>
            <div className="details-card">
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
                    {info.party_users && Object.entries(info.party_users).map(([role, uid]) => {
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
            </div>
            <button className="btn-secondary" onClick={onBack} style={{ marginTop: 24 }}>
                ← Назад
            </button>
        </div>
    );
};
