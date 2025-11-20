import React from 'react';

export function RoleSelector({ onSelect, takenRoles = [] }) {
    return (
        <div>
            <h2 className="step-title">Хто ви у цьому договорі?</h2>
            <div className="selection-grid">
                <div
                    className={`selection-card ${takenRoles.includes('lessor') ? 'disabled' : ''}`}
                    onClick={() => !takenRoles.includes('lessor') && onSelect('lessor')}
                    style={{ opacity: takenRoles.includes('lessor') ? 0.5 : 1, cursor: takenRoles.includes('lessor') ? 'not-allowed' : 'pointer' }}
                >
                    <h3>Орендодавець</h3>
                    <p>{takenRoles.includes('lessor') ? '(Вже заповнено)' : 'Власник житла'}</p>
                </div>
                <div
                    className={`selection-card ${takenRoles.includes('lessee') ? 'disabled' : ''}`}
                    onClick={() => !takenRoles.includes('lessee') && onSelect('lessee')}
                    style={{ opacity: takenRoles.includes('lessee') ? 0.5 : 1, cursor: takenRoles.includes('lessee') ? 'not-allowed' : 'pointer' }}
                >
                    <h3>Орендар</h3>
                    <p>{takenRoles.includes('lessee') ? '(Вже заповнено)' : 'Той, хто винаймає житло'}</p>
                </div>
            </div>
        </div>
    );
}
