import React, { useState, useEffect } from 'react';
import TeamHeroCard from './TeamHeroCard';
import MatchupDetails from './MatchupDetails';
import MatchupHistory from './MatchupHistory';
import CategoryRankings from './CategoryRankings';
import PositionHistoryChart from './PositionHistoryChart';
import TeamTrendsChart from './TeamTrendsChart';
import SeasonProjectionModal from './SeasonProjectionModal';
import PuntAdvisor from './PuntAdvisor';
import LineupOptimizerModal from './LineupOptimizerModal';
import api from '../api';
import { saveState, loadState, StorageKeys } from '../utils/statePersistence';

const Dashboard = ({ period, mainTeam, simulationMode, isPlayoff, calculationEngine = 'calendar', puntCategories = [], onApplyPuntStrategy }) => {
    const [teams, setTeams] = useState([]);
    const [dashboardData, setDashboardData] = useState(null);
    const [loading, setLoading] = useState(true);
    const [seasonProjection, setSeasonProjection] = useState(null);
    const [projectionLoading, setProjectionLoading] = useState(false);
    const [engineValidation, setEngineValidation] = useState(null);
    const [showProjectionModal, setShowProjectionModal] = useState(false);
    const [showLineupOptimizer, setShowLineupOptimizer] = useState(false);
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
        const params = { period, simulation_mode: simulationMode, calculation_engine: calculationEngine };
        
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
    }, [mainTeam, period, simulationMode, customPlayersKey, calculationEngine]);

    // Сохранение состояния при изменении compareTeamId
    useEffect(() => {
        saveState(StorageKeys.DASHBOARD, { compareTeamId });
    }, [compareTeamId]);

    // Загрузка прогноза сезона (не блокирует основной дашборд). В плей-офф данные показываем как «итоги регулярки».
    useEffect(() => {
        if (!mainTeam) {
            setSeasonProjection(null);
            return;
        }

        setProjectionLoading(true);
        
        // Формируем параметры запроса
        const params = { period, simulation_mode: simulationMode, calculation_engine: calculationEngine };
        
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
    }, [mainTeam, period, simulationMode, isPlayoff, calculationEngine]);

    useEffect(() => {
        if (calculationEngine !== 'probabilistic') {
            setEngineValidation(null);
            return;
        }
        api.get('/projections/validation')
            .then(response => setEngineValidation(response.data))
            .catch(() => setEngineValidation(null));
    }, [calculationEngine]);

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
                                    <span className="text-gray-600">Здоровых игроков:</span>
                                    <span className="font-semibold text-lg">
                                        {dashboardData.healthy_players_count !== undefined 
                                            ? `${dashboardData.healthy_players_count} / ${dashboardData.roster_size}`
                                            : dashboardData.roster_size
                                        }
                                    </span>
                                </div>
                                <div className="flex justify-between items-center">
                                    <span className="text-gray-600">Total Z-Score:</span>
                                    <span className="font-semibold text-lg text-blue-600">{dashboardData.total_z_score}</span>
                                </div>
                                {projectionLoading ? (
                                    <div className="flex justify-between items-center">
                                        <span className="text-gray-600">{isPlayoff ? 'Место по итогам регулярки:' : 'Прогноз места:'}</span>
                                        <span className="text-sm text-gray-500">Загрузка...</span>
                                    </div>
                                ) : (seasonProjection && !seasonProjection.error) || (isPlayoff && dashboardData?.league_position) ? (
                                    <div 
                                        className="flex justify-between items-center cursor-pointer hover:bg-gray-50 -mx-2 px-2 py-1 rounded transition-colors"
                                        onClick={() => (seasonProjection && !seasonProjection.error) && setShowProjectionModal(true)}
                                    >
                                        <span className="text-gray-600">{isPlayoff ? 'Место по итогам регулярки:' : 'Прогноз места:'}</span>
                                        <span className="font-semibold text-lg text-blue-600">
                                            {isPlayoff && dashboardData?.league_position != null
                                                ? `${dashboardData.league_position} / ${teams.length || 14}`
                                                : seasonProjection
                                                    ? `${seasonProjection.projected_position} / ${seasonProjection.total_teams}`
                                                    : '—'}
                                        </span>
                                    </div>
                                ) : null}
                                {seasonProjection?.p_playoff != null && !isPlayoff && (
                                    <div className="flex justify-between items-center">
                                        <span className="text-gray-600">Шанс плей-офф:</span>
                                        <span className="font-semibold text-blue-600">{(seasonProjection.p_playoff * 100).toFixed(1)}%</span>
                                    </div>
                                )}
                            </div>
                        </div>

                        <button
                            type="button"
                            onClick={() => setShowLineupOptimizer(true)}
                            className="w-full rounded-lg bg-blue-600 px-4 py-3 font-semibold text-white hover:bg-blue-700"
                        >
                            Оптимизировать состав
                        </button>

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

                    <PuntAdvisor
                        teamId={mainTeam}
                        period={period}
                        activePunts={puntCategories}
                        onApply={onApplyPuntStrategy}
                    />

                    {engineValidation && (
                        <div className="mb-4 rounded-lg border border-gray-200 bg-gray-50 p-4 text-sm">
                            <div className="font-semibold text-gray-700">Точность вероятностного движка</div>
                            <div className="mt-1 text-gray-600">
                                Проверено матчапов: {engineValidation.resolved}
                                {engineValidation.brier_score != null && ` · Brier ${engineValidation.brier_score.toFixed(3)}`}
                                {engineValidation.matchup_accuracy != null && ` · точность исхода ${(engineValidation.matchup_accuracy * 100).toFixed(1)}%`}
                            </div>
                            {!engineValidation.resolved && <div className="mt-1 text-xs text-gray-500">Метрики появятся после завершения записанных прогнозов.</div>}
                        </div>
                    )}

                    {/* Matchup Details */}
                    {dashboardData.current_matchup ? (
                        <MatchupDetails 
                            teamId={mainTeam} 
                            currentMatchup={dashboardData.current_matchup}
                            period={period}
                            calculationEngine={calculationEngine}
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

                    {/* Trends Chart */}
                    {dashboardData.trends && (
                        <TeamTrendsChart trends={dashboardData.trends} />
                    )}

                    {/* Position History Chart */}
                    {mainTeam && (
                        <div className="bg-white border rounded-lg p-6 shadow-sm">
                            <h3 className={`text-lg font-semibold text-gray-700 ${isPlayoff ? 'mb-1' : 'mb-4'}`}>Ранг силы all-vs-all по неделям</h3>
                            {isPlayoff && (
                                <p className="text-sm text-gray-500 mb-4">За регулярный сезон (недели 1–16)</p>
                            )}
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
                    isPlayoff={isPlayoff}
                />
            )}
            {showLineupOptimizer && (
                <LineupOptimizerModal
                    teamId={mainTeam}
                    onClose={() => setShowLineupOptimizer(false)}
                    puntCategories={puntCategories}
                    period={period}
                    calculationEngine={calculationEngine}
                />
            )}
        </div>
    );
};

export default Dashboard;
