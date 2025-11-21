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
import { Dashboard } from './components/Dashboard';
import { ContractDetails } from './components/ContractDetails';

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

    const eventSource = new EventSource(`${api.API_URL}/sessions/${sessionId}/stream`);

    eventSource.onopen = () => {
      setIsOnline(true);
    };

    eventSource.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        console.log("SSE Event:", data);

        if (data.type === 'field_update') {
          // Ignore my own updates to prevent cursor jumping
          if (data.client_id === clientId) return;

          // Update form value
          setFormValues(prev => ({
            ...prev,
            [data.field]: data.value
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
        const newUrl = `${window.location.pathname}?session_id=${sid}`;
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
      await api.setTemplate(sid, templateId);
    }

    setStep('mode');
  };

  const handleModeSelect = async (mode) => {
    setSelectedMode(mode);

    if (sessionId) {
      try {
        await api.setFillingMode(sessionId, mode === 'full' ? 'full' : 'partial');
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
      // Try to claim all known roles.
      try {
        await api.setPartyContext(sessionId, 'lessor', 'individual', clientId);
      } catch (e) { }
      try {
        await api.setPartyContext(sessionId, 'lessee', 'individual', clientId);
      } catch (e) { }
    } else {
      // Partial mode: claim only selected
      try {
        const res = await api.setPartyContext(sessionId, role, 'individual', clientId);
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

  const handleBack = () => {
    switch (step) {
      case 'template': setStep('category'); break;
      case 'mode':
        setStep('template');
        break;
      case 'role': setStep('mode'); break;
      case 'form': setStep('role'); break;
      case 'details': setStep('dashboard'); break;
      case 'dashboard': setStep('category'); break;
      default: setStep('category');
    }
  };

  // --- Form Logic ---

  const fetchSchema = async (sid) => {
    try {
      setIsLoading(true);
      const data = await api.getSchema(sid, 'all', 'values', clientId);
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
    }, 1000),
    []
  );

  const handleChange = (key, fieldName, value, role = null) => {
    setFormValues(prev => ({ ...prev, [key]: value }));
    debouncedUpsert(sessionId, fieldName, value, role, clientId);
  };

  const handleBlur = async (key, fieldName, value, role = null) => {
    if (!sessionId) return;
    try {
      await api.upsertField(sessionId, fieldName, value, role, clientId);
    } catch (e) {
      console.error(`Failed to save ${fieldName} on blur`, e);
    }
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

  const handleOrder = async (isOptional = false) => {
    if (!sessionId) return;

    if (isOptional) {
      alert("Дані успішно збережено! Ви можете скопіювати посилання з адресного рядка і надіслати його іншій стороні для заповнення.");
      return;
    }

    try {
      setIsLoading(true);
      const res = await api.orderContract(sessionId, clientId);
      if (res.ok) {
        await fetchSchema(sessionId);
        setStep('success');
      }
    } catch (e) {
      console.error("Order failed", e);
      alert("Order failed: " + (e.response?.data?.detail || e.message));
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
            />
          ))}
        </SectionCard>

        <div className="actions">
          {schema.status === 'completed' ? (
            <button className="btn-primary" onClick={() => window.open(api.getDownloadUrl(sessionId), '_blank')}>
              Завантажити DOCX
            </button>
          ) : (
            <button
              className="btn-primary"
              onClick={() => handleOrder(isContractOptional)}
              disabled={!isOnline || !(() => {
                if (!schema) return false;
                for (const party of schema.parties) {
                  if (selectedMode === 'single' && party.role !== selectedRole) continue;
                  for (const field of party.fields) {
                    if (field.required && !formValues[field.key]) return false;
                  }
                }
                if (!isContractOptional) {
                  for (const field of schema.contract.fields) {
                    if (field.required && !formValues[field.key]) return false;
                  }
                }
                return true;
              })()}
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
      onClick={() => setStep('dashboard')}
    >
      <span>📂</span> Усі договори
    </button>
  </div >
);
}

// --- AI Chat Component ---
const AIChat = ({ sessionId, clientId, onBack }) => {
  const [messages, setMessages] = useState([
    { role: 'system', content: 'Привіт! Я ваш AI-помічник. Я можу допомогти вам заповнити договір. Просто напишіть мені дані або завантажте документ.' }
  ]);
  const [input, setInput] = useState('');
  const [isSending, setIsSending] = useState(false);

  const handleSend = async () => {
    if (!input.trim()) return;

    const userMsg = { role: 'user', content: input };
    setMessages(prev => [...prev, userMsg]);
    setInput('');
    setIsSending(true);

    try {
      const res = await api.chat(sessionId, userMsg.content);
      setMessages(prev => [...prev, { role: 'assistant', content: res.reply }]);
    } catch (e) {
      console.error("Chat failed", e);
      setMessages(prev => [...prev, { role: 'system', content: 'Вибачте, сталася помилка. Спробуйте ще раз.' }]);
    } finally {
      setIsSending(false);
    }
  };

  return (
    <div className="chat-container">
      <div className="chat-messages">
        {messages.map((m, i) => (
          <div key={i} className={`chat-message ${m.role}`}>
            <div className="message-content">{m.content}</div>
          </div>
        ))}
        {isSending && <div className="chat-message system">Writing...</div>}
      </div>
      <div className="chat-input-area">
        <input
          type="text"
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyPress={e => e.key === 'Enter' && handleSend()}
          placeholder="Напишіть повідомлення..."
          disabled={isSending}
        />
        <button onClick={handleSend} disabled={isSending}>Send</button>
      </div>
      <button className="btn-secondary" style={{ marginTop: 10 }} onClick={onBack}>Back to Form</button>
    </div>
  );
};

export default App;
