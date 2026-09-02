import React, { useEffect, useState } from 'react';
import api from '../api';
import PuntAnalyzerModal from './PuntAnalyzerModal';

const PuntAdvisor = ({ teamId, period, activePunts = [], onApply }) => {
    const [data, setData] = useState(null);
    const [loading, setLoading] = useState(true);
    const [open, setOpen] = useState(false);

    useEffect(() => {
        if (!teamId) return;
        let cancelled = false;
        setLoading(true);
        api.get(`/punt-advisor/${teamId}`, { params: { period } })
            .then(response => {
                if (!cancelled) setData(response.data);
            })
            .catch(error => {
                console.error('Error loading punt analyzer:', error);
                if (!cancelled) setData(null);
            })
            .finally(() => {
                if (!cancelled) setLoading(false);
            });
        return () => { cancelled = true; };
    }, [teamId, period]);

    if (loading) {
        return <div className="bg-white border rounded-lg px-4 py-3 text-sm text-gray-500">Анализируем punt-стратегии…</div>;
    }
    if (!data) return null;

    const recommendation = data.recommendation;
    const strategyName = recommendation.punt_count
        ? `Punt ${recommendation.punt_categories.join(' + ')}`
        : 'Без панта';

    return (
        <>
            <div className="bg-white border rounded-lg p-4 shadow-sm">
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                    <div>
                        <div className="flex items-center gap-2 flex-wrap">
                            <h3 className="font-semibold text-gray-800">Punt-анализатор</h3>
                            <span className="text-xs bg-blue-50 text-blue-700 px-2 py-1 rounded">{strategyName}</span>
                        </div>
                        <p className="text-sm text-gray-500 mt-1">
                            Контроль ядра {recommendation.core_control}% · покрытие соперников {recommendation.opponent_coverage}% · риск {recommendation.risk}
                        </p>
                    </div>
                    <button
                        type="button"
                        onClick={() => setOpen(true)}
                        className="px-3 py-2 rounded border border-blue-200 text-blue-700 text-sm hover:bg-blue-50 shrink-0"
                    >
                        Открыть анализ
                    </button>
                </div>
            </div>

            {open && (
                <PuntAnalyzerModal
                    data={data}
                    activePunts={activePunts}
                    onApply={categories => {
                        onApply(categories);
                        setOpen(false);
                    }}
                    onClose={() => setOpen(false)}
                />
            )}
        </>
    );
};

export default PuntAdvisor;
