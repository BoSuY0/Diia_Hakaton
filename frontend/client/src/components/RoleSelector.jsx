import React from 'react';

export function RoleSelector({ onSelect, parties = [], takenRoles = [], myRoles = [], isFullMode = false }) {
    const heading = isFullMode ? "Оберіть вашу основну роль" : "Хто ви у цьому договорі?";

    return (
        <div>
            <h2 className="step-title">{heading}</h2>
            <div className="selection-grid">
                {parties.map((party) => {
                    const isTaken = takenRoles.includes(party.role);
                    const isMine = myRoles.includes(party.role);
                    const disabled = !isFullMode && isTaken && !isMine;
                    const subtitle = isMine
                        ? "Ця роль вже за вами"
                        : isTaken
                            ? "(Вже заповнено)"
                            : "Обрати роль";

                    return (
                        <div
                            key={party.role}
                            className={`selection-card ${disabled ? 'disabled' : ''} ${isMine ? 'selected' : ''}`}
                            onClick={() => !disabled && onSelect(party.role)}
                            style={{
                                opacity: disabled ? 0.5 : 1,
                                cursor: disabled ? 'not-allowed' : 'pointer'
                            }}
                        >
                            <h3>{party.label || party.role}</h3>
                            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 8 }}>
                                <span className={`pill ${isMine ? 'pill-positive' : isTaken ? 'pill-warning' : 'pill-neutral'}`}>
                                    {isMine ? 'Ваша роль' : isTaken ? 'Зайнята іншою стороною' : 'Вільна роль'}
                                </span>
                            </div>
                            <p style={{ marginTop: 8 }}>{subtitle}</p>
                        </div>
                    );
                })}
            </div>
        </div>
    );
}
