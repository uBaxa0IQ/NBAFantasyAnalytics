import React, { useState, useEffect } from 'react';

const MatchupDetails = ({ teamId, currentMatchup }) => {
    const [matchupData, setMatchupData] = useState(null);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);

    useEffect(() => {
        if (!teamId || !currentMatchup) {
            setMatchupData(null);
            return;
        }

        setLoading(true);
        setError(null);
        fetch(`http://localhost:8000/api/dashboard/${teamId}/matchup-details`)
            .then(res => res.json())
            .then(data => {
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
                console.error('Error fetching matchup details:', err);
                setError('Ошибка загрузки данных матчапа');
                setLoading(false);
            });
    }, [teamId, currentMatchup]);

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
            // Целые числа: округляем до целого
            return Math.round(value).toString();
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
            <h3 className="text-lg font-semibold text-gray-700 mb-4">Детали матчапа</h3>
            
            {/* Заголовок с командами и счетом */}
            <div className="mb-6 flex items-center justify-between flex-wrap gap-4">
                <div className="flex-1 min-w-[200px]">
                    <div className="font-bold text-lg">{matchupData.my_team.name}</div>
                    <div className="text-sm text-gray-600">Неделя {matchupData.week}</div>
                </div>
                <div className="text-center">
                    <div className="text-2xl font-bold text-blue-600">
                        {matchupData.score}
                    </div>
                    <div className="text-xs text-gray-500">Счет матчапа</div>
                </div>
                <div className="flex-1 min-w-[200px] text-right">
                    <div className="font-bold text-lg">{matchupData.opponent.name}</div>
                    <div className="text-sm text-gray-600">Соперник</div>
                </div>
            </div>

            {/* Таблица сравнения */}
            <div className="overflow-x-auto">
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

