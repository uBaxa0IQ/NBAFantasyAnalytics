import React, { useState, useEffect } from 'react';
import api from '../api';

const MatchupDetails = ({ teamId, currentMatchup, period, calculationEngine = 'calendar' }) => {
    const [matchupData, setMatchupData] = useState(null);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);
    const [odds, setOdds] = useState(null);
    const matchupWeek = currentMatchup?.week;

    useEffect(() => {
        let cancelled = false;
        if (!teamId || !matchupWeek) {
            setMatchupData(null);
            return;
        }

        setLoading(true);
        setError(null);
        api.get(`/dashboard/${teamId}/matchup-details`)
            .then(res => res.data)
            .then(data => {
                if (cancelled) return;
                if (data.error) {
                    setError(data.error);
                    setMatchupData(null);
                } else {
                    setMatchupData(data);
                    setError(null);
                }
                setLoading(false);
            })
            .catch(err => {
                if (cancelled) return;
                console.error('Error fetching matchup details:', err);
                setError('Ошибка загрузки данных матчапа');
                setLoading(false);
            });
        if (calculationEngine === 'probabilistic') {
            api.get('/matchup/odds', { params: { team_id: teamId, week: matchupWeek, period, remaining_only: true } })
                .then(response => { if (!cancelled) setOdds(response.data); })
                .catch(() => { if (!cancelled) setOdds(null); });
        } else {
            setOdds(null);
        }
        return () => { cancelled = true; };
    }, [teamId, matchupWeek, period, calculationEngine]);

    const formatValue = (category, value) => {
        if (category === 'FG%' || category === 'FT%' || category === '3PT%') {
            // Проценты: отображаем как десятичную дробь с 4 знаками (например, .4023)
            // Убираем ведущий ноль, если значение меньше 1
            const formatted = value.toFixed(4);
            return formatted.startsWith('0.') ? formatted.substring(1) : formatted;
        } else if (category === 'A/TO') {
            // A/TO: округляем до 3 знаков
            return value.toFixed(3);
        } else {
            // Счетные категории: показываем с одним знаком после запятой
            return value.toFixed(1);
        }
    };

    if (loading) {
        return (
            <div className="bg-white border rounded-lg p-6 shadow-sm">
                <div className="text-center text-gray-500">Загрузка данных матчапа...</div>
            </div>
        );
    }

    if (error) {
        return (
            <div className="bg-white border rounded-lg p-6 shadow-sm">
                <div className="text-center text-red-500">{error}</div>
            </div>
        );
    }

    if (!matchupData) {
        return null;
    }

    return (
        <div className="bg-white border rounded-lg p-6 shadow-sm">
            <div className="flex justify-between items-center mb-4">
                <h3 className="text-lg font-semibold text-gray-700">Детали матчапа</h3>
            </div>

            {odds && (
                <div className="mb-5 rounded-lg border border-blue-200 bg-blue-50 p-4">
                    <div className="flex flex-wrap items-end justify-between gap-3">
                        <div><div className="text-xs text-gray-600">Вероятность победы</div><div className="text-3xl font-bold text-blue-700">{(odds.p_win * 100).toFixed(1)}%</div></div>
                        <div className="text-sm text-gray-700">Ничья {(odds.p_tie * 100).toFixed(1)}% · Поражение {(odds.p_loss * 100).toFixed(1)}%</div>
                    </div>
                    <div className="mt-3 h-2 overflow-hidden rounded bg-red-200"><div className="h-full bg-blue-600" style={{ width: `${odds.p_win * 100}%` }} /></div>
                    {odds.flippable?.length > 0 && <div className="mt-3 text-xs text-gray-600">Категории в борьбе: {odds.flippable.join(', ')}</div>}
                    {odds.categories && (
                        <div className="mt-4 grid gap-2 sm:grid-cols-2">
                            {Object.entries(odds.categories).map(([category, probability]) => (
                                <div key={category} className="rounded border border-blue-100 bg-white p-2">
                                    <div className="mb-1 flex justify-between text-xs">
                                        <span className="font-medium text-gray-700">{category}</span>
                                        <span className="text-gray-600">{(probability.p_win * 100).toFixed(0)}%</span>
                                    </div>
                                    <div className="h-1.5 overflow-hidden rounded bg-red-100">
                                        <div className="h-full bg-blue-500" style={{ width: `${probability.p_win * 100}%` }} />
                                    </div>
                                </div>
                            ))}
                        </div>
                    )}
                    <div className="mt-2 text-xs text-gray-500">{odds.trials} сценариев · оценка модели, не гарантия</div>
                </div>
            )}
            
            {/* Заголовок с командами и счетом */}
            <div className="mb-4 flex items-center justify-between flex-wrap gap-4">
                <div className="flex-1 min-w-[200px]">
                    <div className="font-bold text-lg">{matchupData.my_team.name}</div>
                    {matchupData.my_team.overall_record && (
                        <div className="text-sm text-gray-600">
                            {matchupData.my_team.overall_record}
                            {matchupData.my_team.rank && (
                                <span className="ml-1">, {matchupData.my_team.rank} место</span>
                            )}
                        </div>
                    )}
                    <div className="text-xs text-gray-500 mt-1">Неделя {matchupData.week}</div>
                </div>
                <div className="text-center">
                    <div className="text-2xl font-bold text-blue-600">
                        {matchupData.score}
                    </div>
                    <div className="text-xs text-gray-500">Счет матчапа</div>
                </div>
                <div className="flex-1 min-w-[200px] text-right">
                    <div className="font-bold text-lg">{matchupData.opponent.name}</div>
                    {matchupData.opponent.overall_record && (
                        <div className="text-sm text-gray-600">
                            {matchupData.opponent.overall_record}
                            {matchupData.opponent.rank && (
                                <span className="ml-1">, {matchupData.opponent.rank} место</span>
                            )}
                        </div>
                    )}
                    <div className="text-xs text-gray-500 mt-1">Соперник</div>
                </div>
            </div>

            {/* Таблица сравнения всегда открыта */}
            <div className="mt-4 overflow-x-auto">
                <table className="min-w-full">
                    <thead>
                        <tr className="bg-gray-100 border-b">
                            <th className="px-4 py-3 text-left text-sm font-semibold text-gray-700">Категория</th>
                            <th className="px-4 py-3 text-center text-sm font-semibold text-gray-700">
                                {matchupData.my_team.name}
                            </th>
                            <th className="px-4 py-3 text-center text-sm font-semibold text-gray-700">
                                {matchupData.opponent.name}
                            </th>
                        </tr>
                    </thead>
                    <tbody>
                        {matchupData.categories.map((item, idx) => {
                            const myWins = item.winner === 'my_team';
                            const opponentWins = item.winner === 'opponent';
                            const isTie = item.winner === 'tie';

                            return (
                                <tr 
                                    key={item.category} 
                                    className={`border-b hover:bg-gray-50 ${
                                        idx % 2 === 0 ? 'bg-white' : 'bg-gray-50'
                                    }`}
                                >
                                    <td className="px-4 py-3 text-sm font-medium text-gray-700">
                                        {item.category}
                                    </td>
                                    <td className={`px-4 py-3 text-center text-sm font-semibold ${
                                        myWins ? 'bg-green-100 text-green-800' : 
                                        isTie ? 'bg-gray-100 text-gray-600' : 
                                        'text-gray-700'
                                    }`}>
                                        {formatValue(item.category, item.my_value)}
                                    </td>
                                    <td className={`px-4 py-3 text-center text-sm font-semibold ${
                                        opponentWins ? 'bg-green-100 text-green-800' : 
                                        isTie ? 'bg-gray-100 text-gray-600' : 
                                        'text-gray-700'
                                    }`}>
                                        {formatValue(item.category, item.opponent_value)}
                                    </td>
                                </tr>
                            );
                        })}
                    </tbody>
                </table>
            </div>
        </div>
    );
};

export default MatchupDetails;
