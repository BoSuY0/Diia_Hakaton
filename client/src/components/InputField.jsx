import React from 'react';

export const InputField = ({ label, placeholder, value, onChange, onBlur, type = "text", required = false, disabled = false, error = null }) => (
    <div className={`input-group ${error ? 'has-error' : ''}`}>
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
            onBlur={onBlur}
            disabled={disabled}
        />
        {error && <div className="input-error">{error}</div>}
    </div>
);
