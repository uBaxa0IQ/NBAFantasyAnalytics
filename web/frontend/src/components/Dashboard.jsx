import React, { useState, useEffect } from 'react';
import TeamBalanceRadar from './TeamBalanceRadar';
import MatchupDetails from './MatchupDetails';
import MatchupHistory from './MatchupHistory';
import api from '../api';

const Dashboard = ({ period, setPeriod, puntCategories, setPuntCategories, selectedTeam, setSelectedTeam }) => {
    const [teams, setTeams] = useState([]);
    const [dashboardData, setDashboardData] = useState(null);
    const [loading, setLoading] = useState(true);
    const [refreshStatus, setRefreshStatus] = useState(null);

    // Загрузка списка команд
    useEffect(() => {
        api.get('/teams')
            .then(res => {
                const data = res.data;
                setTeams(data);
                if (!selectedTeam && data.length > 0) {
                    setSelectedTeam(data[0].team_id.toString());
                }
            })
            .catch(err => console.error('Error fetching teams:', err));
    }, []);

    // Загрузка данных дашборда
    useEffect(() => {
        if (!selectedTeam) return;

        setLoading(true);
        api.get(`/dashboard/${selectedTeam}`, {
            params: { period }
        })
            .then(res => res.data)
            .then(data => {
                setDashboardData(data);
                setLoading(false);
            })
            .catch(err => {
                console.error('Error fetching dashboard:', err);
                setLoading(false);
            });
    }, [selectedTeam, period]);

    // Загрузка статуса обновления
    useEffect(() => {
        const loadRefreshStatus = () => {
            api.get('/refresh-status')
                .then(res => {
                    setRefreshStatus(res.data);
                })
                .catch(err => {
                    console.error('Error fetching refresh status:', err);
                });
        };

        loadRefreshStatus();
        // Обновляем статус каждые 30 секунд
        const interval = setInterval(loadRefreshStatus, 30000);
        return () => clearInterval(interval);
    }, []);

    // Форматирование времени последнего обновления
    const formatLastRefresh = (isoString) => {
        if (!isoString) return 'Еще не обновлялось';
        
        const date = new Date(isoString);
        const now = new Date();
        const diffMs = now - date;
        const diffMins = Math.floor(diffMs / 60000);
        const diffSecs = Math.floor((diffMs % 60000) / 1000);

        if (diffMins < 1) {
            return `Только что (${diffSecs} сек назад)`;
        } else if (diffMins < 60) {
            return `${diffMins} мин назад`;
        } else {
            const hours = Math.floor(diffMins / 60);
            return `${hours} ч ${diffMins % 60} мин назад`;
        }
    };

    if (loading) {
        return <div className="text-center p-8">Загрузка...</div>;
    }

    return (
        <div className="space-y-6">
            {/* Team Selector and Refresh Status */}
            <div className="flex gap-4 items-center flex-wrap">
                <div>
                    <label className="block text-sm font-medium mb-2">Выберите команду:</label>
                    <select
                        value={selectedTeam}
                        onChange={(e) => setSelectedTeam(e.target.value)}
                        className="w-full md:w-64 p-2 border rounded"
                    >
                        {teams.map(team => (
                            <option key={team.team_id} value={team.team_id}>
                                {team.team_name}
                            </option>
                        ))}
                    </select>
                </div>

                {/* Индикатор последнего обновления */}
                {refreshStatus && (
                    <div className="mt-6">
                        <div className="bg-gray-50 border rounded px-3 py-2 text-sm">
                            <div className="flex items-center gap-2">
                                <span className="text-gray-600">Последнее обновление:</span>
                                <span className="font-medium text-gray-800">
                                    {refreshStatus.last_refresh_time 
                                        ? formatLastRefresh(refreshStatus.last_refresh_time)
                                        : 'Ожидание первого обновления...'}
                                </span>
                            </div>
                            {refreshStatus.auto_refresh_enabled && (
                                <div className="text-xs text-gray-500 mt-1">
                                    Автообновление каждые {refreshStatus.refresh_interval_minutes} мин
                                </div>
                            )}
                        </div>
                    </div>
                )}
            </div>

            {dashboardData && (
                <>
                    {/* Summary Cards */}
                    <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                        {/* Team Summary */}
                        <div className="bg-white border rounded-lg p-6 shadow-sm">
                            <h3 className="text-lg font-semibold text-gray-700 mb-4">Информация о команде</h3>
                            <div className="space-y-2">
                                <div className="flex justify-between">
                                    <span className="text-gray-600">Название:</span>
                                    <span className="font-semibold">{dashboardData.team_name}</span>
                                </div>
                                <div className="flex justify-between">
                                    <span className="text-gray-600">Игроков:</span>
                                    <span className="font-semibold">{dashboardData.roster_size}</span>
                                </div>
                                <div className="flex justify-between">
                                    <span className="text-gray-600">Total Z-Score:</span>
                                    <span className="font-semibold text-blue-600 text-xl">
                                        {dashboardData.total_z_score}
                                    </span>
                                </div>
                            </div>
                        </div>

                        {/* Current Matchup */}
                        <div className="bg-white border rounded-lg p-6 shadow-sm">
                            <h3 className="text-lg font-semibold text-gray-700 mb-4">Текущий матчап</h3>
                            {dashboardData.current_matchup ? (
                                <div className="space-y-2">
                                    <div className="flex justify-between">
                                        <span className="text-gray-600">Неделя:</span>
                                        <span className="font-semibold">{dashboardData.current_matchup.week}</span>
                                    </div>
                                    <div className="flex justify-between">
                                        <span className="text-gray-600">Соперник:</span>
                                        <span className="font-semibold">{dashboardData.current_matchup.opponent_name}</span>
                                    </div>
                                </div>
                            ) : (
                                <div className="text-gray-500">Нет текущего матчапа</div>
                            )}
                        </div>

                        {/* Injured Players */}
                        <div className="bg-white border rounded-lg p-6 shadow-sm">
                            <h3 className="text-lg font-semibold text-gray-700 mb-4">Травмированные</h3>
                            {dashboardData.injured_players && dashboardData.injured_players.length > 0 ? (
                                <div className="space-y-2 max-h-32 overflow-y-auto">
                                    {dashboardData.injured_players.map((player, idx) => (
                                        <div key={idx} className="flex justify-between items-center text-sm">
                                            <span className="font-medium">{player.name}</span>
                                            <span className={`px-2 py-1 rounded text-xs ${player.injury_status === 'OUT' ? 'bg-red-100 text-red-800' :
                                                player.injury_status === 'DAY_TO_DAY' ? 'bg-yellow-100 text-yellow-800' :
                                                    'bg-gray-100 text-gray-800'
                                                }`}>
                                                {player.injury_status}
                                            </span>
                                        </div>
                                    ))}
                                </div>
                            ) : (
                                <div className="text-gray-500 text-sm">Нет травмированных игроков</div>
                            )}
                        </div>
                    </div>

                    {/* Matchup Details */}
                    {dashboardData.current_matchup && (
                        <MatchupDetails 
                            teamId={selectedTeam} 
                            currentMatchup={dashboardData.current_matchup}
                        />
                    )}

                    {/* Matchup History */}
                    {selectedTeam && (
                        <MatchupHistory teamId={selectedTeam} />
                    )}

                    {/* Top Players */}
                    <div className="bg-white border rounded-lg p-6 shadow-sm">
                        <h3 className="text-lg font-semibold text-gray-700 mb-4">Топ-3 игрока (по Z-Score)</h3>
                        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                            {dashboardData.top_players && dashboardData.top_players.map((player, idx) => (
                                <div key={idx} className="border rounded p-4 bg-gray-50">
                                    <div className="flex items-center justify-between mb-2">
                                        <span className="font-semibold">{player.name}</span>
                                        <span className="text-sm text-gray-600">{player.position}</span>
                                    </div>
                                    <div className="text-2xl font-bold text-blue-600">
                                        {player.total_z.toFixed(2)}
                                    </div>
                                </div>
                            ))}
                        </div>
                    </div>

                    {/* Team Balance Radar */}
                    <div className="bg-white border rounded-lg p-6 shadow-sm">
                        <h3 className="text-lg font-semibold text-gray-700 mb-4">Баланс команды по категориям</h3>
                        <TeamBalanceRadar
                            teamId={selectedTeam}
                            period={period}
                            puntCategories={puntCategories}
                        />
                    </div>
                </>
            )}
        </div>
    );
};

export default Dashboard;
