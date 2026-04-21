import React, { useState, useEffect } from 'react';
import api from '../api';

const CoefficientsManager = () => {
  const [coefficients, setCoefficients] = useState({
    total: 0.40,
    last_30: 0.30,
    last_15: 0.20,
    last_7: 0.10
  });
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');

  // Загрузка текущих коэффициентов
  useEffect(() => {
    loadCoefficients();
  }, []);

  const loadCoefficients = async () => {
    setLoading(true);
    try {
      const response = await api.get('/admin/weighted-coefficients');
      setCoefficients(response.data);
    } catch (err) {
      setError('Ошибка загрузки коэффициентов');
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  const handleCoefficientChange = (key, value) => {
    const numValue = parseFloat(value) || 0;
    setCoefficients(prev => ({
      ...prev,
      [key]: numValue
    }));
  };

  const handleSave = async () => {
    setSaving(true);
    setError('');
    setSuccess('');
    
    try {
      // Нормализуем коэффициенты перед отправкой, чтобы сумма была точно 1.0
      // Последний коэффициент вычисляем так, чтобы сумма была точно 1.0
      const sum = coefficients.total + coefficients.last_30 + coefficients.last_15 + coefficients.last_7;
      const normalizedCoeffs = {
        total: parseFloat((coefficients.total / sum).toFixed(4)),
        last_30: parseFloat((coefficients.last_30 / sum).toFixed(4)),
        last_15: parseFloat((coefficients.last_15 / sum).toFixed(4)),
        last_7: parseFloat((1.0 - (coefficients.total / sum) - (coefficients.last_30 / sum) - (coefficients.last_15 / sum)).toFixed(4))
      };
      
      // Проверяем, что сумма действительно 1.0
      const finalSum = normalizedCoeffs.total + normalizedCoeffs.last_30 + normalizedCoeffs.last_15 + normalizedCoeffs.last_7;
      if (Math.abs(finalSum - 1.0) > 0.0001) {
        // Если все еще неточность, корректируем last_7
        normalizedCoeffs.last_7 = parseFloat((1.0 - normalizedCoeffs.total - normalizedCoeffs.last_30 - normalizedCoeffs.last_15).toFixed(4));
      }
      
      // Логируем для отладки
      console.log('Saving coefficients:', normalizedCoeffs);
      console.log('Sum:', normalizedCoeffs.total + normalizedCoeffs.last_30 + normalizedCoeffs.last_15 + normalizedCoeffs.last_7);
      
      const response = await api.post('/admin/weighted-coefficients', normalizedCoeffs);
      if (response.data.success) {
        setSuccess('Коэффициенты успешно сохранены!');
        // Перезагружаем страницу через 1 секунду, чтобы применить изменения
        setTimeout(() => {
          window.location.reload();
        }, 1000);
      }
    } catch (err) {
      const errorMessage = err.response?.data?.detail || err.message || 'Ошибка при сохранении коэффициентов';
      console.error('Error saving coefficients:', err);
      setError(errorMessage);
    } finally {
      setSaving(false);
    }
  };

  const sum = coefficients.total + coefficients.last_30 + coefficients.last_15 + coefficients.last_7;

  return (
    <div className="max-w-2xl">
      <div className="bg-white rounded-lg shadow-md p-8">
        <h2 className="text-2xl font-bold mb-6 text-gray-800">Управление коэффициентами взвешенного периода</h2>
        
        <div className="space-y-6">
          {/* Поля ввода для коэффициентов */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">
                Season (Весь сезон)
              </label>
              <input
                type="number"
                min="0"
                max="1"
                step="0.01"
                value={coefficients.total}
                onChange={(e) => handleCoefficientChange('total', e.target.value)}
                className="w-full border border-gray-300 rounded-lg px-4 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                placeholder="0.40"
              />
              <div className="text-xs text-gray-500 mt-1">
                {sum > 0 ? `${((coefficients.total / sum) * 100).toFixed(1)}%` : '0%'}
              </div>
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">
                Last 30 (Последние 30 дней)
              </label>
              <input
                type="number"
                min="0"
                max="1"
                step="0.01"
                value={coefficients.last_30}
                onChange={(e) => handleCoefficientChange('last_30', e.target.value)}
                className="w-full border border-gray-300 rounded-lg px-4 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                placeholder="0.30"
              />
              <div className="text-xs text-gray-500 mt-1">
                {sum > 0 ? `${((coefficients.last_30 / sum) * 100).toFixed(1)}%` : '0%'}
              </div>
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">
                Last 15 (Последние 15 дней)
              </label>
              <input
                type="number"
                min="0"
                max="1"
                step="0.01"
                value={coefficients.last_15}
                onChange={(e) => handleCoefficientChange('last_15', e.target.value)}
                className="w-full border border-gray-300 rounded-lg px-4 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                placeholder="0.20"
              />
              <div className="text-xs text-gray-500 mt-1">
                {sum > 0 ? `${((coefficients.last_15 / sum) * 100).toFixed(1)}%` : '0%'}
              </div>
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">
                Last 7 (Последние 7 дней)
              </label>
              <input
                type="number"
                min="0"
                max="1"
                step="0.01"
                value={coefficients.last_7}
                onChange={(e) => handleCoefficientChange('last_7', e.target.value)}
                className="w-full border border-gray-300 rounded-lg px-4 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                placeholder="0.10"
              />
              <div className="text-xs text-gray-500 mt-1">
                {sum > 0 ? `${((coefficients.last_7 / sum) * 100).toFixed(1)}%` : '0%'}
              </div>
            </div>
          </div>

          {/* Индикатор суммы */}
          <div className={`p-4 rounded-lg ${Math.abs(sum - 1.0) < 0.001 ? 'bg-green-50 border border-green-200' : 'bg-yellow-50 border border-yellow-200'}`}>
            <div className="flex justify-between items-center">
              <span className="font-medium text-gray-700">Сумма коэффициентов:</span>
              <span className={`font-bold ${Math.abs(sum - 1.0) < 0.001 ? 'text-green-600' : 'text-yellow-600'}`}>
                {sum.toFixed(3)} {Math.abs(sum - 1.0) < 0.001 ? '✓' : '(должна быть 1.000)'}
              </span>
            </div>
          </div>

          {error && (
            <div className="p-4 bg-red-50 border border-red-200 text-red-700 rounded-lg">
              {error}
            </div>
          )}

          {success && (
            <div className="p-4 bg-green-50 border border-green-200 text-green-700 rounded-lg">
              {success}
            </div>
          )}

          <button
            onClick={handleSave}
            disabled={saving || Math.abs(sum - 1.0) >= 0.001}
            className="w-full bg-blue-600 text-white px-6 py-3 rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed font-medium transition-colors"
          >
            {saving ? 'Сохранение...' : 'Сохранить коэффициенты'}
          </button>
        </div>
      </div>
    </div>
  );
};

export default CoefficientsManager;

