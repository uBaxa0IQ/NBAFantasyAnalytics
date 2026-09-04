import axios from 'axios';

const api = axios.create({
    baseURL: import.meta.env.VITE_API_URL || '/api',
    timeout: 120000, // 2 минуты для долгих запросов (например, генерация промпта)
});

api.interceptors.request.use(config => {
    const token = sessionStorage.getItem('nba-api-token');
    if (token) config.headers.Authorization = `Bearer ${token}`;
    return config;
});
api.interceptors.response.use(response => response, error => {
    if (error.response?.status === 401) window.dispatchEvent(new Event('nba-auth-required'));
    return Promise.reject(error);
});

export default api;
