import React, { useEffect, useMemo, useState } from 'react';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend } from 'recharts';
import api from '../api';
import MatchupDetails from './MatchupDetails';
import PlayoffMatchupModal from './PlayoffMatchupModal';
import { LEAGUE_CATEGORIES as CATEGORIES_ORDER } from '../utils/categories';
const TREND_PERIODS_ORDER = ['Season', 'Last 30', 'Last 15', 'Last 7'];

const BracketSection = ({ title, matchups, seedsByTeamId, onSelect, accent = false }) => {
    if (matchups.length === 0) return null;

    return (
        <div>
            <h3 className="text-lg font-semibold mb-3">{title}</h3>
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                {matchups.map((matchup, idx) => {
                    const team1Seed = seedsByTeamId.get(matchup.team1.id);
                    const team2Seed = seedsByTeamId.get(matchup.team2.id);
                    const seedClass = accent ? 'bg-blue-600 text-white' : 'bg-gray-500 text-white';
                    const scoreClass = accent ? 'text-blue-600' : 'text-gray-700';

                    return (
                        <button
                            type="button"
                            key={`${matchup.team1.id}-${matchup.team2.id}-${idx}`}
                            className="w-full text-left bg-white border rounded-lg p-4 cursor-pointer hover:bg-gray-50 transition-colors"
                            onClick={() => onSelect(matchup)}
                        >
                            <div className="flex items-center justify-between mb-3">
                                <div className="flex items-center gap-2">
                                    <span className={`inline-flex items-center justify-center w-8 h-8 rounded-full text-sm font-bold ${seedClass}`}>
                                        {team1Seed?.seed ?? '—'}
                                    </span>
                                    <div>
                                        <div className="font-semibold">{matchup.team1.name}</div>
                                        {team1Seed && <div className="text-xs text-gray-500">{team1Seed.wins}-{team1Seed.losses}-{team1Seed.ties} ({team1Seed.win_pct}%)</div>}
                                    </div>
                                </div>
                                <div className="text-sm text-gray-500">vs</div>
                                <div className="flex items-center gap-2 text-right">
                                    <div>
                                        <div className="font-semibold">{matchup.team2.name}</div>
                                        {team2Seed && <div className="text-xs text-gray-500">{team2Seed.wins}-{team2Seed.losses}-{team2Seed.ties} ({team2Seed.win_pct}%)</div>}
                                    </div>
                                    <span className={`inline-flex items-center justify-center w-8 h-8 rounded-full text-sm font-bold ${seedClass}`}>
                                        {team2Seed?.seed ?? '—'}
                                    </span>
                                </div>
                            </div>
                            {matchup.score && (
                                <div className="mt-2 flex items-baseline justify-center gap-2">
                                    <span className={`text-2xl font-bold ${scoreClass}`}>{matchup.score.formatted}</span>
                                    <span className="text-xs text-gray-500">счёт по категориям</span>
                                </div>
                            )}
                        </button>
                    );
                })}
            </div>
        </div>
    );
};

const PlayoffAnalysis = ({ period, mainTeam, simulationMode }) => {
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const [data, setData] = useState(null);
    const [subTab, setSubTab] = useState('matchup'); // 'matchup' | 'bracket'
    const [selectedMatchup, setSelectedMatchup] = useState(null);

    const [matchupAnalysisLoading, setMatchupAnalysisLoading] = useState(false);
    const [mainDashboard, setMainDashboard] = useState(null);
    const [opponentDashboard, setOpponentDashboard] = useState(null);
    const [mainCategoryRankings, setMainCategoryRankings] = useState(null);
    const [opponentCategoryRankings, setOpponentCategoryRankings] = useState(null);
    const [showMatchupAnalysisDetails, setShowMatchupAnalysisDetails] = useState(false);

    useEffect(() => {
        const loadBracket = (showLoading = false) => {
            if (showLoading) setLoading(true);
            setError(null);

            api.get('/playoff/bracket')
                .then(res => setData(res.data))
                .catch(err => {
                    console.error('Error fetching playoff bracket:', err);
                    setError('Ошибка загрузки данных плей-офф');
                })
                .finally(() => setLoading(false));
        };

        loadBracket(true);
        const intervalId = setInterval(() => loadBracket(false), 60000);
        return () => clearInterval(intervalId);
    }, []);

    const seedsByTeamId = useMemo(() => {
        if (!data || !data.seeds) return new Map();
        const map = new Map();
        data.seeds.forEach(seed => {
            map.set(seed.team_id, seed);
        });
        return map;
    }, [data]);

    const championshipMatchups = useMemo(() => {
        if (!data || !data.matchups) return [];
        return data.matchups.filter(m => m.type === 'championship');
    }, [data]);

    const placementMatchups = useMemo(() => {
        if (!data || !data.matchups) return [];
        return data.matchups.filter(m => m.type === 'placement');
    }, [data]);

    const consolationMatchups = useMemo(() => {
        if (!data || !data.matchups) return [];
        return data.matchups.filter(m => m.type === 'consolation');
    }, [data]);

    const opponentInfo = useMemo(() => {
        if (!mainTeam || !data?.matchups) return null;
        const mid = parseInt(mainTeam, 10);
        for (const m of data.matchups) {
            if (m.team1.id === mid) return { id: m.team2.id, name: m.team2.name };
            if (m.team2.id === mid) return { id: m.team1.id, name: m.team1.name };
        }
        return null;
    }, [mainTeam, data]);

    useEffect(() => {
        if (subTab !== 'matchup' || !mainTeam || !opponentInfo) {
            setMainDashboard(null);
            setOpponentDashboard(null);
            setMainCategoryRankings(null);
            setOpponentCategoryRankings(null);
            return;
        }

        const params = { period, simulation_mode: simulationMode };
        if (simulationMode === 'top_n') {
            params.top_n_players = 13;
            const saved = localStorage.getItem(`customTeamPlayers_${mainTeam}`);
            if (saved) {
                try {
                    const customPlayers = JSON.parse(saved);
                    if (customPlayers.length > 0) params.custom_team_players = customPlayers.join(',');
                } catch (parseError) {
                    console.warn('Invalid custom roster selection', parseError);
                }
            }
        }

        setMatchupAnalysisLoading(true);
        const opponentId = opponentInfo.id;

        Promise.all([
            api.get(`/dashboard/${mainTeam}`, { params }),
            api.get(`/dashboard/${opponentId}`, { params }),
            api.get(`/dashboard/${mainTeam}/category-rankings`, { params }),
            api.get(`/dashboard/${opponentId}/category-rankings`, { params }),
        ])
            .then(([d1, d2, r1, r2]) => {
                setMainDashboard(d1.data);
                setOpponentDashboard(d2.data);
                setMainCategoryRankings(r1.data);
                setOpponentCategoryRankings(r2.data);
            })
            .catch(err => {
                console.error('Error fetching matchup analysis:', err);
                setMainDashboard(null);
                setOpponentDashboard(null);
                setMainCategoryRankings(null);
                setOpponentCategoryRankings(null);
            })
            .finally(() => setMatchupAnalysisLoading(false));
    }, [subTab, mainTeam, opponentInfo, period, simulationMode]);

    // Вспомогательные функции и данные для таблицы прогноза по средним
    const formatTableVal = (cat, value) => {
        if (value == null) return '—';
        const v = Number(value);
        if (cat === 'FG%' || cat === 'FT%' || cat === '3PT%') return v.toFixed(2);
        if (cat === 'A/TO') return v.toFixed(2);
        return v.toFixed(1);
    };

    const betterForCategory = (cat, mainVal, oppVal) => {
        if (mainVal == null || oppVal == null) return null;
        if (cat === 'TO') return mainVal < oppVal ? 'main' : oppVal < mainVal ? 'opp' : null;
        return mainVal > oppVal ? 'main' : oppVal > mainVal ? 'opp' : null;
    };

    const catRows = useMemo(() => {
        if (!mainCategoryRankings || !opponentCategoryRankings) return [];
        return CATEGORIES_ORDER.map(cat => {
            const mainR = mainCategoryRankings.all_rankings?.find(x => x.category === cat);
            const oppR = opponentCategoryRankings.all_rankings?.find(x => x.category === cat);
            const mainVal = mainR != null ? Number(mainR.value) : null;
            const oppVal = oppR != null ? Number(oppR.value) : null;
            const better = betterForCategory(cat, mainVal, oppVal);
            return { category: cat, mainVal, oppVal, better };
        });
    }, [mainCategoryRankings, opponentCategoryRankings]);

    if (loading) {
        return <div className="text-center p-8 text-gray-600">Загрузка данных плей-офф...</div>;
    }

    if (error) {
        return <div className="text-center p-8 text-red-500">{error}</div>;
    }

    if (!data) {
        return null;
    }

    const { is_playoff, season_complete, current_week, playoff_start_week, round, round_name, playoff_team_count } = data;

    if (!is_playoff && !season_complete) {
        return (
            <div className="p-6">
                <h2 className="text-xl font-semibold mb-2">Плей-офф ещё не начался</h2>
                <p className="text-gray-600">
                    Текущая неделя: {current_week}. Плей-офф стартует с {playoff_start_week}-й недели.
                </p>
            </div>
        );
    }

    return (
        <div className="space-y-6">
            <div className="flex items-center justify-between flex-wrap gap-4">
                <div>
                    <h2 className="text-xl font-semibold">
                        {season_complete ? `Сезон завершён — ${round_name || `раунд ${round}`}` : `Плей-офф — ${round_name || `раунд ${round}`}`}
                    </h2>
                    <p className="text-sm text-gray-600">
                        Matchup period {current_week}. Посевы и тай-брейк получены напрямую из ESPN.
                    </p>
                </div>
                <div className="inline-flex rounded-lg border border-gray-300 bg-white p-1">
                    <button
                        onClick={() => setSubTab('matchup')}
                        className={`px-4 py-2 rounded-md font-medium transition-colors ${
                            subTab === 'matchup'
                                ? 'bg-blue-600 text-white'
                                : 'text-gray-700 hover:bg-gray-100'
                        }`}
                    >
                        Анализ матчапа
                    </button>
                    <button
                        onClick={() => setSubTab('bracket')}
                        className={`px-4 py-2 rounded-md font-medium transition-colors ${
                            subTab === 'bracket'
                                ? 'bg-blue-600 text-white'
                                : 'text-gray-700 hover:bg-gray-100'
                        }`}
                    >
                        Сетка плей-офф
                    </button>
                </div>
            </div>

            {subTab === 'matchup' && (
                <div className="space-y-6">
                    {!mainTeam ? (
                        <div className="bg-white border rounded-lg p-6 shadow-sm">
                            <p className="text-gray-600">
                                Пожалуйста, выберите основную команду в настройках, чтобы увидеть анализ
                                текущего матчапа плей-офф.
                            </p>
                        </div>
                    ) : (
                        <>
                            <MatchupDetails
                                teamId={parseInt(mainTeam, 10)}
                                currentMatchup={{ week: current_week }}
                            />

                            {matchupAnalysisLoading && (
                                <div className="text-center py-4 text-gray-500">Загрузка анализа матчапа...</div>
                            )}

                            {!matchupAnalysisLoading && mainDashboard && opponentDashboard && mainCategoryRankings && opponentCategoryRankings && (
                                <div className="space-y-8">
                                            <div className="space-y-3">
                                                <div className="flex justify-between items-center">
                                                    <h3 className="text-lg font-semibold text-gray-800">Анализ по средним (прогноз)</h3>
                                                    <button
                                                        onClick={() => setShowMatchupAnalysisDetails(prev => !prev)}
                                                        className="text-sm font-medium text-gray-600 hover:text-gray-800 flex items-center gap-2"
                                                    >
                                                        {showMatchupAnalysisDetails ? 'Скрыть анализ' : 'Показать анализ'}
                                                        <span className={`transform transition-transform ${showMatchupAnalysisDetails ? 'rotate-180' : ''}`}>
                                                            ▼
                                                        </span>
                                                    </button>
                                                </div>

                                                {showMatchupAnalysisDetails && (
                                                    <div className="bg-white border border-gray-200 rounded-xl p-6 shadow-sm overflow-x-auto">
                                                        <table className="min-w-full border border-gray-200 text-base">
                                                            <thead>
                                                                <tr className="bg-gray-100 border-b border-gray-200">
                                                                    <th className="px-4 py-3 text-left font-semibold text-gray-800 border-r border-gray-200">Категория</th>
                                                                    <th className="px-4 py-3 text-center font-semibold text-gray-800 border-r border-gray-200">{mainDashboard.team_name}</th>
                                                                    <th className="px-4 py-3 text-center font-semibold text-gray-800">{opponentDashboard.team_name}</th>
                                                                </tr>
                                                            </thead>
                                                            <tbody>
                                                                {catRows.map(({ category, mainVal, oppVal, better }) => (
                                                                    <tr key={category} className="border-b border-gray-100 hover:bg-gray-50">
                                                                        <td className="px-4 py-2.5 font-medium text-gray-800 border-r border-gray-100">{category}</td>
                                                                        <td className={`px-4 py-2.5 text-center border-r border-gray-100 ${better === 'main' ? 'bg-green-100 font-semibold text-green-900' : ''}`}>
                                                                            {formatTableVal(category, mainVal)}
                                                                        </td>
                                                                        <td className={`px-4 py-2.5 text-center ${better === 'opp' ? 'bg-green-100 font-semibold text-green-900' : ''}`}>
                                                                            {formatTableVal(category, oppVal)}
                                                                        </td>
                                                                    </tr>
                                                                ))}
                                                            </tbody>
                                                        </table>
                                                    </div>
                                                )}
                                            </div>

                                            {/* Травмированные — две крупные карточки (всегда видны) */}
                                            <div className="bg-white border border-gray-200 rounded-xl p-8 shadow-sm">
                                                <h3 className="text-xl font-bold text-gray-800 mb-2">Травмированные</h3>
                                                <p className="text-base text-gray-600 mb-6">
                                                    Игроки с ограничениями или в IR у каждой команды.
                                                </p>
                                                <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
                                                    <div className="rounded-xl border-2 border-blue-100 bg-blue-50/30 p-6">
                                                        <div className="text-base font-bold text-blue-800 mb-4">{mainDashboard.team_name}</div>
                                                        {mainDashboard.injured_players?.length > 0 ? (
                                                            <ul className="space-y-3">
                                                                {mainDashboard.injured_players.map((p, idx) => (
                                                                    <li key={idx} className="flex justify-between items-center text-base">
                                                                        <span className="font-medium text-gray-800">{p.name}</span>
                                                                        <span className={`px-3 py-1 rounded-lg text-sm font-semibold ${p.injury_status === 'OUT' ? 'bg-red-200 text-red-900' : p.injury_status === 'DAY_TO_DAY' ? 'bg-yellow-200 text-yellow-900' : 'bg-gray-200 text-gray-800'}`}>
                                                                            {p.injury_status || (p.in_ir ? 'IR' : '—')}
                                                                        </span>
                                                                    </li>
                                                                ))}
                                                            </ul>
                                                        ) : (
                                                            <p className="text-base text-gray-600">Нет травмированных</p>
                                                        )}
                                                    </div>
                                                    <div className="rounded-xl border-2 border-gray-200 bg-gray-50/50 p-6">
                                                        <div className="text-base font-bold text-gray-800 mb-4">{opponentDashboard.team_name}</div>
                                                        {opponentDashboard.injured_players?.length > 0 ? (
                                                            <ul className="space-y-3">
                                                                {opponentDashboard.injured_players.map((p, idx) => (
                                                                    <li key={idx} className="flex justify-between items-center text-base">
                                                                        <span className="font-medium text-gray-800">{p.name}</span>
                                                                        <span className={`px-3 py-1 rounded-lg text-sm font-semibold ${p.injury_status === 'OUT' ? 'bg-red-200 text-red-900' : p.injury_status === 'DAY_TO_DAY' ? 'bg-yellow-200 text-yellow-900' : 'bg-gray-200 text-gray-800'}`}>
                                                                            {p.injury_status || (p.in_ir ? 'IR' : '—')}
                                                                        </span>
                                                                    </li>
                                                                ))}
                                                            </ul>
                                                        ) : (
                                                            <p className="text-base text-gray-600">Нет травмированных</p>
                                                        )}
                                                    </div>
                                                </div>
                                            </div>

                                            {/* Динамика формы (Z-Score) — две команды, как на дашборде, два столбца рядом (всегда видна) */}
                                            <div className="bg-white border border-gray-200 rounded-xl p-6 shadow-sm">
                                                <h3 className="text-lg font-semibold text-gray-700 mb-4">Динамика формы (Z-Score)</h3>
                                                <div className="h-64 w-full">
                                                    {(() => {
                                                        const chartData = TREND_PERIODS_ORDER.map(periodKey => {
                                                            const myZ = mainDashboard.trends?.[periodKey];
                                                            const oppZ = opponentDashboard.trends?.[periodKey];
                                                            return {
                                                                period: periodKey,
                                                                [mainDashboard.team_name]: typeof myZ === 'number' ? myZ : null,
                                                                [opponentDashboard.team_name]: typeof oppZ === 'number' ? oppZ : null,
                                                            };
                                                        }).filter(d => d[mainDashboard.team_name] != null || d[opponentDashboard.team_name] != null);
                                                        const allVals = chartData.flatMap(d => [d[mainDashboard.team_name], d[opponentDashboard.team_name]].filter(Number.isFinite));
                                                        const minV = allVals.length ? Math.min(...allVals) : 0;
                                                        const maxV = allVals.length ? Math.max(...allVals) : 10;
                                                        const domainMin = Math.floor(minV - Math.abs(minV) * 0.1);
                                                        const domainMax = Math.ceil(maxV + Math.abs(maxV) * 0.1);
                                                        return (
                                                            <ResponsiveContainer width="100%" height="100%">
                                                                <BarChart data={chartData} margin={{ top: 20, right: 30, left: 20, bottom: 5 }}>
                                                                    <CartesianGrid strokeDasharray="3 3" vertical={false} />
                                                                    <XAxis dataKey="period" />
                                                                    <YAxis domain={[domainMin, domainMax]} />
                                                                    <Tooltip contentStyle={{ borderRadius: '8px', border: 'none', boxShadow: '0 2px 8px rgba(0,0,0,0.1)' }} cursor={{ fill: 'transparent' }} />
                                                                    <Legend />
                                                                    <Bar dataKey={mainDashboard.team_name} fill="#3b82f6" radius={[4, 4, 0, 0]} name={mainDashboard.team_name} />
                                                                    <Bar dataKey={opponentDashboard.team_name} fill="#6b7280" radius={[4, 4, 0, 0]} name={opponentDashboard.team_name} />
                                                                </BarChart>
                                                            </ResponsiveContainer>
                                                        );
                                                    })()}
                                                </div>
                                                <p className="text-xs text-gray-500 mt-2 text-center">
                                                    Суммарный Z-Score по периодам — две команды для сравнения
                                                </p>
                                            </div>
                                        </div>
                            )}
                        </>
                    )}
                </div>
            )}

            {subTab === 'bracket' && (
                <div className="space-y-6">
                    <BracketSection title="Чемпионский путь" matchups={championshipMatchups} seedsByTeamId={seedsByTeamId} onSelect={setSelectedMatchup} accent />
                    <BracketSection title={`Матчи за места среди Top‑${playoff_team_count}`} matchups={placementMatchups} seedsByTeamId={seedsByTeamId} onSelect={setSelectedMatchup} />
                    <BracketSection title="Утешительный турнир" matchups={consolationMatchups} seedsByTeamId={seedsByTeamId} onSelect={setSelectedMatchup} />
                </div>
            )}

            {selectedMatchup && (
                <PlayoffMatchupModal
                    matchup={selectedMatchup}
                    period={period}
                    simulationMode={simulationMode}
                    onClose={() => setSelectedMatchup(null)}
                />
            )}
        </div>
    );
};

export default PlayoffAnalysis;
