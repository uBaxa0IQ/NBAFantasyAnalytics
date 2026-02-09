import React, { useEffect, useState } from 'react';
import api from '../api';

const CATEGORIES_ORDER = ['PTS', 'REB', 'AST', 'STL', 'BLK', '3PM', 'DD', 'FG%', 'FT%', '3PT%', 'A/TO'];

const VIEW_FORECAST = 'forecast';
const VIEW_CURRENT = 'current';

const PlayoffMatchupModal = ({ matchup, period, simulationMode, onClose }) => {
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const [team1Ranks, setTeam1Ranks] = useState(null);
    const [team2Ranks, setTeam2Ranks] = useState(null);
    const [viewMode, setViewMode] = useState(VIEW_FORECAST);

    useEffect(() => {
        if (!matchup) return;

        const params = { period, simulation_mode: simulationMode };
        if (simulationMode === 'top_n') {
            params.top_n_players = 13;
        }

        setLoading(true);
        setError(null);

        Promise.all([
            api.get(`/dashboard/${matchup.team1.id}/category-rankings`, { params }),
            api.get(`/dashboard/${matchup.team2.id}/category-rankings`, { params }),
        ])
            .then(([r1, r2]) => {
                setTeam1Ranks(r1.data);
                setTeam2Ranks(r2.data);
            })
            .catch(err => {
                console.error('Error fetching playoff matchup modal data:', err);
                setError('Не удалось загрузить данные для анализа матчапа');
            })
            .finally(() => setLoading(false));
    }, [matchup, period, simulationMode]);

    if (!matchup) return null;

    const formatTableVal = (cat, value) => {
        if (value == null) return '—';
        const v = Number(value);
        if (cat === 'FG%' || cat === 'FT%' || cat === '3PT%') return v.toFixed(2);
        if (cat === 'A/TO') return v.toFixed(2);
        return v.toFixed(1);
    };

    const betterForCategory = (cat, t1Val, t2Val) => {
        if (t1Val == null || t2Val == null) return null;
        if (cat === 'TO') return t1Val < t2Val ? 'team1' : t2Val < t1Val ? 'team2' : null;
        return t1Val > t2Val ? 'team1' : t2Val > t1Val ? 'team2' : null;
    };

    const catRows = (() => {
        if (!team1Ranks || !team2Ranks) return [];
        return CATEGORIES_ORDER.map(cat => {
            const r1 = team1Ranks.all_rankings?.find(x => x.category === cat);
            const r2 = team2Ranks.all_rankings?.find(x => x.category === cat);
            const v1 = r1 != null ? Number(r1.value) : null;
            const v2 = r2 != null ? Number(r2.value) : null;
            const better = betterForCategory(cat, v1, v2);
            return { category: cat, v1, v2, better };
        });
    })();

    let team1Wins = 0;
    let team2Wins = 0;
    let ties = 0;
    catRows.forEach(row => {
        if (row.better === 'team1') team1Wins += 1;
        else if (row.better === 'team2') team2Wins += 1;
        else ties += 1;
    });

    return (
        <div
            className="fixed inset-0 z-[70] flex items-center justify-center bg-black bg-opacity-50"
            onClick={onClose}
        >
            <div
                className="bg-white rounded-xl shadow-2xl max-w-4xl w-full max-h-[90vh] overflow-y-auto m-4"
                onClick={e => e.stopPropagation()}
            >
                <div className="p-6">
                    <div className="flex justify-between items-start mb-4">
                        <div>
                            <h2 className="text-2xl font-bold text-gray-800">
                                Матчап плей-офф
                            </h2>
                            <p className="mt-1 text-sm text-gray-600">
                                Краткий анализ по средним в категориях (текущий период: {period}).
                            </p>
                        </div>
                        <button
                            onClick={onClose}
                            className="text-gray-500 hover:text-gray-700 text-2xl font-bold leading-none"
                        >
                            ×
                        </button>
                    </div>

                    <div className="inline-flex rounded-lg border border-gray-300 bg-gray-100 p-1 mb-4">
                        <button
                            type="button"
                            onClick={() => setViewMode(VIEW_FORECAST)}
                            className={`px-4 py-2 rounded-md text-sm font-medium transition-colors ${
                                viewMode === VIEW_FORECAST ? 'bg-white text-blue-600 shadow' : 'text-gray-600 hover:text-gray-800'
                            }`}
                        >
                            Прогноз (по средним)
                        </button>
                        <button
                            type="button"
                            onClick={() => setViewMode(VIEW_CURRENT)}
                            className={`px-4 py-2 rounded-md text-sm font-medium transition-colors ${
                                viewMode === VIEW_CURRENT ? 'bg-white text-blue-600 shadow' : 'text-gray-600 hover:text-gray-800'
                            }`}
                        >
                            Текущий результат
                        </button>
                    </div>

                    <div className="mb-4 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2">
                        <div className="flex items-center gap-2">
                            <span className="inline-flex items-center justify-center w-7 h-7 rounded-full bg-blue-600 text-white text-sm font-bold">
                                {matchup.team1.seed ?? '—'}
                            </span>
                            <span className="font-semibold text-gray-800">{matchup.team1.name}</span>
                        </div>
                        <div className="text-xs sm:text-sm text-gray-500 text-center">
                            {viewMode === VIEW_FORECAST ? (
                                <>
                                    Прогноз по категориям:{' '}
                                    <span className="font-semibold text-blue-600">
                                        {team1Wins}-{team2Wins}
                                    </span>
                                    {ties > 0 && (
                                        <span className="text-gray-500">
                                            {' '}
                                            (ничьих: {ties})
                                        </span>
                                    )}
                                </>
                            ) : matchup.score ? (
                                <>
                                    Текущий счёт:{' '}
                                    <span className="font-semibold text-blue-600">
                                        {matchup.score.formatted}
                                    </span>
                                    {matchup.score.ties > 0 && (
                                        <span className="text-gray-500">
                                            {' '}
                                            (ничьих: {matchup.score.ties})
                                        </span>
                                    )}
                                </>
                            ) : (
                                <span className="text-gray-500">Данные по текущему счёту пока недоступны</span>
                            )}
                        </div>
                        <div className="flex items-center gap-2 justify-end">
                            <span className="font-semibold text-gray-800 text-right">{matchup.team2.name}</span>
                            <span className="inline-flex items-center justify-center w-7 h-7 rounded-full bg-blue-600 text-white text-sm font-bold">
                                {matchup.team2.seed ?? '—'}
                            </span>
                        </div>
                    </div>

                    {loading && (
                        <div className="py-8 text-center text-gray-500">
                            Загрузка анализа матчапа...
                        </div>
                    )}

                    {error && !loading && (
                        <div className="py-4 text-center text-red-500">
                            {error}
                        </div>
                    )}

                    {viewMode === VIEW_CURRENT && (
                        <p className="text-sm text-gray-500 mb-2">
                            {matchup.score
                                ? 'Счёт по категориям за текущую неделю плей-офф.'
                                : 'Текущий счёт по категориям появится после обновления данных матчапа.'}
                        </p>
                    )}

                    {!loading && !error && viewMode === VIEW_FORECAST && catRows.length > 0 && (
                        <div className="bg-white border border-gray-200 rounded-lg overflow-x-auto">
                            <table className="min-w-full border-collapse">
                                <thead>
                                    <tr className="bg-gray-100 border-b border-gray-200">
                                        <th className="px-4 py-2 text-left text-sm font-semibold text-gray-800 border-r border-gray-200">
                                            Категория
                                        </th>
                                        <th className="px-4 py-2 text-center text-sm font-semibold text-gray-800 border-r border-gray-200">
                                            {matchup.team1.name}
                                        </th>
                                        <th className="px-4 py-2 text-center text-sm font-semibold text-gray-800">
                                            {matchup.team2.name}
                                        </th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {catRows.map(({ category, v1, v2, better }) => (
                                        <tr
                                            key={category}
                                            className="border-b border-gray-100 hover:bg-gray-50"
                                        >
                                            <td className="px-4 py-2 text-sm font-medium text-gray-800 border-r border-gray-100">
                                                {category}
                                            </td>
                                            <td
                                                className={`px-4 py-2 text-sm text-center border-r border-gray-100 ${
                                                    better === 'team1'
                                                        ? 'bg-green-100 font-semibold text-green-900'
                                                        : ''
                                                }`}
                                            >
                                                {formatTableVal(category, v1)}
                                            </td>
                                            <td
                                                className={`px-4 py-2 text-sm text-center ${
                                                    better === 'team2'
                                                        ? 'bg-green-100 font-semibold text-green-900'
                                                        : ''
                                                }`}
                                            >
                                                {formatTableVal(category, v2)}
                                            </td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
};

export default PlayoffMatchupModal;

