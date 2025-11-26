import React, { useState, useEffect } from 'react';
import api from '../api';
import SimulationDetailsModal from './SimulationDetailsModal';

const Simulation = () => {
    const [weeks, setWeeks] = useState([]);
    const [currentWeek, setCurrentWeek] = useState(1);
    const [selectedWeek, setSelectedWeek] = useState('');
    const [weeksCount, setWeeksCount] = useState(null);  // null = текущая неделя (все недели)
    const [results, setResults] = useState(null);
    const [loading, setLoading] = useState(false);
    const [simulationMode, setSimulationMode] = useState('matchup'); // 'matchup', 'team_stats_avg', 'z_scores'
    const [period, setPeriod] = useState('2026_total');
    const [selectedTeam, setSelectedTeam] = useState(null);  // Для модального окна
    const [excludeIr, setExcludeIr] = useState(false);

    useEffect(() => {
        api.get('/weeks').then(res => {
            setWeeks(res.data.weeks);
            setCurrentWeek(res.data.current_week);
            setSelectedWeek(res.data.current_week);
            setWeeksCount(res.data.current_week);  // По умолчанию - все недели
        });
    }, []);

    useEffect(() => {
        if (simulationMode === 'matchup') {
            // Для режима matchup нужны недели
            if (selectedWeek && weeksCount !== null) {
                setLoading(true);
                api.get(`/simulation-detailed/${selectedWeek}?weeks_count=${weeksCount}&mode=matchup&exclude_ir=${excludeIr}`)
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
            api.get(`/simulation-detailed/1?mode=${simulationMode}&period=${period}&exclude_ir=${excludeIr}`)
                .then(res => {
                    setResults(res.data.results);
                    setLoading(false);
                })
                .catch(err => {
                    console.error(err);
                    setLoading(false);
                });
        }
    }, [selectedWeek, weeksCount, simulationMode, period, excludeIr]);

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

                {simulationMode === 'matchup' ? (
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
                ) : (
                    <div>
                        <label className="mr-2 font-bold">Период:</label>
                        <select className="border p-2 rounded" value={period} onChange={e => setPeriod(e.target.value)}>
                            <option value="2026_total">Весь сезон</option>
                            <option value="2026_last_30">Последние 30 дней</option>
                            <option value="2026_last_15">Последние 15 дней</option>
                            <option value="2026_last_7">Последние 7 дней</option>
                            <option value="2026_projected">Прогноз</option>
                        </select>
                    </div>
                )}

                <label className="flex items-center gap-2 cursor-pointer bg-gray-100 px-3 py-2 rounded hover:bg-gray-200">
                    <input
                        type="checkbox"
                        checked={excludeIr}
                        onChange={e => setExcludeIr(e.target.checked)}
                    />
                    <span className="font-medium">Исключить IR игроков</span>
                </label>
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

