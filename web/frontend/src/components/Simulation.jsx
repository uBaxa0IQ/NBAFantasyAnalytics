import React, { useState, useEffect } from 'react';
import api from '../api';
import SimulationDetailsModal from './SimulationDetailsModal';
import { saveState, loadState, StorageKeys } from '../utils/statePersistence';

const Simulation = ({ period, simulationMode, mainTeam, calculationEngine = 'calendar' }) => {
    const savedState = loadState(StorageKeys.SIMULATION, {});
    const [weeks, setWeeks] = useState([]);
    const [currentWeek, setCurrentWeek] = useState(1);
    const [selectedWeek, setSelectedWeek] = useState(savedState.selectedWeek || '');
    const [weeksCount, setWeeksCount] = useState(savedState.weeksCount !== undefined ? savedState.weeksCount : null);
    const [results, setResults] = useState(null);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);
    const [matchupOdds, setMatchupOdds] = useState(null);
    const savedSimulationType = savedState.simulationType === 'team_stats_avg' ? 'schedule_projection' : savedState.simulationType;
    const [simulationType, setSimulationType] = useState(savedSimulationType || 'schedule_projection');
    const projectionMode = calculationEngine === 'legacy' ? 'team_stats_avg' : 'schedule_projection';
    const effectiveSimulationType = ['schedule_projection', 'team_stats_avg'].includes(simulationType)
        ? projectionMode
        : simulationType;
    const [selectedTeam, setSelectedTeam] = useState(null);  // Для модального окна

    useEffect(() => {
        api.get('/weeks').then(res => {
            setWeeks(res.data.weeks);
            setCurrentWeek(res.data.current_week);
            // Используем сохраненное значение или текущую неделю
            setSelectedWeek(current => current || res.data.current_week);
            // Используем сохраненное значение или текущую неделю
            setWeeksCount(current => current ?? res.data.current_week);
        });
    }, []);

    // Сохранение состояния при изменении
    useEffect(() => {
        saveState(StorageKeys.SIMULATION, {
            simulationType: effectiveSimulationType,
            selectedWeek,
            weeksCount
        });
    }, [effectiveSimulationType, selectedWeek, weeksCount]);

    useEffect(() => {
        // каждый новый запрос сбрасывает предыдущую ошибку
        setError(null);

        if (effectiveSimulationType === 'matchup') {
            // Для режима matchup нужны недели
            if (selectedWeek && weeksCount !== null) {
                setLoading(true);
                // Для режима matchup не используем simulation_mode (он работает по матчапам)
                api.get(`/simulation-detailed/${selectedWeek}?weeks_count=${weeksCount}&mode=matchup&simulation_mode=${simulationMode}`)
                    .then(res => {
                        if (res.data && res.data.error) {
                            // Для случая отсутствия статистики за выбранную неделю
                            if (res.data.error === 'No stats found' && parseInt(selectedWeek, 10) === currentWeek) {
                                setError('Симуляция по матчапам для текущей недели пока недоступна.');
                            } else {
                                setError(res.data.error);
                            }
                            setResults(null);
                        } else {
                            setResults(res.data.results);
                        }
                        setLoading(false);
                    })
                    .catch(err => {
                        console.error(err);
                        // Если это текущая неделя, даём более понятное сообщение
                        if (parseInt(selectedWeek, 10) === currentWeek) {
                            setError('Симуляция по матчапам для текущей недели пока недоступна или произошла ошибка. Попробуйте выбрать прошлую неделю или зайдите позже.');
                        } else {
                            setError('Не удалось загрузить результаты симуляции. Попробуйте позже.');
                        }
                        setLoading(false);
                    });
            }
        } else if (effectiveSimulationType === 'schedule_projection') {
            setLoading(true);
            api.get('/projections/league', {
                params: {
                    period,
                    matchup_period: selectedWeek || currentWeek,
                    remaining_only: parseInt(selectedWeek || currentWeek, 10) === currentWeek
                }
            })
                .then(res => setResults(res.data.results))
                .catch(err => {
                    console.error(err);
                    setError('Не удалось построить календарный прогноз.');
                    setResults(null);
                })
                .finally(() => setLoading(false));
        } else {
            // Для других режимов нужен период
            setLoading(true);
            
            // Формируем параметры запроса
            const params = {
                mode: effectiveSimulationType,
                period: period,
                simulation_mode: simulationMode
            };
            
            // Если режим top_n, добавляем дополнительные параметры
            if (simulationMode === 'top_n') {
                params.top_n_players = 13;
                if (mainTeam) {
                    params.custom_team_id = mainTeam;
                    // Загружаем выбранных игроков из localStorage
                    const saved = localStorage.getItem(`customTeamPlayers_${mainTeam}`);
                    if (saved) {
                        try {
                            const customPlayers = JSON.parse(saved);
                            if (customPlayers.length > 0) {
                                params.custom_team_players = customPlayers.join(',');
                            }
                        } catch (e) {
                            console.error('Error parsing custom players:', e);
                        }
                    }
                }
            }
            
            // Формируем query string
            const queryString = Object.entries(params)
                .map(([key, value]) => `${key}=${encodeURIComponent(value)}`)
                .join('&');
            
            api.get(`/simulation-detailed/1?${queryString}`)
                .then(res => {
                    if (res.data && res.data.error) {
                        setError(res.data.error);
                        setResults(null);
                    } else {
                        setResults(res.data.results);
                    }
                    setLoading(false);
                })
                .catch(err => {
                    console.error(err);
                    setError('Не удалось загрузить результаты симуляции. Попробуйте позже.');
                    setLoading(false);
                });
        }
    }, [selectedWeek, weeksCount, effectiveSimulationType, period, simulationMode, mainTeam, currentWeek]);

    useEffect(() => {
        let cancelled = false;
        if (calculationEngine !== 'probabilistic' || !mainTeam || !currentWeek) {
            setMatchupOdds(null);
            return () => { cancelled = true; };
        }
        api.get('/matchup/odds', { params: { team_id: mainTeam, week: selectedWeek || currentWeek, period, remaining_only: parseInt(selectedWeek || currentWeek, 10) === currentWeek } })
            .then(response => { if (!cancelled) setMatchupOdds(response.data); })
            .catch(() => { if (!cancelled) setMatchupOdds(null); });
        return () => { cancelled = true; };
    }, [calculationEngine, mainTeam, selectedWeek, currentWeek, period]);

    // Генерируем опции для количества недель
    const weeksOptions = selectedWeek ? Array.from({ length: parseInt(selectedWeek) }, (_, i) => i + 1) : [];

    const handleTeamClick = (team) => {
        setSelectedTeam(team);
    };

    return (
        <div className="p-4">
            <div className="mb-4 flex gap-4 items-center flex-wrap">
                <div className="inline-flex rounded-lg border border-gray-300 bg-white p-1">
                    <button
                        onClick={() => setSimulationType('matchup')}
                        className={`px-4 py-2 rounded-md font-medium transition-colors ${effectiveSimulationType === 'matchup' ? 'bg-blue-600 text-white' : 'text-gray-700 hover:bg-gray-100'}`}
                    >
                        По матчапам
                    </button>
                    <button
                        onClick={() => setSimulationType(projectionMode)}
                        className={`px-4 py-2 rounded-md font-medium transition-colors ${effectiveSimulationType === projectionMode ? 'bg-blue-600 text-white' : 'text-gray-700 hover:bg-gray-100'}`}
                    >
                        {calculationEngine === 'legacy' ? 'По средним значениям' : calculationEngine === 'probabilistic' ? 'Вероятностный прогноз' : 'Прогноз по календарю'}
                    </button>
                    <button
                        onClick={() => setSimulationType('z_scores')}
                        className={`px-4 py-2 rounded-md font-medium transition-colors ${effectiveSimulationType === 'z_scores' ? 'bg-blue-600 text-white' : 'text-gray-700 hover:bg-gray-100'}`}
                    >
                        По Z-score
                    </button>
                </div>

                {(effectiveSimulationType === 'matchup' || effectiveSimulationType === 'schedule_projection') && (
                    <>
                        {effectiveSimulationType === 'matchup' && <div>
                            <label className="mr-2 font-bold">Выберите неделю:</label>
                            <select
                                className="border p-2 rounded"
                                value={selectedWeek}
                                onChange={e => setSelectedWeek(e.target.value)}
                            >
                                {weeks.map(w => (
                                    <option key={w} value={w}>Неделя {w}</option>
                                ))}
                            </select>
                        </div>}

                        <div>
                            <label className="mr-2 font-bold">Средние за:</label>
                            <select
                                className="border p-2 rounded"
                                value={weeksCount || ''}
                                onChange={e => setWeeksCount(parseInt(e.target.value))}
                            >
                                {weeksOptions.map(n => (
                                    <option key={n} value={n}>
                                        {n === parseInt(selectedWeek) ? `${n} недель (все)` : `${n} ${n === 1 ? 'неделю' : n < 5 ? 'недели' : 'недель'}`}
                                    </option>
                                ))}
                            </select>
                        </div>
                    </>
                )}
            </div>

            {loading && <div>Симуляция матчапов...</div>}
            {error && !loading && (
                <div className="mb-4 text-sm text-yellow-700 bg-yellow-50 border border-yellow-200 rounded p-3">
                    {error}
                </div>
            )}

            {matchupOdds && (
                <div className="mb-4 rounded-lg border border-blue-200 bg-blue-50 p-4">
                    <div className="text-sm text-gray-600">{matchupOdds.team1_name} — {matchupOdds.team2_name}</div>
                    <div className="mt-1 text-2xl font-bold text-blue-700">P(win) {(matchupOdds.p_win * 100).toFixed(1)}%</div>
                    <div className="text-xs text-gray-600">Ничья {(matchupOdds.p_tie * 100).toFixed(1)}% · поражение {(matchupOdds.p_loss * 100).toFixed(1)}% · {matchupOdds.trials} сценариев</div>
                    {matchupOdds.flippable?.length > 0 && <div className="mt-2 text-xs text-gray-600">Категории в борьбе: {matchupOdds.flippable.join(', ')}</div>}
                </div>
            )}

            {results && (
                <div className="overflow-x-auto">
                    {calculationEngine === 'probabilistic' && (
                        <div className="mb-2 text-xs text-gray-500">Таблица ниже — календарная проверка силы против всей лиги; персональный прогноз находится в карточке выше.</div>
                    )}
                    <table className="min-w-full bg-white border">
                        <thead>
                            <tr className="bg-gray-100">
                                <th className="p-2 border text-center">Ранг</th>
                                <th className="p-2 border text-left">Команда</th>
                                <th className="p-2 border text-center">Победы</th>
                                <th className="p-2 border text-center">Поражения</th>
                                <th className="p-2 border text-center">Ничьи</th>
                                <th className="p-2 border text-center">Винрейт</th>
                            </tr>
                        </thead>
                        <tbody>
                            {results.map((team, index) => (
                                <tr
                                    key={team.name}
                                    className="hover:bg-blue-50 cursor-pointer transition-colors"
                                    onClick={() => handleTeamClick(team)}
                                >
                                    <td className="p-2 border text-center font-bold">{index + 1}</td>
                                    <td className="p-2 border font-medium text-blue-600 hover:underline">{team.name}</td>
                                    <td className="p-2 border text-center text-green-600 font-bold">{team.wins}</td>
                                    <td className="p-2 border text-center text-red-600">{team.losses}</td>
                                    <td className="p-2 border text-center text-gray-500">{team.ties}</td>
                                    <td className="p-2 border text-center font-bold">{team.win_rate}%</td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            )}

            {selectedTeam && (
                <SimulationDetailsModal
                    team={selectedTeam}
                    onClose={() => setSelectedTeam(null)}
                />
            )}
        </div>
    );
};

export default Simulation;
