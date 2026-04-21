/**
 * Утилита для расчета цвета на основе тренда игрока.
 * Тренд = total_z_15_days - total_z_season
 * Положительное значение = улучшение (ярко-зеленый)
 * Отрицательное значение = ухудшение (ярко-красный)
 */

/**
 * Преобразует значение тренда в цвет RGB
 * @param {number} trend - Разница между 15 днями и сезоном (total_z_15 - total_z_season)
 * @returns {string} - RGB цвет в формате 'rgb(r, g, b)'
 */
export const getTrendColor = (trend) => {
    if (trend === undefined || trend === null || isNaN(trend)) {
        return 'rgb(107, 114, 128)'; // Серый для отсутствующих данных
    }

    // Нормализуем тренд в диапазон -3 до +3 для расчета цвета
    // Значения за пределами этого диапазона будут обрезаны
    const normalizedTrend = Math.max(-3, Math.min(3, trend));
    
    if (normalizedTrend >= 0) {
        // Улучшение: от серого (0) до ярко-зеленого (3+)
        // Используем градиент: серый -> светло-зеленый -> ярко-зеленый
        const intensity = Math.min(1, normalizedTrend / 3); // 0 -> 1 для тренда от 0 до 3+
        
        // Ярко-зеленый: rgb(34, 197, 94) - это green-500 в Tailwind
        // Для максимальной яркости используем green-400: rgb(74, 222, 128)
        const r = Math.round(107 - (107 - 74) * intensity); // 107 -> 74
        const g = Math.round(114 + (222 - 114) * intensity); // 114 -> 222
        const b = Math.round(128 - (128 - 128) * intensity); // 128 -> 128 (не меняется)
        return `rgb(${r}, ${g}, ${b})`;
    } else {
        // Ухудшение: от серого (0) до ярко-красного (-3-)
        // Используем градиент: серый -> светло-красный -> ярко-красный
        const absTrend = Math.abs(normalizedTrend);
        const intensity = Math.min(1, absTrend / 3); // 0 -> 1 для тренда от 0 до -3-
        
        // Ярко-красный: rgb(239, 68, 68) - это red-500 в Tailwind
        // Для максимальной яркости используем red-400: rgb(248, 113, 113)
        const r = Math.round(107 + (248 - 107) * intensity); // 107 -> 248
        const g = Math.round(114 - (114 - 113) * intensity); // 114 -> 113
        const b = Math.round(128 - (128 - 113) * intensity); // 128 -> 113
        return `rgb(${r}, ${g}, ${b})`;
    }
};

