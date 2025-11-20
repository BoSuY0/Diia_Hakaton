import React, { useEffect, useState } from 'react';
import { api } from '../api';

export function CategorySelector({ onSelect }) {
    const [categories, setCategories] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);

    useEffect(() => {
        api.getCategories()
            .then(data => {
                if (Array.isArray(data)) {
                    setCategories(data);
                } else {
                    console.error("Categories data is not an array:", data);
                    setCategories([]);
                }
                setLoading(false);
            })
            .catch(err => {
                console.error("Failed to load categories:", err);
                setError("Не вдалося завантажити категорії.");
                setLoading(false);
            });
    }, []);

    if (loading) return <div>Завантаження категорій...</div>;
    if (error) return <div className="error-state">{error}</div>;

    return (
        <div className="selection-grid">
            {categories.map(cat => (
                <div key={cat.id} className="selection-card" onClick={() => onSelect(cat.id)}>
                    <h3>{cat.label}</h3>
                    {/* <p>{cat.description}</p> */}
                </div>
            ))}
        </div>
    );
}
