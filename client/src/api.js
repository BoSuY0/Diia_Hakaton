import axios from 'axios';

const API_URL = 'http://localhost:8000';

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
        // Since there is no direct endpoint for set_party_context, we use the chat endpoint
        // or we rely on the fact that upsert_field might work if we set the role explicitly?
        // No, upsert_field needs the party type to be set to validate fields.
        // We need to simulate the tool call or use the chat endpoint.
        // Using chat endpoint is safer.
        return axios.post(`${API_URL}/chat`, {
            session_id: sessionId,
            message: `set role to ${role} and person type to ${personType}`
        });
    },

    async upsertField(sessionId, field, value, role = null) {
        const payload = { field, value };
        if (role) {
            payload.role = role;
        }
        return axios.post(`${API_URL}/sessions/${sessionId}/fields`, payload);
    },

    async getContract(sessionId) {
        return axios.get(`${API_URL}/sessions/${sessionId}/contract`);
    },

    async getPreview(sessionId) {
        return axios.get(`${API_URL}/sessions/${sessionId}/contract/preview`, {
            responseType: 'blob'
        });
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
    }
};
