import React, { useEffect, useState, useCallback } from 'react';
// Trigger rebuild
import './App.css';
import { api } from './api';
import { SectionCard } from './components/SectionCard';
import { InputField } from './components/InputField';
import PreviewDrawer from './components/PreviewDrawer';
import { CategorySelector } from './components/CategorySelector';
import { TemplateSelector } from './components/TemplateSelector';
import { ModeSelector } from './components/ModeSelector';
import { RoleSelector } from './components/RoleSelector';
import { Dashboard } from './components/Dashboard';
import { ContractDetails } from './components/ContractDetails';
import { AIChat } from './components/AIChat';

// Simple debounce utility
const debounce = (func, wait) => {
  let timeout;
  return (...args) => {
    clearTimeout(timeout);
    timeout = setTimeout(() => func(...args), wait);
  };
};

function App() {
  // Steps: 'category' -> 'template' -> 'mode' -> 'role' -> 'form' -> 'success' -> 'details' -> 'dashboard'
  const [step, setStep] = useState('category');

  const [sessionId, setSessionId] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [showPreview, setShowPreview] = useState(false);
  const [schema, setSchema] = useState(null);
  const [formValues, setFormValues] = useState({});
  const [fieldErrors, setFieldErrors] = useState({});
  const [missingRequirements, setMissingRequirements] = useState(null);

  const [clientId] = useState(() => {
    const stored = localStorage.getItem('diia_client_id');
    if (stored) return stored;
    const newId = Math.random().toString(36).substring(7);
    localStorage.setItem('diia_client_id', newId);
    return newId;
  });

  // Derived state for taken roles (reactive to formValues)
  const takenRoles = React.useMemo(() => {
    if (!schema || !schema.parties) return [];
    const taken = [];
    schema.parties.forEach(party => {
      // Only mark as taken if claimed by SOMEONE ELSE
      if (party.claimed_by && party.claimed_by !== clientId) {
        taken.push(party.role);
      }
    });
    return taken;
  }, [schema, clientId]);

  const extractErrorsFromSchema = (schemaData) => {
    const errors = {};
    if (!schemaData) return errors;

    if (schemaData.parties) {
      schemaData.parties.forEach(party => {
        (party.fields || []).forEach(field => {
          if (field.status === 'error') {
            errors[field.key] = field.error || 'Некоректне значення';
          }
        });
      });
    }

    if (schemaData.contract && schemaData.contract.fields) {
      schemaData.contract.fields.forEach(field => {
        if (field.status === 'error') {
          errors[field.key] = field.error || 'Некоректне значення';
        }
      });
    }
    return errors;
  };

  const extractErrorMessage = (error, fallback = 'Сталася помилка') => {
    const detail = error?.response?.data?.detail;
    if (!detail) return fallback;
    if (typeof detail === 'string') return detail;
    if (typeof detail === 'object') return detail.message || detail.error || fallback;
    return fallback;
  };

  // Selections
  const [selectedCategory, setSelectedCategory] = useState(null);
  const [selectedTemplate, setSelectedTemplate] = useState(null);
  const [selectedMode, setSelectedMode] = useState(null); // 'single', 'full', 'ai'
  const [selectedRole, setSelectedRole] = useState(null); // 'lessor', 'lessee'
  const [isOnline, setIsOnline] = useState(navigator.onLine);

  // Initialize session on mount
  const initialized = React.useRef(false);
  useEffect(() => {
    if (initialized.current) return;
    initialized.current = true;

    const init = async () => {
      // Ensure we are on the root path
      if (window.location.pathname !== '/') {
        const cleanUrl = `/${window.location.search}`;
        window.history.replaceState({}, '', cleanUrl);
      }

      const params = new URLSearchParams(window.location.search);
      const sid = params.get('session_id');

      if (sid) {
        console.log("Found session_id in URL:", sid);
        setSessionId(sid);
        await restoreSession(sid);
      } else {
        setIsLoading(false);
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
      const data = await api.getSchema(sid, 'all', 'values', clientId);

      if (data && data.contract) {
        setSchema(data);
        setFieldErrors(extractErrorsFromSchema(data));
        setMissingRequirements(null);
        if (data.filling_mode) {
          setSelectedMode(data.filling_mode === 'full' ? 'full' : 'single');
        }

        const initialValues = {};

        if (data.parties) {
          data.parties.forEach(party => {
            party.fields.forEach(field => {
              if (field.value) {
                initialValues[field.key] = field.value;
              }
            });
          });
        }
        data.contract.fields.forEach(field => {
          initialValues[field.key] = field.value || '';
        });

        setFormValues(prev => ({ ...prev, ...initialValues }));

        // Check if I have a role
        const myRole = data.parties.find(p => p.claimed_by === clientId)?.role;

        if (myRole) {
          if (data.filling_mode) {
            setStep('role');
          } else {
            setStep('mode');
          }
        } else {
          // No role yet
          if (data.filling_mode) {
            setStep('role');
          } else {
            setStep('mode');
          }
        }
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
    if (!sessionId) return;

    const eventSource = new EventSource(`${api.API_URL}/sessions/${sessionId}/stream?client_id=${clientId}`);

    eventSource.onopen = () => {
      setIsOnline(true);
    };

    eventSource.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        console.log("SSE Event:", data);

        if (data.type === 'field_update') {
          const incomingKey = data.field_key || (data.role ? `${data.role}.${data.field}` : data.field);
          if (!incomingKey) return;

          // Update form value
          setFormValues(prev => ({
            ...prev,
            [incomingKey]: data.value
          }));
        } else if (data.type === 'schema_update') {
          fetchSchema(sessionId);
        }
      } catch (e) {
        console.error("SSE parse error", e);
      }
    };

    eventSource.onerror = (e) => {
      console.error("SSE error", e);
      if (eventSource.readyState === EventSource.CLOSED || eventSource.readyState === EventSource.CONNECTING) {
        if (!navigator.onLine) setIsOnline(false);
      }
      eventSource.close();
    };

    return () => {
      eventSource.close();
    };
  }, [sessionId, clientId]);

  // --- Step Handlers ---

  const handleCategorySelect = (categoryId) => {
    setSelectedCategory(categoryId);
    setStep('template');
  };

  const handleTemplateSelect = async (templateId) => {
    setSelectedTemplate(templateId);

    let sid = sessionId;
    if (!sid) {
      try {
        setIsLoading(true);
        const session = await api.createSession();
        sid = session.session_id;
        setSessionId(sid);
        const newUrl = `/?session_id=${sid}`;
        window.history.pushState({ path: newUrl }, '', newUrl);

        // Set category and template
        await api.setCategory(sid, selectedCategory);
        await api.setTemplate(sid, templateId);
      } catch (e) {
        console.error("Failed to create session", e);
        alert("Failed to create session");
        setIsLoading(false);
        return;
      } finally {
        setIsLoading(false);
      }
    } else {
      if (selectedCategory) {
        try {
          await api.setCategory(sid, selectedCategory);
        } catch (e) {
          console.error("Failed to set category", e);
        }
      }
      await api.setTemplate(sid, templateId);
    }

    setStep('mode');
  };

  const handleModeSelect = async (mode) => {
    setSelectedMode(mode);

    if (sessionId) {
      try {
        await api.setFillingMode(sessionId, mode === 'full' ? 'full' : 'partial', clientId);
      } catch (e) {
        console.error("Failed to set mode", e);
      }
    }

    if (mode === 'ai') {
      setStep('ai_chat');
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

    if (selectedMode === 'full') {
      // Try to claim all known roles dynamically
      if (schema && schema.parties) {
        for (const party of schema.parties) {
          const defaultType = party.allowed_types && party.allowed_types.length > 0 ? party.allowed_types[0].value : 'individual';
          try {
            await api.setPartyContext(sessionId, party.role, defaultType, clientId);
          } catch (e) {
            console.error(`Failed to set context for ${party.role}`, e);
          }
        }
      }
    } else {
      // Partial mode: claim only selected
      const party = schema && schema.parties ? schema.parties.find(p => p.role === role) : null;
      const defaultType = party && party.allowed_types && party.allowed_types.length > 0 ? party.allowed_types[0].value : 'individual';

      try {
        const res = await api.setPartyContext(sessionId, role, defaultType, clientId);
        if (res.data && !res.data.ok) {
          alert(res.data.error || "Не вдалося обрати роль. Можливо, вона вже зайнята.");
          await fetchSchema(sessionId);
          return;
        }
      } catch (error) {
        console.error("Role selection error:", error);
        if (error.response && error.response.data && error.response.data.detail) {
          alert(`Помилка: ${error.response.data.detail}`);
        } else {
          alert("Не вдалося обрати роль. Спробуйте оновити сторінку.");
        }
        await fetchSchema(sessionId);
        return;
      }
    }

    await fetchSchema(sessionId);
    setStep('form');
  };

  const clearUrlSession = () => {
    window.history.pushState({}, '', '/');
  };

  const handleBack = () => {
    switch (step) {
      case 'template':
        setStep('category');
        setSessionId(null);
        clearUrlSession();
        break;
      case 'mode':
        setStep('template');
        break;
      case 'role': setStep('mode'); break;
      case 'form': setStep('role'); break;
      case 'details':
        setStep('dashboard');
        clearUrlSession();
        break;
      case 'dashboard':
        setStep('category');
        setSessionId(null);
        clearUrlSession();
        break;
      default:
        setStep('category');
        setSessionId(null);
        clearUrlSession();
    }
  };

  // --- Form Logic ---

  const saveFieldValue = useCallback(async (sid, fieldName, value, role, fieldKey, options = {}) => {
    if (!sid) return;
    const { silent = false } = options;
    try {
      const res = await api.upsertField(sid, fieldName, value, role, clientId);
      const data = res?.data || res;
      const status = data?.status || data?.field_state?.status;
      const errorText = data?.error || data?.field_state?.error;

      setFieldErrors(prev => {
        const next = { ...prev };
        if (status === 'error') {
          next[fieldKey] = errorText || 'Некоректне значення';
        } else {
          delete next[fieldKey];
        }
        return next;
      });
    } catch (error) {
      const message = extractErrorMessage(error, 'Не вдалося зберегти значення');
      setFieldErrors(prev => ({ ...prev, [fieldKey]: message }));
      if (!silent) {
        console.error(`Failed to save ${fieldName}`, error);
      }
    }
  }, [clientId]);

  const fetchSchema = async (sid) => {
    try {
      setIsLoading(true);
      const data = await api.getSchema(sid, 'all', 'values', clientId);
      setSchema(data);
      setFieldErrors(extractErrorsFromSchema(data));
      setMissingRequirements(null);

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
    debounce(async (sid, field, value, role, fieldKey) => {
      await saveFieldValue(sid, field, value, role, fieldKey, { silent: true });
    }, 1000),
    [saveFieldValue]
  );

  const handleChange = (key, fieldName, value, role = null) => {
    setMissingRequirements(null);
    setFormValues(prev => ({ ...prev, [key]: value }));
    debouncedUpsert(sessionId, fieldName, value, role, key);
  };

  const handleBlur = async (key, fieldName, value, role = null) => {
    if (!sessionId) return;
    setMissingRequirements(null);
    await saveFieldValue(sessionId, fieldName, value, role, key);
  };

  const handlePartyTypeChange = async (role, newType) => {
    if (!sessionId) return;
    try {
      setIsLoading(true);
      setMissingRequirements(null);
      await api.setPartyContext(sessionId, role, newType, clientId);
      await fetchSchema(sessionId);
    } catch (e) {
      console.error("Failed to change party type", e);
      setIsLoading(false);
    }
  };

  const handlePreview = () => {
    if (!sessionId) return;
    const tpl = schema?.template_id || selectedTemplate;
    if (!tpl) {
      alert("Спочатку оберіть шаблон договору.");
      return;
    }
    api.buildContract(sessionId, tpl, clientId)
      .catch((e) => {
        console.error("Failed to build before preview", e);
      })
      .finally(() => {
        setShowPreview(true);
      });
  };

  const handleOrder = async (isOptional = false) => {
    if (!sessionId) return;

    if (isOptional) {
      alert("Дані успішно збережено! Ви можете скопіювати посилання з адресного рядка і надіслати його іншій стороні для заповнення.");
      return;
    }

    try {
      setIsLoading(true);
      setMissingRequirements(null);
      const res = await api.orderContract(sessionId, clientId);
      if (res.ok) {
        await fetchSchema(sessionId);
        setMissingRequirements(null);
        setStep('success');
      }
    } catch (e) {
      console.error("Order failed", e);
      let message = extractErrorMessage(e, 'Не вдалося сформувати договір');
      let missing = null;
      const detail = e.response?.data?.detail;
      if (detail && typeof detail === 'object' && detail.missing) {
        missing = detail.missing;
      }

      if (!missing) {
        try {
          const reqInfo = await api.getRequirements(sessionId, clientId);
          missing = reqInfo?.missing;
        } catch (reqErr) {
          console.error("Failed to fetch requirements", reqErr);
        }
      }

      if (missing) {
        setMissingRequirements(missing);
      }
      alert("Не вдалося замовити договір: " + message);
    } finally {
      setIsLoading(false);
    }
  };

  // Derived state for my roles
  const myRoles = React.useMemo(() => {
    if (!schema || !schema.parties) return [];
    return schema.parties.filter(p => p.claimed_by === clientId).map(p => p.role);
  }, [schema, clientId]);

  // --- Render Helpers ---

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

    const canSubmit = () => {
      if (!schema) return false;
      for (const party of schema.parties) {
        if (selectedMode === 'single' && party.role !== selectedRole) continue;
        for (const field of party.fields) {
          if (field.required) {
            if (!formValues[field.key]) return false;
            if (fieldErrors[field.key]) return false;
          }
        }
      }
      if (!isContractOptional) {
        for (const field of schema.contract.fields) {
          if (field.required) {
            if (!formValues[field.key]) return false;
            if (fieldErrors[field.key]) return false;
          }
        }
      }
      return true;
    };

    return (
      <>
        {schema.parties.map(party => {
          const isMyRole = party.role === selectedRole;
          const isTaken = takenRoles.includes(party.role);

          const isFullMode = selectedMode === 'full';
          const isEditable = isFullMode ? true : (isSingleMode ? isMyRole : !isTaken);

          if (isSingleMode && !isMyRole && !isTaken) return null;

          return (
            <SectionCard
              key={party.role}
              title={party.label}
              subtitle={party.claimed_by && party.claimed_by !== clientId ? '(Заповнено іншою стороною)' : `Вкажіть дані для сторони "${party.label}"`}
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
                  onBlur={() => handleBlur(field.key, field.field_name, formValues[field.key], party.role)}
                  required={field.required}
                  disabled={!isEditable || !isOnline}
                  error={fieldErrors[field.key]}
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
              onBlur={() => handleBlur(field.key, field.field_name, formValues[field.key], null)}
              required={field.required}
              disabled={!isOnline}
              error={fieldErrors[field.key]}
            />
          ))}
        </SectionCard>

        {missingRequirements && (
          <div className="validation-banner">
            <div className="validation-title">Заповніть обов'язкові поля перед замовленням</div>
            <ul className="validation-list">
              {missingRequirements.contract?.map(item => (
                <li key={`contract-${item.key}`}>Умова договору: {item.label || item.field}</li>
              ))}
              {Object.values(missingRequirements.roles || {}).map(role => (
                role.missing_fields?.map(f => (
                  <li key={`${role.role}-${f.key}`}>
                    {role.role_label || role.role}: {f.label || f.field}
                  </li>
                ))
              ))}
            </ul>
          </div>
        )}

        <div className="actions">
          {schema.status === 'completed' ? (
            <button className="btn-primary" onClick={() => window.open(api.getDownloadUrl(sessionId, clientId), '_blank')}>
              Завантажити DOCX
            </button>
          ) : (
          <button
            className="btn-primary"
            onClick={() => handleOrder(isContractOptional)}
            disabled={!isOnline || !canSubmit()}
            title={!isOnline ? "Немає зв'язку" : "Заповніть всі обов'язкові поля"}
          >
            {isContractOptional ? 'Зберегти та продовжити' : 'Замовити договір'}
          </button>
        )}
          <button className="btn-secondary" onClick={handlePreview}>
            Попередній перегляд
          </button>
        </div>
      </>
    );
  };

  const renderStep = () => {
    switch (step) {
      case 'category':
        return <CategorySelector onSelect={handleCategorySelect} />;
      case 'template':
        return (
          <TemplateSelector
            categoryId={selectedCategory}
            onSelect={handleTemplateSelect}
            onBack={handleBack}
          />
        );
      case 'mode':
        return (
          <ModeSelector
            onSelect={handleModeSelect}
            onBack={handleBack}
          />
        );
      case 'role':
        return (
          <RoleSelector
            onSelect={handleRoleSelect}
            takenRoles={takenRoles}
            myRoles={myRoles}
            isFullMode={selectedMode === 'full'}
            parties={schema?.parties || []}
          />
        );
      case 'form':
        return renderForm();
      case 'success':
        return (
          <div className="success-screen">
            <h2>Договір успішно створено!</h2>
            <p>Чернетку можна переглянути зараз, а завантаження оригіналу стане доступним після підпису всіх сторін.</p>
            <button className="btn-primary" onClick={() => window.open(`${api.API_URL}/sessions/${sessionId}/contract/preview`, '_blank')}>
              👁️ Переглянути чернетку
            </button>
            <button className="btn-secondary" onClick={() => {
              setStep('dashboard');
              clearUrlSession();
            }}>
              На головну
            </button>
          </div>
        );
      case 'details':
        return (
          <ContractDetails
            sessionId={sessionId}
            clientId={clientId}
            onBack={handleBack}
            onEdit={() => setStep('form')}
          />
        );
      case 'dashboard':
        return (
          <Dashboard
            clientId={clientId}
            onSelectSession={(sid) => {
              setSessionId(sid);
              fetchSchema(sid);
              setStep('details');
            }}
            onBack={handleBack}
          />
        );
      case 'ai_chat':
        return (
          <AIChat
            sessionId={sessionId}
            clientId={clientId}
            onBack={() => setStep('mode')}
          />
        );
      default:
        return <div>Unknown step</div>;
    }
  };

  return (
    <div className="app-container">
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
        clientId={clientId}
      />

      <header className="header">
        {step !== 'category' && step !== 'dashboard' && (
          <button className="back-button" onClick={handleBack}>←</button>
        )}
        <h1 className="title">Договір оренди житла</h1>
      </header>

      <div className="content-area">
        {renderStep()}
      </div>

      <button
        className="floating-dashboard-btn"
        onClick={() => {
          setStep('dashboard');
          clearUrlSession();
        }}
      >
        <span>📂</span> Усі договори
      </button>
    </div>
  );
}

export default App;
