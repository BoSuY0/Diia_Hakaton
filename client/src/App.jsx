import React, { useEffect, useState, useCallback } from 'react';
import './App.css';
import { api } from './api';
import { SectionCard } from './components/SectionCard';
import { InputField } from './components/InputField';
import { PreviewDrawer } from './components/PreviewDrawer';

// Simple debounce utility
const debounce = (func, wait) => {
  let timeout;
  return (...args) => {
    clearTimeout(timeout);
    timeout = setTimeout(() => func(...args), wait);
  };
};

function App() {
  const [sessionId, setSessionId] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [showPreview, setShowPreview] = useState(false);
  const [previewBlob, setPreviewBlob] = useState(null);
  const [schema, setSchema] = useState(null);

  // We store form data in a flat key-value map for easy access, 
  // though the schema also holds values.
  // Actually, we can just update the schema state or keep a separate values map.
  // A separate values map is cleaner for React inputs.
  const [formValues, setFormValues] = useState({});

  // Initialize session
  useEffect(() => {
    const init = async () => {
      try {
        const session = await api.createSession();
        const sid = session.session_id;
        setSessionId(sid);

        // Setup context (defaults)
        await api.setCategory(sid, 'lease_living');
        await api.setTemplate(sid, 'lease_flat');

        // Explicitly set defaults in backend to ensure builder sees them
        await api.setPartyContext(sid, 'lessor', 'individual');
        await api.setPartyContext(sid, 'lessee', 'individual');

        // Initial fetch of schema
        await fetchSchema(sid);

        setIsLoading(false);
      } catch (e) {
        console.error("Failed to init session", e);
        alert("Failed to initialize session. Check backend.");
        setIsLoading(false);
      }
    };
    init();
  }, []);

  const fetchSchema = async (sid) => {
    try {
      const { data } = await api.getSchema(sid, 'all', 'values');
      setSchema(data);

      // Populate initial form values from schema
      const initialValues = {};

      // Parties
      data.parties.forEach(party => {
        party.fields.forEach(field => {
          initialValues[field.key] = field.value || '';
        });
      });

      // Contract
      data.contract.fields.forEach(field => {
        initialValues[field.key] = field.value || '';
      });

      setFormValues(prev => ({ ...prev, ...initialValues }));
    } catch (e) {
      console.error("Failed to fetch schema", e);
    }
  };

  // Debounced API call
  const debouncedUpsert = useCallback(
    debounce(async (sid, field, value, role) => {
      if (!sid) return;
      try {
        await api.upsertField(sid, field, value, role);
        console.log(`Saved ${field} (${role || 'contract'})`);
      } catch (e) {
        console.error(`Failed to save ${field}`, e);
      }
    }, 500),
    []
  );

  const handleChange = (key, fieldName, value, role = null) => {
    setFormValues(prev => ({ ...prev, [key]: value }));
    debouncedUpsert(sessionId, fieldName, value, role);
  };

  const handlePartyTypeChange = async (role, newType) => {
    if (!sessionId) return;
    try {
      setIsLoading(true);
      // We need to tell backend about the type change.
      // Currently we don't have a direct endpoint for this in the plan, 
      // but we can use the chat endpoint or upsert a dummy field?
      // Actually, the best way is to use the chat endpoint to "set context".
      // "Set lessor to company"

      await api.setPartyContext(sessionId, role, newType);

      // Refresh schema to get new fields
      await fetchSchema(sessionId);
      setIsLoading(false);
    } catch (e) {
      console.error("Failed to change party type", e);
      setIsLoading(false);
    }
  };

  const handlePreview = async () => {
    if (!sessionId) return;
    try {
      setIsLoading(true);
      const response = await api.getPreview(sessionId);
      const blob = new Blob([response.data], { type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' });
      setPreviewBlob(blob);
      setShowPreview(true);
      setIsLoading(false);
    } catch (e) {
      console.error("Preview failed", e);
      alert("Preview failed. Ensure all required fields are filled.");
      setIsLoading(false);
    }
  };

  const handleOrder = async () => {
    if (!sessionId) return;
    try {
      setIsLoading(true);
      const res = await api.orderContract(sessionId);
      if (res.ok) {
        alert("Договір успішно сформовано! Завантаження почнеться автоматично.");
        // Trigger download
        window.location.href = `${api.API_URL}${res.download_url}`;
      }
      setIsLoading(false);
    } catch (e) {
      console.error("Order failed", e);
      alert("Order failed: " + (e.response?.data?.detail || e.message));
      setIsLoading(false);
    }
  };

  return (
    <div className="app-container">
      {isLoading && <div className="loading-overlay">Loading...</div>}

      <PreviewDrawer
        isOpen={showPreview}
        onClose={() => setShowPreview(false)}
        docBlob={previewBlob}
      />

      <header className="header">
        <button className="back-button">←</button>
        <h1 className="title">Договір оренди житла</h1>
      </header>

      {schema && schema.parties.map(party => (
        <SectionCard
          key={party.role}
          title={party.label}
          subtitle={`Вкажіть дані для сторони "${party.label}"`}
        >
          <div style={{ marginBottom: 16 }}>
            <label className="input-label">Тип особи</label>
            <select
              className="text-input"
              value={party.person_type}
              onChange={(e) => handlePartyTypeChange(party.role, e.target.value)}
            >
              {party.allowed_types.map(t => (
                <option key={t.value} value={t.value}>{t.label}</option>
              ))}
            </select>
          </div>

          {party.fields.map(field => (
            <InputField
              key={field.key}
              label={field.label}
              placeholder={field.placeholder}
              value={formValues[field.key]}
              onChange={(val) => handleChange(field.key, field.field_name, val, party.role)}
              required={field.required}
            />
          ))}
        </SectionCard>
      ))}

      {schema && (
        <SectionCard
          title={schema.contract.title}
          subtitle={schema.contract.subtitle}
        >
          {schema.contract.fields.map(field => (
            <InputField
              key={field.key}
              label={field.label}
              placeholder={field.placeholder}
              value={formValues[field.key]}
              onChange={(val) => handleChange(field.key, field.field_name, val, null)}
              required={field.required}
            />
          ))}
        </SectionCard>
      )}

      <div className="info-banner">
        <div className="info-icon">i</div>
        <span>Заповніть усі необхідні поля договору.</span>
      </div>

      <div className="actions">
        <button className="btn-primary" onClick={handleOrder}>
          Замовити договір
        </button>
        <button className="btn-secondary" onClick={handlePreview}>
          Попередній перегляд
        </button>
      </div>
    </div>
  );
}

export default App;
