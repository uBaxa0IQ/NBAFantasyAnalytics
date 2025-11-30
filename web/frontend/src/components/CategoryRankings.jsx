import React, { useState, useEffect } from 'react';
import api from '../api';

const PERCENTAGE_CATEGORIES = ['FG%', 'FT%', '3PT%', 'A/TO'];

const CategoryRankings = ({ teamId, period, excludeIr, showTopOnly = false }) => {
    const [data, setData] = useState(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const [selectedCategory, setSelectedCategory] = useState(null);
    const [showFullTable, setShowFullTable] = useState(false);

    useEffect(() => {
        if (!teamId) {
            setLoading(false);
            return;
        }

        setLoading(true);
        api.get(`/dashboard/${teamId}/category-rankings`, {
            params: { period, exclude_ir: excludeIr }
        })
            .then(res => {
                setData(res.data);
                setError(null);
                setLoading(false);
            })
            .catch(err => {
                console.error('Error fetching category rankings:', err);
                setError('Ошибка загрузки рейтингов');
                setLoading(false);
            });
    }, [teamId, period, excludeIr]);

    const formatValue = (category, value) => {
        if (PERCENTAGE_CATEGORIES.includes(category)) {
            if (category === 'A/TO') {
                return value.toFixed(2);
            }
            return value.toFixed(1) + '%';
        }
        return value.toFixed(1);
    };

    const getRankColor = (rank, totalTeams) => {
        if (rank <= 3) return 'bg-green-100 text-green-800 border-green-300';
        if (rank <= Math.ceil(totalTeams / 2)) return 'bg-yellow-100 text-yellow-800 border-yellow-300';
        return 'bg-gray-100 text-gray-800 border-gray-300';
    };

    const getRankBadgeColor = (rank) => {
        if (rank === 1) return 'bg-yellow-500 text-white';
        if (rank === 2) return 'bg-gray-400 text-white';
        if (rank === 3) return 'bg-orange-500 text-white';
        return 'bg-gray-300 text-gray-700';
    };

    if (loading) {
        return (
            <div className="text-center p-8">
                <div className="text-gray-500">Загрузка рейтингов...</div>
            </div>
        );
    }

    if (error) {
        return (
            <div className="text-center p-8 text-red-500">
                {error}
            </div>
        );
    }

    if (!data || !data.top_categories || !data.all_rankings) {
        return null;
    }

    return (
        <div className="space-y-6">
            {showTopOnly ? (
                /* Top 3 Categories with Collapsible Table */
                <div className="bg-white border rounded-lg p-6 shadow-sm">
                    <div className="flex justify-between items-center mb-4">
                        <h3 className="text-lg font-semibold text-gray-700">Топ-3 сильных категорий</h3>
                        <button
                            onClick={() => setShowFullTable(!showFullTable)}
                            className="text-gray-500 hover:text-gray-700 text-sm font-medium flex items-center gap-2"
                        >
                            {showFullTable ? 'Скрыть' : 'Показать'} таблицу
                            <span className={`transform transition-transform ${showFullTable ? 'rotate-180' : ''}`}>
                                ▼
                            </span>
                        </button>
                    </div>
                    <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-4">
                        {data.top_categories.map((category, idx) => (
                            <div key={idx} className="border-2 rounded-lg p-6 bg-gradient-to-br from-blue-50 to-white">
                                <div className="flex items-center justify-between mb-3">
                                    <span className="text-2xl font-bold text-gray-800">{category.category}</span>
                                    <span className={`px-3 py-1 rounded-full text-sm font-bold ${getRankBadgeColor(category.rank)}`}>
                                        #{category.rank}
                                    </span>
                                </div>
                                <div className="text-3xl font-bold text-blue-600 mb-2">
                                    {formatValue(category.category, category.value)}
                                </div>
                            </div>
                        ))}
                    </div>

                    {/* Collapsible Table */}
                    {showFullTable && data && data.all_rankings && (
                        <div className="mt-4 overflow-x-auto">
                            <table className="min-w-full bg-white border">
                                <thead>
                                    <tr className="bg-gray-100">
                                        <th className="p-3 border text-left font-semibold">Категория</th>
                                        <th className="p-3 border text-center font-semibold">Позиция</th>
                                        <th className="p-3 border text-center font-semibold">Значение</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {data.all_rankings.map((ranking, idx) => {
                                        const totalTeams = data.category_teams?.[ranking.category]?.length || 0;
                                        return (
                                            <tr 
                                                key={idx} 
                                                className={`hover:bg-gray-50 cursor-pointer ${getRankColor(ranking.rank, totalTeams)}`}
                                                onClick={() => setSelectedCategory(ranking.category)}
                                            >
                                                <td className="p-3 border font-medium">{ranking.category}</td>
                                                <td className="p-3 border text-center">
                                                    <span className={`inline-block px-3 py-1 rounded-full text-sm font-bold ${getRankBadgeColor(ranking.rank)}`}>
                                                        #{ranking.rank}
                                                    </span>
                                                </td>
                                                <td className="p-3 border text-center font-semibold text-lg">
                                                    {formatValue(ranking.category, ranking.value)}
                                                </td>
                                            </tr>
                                        );
                                    })}
                                </tbody>
                            </table>
                        </div>
                    )}
                </div>
            ) : (
                /* Full Rankings Table Only */
                <div className="bg-white border rounded-lg p-6 shadow-sm">
                    <h3 className="text-lg font-semibold text-gray-700 mb-4">Рейтинг по всем категориям</h3>
                    <div className="overflow-x-auto">
                        <table className="min-w-full bg-white border">
                            <thead>
                                <tr className="bg-gray-100">
                                    <th className="p-3 border text-left font-semibold">Категория</th>
                                    <th className="p-3 border text-center font-semibold">Позиция</th>
                                    <th className="p-3 border text-center font-semibold">Значение</th>
                                </tr>
                            </thead>
                            <tbody>
                                {data.all_rankings.map((ranking, idx) => {
                                    const totalTeams = data.category_teams?.[ranking.category]?.length || 0;
                                    return (
                                        <tr 
                                            key={idx} 
                                            className={`hover:bg-gray-50 cursor-pointer ${getRankColor(ranking.rank, totalTeams)}`}
                                            onClick={() => setSelectedCategory(ranking.category)}
                                        >
                                            <td className="p-3 border font-medium">{ranking.category}</td>
                                            <td className="p-3 border text-center">
                                                <span className={`inline-block px-3 py-1 rounded-full text-sm font-bold ${getRankBadgeColor(ranking.rank)}`}>
                                                    #{ranking.rank}
                                                </span>
                                            </td>
                                            <td className="p-3 border text-center font-semibold text-lg">
                                                {formatValue(ranking.category, ranking.value)}
                                            </td>
                                        </tr>
                                    );
                                })}
                            </tbody>
                        </table>
                    </div>
                </div>
            )}

            {/* Category Teams Modal */}
            {selectedCategory && data.category_teams && data.category_teams[selectedCategory] && (
                <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-[60]" onClick={() => setSelectedCategory(null)}>
                    <div className="bg-white rounded-lg shadow-xl max-w-3xl w-full mx-4 max-h-[90vh] overflow-y-auto" onClick={(e) => e.stopPropagation()}>
                        <div className="p-6">
                            <div className="flex justify-between items-center mb-6">
                                <h2 className="text-2xl font-bold text-gray-800">
                                    Рейтинг команд: {selectedCategory}
                                </h2>
                                <button
                                    onClick={() => setSelectedCategory(null)}
                                    className="text-gray-500 hover:text-gray-700 text-2xl font-bold"
                                >
                                    ×
                                </button>
                            </div>

                            <div className="overflow-x-auto">
                                <table className="min-w-full bg-white border">
                                    <thead>
                                        <tr className="bg-gray-100">
                                            <th className="p-3 border text-center font-semibold">Место</th>
                                            <th className="p-3 border text-left font-semibold">Команда</th>
                                            <th className="p-3 border text-center font-semibold">Значение</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {data.category_teams[selectedCategory].map((team, idx) => {
                                            const isMyTeam = team.team_id.toString() === teamId.toString();
                                            return (
                                                <tr 
                                                    key={idx} 
                                                    className={`hover:bg-gray-50 ${isMyTeam ? 'bg-blue-50 font-semibold' : ''}`}
                                                >
                                                    <td className="p-3 border text-center">
                                                        <span className={`inline-block px-3 py-1 rounded-full text-sm font-bold ${getRankBadgeColor(team.rank)}`}>
                                                            #{team.rank}
                                                        </span>
                                                    </td>
                                                    <td className="p-3 border">
                                                        {team.team_name}
                                                        {isMyTeam && (
                                                            <span className="ml-2 text-xs text-blue-600">(Ваша команда)</span>
                                                        )}
                                                    </td>
                                                    <td className="p-3 border text-center font-semibold">
                                                        {formatValue(selectedCategory, team.value)}
                                                    </td>
                                                </tr>
                                            );
                                        })}
                                    </tbody>
                                </table>
                            </div>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
};

export default CategoryRankings;

