import React from 'react';

export function RoleSelector({ onSelect, takenRoles = [], isFullMode = false }) {
    // In Full Mode, we select the PRIMARY role (who is initiating), but we will fill both.
    // Or maybe we skip role selection in Full Mode?
    // Usually we still need to know "who am I" for the session context (owner).
    // Let's assume we select the "Main" role.

    return (
        <div>
            <h2 className="step-title">{isFullMode ? "Оберіть вашу основну роль" : "Хто ви у цьому договорі?"}</h2>
            <div className="selection-grid">
                <div
                    className={`selection-card ${!isFullMode && takenRoles.includes('lessor') ? 'disabled' : ''}`}
                    onClick={() => (isFullMode || !takenRoles.includes('lessor')) && onSelect('lessor')}
                    style={{
                        opacity: !isFullMode && takenRoles.includes('lessor') ? 0.5 : 1,
                        cursor: !isFullMode && takenRoles.includes('lessor') ? 'not-allowed' : 'pointer'
                    }}
                >
                    <h3>Орендодавець</h3>
                    <p>{!isFullMode && takenRoles.includes('lessor') ? '(Вже заповнено)' : 'Власник житла'}</p>
                </div>
                <div
                    className={`selection-card ${!isFullMode && takenRoles.includes('lessee') ? 'disabled' : ''}`}
                    onClick={() => (isFullMode || !takenRoles.includes('lessee')) && onSelect('lessee')}
                    style={{
                        opacity: !isFullMode && takenRoles.includes('lessee') ? 0.5 : 1,
                        cursor: !isFullMode && takenRoles.includes('lessee') ? 'not-allowed' : 'pointer'
                    }}
                >
                    <h3>Орендар</h3>
                    <p>{!isFullMode && takenRoles.includes('lessee') ? '(Вже заповнено)' : 'Той, хто винаймає житло'}</p>
                </div>
            </div>
        </div>
    );
}
