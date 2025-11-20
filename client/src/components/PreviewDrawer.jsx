import { useState, useEffect } from 'react';
import { X, Download } from 'lucide-react';
import { api } from '../api';

export default function PreviewDrawer({ isOpen, onClose, sessionId }) {
    const [htmlContent, setHtmlContent] = useState(null);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);

    useEffect(() => {
        if (isOpen && sessionId) {
            fetchPreview();
        }
    }, [isOpen, sessionId]);

    const fetchPreview = async () => {
        setLoading(true);
        setError(null);
        try {
            // Use api.API_URL to ensure correct host (e.g. when accessing from mobile via IP)
            const response = await fetch(`${api.API_URL}/sessions/${sessionId}/contract/preview`);
            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.detail || 'Preview failed');
            }
            const html = await response.text();
            setHtmlContent(html);
        } catch (err) {
            console.error('Preview error:', err);
            setError(err.message);
        } finally {
            setLoading(false);
        }
    };

    const handleDownload = () => {
        window.open(api.getDownloadUrl(sessionId), '_blank');
    };

    if (!isOpen) return null;

    return (
        <div className="drawer-overlay" onClick={onClose}>
            <div className="drawer-container" onClick={e => e.stopPropagation()}>
                <div className="drawer-header">
                    <h2>Попередній перегляд</h2>
                    <button className="close-btn" onClick={onClose}>
                        <X size={24} />
                    </button>
                </div>

                <div className="drawer-content">
                    {loading ? (
                        <div className="loading-state">Завантаження документа...</div>
                    ) : error ? (
                        <div className="error-state">
                            <p>Помилка: {error}</p>
                            <button onClick={fetchPreview}>Спробувати знову</button>
                        </div>
                    ) : (
                        <div className="html-preview-container">
                            <iframe
                                srcDoc={htmlContent}
                                title="Document Preview"
                                style={{ width: '100%', height: '100%', border: 'none', background: 'white' }}
                            />
                        </div>
                    )}
                </div>

                <div className="drawer-footer">
                    <button className="download-btn" onClick={handleDownload} disabled={loading || error}>
                        <Download size={20} style={{ marginRight: '8px' }} />
                        Завантажити PDF (Оригінал)
                    </button>
                </div>
            </div>
        </div>
    );
}
