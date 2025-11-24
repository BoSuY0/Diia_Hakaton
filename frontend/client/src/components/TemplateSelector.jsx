import React, { useEffect, useState } from 'react';
import { api } from '../api';

export function TemplateSelector({ categoryId, onSelect }) {
    const [templates, setTemplates] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);

    useEffect(() => {
        if (categoryId) {
            setLoading(true);
            api.getTemplates(categoryId)
                .then(data => {
                    if (Array.isArray(data)) {
                        setTemplates(data);
                    } else if (data.templates && Array.isArray(data.templates)) {
                        setTemplates(data.templates);
                    } else {
                        console.error("Templates data is not an array:", data);
                        setTemplates([]);
                    }
                    setLoading(false);
                })
                .catch(err => {
                    console.error("Failed to load templates:", err);
                    setError("Не вдалося завантажити шаблони.");
                    setLoading(false);
                });
        }
    }, [categoryId]);

    if (loading) return <div>Завантаження шаблонів...</div>;
    if (error) return <div className="error-state">{error}</div>;

    return (
        <div>
            <div className="selection-grid">
                {templates.length > 0 ? (
                    templates.map(tmpl => (
                        <div key={tmpl.id} className="selection-card" onClick={() => onSelect(tmpl)}>
                            <h3>{tmpl.name}</h3>
                        </div>
                    ))
                ) : (
                    <div>Немає доступних шаблонів для цієї категорії.</div>
                )}
            </div>
        </div>
    );
}
