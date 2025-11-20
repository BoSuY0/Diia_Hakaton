import React, { useEffect, useState, useCallback } from 'react';
import './App.css';
import { api } from './api';
import { SectionCard } from './components/SectionCard';
import { InputField } from './components/InputField';
import PreviewDrawer from './components/PreviewDrawer';
import { CategorySelector } from './components/CategorySelector';
import { TemplateSelector } from './components/TemplateSelector';
import { ModeSelector } from './components/ModeSelector';
import { RoleSelector } from './components/RoleSelector';

// Simple debounce utility
const debounce = (func, wait) => {
  let timeout;
  return (...args) => {
    clearTimeout(timeout);
    timeout = setTimeout(() => func(...args), wait);
  };
};

function App() {
  // Steps: 'category' -> 'template' -> 'mode' -> 'role' -> 'form'
  const [step, setStep] = useState('category');

  const [sessionId, setSessionId] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [showPreview, setShowPreview] = useState(false);
  const [schema, setSchema] = useState(null);
  const [formValues, setFormValues] = useState({});
  const [takenRoles, setTakenRoles] = useState([]);

  // Selections
  const [selectedCategory, setSelectedCategory] = useState(null);
  const [selectedTemplate, setSelectedTemplate] = useState(null);
  const [selectedMode, setSelectedMode] = useState(null); // 'single', 'full', 'ai'
  const [selectedRole, setSelectedRole] = useState(null); // 'lessor', 'lessee'

  const [clientId] = useState(() => Math.random().toString(36).substring(7));
  const [isOnline, setIsOnline] = useState(navigator.onLine);

  // Initialize session on mount
  const initialized = React.useRef(false);
  useEffect(() => {
    if (initialized.current) return;
    initialized.current = true;

    const init = async () => {
      const params = new URLSearchParams(window.location.search);
      const sid = params.get('session_id');

      if (sid) {
        console.log("Found session_id in URL:", sid);
        setSessionId(sid);
        await restoreSession(sid);
      } else {
        try {
          const session = await api.createSession();
          setSessionId(session.session_id);
          // Update URL with new session_id
          const newUrl = `${window.location.pathname}?session_id=${session.session_id}`;
          window.history.pushState({ path: newUrl }, '', newUrl);
          setIsLoading(false);
        } catch (e) {
          console.error("Failed to init session", e);
          alert("Failed to initialize session. Check backend.");
          setIsLoading(false);
        }
      }
    };
    init();
  }, []);

  // Network Status Listeners
  useEffect(() => {
    const handleOnline = () => {
      setIsOnline(true);
      if (sessionId) {
        console.log("Back online, resyncing...");
        fetchSchema(sessionId);
      }
    };

    const handleOffline = () => {
      setIsOnline(false);
    };

    window.addEventListener('online', handleOnline);
    window.addEventListener('offline', handleOffline);

    return () => {
      window.removeEventListener('online', handleOnline);
      window.removeEventListener('offline', handleOffline);
    };
  }, [sessionId]);

  const restoreSession = async (sid) => {
    try {
      setIsLoading(true);
      const data = await api.getSchema(sid, 'all', 'values');

      if (data && data.contract) {
        setSchema(data);

        const initialValues = {};
        const taken = [];

        if (data.parties) {
          data.parties.forEach(party => {
            // Check if party has significant data filled
            let hasData = false;
            party.fields.forEach(field => {
              if (field.value) {
                initialValues[field.key] = field.value;
                hasData = true;
              }
            });
            if (hasData) {
              taken.push(party.role);
            }
          });
        }
        data.contract.fields.forEach(field => {
          initialValues[field.key] = field.value || '';
        });

        setFormValues(prev => ({ ...prev, ...initialValues }));
        setTakenRoles(taken);

        // If we have data, assume we can skip category/template selection
        // Go to Mode selection to let user decide how to proceed
        setStep('mode');
      } else {
        setStep('category');
      }
    } catch (e) {
      console.error("Failed to restore session:", e);
      setStep('category');
    } finally {
      setIsLoading(false);
    }
  };

  // SSE for real-time updates
  useEffect(() => {
    if (step !== 'form' || !sessionId) return;

    const eventSource = new EventSource(`${api.API_URL}/sessions/${sessionId}/stream`);

    eventSource.onopen = () => {
      setIsOnline(true);
      // Optional: we could fetchSchema here too, but 'online' event usually handles it
    };

    eventSource.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data.type === 'field_update') {
          // Ignore my own updates to prevent cursor jumping
          if (data.client_id === clientId) return;

          // Update form value
          setFormValues(prev => ({
            ...prev,
            [data.field]: data.value
          }));
        }
      } catch (e) {
        console.error("SSE parse error", e);
      }
    };

    eventSource.onerror = (e) => {
      console.error("SSE error", e);
      // If SSE fails, we might be offline or server down
      if (eventSource.readyState === EventSource.CLOSED || eventSource.readyState === EventSource.CONNECTING) {
        // Don't force offline here immediately as it might be a momentary reconnect,
        // but if navigator.onLine is false, we are definitely offline.
        if (!navigator.onLine) setIsOnline(false);
      }
      eventSource.close();
    };

    return () => {
      eventSource.close();
    };
  }, [step, sessionId, clientId]);

  // --- Step Handlers ---

  const handleCategorySelect = async (categoryId) => {
    setSelectedCategory(categoryId);
    await api.setCategory(sessionId, categoryId);
    setStep('template');
  };

  const handleTemplateSelect = async (templateId) => {
    setSelectedTemplate(templateId);
    await api.setTemplate(sessionId, templateId);
    setStep('mode');
  };

  const handleModeSelect = (mode) => {
    setSelectedMode(mode);
    if (mode === 'ai') {
      alert("AI режим ще в розробці");
      return;
    }
    setStep('role');
  };

  const handleRoleSelect = async (role) => {
    // Check if role is taken
    if (takenRoles.includes(role)) {
      const confirm = window.confirm("Ця роль вже заповнена іншим користувачем. Ви впевнені, що хочете змінити дані? Це може призвести до втрати попередніх даних.");
      if (!confirm) return;
    }

    setSelectedRole(role);
    await api.setPartyContext(sessionId, 'lessor', 'individual');
    await api.setPartyContext(sessionId, 'lessee', 'individual');

    await fetchSchema(sessionId);
    setStep('form');
  };

  const handleBack = () => {
    switch (step) {
      case 'template': setStep('category'); break;
      case 'mode':
        // If we restored session, we might not have selectedTemplate locally set.
        // But if user wants to go back, they probably want to change template.
        setStep('template');
        break;
      case 'role': setStep('mode'); break;
      case 'form': setStep('role'); break;
      default: setStep('category');
    }
  };

  // --- Form Logic ---

  const fetchSchema = async (sid) => {
    try {
      setIsLoading(true);
      const data = await api.getSchema(sid, 'all', 'values');
      setSchema(data);

      // Populate initial form values
      const initialValues = {};
      if (data.parties) {
        data.parties.forEach(party => {
          party.fields.forEach(field => {
            initialValues[field.key] = field.value || '';
          });
        });
      }
      data.contract.fields.forEach(field => {
        initialValues[field.key] = field.value || '';
      });
      setFormValues(prev => ({ ...prev, ...initialValues }));
    } catch (e) {
      console.error("Failed to fetch schema", e);
    } finally {
      setIsLoading(false);
    }
  };

  const debouncedUpsert = useCallback(
    debounce(async (sid, field, value, role, cid) => {
      if (!sid) return;
      try {
        await api.upsertField(sid, field, value, role, cid);
      } catch (e) {
        console.error(`Failed to save ${field}`, e);
      }
    }, 500),
    []
  );

  const handleChange = (key, fieldName, value, role = null) => {
    setFormValues(prev => ({ ...prev, [key]: value }));
    debouncedUpsert(sessionId, fieldName, value, role, clientId);
  };

  const handlePartyTypeChange = async (role, newType) => {
    if (!sessionId) return;
    try {
      setIsLoading(true);
      await api.setPartyContext(sessionId, role, newType);
      await fetchSchema(sessionId);
    } catch (e) {
      console.error("Failed to change party type", e);
      setIsLoading(false);
    }
  };

  const handlePreview = () => {
    if (!sessionId) return;
    setShowPreview(true);
  };

  const handleOrder = async () => {
    if (!sessionId) return;
    try {
      setIsLoading(true);
      const res = await api.orderContract(sessionId);
      if (res.ok) {
        alert("Договір успішно сформовано і збережено в системі!");
      }
    } catch (e) {
      console.error("Order failed", e);
      alert("Order failed: " + (e.response?.data?.detail || e.message));
    }
  };

  // --- Render Helpers ---

  const renderStep = () => {
    switch (step) {
      case 'category':
        return <CategorySelector onSelect={handleCategorySelect} />;
      case 'template':
        return (
          <TemplateSelector
            categoryId={selectedCategory}
            onSelect={handleTemplateSelect}
          />
        );
      case 'mode':
        return (
          <ModeSelector
            onSelect={handleModeSelect}
          />
        );
      case 'role':
        return (
          <RoleSelector
            onSelect={handleRoleSelect}
            takenRoles={takenRoles}
          />
        );
      case 'form':
        return renderForm();
      default:
        return <div>Unknown step</div>;
    }
  };

  const renderForm = () => {
    if (!schema) return <div>Loading form...</div>;

    // Logic for Contract Conditions Optionality
    const allRoles = schema.parties.map(p => p.role);
    const otherRoles = allRoles.filter(r => r !== selectedRole);
    const areAllOtherRolesTaken = otherRoles.every(r => takenRoles.includes(r));

    const isSingleMode = selectedMode === 'single';
    // If single mode, optional ONLY if there are still open roles.
    // If full mode, always mandatory.
    const isContractOptional = isSingleMode && !areAllOtherRolesTaken;

    return (
      <>
        {schema.parties.map(party => {
          const isMyRole = party.role === selectedRole;
          const isTaken = takenRoles.includes(party.role);

          // If single mode, I edit ONLY my role.
          // Other roles are read-only.
          const isEditable = isSingleMode ? isMyRole : !isTaken;

          // Hide empty other roles in single mode if they are not taken
          if (isSingleMode && !isMyRole && !isTaken) return null;

          return (
            <SectionCard
              key={party.role}
              title={party.label}
              subtitle={isTaken ? '(Заповнено іншою стороною)' : `Вкажіть дані для сторони "${party.label}"`}
            >
              <div style={{ marginBottom: 16 }}>
                <label className="input-label">Тип особи</label>
                <select
                  className="text-input"
                  value={party.person_type}
                  onChange={(e) => handlePartyTypeChange(party.role, e.target.value)}
                  disabled={!isEditable || !isOnline}
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
                  disabled={!isEditable || !isOnline}
                />
              ))}
            </SectionCard>
          );
        })}

        <SectionCard
          title={`${schema.contract.title} ${isContractOptional ? '(за бажанням)' : ''}`}
          subtitle={isContractOptional
            ? "Ви можете заповнити умови зараз або залишити це для іншої сторони."
            : schema.contract.subtitle}
        >
          {schema.contract.fields.map(field => (
            <InputField
              key={field.key}
              label={field.label}
              placeholder={field.placeholder}
              value={formValues[field.key]}
              onChange={(val) => handleChange(field.key, field.field_name, val, null)}
              required={isContractOptional ? false : field.required}
              disabled={!isOnline}
            />
          ))}
        </SectionCard>

        <div className="actions">
          <button className="btn-primary" onClick={handleOrder} disabled={!isOnline}>
            {isContractOptional ? 'Зберегти та продовжити' : 'Замовити договір'}
          </button>
          <button className="btn-secondary" onClick={handlePreview}>
            Попередній перегляд
          </button>
        </div>
      </>
    );
  };

  return (
    <div className="app-container">
      {isLoading && <div className="loading-overlay">Loading...</div>}

      {!isOnline && (
        <div className="offline-notification">
          <span>⚠️</span>
          <span>Зв'язок втрачено. Редагування недоступне.</span>
        </div>
      )}

      <PreviewDrawer
        isOpen={showPreview}
        onClose={() => setShowPreview(false)}
        sessionId={sessionId}
      />

      <header className="header">
        {step !== 'category' && (
          <button className="back-button" onClick={handleBack}>←</button>
        )}
        <h1 className="title">Договір оренди житла</h1>
      </header>

      <div className="content-area">
        {renderStep()}
      </div>
    </div>
  );
}

export default App;
