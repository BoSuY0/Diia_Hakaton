import axios from 'axios';

const API_URL = `http://${window.location.hostname}:8000`;

export const api = {
    API_URL,
    async createSession() {
        const response = await axios.post(`${API_URL}/sessions`, {});
        return response.data;
    },

    async setCategory(sessionId, categoryId) {
        return axios.post(`${API_URL}/sessions/${sessionId}/category`, { category_id: categoryId });
    },

    async setTemplate(sessionId, templateId) {
        return axios.post(`${API_URL}/sessions/${sessionId}/template`, { template_id: templateId });
    },

    async buildContract(sessionId, templateId, clientId) {
        const config = {};
        if (clientId) {
            config.headers = { 'X-Client-ID': clientId };
        }
        return axios.post(`${API_URL}/sessions/${sessionId}/build`, { template_id: templateId }, config);
    },

    async setPartyContext(sessionId, role, personType, clientId) {
        const config = {};
        if (clientId) {
            config.headers = { 'X-Client-ID': clientId };
        }
        return axios.post(`${API_URL}/sessions/${sessionId}/party-context`, {
            role: role,
            person_type: personType
        }, config);
    },

    async setFillingMode(sessionId, mode, clientId) {
        const config = {};
        if (clientId) {
            config.headers = { 'X-Client-ID': clientId };
        }
        return axios.post(`${API_URL}/sessions/${sessionId}/filling-mode`, { mode }, config);
    },

    async upsertField(sessionId, field, value, role = null, clientId = null) {
        const payload = { field, value };
        if (role) {
            payload.role = role;
        }
        const config = {};
        if (clientId) {
            config.headers = { 'X-Client-ID': clientId };
        }
        return axios.post(`${API_URL}/sessions/${sessionId}/fields`, payload, config);
    },

    async getContract(sessionId, clientId) {
        const config = {};
        if (clientId) {
            config.headers = { 'X-Client-ID': clientId };
        }
        return axios.get(`${API_URL}/sessions/${sessionId}/contract`, config);
    },

    async getPreview(sessionId, clientId) {
        const config = {};
        if (clientId) {
            config.headers = { 'X-Client-ID': clientId };
        }
        return axios.get(`${API_URL}/sessions/${sessionId}/contract/preview`, config);
    },

    getDownloadUrl(sessionId, clientId) {
        const suffix = clientId ? `?client_id=${clientId}` : '';
        return `${API_URL}/sessions/${sessionId}/contract/download${suffix}`;
    },

    async getSchema(sessionId, scope = 'all', dataMode = 'values', clientId = null) {
        const config = {
            params: { scope, data_mode: dataMode }
        };
        if (clientId) {
            config.headers = { 'X-Client-ID': clientId };
        }
        const res = await axios.get(`${API_URL}/sessions/${sessionId}/schema`, config);
        return res.data;
    },

    async orderContract(sessionId, clientId) {
        const config = {};
        if (clientId) {
            config.headers = { 'X-Client-ID': clientId };
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

    async getHistory(sessionId, clientId) {
        const config = {};
        if (clientId) {
            config.headers = { 'X-Client-ID': clientId };
        }
        const res = await axios.get(`${API_URL}/sessions/${sessionId}/history`, config);
        return res.data;
    },

    async getRequirements(sessionId, clientId) {
        const config = {};
        if (clientId) {
            config.headers = { 'X-Client-ID': clientId };
        }
        const res = await axios.get(`${API_URL}/sessions/${sessionId}/requirements`, config);
        return res.data;
    },

    async chat(sessionId, message) {
        const res = await axios.post(`${API_URL}/chat`, {
            session_id: sessionId,
            message: message
        });
        return res.data;
    },

    async getMySessions(clientId) {
        const config = {};
        if (clientId) {
            config.headers = { 'X-Client-ID': clientId };
        }
        const res = await axios.get(`${API_URL}/my-sessions`, config);
        return res.data;
    },

    async signContract(sessionId, clientId) {
        const config = {};
        if (clientId) {
            config.headers = { 'X-Client-ID': clientId };
        }
        const res = await axios.post(`${API_URL}/sessions/${sessionId}/contract/sign`, {}, config);
        return res.data;
    }
};
