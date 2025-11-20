import React from 'react';

export const InputField = ({ label, placeholder, value, onChange, type = "text", required = false }) => (
    <div className="input-group">
        <label className="input-label">
            {label}
            {required && <span className="required-indicator">*</span>}
            {!required && <span className="optional-indicator">(опційно)</span>}
        </label>
        <input
            className="text-input"
            type={type}
            placeholder={placeholder}
            value={value || ''}
            onChange={(e) => onChange(e.target.value)}
        />
    </div>
);
