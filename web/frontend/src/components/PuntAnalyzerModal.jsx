import React, { useMemo, useState } from 'react';

const sameCategories = (left = [], right = []) => (
    [...left].sort().join('|') === [...right].sort().join('|')
);

const Metric = ({ value, label, hint }) => (
    <div className="border rounded-lg p-3 bg-gray-50">
        <div className="text-xl font-semibold text-gray-800">{value}</div>
        <div className="text-sm text-gray-600">{label}</div>
        <div className="text-xs text-gray-400 mt-1">{hint}</div>
    </div>
);

const PuntAnalyzerModal = ({ data, activePunts, onApply, onClose }) => {
    const initialDepth = data.recommendation?.punt_count || 0;
    const [depth, setDepth] = useState(initialDepth);
    const [alternativeIndex, setAlternativeIndex] = useState(-1);
    const [customPunts, setCustomPunts] = useState(null);

    const depthData = useMemo(
        () => data.strategies_by_depth.find(item => item.punt_count === depth),
        [data, depth],
    );
    const customStrategy = customPunts && data.strategy_options.find(option => (
        sameCategories(option.punt_categories, customPunts)
    ));
    const strategy = customStrategy || (alternativeIndex < 0
        ? depthData.best
        : depthData.alternatives[alternativeIndex] || depthData.best);
    const puntSet = new Set(strategy.punt_categories);
    const isActive = sameCategories(activePunts, strategy.punt_categories);

    const selectDepth = value => {
        setDepth(value);
        setAlternativeIndex(-1);
        setCustomPunts(null);
    };

    const toggleCategory = category => {
        const current = strategy.punt_categories;
        const next = current.includes(category)
            ? current.filter(item => item !== category)
            : [...current, category];
        if (next.length > data.max_punts) return;
        setDepth(next.length);
        setAlternativeIndex(-1);
        setCustomPunts(next);
    };

    return (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4" onClick={onClose}>
            <div className="bg-white rounded-lg shadow-xl w-full max-w-4xl max-h-[90vh] overflow-y-auto" onClick={event => event.stopPropagation()}>
                <div className="p-4 border-b flex items-start justify-between gap-4">
                    <div>
                        <h2 className="text-xl font-semibold text-gray-800">Punt-анализатор</h2>
                        <p className="text-sm text-gray-500 mt-1">Сравнение всех {data.total_combinations} допустимых комбинаций текущего состава</p>
                    </div>
                    <button type="button" onClick={onClose} className="text-2xl leading-none text-gray-400 hover:text-gray-700">×</button>
                </div>

                <div className="p-4 space-y-5">
                    <p className="text-sm text-amber-800">Диагностика текущего состава: исключение категорий повышает средний контроль оставшихся, но само по себе не усиливает команду. Для победы нужно {data.winning_categories} категорий.</p>
                    <div>
                        <div className="text-sm font-medium text-gray-700 mb-2">Глубина стратегии</div>
                        <div className="grid grid-cols-6 gap-2">
                            {data.strategies_by_depth.map(item => (
                                <button
                                    key={item.punt_count}
                                    type="button"
                                    onClick={() => selectDepth(item.punt_count)}
                                    className={`py-2 rounded border text-sm ${depth === item.punt_count ? 'bg-blue-600 text-white border-blue-600' : 'bg-white text-gray-600 hover:bg-gray-50'}`}
                                >
                                    {item.punt_count}
                                </button>
                            ))}
                        </div>
                        <p className="text-xs text-gray-400 mt-1">Количество категорий, которыми стратегия сознательно жертвует</p>
                    </div>

                    <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                        <div>
                            <div className="text-lg font-semibold text-gray-800">
                                {strategy.punt_count ? `Punt ${strategy.punt_categories.join(' + ')}` : 'Сбалансированная стратегия'}
                            </div>
                            <p className="text-sm text-gray-500">
                                Нужно выиграть 6 из {strategy.available_categories} оставшихся категорий · риск {strategy.risk}
                            </p>
                        </div>
                        <button
                            type="button"
                            disabled={isActive}
                            onClick={() => onApply(strategy.punt_categories)}
                            className={`px-4 py-2 rounded text-sm shrink-0 ${isActive ? 'bg-gray-100 text-gray-500' : 'bg-blue-600 text-white hover:bg-blue-700'}`}
                        >
                            {isActive ? 'Стратегия активна' : 'Применить стратегию'}
                        </button>
                    </div>

                    <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                        <Metric
                            value={`${strategy.core_control}%`}
                            label="Контроль ядра"
                            hint={`${strategy.control_gain >= 0 ? '+' : ''}${strategy.control_gain}% к игре без панта`}
                        />
                        <Metric
                            value={`${strategy.opponent_coverage}%`}
                            label="Покрытие соперников"
                            hint="Против кого ядра хватает для победы"
                        />
                        <Metric
                            value={strategy.margin_for_error}
                            label="Запас категорий"
                            hint="Сколько можно дополнительно проиграть"
                        />
                    </div>

                    <div>
                        <div className="flex items-center justify-between gap-3 mb-2">
                            <h3 className="font-medium text-gray-700">Категории</h3>
                            <span className="text-xs text-gray-400">Нажмите категорию, чтобы изменить комбинацию</span>
                        </div>
                        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                            {data.category_profiles.map(category => {
                                const punted = puntSet.has(category.category);
                                return (
                                    <button
                                        key={category.category}
                                        type="button"
                                        onClick={() => toggleCategory(category.category)}
                                        className={`flex items-center justify-between border rounded px-3 py-2 text-left ${punted ? 'bg-gray-100 text-gray-400' : 'bg-white hover:bg-gray-50'}`}
                                    >
                                        <div className="flex items-center gap-2">
                                            <span className="font-medium">{category.category}</span>
                                            {punted && <span className="text-xs">PUNT</span>}
                                        </div>
                                        <div className="text-right text-sm">
                                            <span className={punted ? '' : category.win_rate >= 60 ? 'text-green-600' : category.win_rate < 40 ? 'text-red-600' : 'text-gray-600'}>
                                                {category.win_rate}%
                                            </span>
                                            <span className="text-xs text-gray-400 ml-2">#{category.rank}</span>
                                        </div>
                                    </button>
                                );
                            })}
                        </div>
                    </div>

                    {depthData.alternatives.length > 0 && (
                        <div>
                            <h3 className="text-sm font-medium text-gray-700 mb-2">Другие комбинации этой глубины</h3>
                            <div className="flex gap-2 flex-wrap">
                                <button
                                    type="button"
                                    onClick={() => { setAlternativeIndex(-1); setCustomPunts(null); }}
                                    className={`px-3 py-2 rounded border text-sm ${alternativeIndex < 0 ? 'border-blue-500 text-blue-700 bg-blue-50' : 'text-gray-600'}`}
                                >
                                    {depthData.best.punt_categories.join(' + ') || 'Без панта'}
                                </button>
                                {depthData.alternatives.map((alternative, index) => (
                                    <button
                                        key={alternative.punt_categories.join('-')}
                                        type="button"
                                        onClick={() => { setAlternativeIndex(index); setCustomPunts(null); }}
                                        className={`px-3 py-2 rounded border text-sm ${alternativeIndex === index ? 'border-blue-500 text-blue-700 bg-blue-50' : 'text-gray-600'}`}
                                    >
                                        {alternative.punt_categories.join(' + ')}
                                    </button>
                                ))}
                            </div>
                        </div>
                    )}

                    <p className="text-xs text-gray-400 border-t pt-3">
                        Больше пантов обычно повышает контроль оставшегося ядра, но уменьшает запас на ошибку. Анализ не меняет статистику состава и не исключает категории из правил ESPN.
                    </p>
                </div>
            </div>
        </div>
    );
};

export default PuntAnalyzerModal;
