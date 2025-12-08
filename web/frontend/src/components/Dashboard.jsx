import React, { useState, useEffect } from 'react';
import TeamHeroCard from './TeamHeroCard';
import MatchupDetails from './MatchupDetails';
import MatchupHistory from './MatchupHistory';
import CategoryRankings from './CategoryRankings';
import PositionHistoryChart from './PositionHistoryChart';
import SeasonProjectionModal from './SeasonProjectionModal';
import api from '../api';
import { saveState, loadState, StorageKeys } from '../utils/statePersistence';

const Dashboard = ({ period, puntCategories, mainTeam, simulationMode }) => {
    const [teams, setTeams] = useState([]);
    const [dashboardData, setDashboardData] = useState(null);
    const [loading, setLoading] = useState(true);
    const [seasonProjection, setSeasonProjection] = useState(null);
    const [projectionLoading, setProjectionLoading] = useState(false);
    const [showProjectionModal, setShowProjectionModal] = useState(false);
    const [compareTeamId, setCompareTeamId] = useState(() => {
        const saved = loadState(StorageKeys.DASHBOARD, {});
        return saved.compareTeamId || '';
    });

    // Загрузка списка команд
    useEffect(() => {
        api.get('/teams')
            .then(res => {
                setTeams(res.data);
            })
            .catch(err => console.error('Error fetching teams:', err));
    }, []);

    // Отслеживаем изменения в localStorage для выбранных игроков
    const [customPlayersKey, setCustomPlayersKey] = useState(0);

    useEffect(() => {
        if (!mainTeam || simulationMode !== 'top_n') return;

        const storageKey = `customTeamPlayers_${mainTeam}`;
        
        // Функция для проверки изменений
        const checkStorage = () => {
            setCustomPlayersKey(prev => prev + 1); // Принудительно обновляем
        };

        // Проверяем при монтировании
        checkStorage();

        // Слушаем события storage (для обновлений из других вкладок)
        window.addEventListener('storage', (e) => {
            if (e.key === storageKey) {
                checkStorage();
            }
        });

        // Слушаем кастомное событие для обновлений в той же вкладке
        window.addEventListener('customTeamPlayersUpdated', (e) => {
            if (e.detail && e.detail.teamId === mainTeam) {
                checkStorage();
            }
        });

        return () => {
            window.removeEventListener('storage', checkStorage);
            window.removeEventListener('customTeamPlayersUpdated', checkStorage);
        };
    }, [mainTeam, simulationMode]);

    // Загрузка данных дашборда
    useEffect(() => {
        if (!mainTeam) return;

        setLoading(true);
        
        // Формируем параметры запроса
        const params = { period, simulation_mode: simulationMode };
        
        // Если режим top_n, добавляем дополнительные параметры
        if (simulationMode === 'top_n') {
            params.top_n_players = 13;
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
        
        api.get(`/dashboard/${mainTeam}`, { params })
            .then(res => res.data)
            .then(data => {
                setDashboardData(data);
                setLoading(false);
            })
            .catch(err => {
                console.error('Error fetching dashboard:', err);
                setLoading(false);
            });
    }, [mainTeam, period, simulationMode, customPlayersKey]);

    // Сохранение состояния при изменении compareTeamId
    useEffect(() => {
        saveState(StorageKeys.DASHBOARD, { compareTeamId });
    }, [compareTeamId]);

    // Загрузка прогноза сезона (не блокирует основной дашборд)
    useEffect(() => {
        if (!mainTeam) {
            setSeasonProjection(null);
            return;
        }

        setProjectionLoading(true);
        
        // Формируем параметры запроса
        const params = { period, simulation_mode: simulationMode };
        
        // Если режим top_n, добавляем дополнительные параметры
        if (simulationMode === 'top_n') {
            params.top_n_players = 13;
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
        
        api.get(`/dashboard/${mainTeam}/season-projection`, { params })
            .then(res => {
                setSeasonProjection(res.data);
                setProjectionLoading(false);
            })
            .catch(err => {
                console.error('Error fetching season projection:', err);
                setSeasonProjection(null);
                setProjectionLoading(false);
            });
    }, [mainTeam, period, simulationMode]);

    if (!mainTeam) {
        return (
            <div className="text-center p-8">
                <p className="text-gray-600">Пожалуйста, выберите основную команду в настройках</p>
            </div>
        );
    }

    if (loading) {
        return <div className="text-center p-8">Загрузка...</div>;
    }

    return (
        <div className="space-y-6">
            {dashboardData && (
                <>
                    {/* Hero Card with Team Name, Position, and Radar */}
                    <TeamHeroCard
                        teamName={dashboardData.team_name}
                        leaguePosition={dashboardData.league_position}
                        teamId={mainTeam}
                        period={period}
                        simulationMode={simulationMode}
                        compareTeamId={compareTeamId}
                        compareTeamName={compareTeamId ? teams.find(t => t.team_id.toString() === compareTeamId)?.team_name : null}
                        teams={teams}
                        onCompareChange={(value) => setCompareTeamId(value)}
                    />

                    {/* Summary Cards */}
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                        {/* Team Stats */}
                        <div className="bg-white border rounded-lg p-6 shadow-sm">
                            <h3 className="text-lg font-semibold text-gray-700 mb-4">Статистика команды</h3>
                            <div className="space-y-3">
                                <div className="flex justify-between items-center">
                                    <span className="text-gray-600">Игроков в ростер:</span>
                                    <span className="font-semibold text-lg">{dashboardData.roster_size}</span>
                                </div>
                                <div className="flex justify-between items-center">
                                    <span className="text-gray-600">Total Z-Score:</span>
                                    <span className="font-semibold text-lg text-blue-600">{dashboardData.total_z_score}</span>
                                </div>
                                {projectionLoading ? (
                                    <div className="flex justify-between items-center">
                                        <span className="text-gray-600">Прогноз места:</span>
                                        <span className="text-sm text-gray-500">Загрузка...</span>
                                    </div>
                                ) : seasonProjection && !seasonProjection.error ? (
                                    <div 
                                        className="flex justify-between items-center cursor-pointer hover:bg-gray-50 -mx-2 px-2 py-1 rounded transition-colors"
                                        onClick={() => setShowProjectionModal(true)}
                                    >
                                        <span className="text-gray-600">Прогноз места:</span>
                                        <span className="font-semibold text-lg text-blue-600">
                                            {seasonProjection.projected_position} / {seasonProjection.total_teams}
                                        </span>
                                    </div>
                                ) : null}
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
                    {dashboardData.current_matchup ? (
                        <MatchupDetails 
                            teamId={mainTeam} 
                            currentMatchup={dashboardData.current_matchup}
                        />
                    ) : (
                        <div className="bg-white border rounded-lg p-6 shadow-sm">
                            <h3 className="text-lg font-semibold text-gray-700 mb-2">
                                Детали матчапа
                            </h3>
                            <p className="text-sm text-gray-600">
                                Данные по текущему матчапу пока недоступны.
                            </p>
                        </div>
                    )}

                    {/* Matchup History */}
                    {mainTeam && (
                        <MatchupHistory teamId={mainTeam} />
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

                    {/* Top 3 Categories */}
                    {mainTeam && (
                        <CategoryRankings 
                            teamId={mainTeam}
                            period={period}
                            simulationMode={simulationMode}
                            showTopOnly={true}
                        />
                    )}

                    {/* Position History Chart */}
                    {mainTeam && (
                        <div className="bg-white border rounded-lg p-6 shadow-sm">
                            <h3 className="text-lg font-semibold text-gray-700 mb-4">Изменение позиции в лиге</h3>
                            <PositionHistoryChart
                                teamId={mainTeam}
                                period={period}
                                simulationMode={simulationMode}
                            />
                        </div>
                    )}

                </>
            )}

            {/* Season Projection Modal */}
            {showProjectionModal && seasonProjection && !seasonProjection.error && (
                <SeasonProjectionModal
                    projection={seasonProjection}
                    onClose={() => setShowProjectionModal(false)}
                />
            )}
        </div>
    );
};

export default Dashboard;
