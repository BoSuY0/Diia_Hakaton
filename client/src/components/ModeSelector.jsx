import React from 'react';

export function ModeSelector({ onSelect }) {
    return (
        <div>
            <h2 className="step-title">Як ви хочете заповнити договір?</h2>
            <div className="selection-grid">
                <div className="selection-card" onClick={() => onSelect('single')}>
                    <h3>Тільки свою частину</h3>
                    <p>Я заповню свої дані, а інша сторона заповнить свої пізніше.</p>
                </div>
                <div className="selection-card" onClick={() => onSelect('full')}>
                    <h3>За обидві сторони</h3>
                    <p>Я маю всі дані і заповню договір повністю.</p>
                </div>
                <div className="selection-card ai-card" onClick={() => onSelect('ai')}>
                    <h3>Через AI-асистента</h3>
                    <p>Допоможіть мені заповнити договір у режимі чату.</p>
                </div>
            </div>
        </div>
    );
}
