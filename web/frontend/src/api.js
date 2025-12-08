import axios from 'axios';

const api = axios.create({
    baseURL: import.meta.env.VITE_API_URL || 'http://localhost:8000/api',
    timeout: 120000, // 2 минуты для долгих запросов (например, генерация промпта)
});

export default api;
