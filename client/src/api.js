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

    async setPartyContext(sessionId, role, personType) {
        return axios.post(`${API_URL}/sessions/${sessionId}/party-context`, {
            role: role,
            person_type: personType
        });
    },

    async upsertField(sessionId, field, value, role = null, clientId = null) {
        const payload = { field, value };
        if (role) {
            payload.role = role;
        }
        if (clientId) {
            payload.client_id = clientId;
        }
        return axios.post(`${API_URL}/sessions/${sessionId}/fields`, payload);
    },

    async getContract(sessionId) {
        return axios.get(`${API_URL}/sessions/${sessionId}/contract`);
    },

    async getPreview(sessionId) {
        return axios.get(`${API_URL}/sessions/${sessionId}/contract/preview`);
    },

    getDownloadUrl(sessionId) {
        return `${API_URL}/sessions/${sessionId}/contract/download`;
    },

    async getSchema(sessionId, scope = 'all', dataMode = 'values') {
        const res = await axios.get(`${API_URL}/sessions/${sessionId}/schema`, {
            params: { scope, data_mode: dataMode }
        });
        return res.data;
    },

    async orderContract(sessionId) {
        const res = await axios.post(`${API_URL}/sessions/${sessionId}/order`);
        return res.data;
    },

    async getCategories() {
        const res = await axios.get(`${API_URL}/categories`);
        return res.data;
    },

    async getTemplates(categoryId) {
        const res = await axios.get(`${API_URL}/categories/${categoryId}/templates`);
        return res.data;
    }
};
