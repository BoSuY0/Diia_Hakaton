import React from 'react';

export const SectionCard = ({ title, subtitle, children }) => (
    <div className="card">
        <h3 className="card-title">{title}</h3>
        <p className="card-subtitle">{subtitle}</p>
        {children}
    </div>
);
