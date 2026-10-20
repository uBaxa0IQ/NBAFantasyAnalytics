import React, { useState, useEffect } from 'react';
import api from '../api';
import SimulationDetailsModal from './SimulationDetailsModal';
import { saveState, loadState, StorageKeys } from '../utils/statePersistence';

const Simulation = ({ period, simulationMode, mainTeam, calculationEngine = 'calendar' }) => {
    const savedState = loadState(StorageKeys.SIMULATION, {});
    const [weeks, setWeeks] = useState([]);
    const [forecastWeeks, setForecastWeeks] = useState([]);
    const [currentWeek, setCurrentWeek] = useState(null);
    const [selectedWeek, setSelectedWeek] = useState(savedState.selectedWeek || '');
    const [weeksCount, setWeeksCount] = useState(savedState.weeksCount !== undefined ? savedState.weeksCount : null);
    const [results, setResults] = useState(null);
    const [resultsKind, setResultsKind] = useState(null);
    const [calendarView, setCalendarView] = useState(savedState.calendarView === 'week' ? 'week' : 'season');
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
            setForecastWeeks(res.data.forecast_weeks || [res.data.current_week]);
            setCurrentWeek(res.data.current_week);
            setSelectedWeek(current => {
                const week = Number(current);
                if (effectiveSimulationType === 'schedule_projection') {
                    return week >= res.data.current_week && (res.data.forecast_weeks || []).includes(week)
                        ? week : res.data.current_week;
                }
                return week >= 1 && week <= res.data.current_week ? week : res.data.current_week;
            });
            // Используем сохраненное значение или текущую неделю
            setWeeksCount(current => current ?? res.data.current_week);
        });
    }, [effectiveSimulationType]);

    // Сохранение состояния при изменении
    useEffect(() => {
        saveState(StorageKeys.SIMULATION, {
            simulationType: effectiveSimulationType,
            selectedWeek,
            weeksCount,
            calendarView,
        });
    }, [effectiveSimulationType, selectedWeek, weeksCount, calendarView]);

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
                            setResultsKind('matchup');
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
            if (!currentWeek) return;
            let active = true;
            setLoading(true);
            setResults(null);
            const isSeason = calendarView === 'season';
            api.get(isSeason ? '/projections/season' : '/projections/matchups', {
                params: isSeason
                    ? { period, calculation_engine: calculationEngine }
                    : { period, matchup_period: selectedWeek || currentWeek }
            })
                .then(res => {
                    if (!active) return;
                    if (isSeason) {
                        const names = new Map(res.data.standings.map(team => [team.team_id, team.team_name]));
                        setResults(res.data.standings.map(team => ({
                            ...team,
                            name: team.team_name,
                            isSeasonProjection: true,
                            matchups: (team.projected_matchups || []).map(matchup => ({
                                ...matchup,
                                opponent_name: names.get(matchup.opponent_id) || `Команда ${matchup.opponent_id}`,
                            })),
                        })));
                    } else {
                        setResults(res.data.matchups);
                    }
                    setResultsKind(isSeason ? 'schedule_season' : 'schedule_week');
                })
                .catch(err => {
                    if (!active) return;
                    console.error(err);
                    setError('Не удалось построить календарный прогноз.');
                    setResults(null);
                })
                .finally(() => { if (active) setLoading(false); });
            return () => { active = false; };
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
                        setResultsKind(effectiveSimulationType);
                    }
                    setLoading(false);
                })
                .catch(err => {
                    console.error(err);
                    setError('Не удалось загрузить результаты симуляции. Попробуйте позже.');
                    setLoading(false);
                });
        }
    }, [selectedWeek, weeksCount, effectiveSimulationType, calendarView, calculationEngine, period, simulationMode, mainTeam, currentWeek]);

    useEffect(() => {
        let cancelled = false;
        if (calculationEngine !== 'probabilistic' || calendarView !== 'week' || !mainTeam || !currentWeek) {
            setMatchupOdds(null);
            return () => { cancelled = true; };
        }
        api.get('/matchup/odds', { params: { team_id: mainTeam, week: selectedWeek || currentWeek, period, remaining_only: parseInt(selectedWeek || currentWeek, 10) === currentWeek } })
            .then(response => { if (!cancelled) setMatchupOdds(response.data); })
            .catch(() => { if (!cancelled) setMatchupOdds(null); });
        return () => { cancelled = true; };
    }, [calculationEngine, calendarView, mainTeam, selectedWeek, currentWeek, period]);

    // Генерируем опции для количества недель
    const weeksOptions = selectedWeek ? Array.from({ length: parseInt(selectedWeek) }, (_, i) => i + 1) : [];

    const handleTeamClick = (team) => {
        setSelectedTeam(team);
    };

    const formatCategory = (category, value) => {
        if (value == null) return '—';
        return category.endsWith('%') ? `${(value * 100).toFixed(1)}%` : Number(value).toFixed(1);
    };

    const expectedResultsKind = effectiveSimulationType === 'schedule_projection'
        ? `schedule_${calendarView}` : effectiveSimulationType;
    const visibleResults = resultsKind === expectedResultsKind ? results : null;

    const selectSimulationType = (type) => {
        if (type === 'matchup' && Number(selectedWeek) > currentWeek) {
            setSelectedWeek(currentWeek);
        } else if (type === projectionMode && Number(selectedWeek) < currentWeek) {
            setSelectedWeek(currentWeek);
        }
        setSimulationType(type);
    };

    return (
        <div className="p-4">
            <div className="mb-4 flex gap-4 items-center flex-wrap">
                <div className="inline-flex rounded-lg border border-gray-300 bg-white p-1">
                    <button
                        onClick={() => selectSimulationType('matchup')}
                        className={`px-4 py-2 rounded-md font-medium transition-colors ${effectiveSimulationType === 'matchup' ? 'bg-blue-600 text-white' : 'text-gray-700 hover:bg-gray-100'}`}
                    >
                        По матчапам
                    </button>
                    <button
                        onClick={() => selectSimulationType(projectionMode)}
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

                {effectiveSimulationType === 'schedule_projection' && (
                    <div className="inline-flex rounded-lg border border-gray-300 bg-white p-1">
                        <button type="button" onClick={() => setCalendarView('season')}
                            className={`px-4 py-2 rounded-md font-medium ${calendarView === 'season' ? 'bg-blue-600 text-white' : 'text-gray-700 hover:bg-gray-100'}`}>
                            Итог сезона
                        </button>
                        <button type="button" onClick={() => setCalendarView('week')}
                            className={`px-4 py-2 rounded-md font-medium ${calendarView === 'week' ? 'bg-blue-600 text-white' : 'text-gray-700 hover:bg-gray-100'}`}>
                            Неделя
                        </button>
                    </div>
                )}

                {(effectiveSimulationType === 'matchup' || (effectiveSimulationType === 'schedule_projection' && calendarView === 'week')) && (
                    <>
                        <div>
                            <label className="mr-2 font-bold">{effectiveSimulationType === 'matchup' ? 'Неделя статистики:' : 'Неделя прогноза:'}</label>
                            <select
                                className="border p-2 rounded"
                                value={selectedWeek}
                                onChange={e => setSelectedWeek(e.target.value)}
                            >
                                {(effectiveSimulationType === 'matchup' ? weeks : forecastWeeks).map(w => (
                                    <option key={w} value={w}>Неделя {w}</option>
                                ))}
                            </select>
                        </div>

                        {effectiveSimulationType === 'matchup' && <div>
                            <label className="mr-2 font-bold">Усреднить последние:</label>
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
                        </div>}
                    </>
                )}
            </div>

            {loading && <div>Считаем прогноз...</div>}
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

            {visibleResults && effectiveSimulationType === 'schedule_projection' && calendarView === 'week' && (
                <div className="space-y-4">
                    <div className="flex items-center justify-between">
                        <h2 className="text-lg font-semibold text-gray-800">Неделя {selectedWeek || currentWeek}</h2>
                        <span className="text-sm text-gray-500">{visibleResults.length} матчапов</span>
                    </div>
                    {visibleResults.length === 0 && <p className="rounded-xl border bg-white p-5 text-gray-500">На эту неделю нет матчапов.</p>}
                    {[...visibleResults].sort((a, b) => Number(String(b.team1_id) === String(mainTeam) || String(b.team2_id) === String(mainTeam)) - Number(String(a.team1_id) === String(mainTeam) || String(a.team2_id) === String(mainTeam))).map((matchup, index) => {
                        const isMyMatchup = String(mainTeam) === String(matchup.team1_id) || String(mainTeam) === String(matchup.team2_id);
                        return <div key={`${matchup.team1_id}-${matchup.team2_id}`} className={`overflow-hidden rounded-xl border bg-white shadow-sm ${isMyMatchup ? 'border-blue-300' : 'border-gray-200'}`}>
                            <div className="flex items-center justify-between border-b border-gray-100 bg-gray-50 px-5 py-2 text-xs font-medium text-gray-500">
                                <span>Матчап {index + 1}</span>
                                {isMyMatchup && <span className="rounded-full bg-blue-100 px-2.5 py-1 text-blue-700">Ваша команда</span>}
                            </div>
                            <div className="grid grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] items-center gap-3 px-5 py-5">
                                <div className={`min-w-0 text-right font-semibold ${matchup.team1_wins > matchup.team2_wins ? 'text-gray-900' : 'text-gray-600'}`}>{matchup.team1_name}</div>
                                <div className="rounded-lg bg-blue-50 px-4 py-2 text-center text-xl font-bold tabular-nums text-blue-800">{matchup.team1_wins} : {matchup.team2_wins}</div>
                                <div className={`min-w-0 font-semibold ${matchup.team2_wins > matchup.team1_wins ? 'text-gray-900' : 'text-gray-600'}`}>{matchup.team2_name}</div>
                            </div>
                            <details className="border-t border-gray-100 text-sm">
                                <summary className="cursor-pointer px-5 py-3 font-medium text-blue-700 hover:bg-blue-50">Категории</summary>
                                <div className="overflow-x-auto px-5 pb-4">
                                    <table className="min-w-full text-sm">
                                        <thead><tr className="bg-gray-50 text-gray-600"><th className="p-2 text-left">Категория</th><th className="p-2 text-right">{matchup.team1_name}</th><th className="p-2 text-right">{matchup.team2_name}</th></tr></thead>
                                        <tbody>{matchup.categories.map(row => <tr key={row.name} className="border-t border-gray-100"><td className="p-2 font-medium">{row.name}</td><td className={`p-2 text-right tabular-nums ${row.winner === 'win' ? 'font-semibold text-green-700' : ''}`}>{formatCategory(row.name, row.team1)}</td><td className={`p-2 text-right tabular-nums ${row.winner === 'loss' ? 'font-semibold text-green-700' : ''}`}>{formatCategory(row.name, row.team2)}</td></tr>)}</tbody>
                                    </table>
                                </div>
                            </details>
                        </div>;
                    })}
                </div>
            )}

            {visibleResults && !(effectiveSimulationType === 'schedule_projection' && calendarView === 'week') && (
                <div className="overflow-x-auto">
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
                            {visibleResults.map((team, index) => (
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
