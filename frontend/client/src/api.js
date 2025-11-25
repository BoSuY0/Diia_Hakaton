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

  async createSession(userId, options = {}) {
    const config = {};
    const headers = buildAuthHeaders(userId);
    if (headers) {
      config.headers = headers;
    }
    // Support full initialization with options:
    // { category_id, template_id, filling_mode, role, person_type }
    const payload = {};
    if (options.category_id) payload.category_id = options.category_id;
    if (options.template_id) payload.template_id = options.template_id;
    if (options.filling_mode) payload.filling_mode = options.filling_mode;
    if (options.role) payload.role = options.role;
    if (options.person_type) payload.person_type = options.person_type;
    
    const response = await axios.post(`${API_URL}/sessions`, payload, config);
    return response.data;
  },

  async setCategory(sessionId, categoryId, userId = null) {
    const config = {};
    const headers = buildAuthHeaders(userId);
    if (headers) {
      config.headers = headers;
    }
    return axios.post(`${API_URL}/sessions/${sessionId}/category`, { category_id: categoryId }, config);
  },

  async setTemplate(sessionId, templateId, userId = null) {
    const config = {};
    const headers = buildAuthHeaders(userId);
    if (headers) {
      config.headers = headers;
    }
    return axios.post(`${API_URL}/sessions/${sessionId}/template`, { template_id: templateId }, config);
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

  /**
   * Get category schema (roles, person types, fields) WITHOUT creating a session.
   * Use this to show role selection UI before session creation.
   */
  async getCategorySchema(categoryId) {
    const res = await axios.get(`${API_URL}/categories/${categoryId}/schema`);
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
