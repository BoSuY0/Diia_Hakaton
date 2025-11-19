import React, { useEffect, useState } from 'react';
import mammoth from 'mammoth';

export const PreviewDrawer = ({ isOpen, onClose, docBlob }) => {
    const [htmlContent, setHtmlContent] = useState('');
    const [loading, setLoading] = useState(false);

    useEffect(() => {
        if (isOpen && docBlob) {
            setLoading(true);
            const reader = new FileReader();
            reader.onload = async (event) => {
                try {
                    const arrayBuffer = event.target.result;
                    const result = await mammoth.convertToHtml({ arrayBuffer });
                    setHtmlContent(result.value);
                } catch (e) {
                    console.error("Mammoth conversion failed", e);
                    setHtmlContent('<p style="color:red">Не вдалося відобразити документ.</p>');
                } finally {
                    setLoading(false);
                }
            };
            reader.readAsArrayBuffer(docBlob);
        }
    }, [isOpen, docBlob]);

    if (!isOpen) return null;

    return (
        <>
            <div className="drawer-overlay" onClick={onClose} />
            <div className={`preview-drawer ${isOpen ? 'open' : ''}`}>
                <div className="drawer-header">
                    <div className="drawer-title">Попередній перегляд</div>
                    <button className="close-btn" onClick={onClose}>&times;</button>
                </div>
                <div className="drawer-content">
                    {loading ? (
                        <div style={{ textAlign: 'center', padding: 20 }}>Завантаження документу...</div>
                    ) : (
                        <div
                            className="document-paper"
                            dangerouslySetInnerHTML={{ __html: htmlContent }}
                        />
                    )}
                </div>
            </div>
        </>
    );
};
