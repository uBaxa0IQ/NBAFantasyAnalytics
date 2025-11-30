import React, { useState, useEffect } from 'react';
import api from '../api';
import SimulationDetailsModal from './SimulationDetailsModal';
import { saveState, loadState, StorageKeys } from '../utils/statePersistence';

const Simulation = ({ period, excludeIrForSimulations }) => {
    const savedState = loadState(StorageKeys.SIMULATION, {});
    const [weeks, setWeeks] = useState([]);
    const [currentWeek, setCurrentWeek] = useState(1);
    const [selectedWeek, setSelectedWeek] = useState(savedState.selectedWeek || '');
    const [weeksCount, setWeeksCount] = useState(savedState.weeksCount !== undefined ? savedState.weeksCount : null);
    const [results, setResults] = useState(null);
    const [loading, setLoading] = useState(false);
    const [simulationMode, setSimulationMode] = useState(savedState.simulationMode || 'matchup'); // 'matchup', 'team_stats_avg', 'z_scores'
    const [selectedTeam, setSelectedTeam] = useState(null);  // Для модального окна

    useEffect(() => {
        api.get('/weeks').then(res => {
            setWeeks(res.data.weeks);
            setCurrentWeek(res.data.current_week);
            // Используем сохраненное значение или текущую неделю
            if (!selectedWeek) {
                setSelectedWeek(res.data.current_week);
            }
            // Используем сохраненное значение или текущую неделю
            if (weeksCount === null && savedState.weeksCount === undefined) {
                setWeeksCount(res.data.current_week);
            }
        });
    }, []);

    // Сохранение состояния при изменении
    useEffect(() => {
        saveState(StorageKeys.SIMULATION, {
            simulationMode,
            selectedWeek,
            weeksCount
        });
    }, [simulationMode, selectedWeek, weeksCount]);

    useEffect(() => {
        if (simulationMode === 'matchup') {
            // Для режима matchup нужны недели
            if (selectedWeek && weeksCount !== null) {
                setLoading(true);
                api.get(`/simulation-detailed/${selectedWeek}?weeks_count=${weeksCount}&mode=matchup&exclude_ir=${excludeIrForSimulations}`)
                    .then(res => {
                        setResults(res.data.results);
                        setLoading(false);
                    })
                    .catch(err => {
                        console.error(err);
                        setLoading(false);
                    });
            }
        } else {
            // Для других режимов нужен период
            setLoading(true);
            api.get(`/simulation-detailed/1?mode=${simulationMode}&period=${period}&exclude_ir=${excludeIrForSimulations}`)
                .then(res => {
                    setResults(res.data.results);
                    setLoading(false);
                })
                .catch(err => {
                    console.error(err);
                    setLoading(false);
                });
        }
    }, [selectedWeek, weeksCount, simulationMode, period, excludeIrForSimulations]);

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
                        onClick={() => setSimulationMode('matchup')}
                        className={`px-4 py-2 rounded-md font-medium transition-colors ${simulationMode === 'matchup' ? 'bg-blue-600 text-white' : 'text-gray-700 hover:bg-gray-100'}`}
                    >
                        По матчапам
                    </button>
                    <button
                        onClick={() => setSimulationMode('team_stats_avg')}
                        className={`px-4 py-2 rounded-md font-medium transition-colors ${simulationMode === 'team_stats_avg' ? 'bg-blue-600 text-white' : 'text-gray-700 hover:bg-gray-100'}`}
                    >
                        По статистике (avg)
                    </button>
                    <button
                        onClick={() => setSimulationMode('z_scores')}
                        className={`px-4 py-2 rounded-md font-medium transition-colors ${simulationMode === 'z_scores' ? 'bg-blue-600 text-white' : 'text-gray-700 hover:bg-gray-100'}`}
                    >
                        По Z-score
                    </button>
                </div>

                {simulationMode === 'matchup' && (
                    <>
                        <div>
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
                        </div>

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

            {results && (
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

