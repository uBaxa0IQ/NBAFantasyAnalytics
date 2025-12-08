import React, { useState, useEffect } from 'react';
import api from '../api';

const PromptModal = ({ isOpen, onClose, period, simulationMode, topNPlayers, mainTeamId, puntCategories }) => {
    const [prompt, setPrompt] = useState('');
    const [loading, setLoading] = useState(false);
    const [copied, setCopied] = useState(false);

    useEffect(() => {
        if (isOpen) {
            loadPrompt();
        } else {
            setPrompt('');
            setCopied(false);
        }
    }, [isOpen, period, simulationMode, topNPlayers, mainTeamId, puntCategories]);

    const loadPrompt = async () => {
        setLoading(true);
        try {
            // Получаем custom_team_players из localStorage
            const customPlayers = mainTeamId ? localStorage.getItem(`customTeamPlayers_${mainTeamId}`) : null;
            const customPlayersList = customPlayers ? JSON.parse(customPlayers).join(',') : null;
            
            // Формируем параметры запроса
            const params = new URLSearchParams({
                period: period,
                simulation_mode: simulationMode,
                top_n_players: topNPlayers,
            });
            
            if (mainTeamId) {
                params.append('main_team_id', mainTeamId);
            }
            
            if (customPlayersList) {
                params.append('custom_team_players', customPlayersList);
            }
            
            if (puntCategories && puntCategories.length > 0) {
                params.append('punt_categories', puntCategories.join(','));
            }
            
            // Просим сервер вернуть компактный JSON без лишней разметки
            params.append('compact', '1');
            
            const response = await api.get(`/generate-prompt?${params.toString()}`);
            
            if (response.data.prompt) {
                setPrompt(response.data.prompt);
            } else {
                alert('Ошибка при генерации промпта');
            }
        } catch (error) {
            console.error('Error loading prompt:', error);
            alert('Ошибка при загрузке промпта: ' + (error.response?.data?.error || error.message));
        } finally {
            setLoading(false);
        }
    };

    const handleCopy = () => {
        navigator.clipboard.writeText(prompt).then(() => {
            setCopied(true);
            setTimeout(() => setCopied(false), 2000);
        }).catch(err => {
            console.error('Failed to copy:', err);
            alert('Не удалось скопировать промпт');
        });
    };

    if (!isOpen) return null;

    return (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50" onClick={onClose}>
            <div className="bg-white rounded-lg shadow-xl max-w-5xl w-full mx-4 max-h-[90vh] flex flex-col" onClick={(e) => e.stopPropagation()}>
                <div className="p-6 border-b flex justify-between items-center">
                    <h2 className="text-2xl font-bold text-gray-800">Промпт для LLM</h2>
                    <button
                        onClick={onClose}
                        className="text-gray-500 hover:text-gray-700 text-2xl font-bold"
                    >
                        ×
                    </button>
                </div>

                <div className="p-6 flex-1 overflow-y-auto">
                    {loading ? (
                        <div className="text-center py-8">
                            <div className="inline-block animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600"></div>
                            <p className="mt-4 text-gray-600">Генерация промпта...</p>
                        </div>
                    ) : prompt ? (
                        <div className="space-y-4">
                            <div className="bg-gray-50 border rounded p-4">
                                <div className="flex justify-between items-center mb-2">
                                    <p className="text-sm text-gray-600">
                                        Скопируйте промпт и вставьте в чат LLM (ChatGPT, Claude и т.д.)
                                    </p>
                                    <button
                                        onClick={handleCopy}
                                        className={`px-4 py-2 rounded text-sm font-medium ${
                                            copied
                                                ? 'bg-green-600 text-white'
                                                : 'bg-blue-600 text-white hover:bg-blue-700'
                                        }`}
                                    >
                                        {copied ? '✓ Скопировано!' : 'Копировать'}
                                    </button>
                                </div>
                            </div>
                            <textarea
                                readOnly
                                value={prompt}
                                className="w-full h-96 p-4 border rounded font-mono text-sm resize-none"
                                style={{ whiteSpace: 'pre-wrap', wordWrap: 'break-word' }}
                            />
                        </div>
                    ) : (
                        <div className="text-center py-8 text-gray-500">
                            Не удалось загрузить промпт
                        </div>
                    )}
                </div>

                <div className="p-6 border-t flex justify-end">
                    <button
                        onClick={onClose}
                        className="px-4 py-2 bg-gray-600 text-white rounded hover:bg-gray-700"
                    >
                        Закрыть
                    </button>
                </div>
            </div>
        </div>
    );
};

export default PromptModal;

