import axios from 'axios';

const API_URL = import.meta.env.VITE_API_URL || '/api';

const getAuthToken = () => {
  if (typeof localStorage === 'undefined') return import.meta.env.VITE_AUTH_TOKEN || null;
  return localStorage.getItem('diia_auth_token') || import.meta.env.VITE_AUTH_TOKEN || null;
};

const buildAuthHeaders = (userId) => {
  const headers = {};
  const token = getAuthToken();
  if (token) headers['Authorization'] = `Bearer ${token}`;
  if (userId) headers['X-User-ID'] = userId;
  return Object.keys(headers).length > 0 ? headers : undefined;
};

export const api = {
  API_URL,
  getAuthToken,

  async createSession(userId) {
    const config = {};
    const headers = buildAuthHeaders(userId);
    if (headers) {
      config.headers = headers;
    }
    const response = await axios.post(`${API_URL}/sessions`, {}, config);
    return response.data;
  },

  async setCategory(sessionId, categoryId) {
    return axios.post(`${API_URL}/sessions/${sessionId}/category`, { category_id: categoryId });
  },

  async setTemplate(sessionId, templateId) {
    return axios.post(`${API_URL}/sessions/${sessionId}/template`, { template_id: templateId });
  },

  async buildContract(sessionId, templateId, userId) {
    const config = {};
    const headers = buildAuthHeaders(userId);
    if (headers) {
      config.headers = headers;
    }
    return axios.post(`${API_URL}/sessions/${sessionId}/build`, { template_id: templateId }, config);
  },

  async setPartyContext(sessionId, role, personType, userId) {
    const config = {};
    const headers = buildAuthHeaders(userId);
    if (headers) {
      config.headers = headers;
    }
    return axios.post(
      `${API_URL}/sessions/${sessionId}/party-context`,
      {
        role,
        person_type: personType,
      },
      config,
    );
  },

  async setFillingMode(sessionId, mode, userId) {
    const config = {};
    const headers = buildAuthHeaders(userId);
    if (headers) {
      config.headers = headers;
    }
    return axios.post(`${API_URL}/sessions/${sessionId}/filling-mode`, { mode }, config);
  },

  async upsertField(sessionId, field, value, role = null, userId = null) {
    const payload = { field, value };
    if (role) {
      payload.role = role;
    }
    const config = {};
    const headers = buildAuthHeaders(userId);
    if (headers) {
      config.headers = headers;
    }
    return axios.post(`${API_URL}/sessions/${sessionId}/fields`, payload, config);
  },

  async getContract(sessionId, userId) {
    const config = {};
    const headers = buildAuthHeaders(userId);
    if (headers) {
      config.headers = headers;
    }
    return axios.get(`${API_URL}/sessions/${sessionId}/contract`, config);
  },

  getDownloadUrl(sessionId, userId) {
    const suffix = userId ? `?user_id=${userId}` : '';
    return `${API_URL}/sessions/${sessionId}/contract/download${suffix}`;
  },

  async getSchema(sessionId, scope = 'all', dataMode = 'values', userId = null) {
    const config = {
      params: { scope, data_mode: dataMode },
    };
    const headers = buildAuthHeaders(userId);
    if (headers) {
      config.headers = headers;
    }
    const res = await axios.get(`${API_URL}/sessions/${sessionId}/schema`, config);
    return res.data;
  },

  async orderContract(sessionId, userId) {
    const config = {};
    const headers = buildAuthHeaders(userId);
    if (headers) {
      config.headers = headers;
    }
    const res = await axios.post(`${API_URL}/sessions/${sessionId}/order`, {}, config);
    return res.data;
  },

  async getCategories() {
    const res = await axios.get(`${API_URL}/categories`);
    return res.data;
  },

  async getTemplates(categoryId) {
    const res = await axios.get(`${API_URL}/categories/${categoryId}/templates`);
    return res.data;
  },

  async getHistory(sessionId, userId) {
    const config = {};
    const headers = buildAuthHeaders(userId);
    if (headers) {
      config.headers = headers;
    }
    const res = await axios.get(`${API_URL}/sessions/${sessionId}/history`, config);
    return res.data;
  },

  async getRequirements(sessionId, userId) {
    const config = {};
    const headers = buildAuthHeaders(userId);
    if (headers) {
      config.headers = headers;
    }
    const res = await axios.get(`${API_URL}/sessions/${sessionId}/requirements`, config);
    return res.data;
  },

  async chat(sessionId, message, userId) {
    const config = {};
    const headers = buildAuthHeaders(userId);
    if (headers) {
      config.headers = headers;
    }
    const res = await axios.post(`${API_URL}/chat`, {
      session_id: sessionId,
      message,
    }, config);
    return res.data;
  },

  async getMySessions(userId) {
    const config = {};
    const headers = buildAuthHeaders(userId);
    if (headers) {
      config.headers = headers;
    }
    const res = await axios.get(`${API_URL}/my-sessions`, config);
    return res.data;
  },

  async signContract(sessionId, userId) {
    const config = {};
    const headers = buildAuthHeaders(userId);
    if (headers) {
      config.headers = headers;
    }
    const res = await axios.post(`${API_URL}/sessions/${sessionId}/contract/sign`, {}, config);
    return res.data;
  },
};

export { getAuthToken };
