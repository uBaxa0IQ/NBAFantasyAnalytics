import React, { useState, useEffect } from 'react';
import api from '../api';

const PromptModal = ({ isOpen, onClose, period, simulationMode, topNPlayers, mainTeamId, puntCategories }) => {
    const [prompt, setPrompt] = useState('');
    const [data, setData] = useState(null);
    const [loading, setLoading] = useState(false);
    const [copied, setCopied] = useState(false);

    useEffect(() => {
        if (isOpen) {
            loadPrompt();
        } else {
            setPrompt('');
            setData(null);
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
            
            // Дебаг вывод
            console.log('=== PROMPT GENERATION DEBUG ===');
            console.log('Response keys:', Object.keys(response.data));
            console.log('Has prompt:', !!response.data.prompt);
            console.log('Has data:', !!response.data.data);
            
            if (response.data.prompt) {
                setPrompt(response.data.prompt);
                // Сохраняем также структурированные данные для отображения
                if (response.data.data) {
                    const dataObj = response.data.data;
                    console.log('Data structure:', {
                        li: !!dataObj.li,
                        t: dataObj.t?.length || 0,
                        p: dataObj.p?.length || 0,
                        s: !!dataObj.s,
                        mh: dataObj.mh?.length || 0,
                        um: dataObj.um?.length || 0,
                        fa: dataObj.fa?.length || 0,
                        sim: {
                            by_avg: !!dataObj.sim?.by_avg,
                            by_avg_results: dataObj.sim?.by_avg?.r?.length || 0,
                            by_z_score: !!dataObj.sim?.by_z_score,
                            by_z_score_results: dataObj.sim?.by_z_score?.r?.length || 0
                        },
                        cr: Object.keys(dataObj.cr || {}).length,
                        lm: Object.keys(dataObj.lm || {}).length
                    });
                    setData(dataObj);
                } else {
                    console.warn('No data object in response!');
                }
                console.log('Prompt length:', response.data.prompt.length);
                console.log('=== END DEBUG ===');
            } else {
                console.error('No prompt in response!', response.data);
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
                            {/* Информация о структуре данных */}
                            {data && (
                                <div className="bg-blue-50 border border-blue-200 rounded p-4">
                                    <h3 className="text-sm font-semibold text-blue-800 mb-3">Включенные данные в промпт:</h3>
                                    <div className="grid grid-cols-2 gap-2 text-xs">
                                        <div className="flex items-center gap-2">
                                            <span className={`w-2 h-2 rounded-full ${data.li ? 'bg-green-500' : 'bg-gray-300'}`}></span>
                                            <span>Информация о лиге</span>
                                            {data.li && <span className="text-gray-500">({data.li.tt} команд)</span>}
                                        </div>
                                        <div className="flex items-center gap-2">
                                            <span className={`w-2 h-2 rounded-full ${data.t && data.t.length > 0 ? 'bg-green-500' : 'bg-gray-300'}`}></span>
                                            <span>Команды</span>
                                            {data.t && <span className="text-gray-500">({data.t.length})</span>}
                                        </div>
                                        <div className="flex items-center gap-2">
                                            <span className={`w-2 h-2 rounded-full ${data.p && data.p.length > 0 ? 'bg-green-500' : 'bg-gray-300'}`}></span>
                                            <span>Игроки</span>
                                            {data.p && <span className="text-gray-500">({data.p.length})</span>}
                                        </div>
                                        <div className="flex items-center gap-2">
                                            <span className={`w-2 h-2 rounded-full ${data.fa && data.fa.length > 0 ? 'bg-green-500' : 'bg-gray-300'}`}></span>
                                            <span>Свободные агенты</span>
                                            {data.fa && <span className="text-gray-500">({data.fa.length})</span>}
                                        </div>
                                        <div className="flex items-center gap-2">
                                            <span className={`w-2 h-2 rounded-full ${data.sim && (data.sim.by_avg || data.sim.by_z_score) ? 'bg-green-500' : 'bg-yellow-500'}`}></span>
                                            <span>Симуляции</span>
                                            {data.sim && (
                                                <span className="text-gray-500">
                                                    ({data.sim.by_avg?.r?.length || 0} avg, {data.sim.by_z_score?.r?.length || 0} z-score)
                                                </span>
                                            )}
                                        </div>
                                        <div className="flex items-center gap-2">
                                            <span className={`w-2 h-2 rounded-full ${data.cr && Object.keys(data.cr).length > 0 ? 'bg-green-500' : 'bg-yellow-500'}`}></span>
                                            <span>Рейтинги категорий</span>
                                            {data.cr && <span className="text-gray-500">({Object.keys(data.cr).length} категорий)</span>}
                                        </div>
                                        <div className="flex items-center gap-2">
                                            <span className={`w-2 h-2 rounded-full ${data.mh && data.mh.length > 0 ? 'bg-green-500' : 'bg-yellow-500'}`}></span>
                                            <span>История матчапов</span>
                                            {data.mh && <span className="text-gray-500">({data.mh.length} матчей)</span>}
                                        </div>
                                        <div className="flex items-center gap-2">
                                            <span className={`w-2 h-2 rounded-full ${data.um && data.um.length > 0 ? 'bg-green-500' : 'bg-yellow-500'}`}></span>
                                            <span>Будущие матчапы</span>
                                            {data.um && <span className="text-gray-500">({data.um.length})</span>}
                                        </div>
                                        <div className="flex items-center gap-2">
                                            <span className={`w-2 h-2 rounded-full ${data.lm && Object.keys(data.lm).length > 0 ? 'bg-green-500' : 'bg-gray-300'}`}></span>
                                            <span>Метрики лиги</span>
                                            {data.lm && <span className="text-gray-500">({Object.keys(data.lm).length} категорий)</span>}
                                        </div>
                                    </div>
                                    <p className="text-xs text-gray-600 mt-3">
                                        <span className="w-2 h-2 rounded-full bg-green-500 inline-block mr-1"></span> = данные включены
                                        <span className="w-2 h-2 rounded-full bg-yellow-500 inline-block mr-1 ml-3"></span> = пусто (но структура есть)
                                        <span className="w-2 h-2 rounded-full bg-gray-300 inline-block mr-1 ml-3"></span> = отсутствует
                                    </p>
                                    <button
                                        onClick={() => {
                                            console.log('=== FULL DATA STRUCTURE ===');
                                            console.log(data);
                                            console.log('=== END FULL DATA ===');
                                            alert('Полная структура данных выведена в консоль браузера (F12 -> Console)');
                                        }}
                                        className="mt-2 px-3 py-1 bg-blue-500 text-white text-xs rounded hover:bg-blue-600"
                                    >
                                        Показать полную структуру в консоли
                                    </button>
                                </div>
                            )}
                            
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

