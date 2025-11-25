import React, { useMemo, useState } from 'react';

const buildShareUrl = (sessionId, role) => {
  if (!sessionId) return '';
  const url = new URL(window.location.href);
  url.searchParams.set('session_id', sessionId);
  if (role) {
    url.searchParams.set('role', role);
  } else {
    url.searchParams.delete('role');
  }
  url.pathname = '/';
  return url.toString();
};

export function ShareLinkCard({ sessionId, parties = [], userId }) {
  const [copiedRole, setCopiedRole] = useState(null);

  const roles = useMemo(() => parties || [], [parties]);
  if (!sessionId || roles.length === 0) return null;

  const handleCopy = async (role) => {
    const link = buildShareUrl(sessionId, role);
    try {
      await navigator.clipboard.writeText(link);
      setCopiedRole(role || 'any');
      setTimeout(() => setCopiedRole(null), 1500);
    } catch (err) {
      // Fallback prompt for older browsers
      window.prompt('Скопіюйте посилання та надішліть іншій стороні', link);
    }
  };

  return (
    <div className="card share-card">
      <div className="share-card__header">
        <div>
          <p className="card-title" style={{ marginBottom: 4 }}>Поділитися посиланням</p>
          <p className="card-subtitle" style={{ marginBottom: 0 }}>
            Скопіюйте лінк для контрагента. URL вже містить session_id та роль.
          </p>
        </div>
        <span className="pill pill-muted">multi-user</span>
      </div>

      <div className="share-roles">
        {roles.map((party) => {
          const isMine = party.claimed_by === userId;
          const isFree = !party.claimed_by;
          const status = isMine ? 'Ваша роль' : isFree ? 'Вільна' : 'Зайнята іншою стороною';
          const statusClass = isMine ? 'pill-positive' : isFree ? 'pill-neutral' : 'pill-warning';
          const copied = copiedRole === party.role;

          return (
            <div key={party.role} className="share-role-row">
              <div>
                <div className="share-role-title">{party.label || party.role}</div>
                <div className="pill-row">
                  <span className={`pill ${statusClass}`}>{status}</span>
                </div>
              </div>
              <button
                className="btn-tertiary"
                onClick={() => handleCopy(party.role)}
                title="Скопіювати посилання для цієї ролі"
              >
                {copied ? 'Скопійовано' : 'Копіювати лінк'}
              </button>
            </div>
          );
        })}
      </div>
    </div>
  );
}
