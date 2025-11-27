import React, { useState, useEffect } from 'react';
import TeamBalanceRadar from './TeamBalanceRadar';
import MatchupDetails from './MatchupDetails';
import api from '../api';

const Dashboard = ({ period, setPeriod, puntCategories, setPuntCategories, selectedTeam, setSelectedTeam }) => {
    const [teams, setTeams] = useState([]);
    const [dashboardData, setDashboardData] = useState(null);
    const [loading, setLoading] = useState(true);
    const [excludeIr, setExcludeIr] = useState(false);
    const [compareTeamId, setCompareTeamId] = useState('');
    const [refreshing, setRefreshing] = useState(false);
    const [refreshMessage, setRefreshMessage] = useState(null);

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
            params: { period, exclude_ir: excludeIr }
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
    }, [selectedTeam, period, excludeIr]);

    // Функция обновления данных с API
    const handleRefreshData = async () => {
        setRefreshing(true);
        setRefreshMessage(null);
        
        try {
            const response = await api.post('/refresh-league');
            if (response.data.success) {
                setRefreshMessage({ type: 'success', text: response.data.message });
                
                // Перезагружаем список команд и данные дашборда
                const teamsRes = await api.get('/teams');
                const teamsData = teamsRes.data;
                setTeams(teamsData);
                
                // Если выбранная команда все еще существует, перезагружаем данные
                if (selectedTeam) {
                    const dashboardRes = await api.get(`/dashboard/${selectedTeam}`, {
                        params: { period, exclude_ir: excludeIr }
                    });
                    setDashboardData(dashboardRes.data);
                }
            } else {
                setRefreshMessage({ type: 'error', text: response.data.message });
            }
        } catch (err) {
            console.error('Error refreshing data:', err);
            setRefreshMessage({ type: 'error', text: 'Ошибка при обновлении данных' });
        } finally {
            setRefreshing(false);
            // Скрываем сообщение через 5 секунд
            setTimeout(() => setRefreshMessage(null), 5000);
        }
    };

    if (loading) {
        return <div className="text-center p-8">Загрузка...</div>;
    }

    return (
        <div className="space-y-6">
            {/* Team Selector and Refresh Button */}
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

                <div className="mt-6">
                    <label className="flex items-center gap-2 cursor-pointer bg-gray-100 px-3 py-2 rounded hover:bg-gray-200">
                        <input
                            type="checkbox"
                            checked={excludeIr}
                            onChange={e => setExcludeIr(e.target.checked)}
                        />
                        <span className="font-medium">Исключить IR игроков</span>
                    </label>
                </div>

                <div className="mt-6">
                    <button
                        onClick={handleRefreshData}
                        disabled={refreshing}
                        className={`px-4 py-2 rounded font-medium transition-colors ${
                            refreshing
                                ? 'bg-gray-400 cursor-not-allowed text-white'
                                : 'bg-blue-600 hover:bg-blue-700 text-white'
                        }`}
                    >
                        {refreshing ? 'Обновление...' : 'Обновить данные'}
                    </button>
                </div>
            </div>

            {/* Refresh Message */}
            {refreshMessage && (
                <div className={`p-3 rounded ${
                    refreshMessage.type === 'success' 
                        ? 'bg-green-100 text-green-800 border border-green-300' 
                        : 'bg-red-100 text-red-800 border border-red-300'
                }`}>
                    {refreshMessage.text}
                </div>
            )}

            {dashboardData && (
                <>
                    {/* Summary Cards */}
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
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
                        <div className="flex items-center justify-between mb-4 flex-wrap gap-4">
                            <h3 className="text-lg font-semibold text-gray-700">Баланс команды по категориям</h3>
                            <div className="flex items-center gap-2">
                                <label className="text-sm text-gray-600">Сравнить с:</label>
                                <select
                                    value={compareTeamId}
                                    onChange={(e) => setCompareTeamId(e.target.value)}
                                    className="border p-2 rounded text-sm min-w-[200px]"
                                >
                                    <option value="">Не сравнивать</option>
                                    {teams
                                        .filter(team => team.team_id.toString() !== selectedTeam)
                                        .map(team => (
                                            <option key={team.team_id} value={team.team_id}>
                                                {team.team_name}
                                            </option>
                                        ))}
                                </select>
                            </div>
                        </div>
                        <TeamBalanceRadar
                            teamId={selectedTeam}
                            period={period}
                            puntCategories={puntCategories}
                            excludeIr={excludeIr}
                            compareTeamId={compareTeamId || null}
                            compareTeamName={compareTeamId ? teams.find(t => t.team_id.toString() === compareTeamId)?.team_name : null}
                        />
                    </div>
                </>
            )}
        </div>
    );
};

export default Dashboard;
