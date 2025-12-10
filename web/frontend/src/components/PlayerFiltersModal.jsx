import React, { useState, useEffect } from 'react';

const CATEGORIES = ['PTS', 'REB', 'AST', 'STL', 'BLK', '3PM', 'DD', 'FG%', 'FT%', '3PT%', 'A/TO'];

const PlayerFiltersModal = ({ isOpen, onClose, onApply, initialFilters = {} }) => {
    const [filters, setFilters] = useState({});

    // Инициализация фильтров при открытии модального окна
    useEffect(() => {
        if (isOpen) {
            setFilters(initialFilters || {});
        }
    }, [isOpen, initialFilters]);

    const handleFilterChange = (category, value) => {
        const numValue = value === '' ? null : parseFloat(value);
        setFilters(prev => {
            const newFilters = { ...prev };
            if (numValue === null || isNaN(numValue)) {
                delete newFilters[category];
            } else {
                newFilters[category] = numValue;
            }
            return newFilters;
        });
    };

    const handleReset = () => {
        setFilters({});
    };

    const handleApply = () => {
        onApply(filters);
        onClose();
    };

    const getFilterValue = (category) => {
        const value = filters[category];
        return value !== undefined && value !== null ? value.toString() : '';
    };

    const isPercentageCategory = (cat) => {
        return ['FG%', 'FT%', '3PT%'].includes(cat);
    };

    if (!isOpen) return null;

    return (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50" onClick={onClose}>
            <div className="bg-white rounded-lg shadow-xl max-w-3xl w-full mx-4 max-h-[90vh] overflow-y-auto" onClick={(e) => e.stopPropagation()}>
                <div className="p-6">
                    <div className="flex justify-between items-center mb-6">
                        <h2 className="text-2xl font-bold text-gray-800">Фильтры игроков</h2>
                        <button
                            onClick={onClose}
                            className="text-gray-500 hover:text-gray-700 text-2xl font-bold"
                        >
                            ×
                        </button>
                    </div>

                    <div className="mb-4 text-sm text-gray-600">
                        Укажите минимальные значения для фильтрации игроков. Оставьте поле пустым, чтобы не применять фильтр по этой категории.
                    </div>

                    <div className="grid grid-cols-2 md:grid-cols-3 gap-4 mb-6">
                        {CATEGORIES.map(category => (
                            <div key={category}>
                                <label className="block text-sm font-medium text-gray-700 mb-1">
                                    {category}
                                </label>
                                <input
                                    type="number"
                                    step={isPercentageCategory(category) ? "0.1" : "0.1"}
                                    min="0"
                                    className="w-full border p-2 rounded"
                                    placeholder={isPercentageCategory(category) ? "0.0-100.0" : "0.0"}
                                    value={getFilterValue(category)}
                                    onChange={(e) => handleFilterChange(category, e.target.value)}
                                />
                            </div>
                        ))}
                    </div>

                    <div className="flex justify-end gap-4 pt-4 border-t">
                        <button
                            onClick={handleReset}
                            className="px-4 py-2 border border-gray-300 rounded hover:bg-gray-100"
                        >
                            Сбросить
                        </button>
                        <button
                            onClick={onClose}
                            className="px-4 py-2 border border-gray-300 rounded hover:bg-gray-100"
                        >
                            Отмена
                        </button>
                        <button
                            onClick={handleApply}
                            className="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700"
                        >
                            Применить
                        </button>
                    </div>
                </div>
            </div>
        </div>
    );
};

export default PlayerFiltersModal;







