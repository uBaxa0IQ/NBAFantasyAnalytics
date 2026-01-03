import React, { useState, useEffect } from 'react';
import api from '../api';
import CoefficientsManager from './CoefficientsManager';
import TradeOptimizer from './TradeOptimizer';

const AdminPanel = () => {
  const [activeTab, setActiveTab] = useState('trades'); // 'trades', 'settings', 'coefficients'
  
  // Состояние для истории трейдов
  const [tradeLogs, setTradeLogs] = useState([]);
  const [tradeStats, setTradeStats] = useState(null);
  const [loadingLogs, setLoadingLogs] = useState(false);
  const [filters, setFilters] = useState({
    timePeriod: 'all',
    tradeType: 'all',
    limit: 100
  });
  const [selectedTrade, setSelectedTrade] = useState(null); // Выбранный трейд для детального просмотра

  // Состояние для настроек (смена пароля)
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [loading, setLoading] = useState(false);

  // Состояние для настроек лиги
  const [leagueSettings, setLeagueSettings] = useState({
    force_weighted_mode: false,
    forced_period: '2026_weighted'
  });

  // Загрузка истории трейдов и настроек
  useEffect(() => {
    if (activeTab === 'trades') {
      loadTradeLogs();
      loadTradeStats();
    } else if (activeTab === 'settings') {
      loadLeagueSettings();
    }
  }, [filters, activeTab]);

  const loadLeagueSettings = async () => {
    try {
      const response = await api.get('/admin/settings');
      setLeagueSettings(response.data);
    } catch (err) {
      console.error('Error loading league settings:', err);
    }
  };

  const handleLeagueSettingChange = async (key, value) => {
    try {
      const newSettings = { ...leagueSettings, [key]: value };
      // Оптимистичное обновление
      setLeagueSettings(newSettings);
      
      await api.post('/admin/settings', newSettings);
    } catch (err) {
      console.error('Error updating league settings:', err);
      // Откат при ошибке
      loadLeagueSettings();
      alert('Ошибка при сохранении настроек');
    }
  };

  const loadTradeLogs = async () => {
    setLoadingLogs(true);
    try {
      const params = new URLSearchParams({
        limit: filters.limit.toString()
      });
      if (filters.timePeriod !== 'all') {
        params.append('time_period', filters.timePeriod);
      }
      if (filters.tradeType !== 'all') {
        params.append('trade_type', filters.tradeType);
      }
      
      const response = await api.get(`/admin/trade-logs?${params.toString()}`);
      setTradeLogs(response.data.logs || []);
    } catch (err) {
      console.error('Error loading trade logs:', err);
      setTradeLogs([]);
    } finally {
      setLoadingLogs(false);
    }
  };

  const loadTradeStats = async () => {
    try {
      const response = await api.get('/admin/trade-stats');
      setTradeStats(response.data);
    } catch (err) {
      console.error('Error loading trade stats:', err);
    }
  };

  const formatDate = (dateString) => {
    try {
      const date = new Date(dateString);
      // Используем локальное время устройства или московское время
      return date.toLocaleString('ru-RU', {
        timeZone: 'Europe/Moscow', // Московское время (UTC+3)
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit'
      });
    } catch (e) {
      return dateString;
    }
  };

  const handleChangePassword = async (e) => {
    e.preventDefault();
    setError('');
    setSuccess('');

    if (!newPassword) {
      setError('Введите новый пароль');
      return;
    }

    if (newPassword.length < 3) {
      setError('Пароль должен быть не менее 3 символов');
      return;
    }

    if (newPassword !== confirmPassword) {
      setError('Пароли не совпадают');
      return;
    }

    setLoading(true);

    try {
      const response = await api.post('/admin/change-password', {
        new_password: newPassword
      });

      if (response.data.success) {
        setSuccess('Пароль успешно изменен!');
        setNewPassword('');
        setConfirmPassword('');
      }
    } catch (err) {
      setError(err.response?.data?.detail || 'Ошибка при изменении пароля');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Вкладки */}
      <div className="bg-white border-b shadow-sm sticky top-0 z-10">
        <div className="container mx-auto max-w-7xl">
          <div className="flex space-x-1">
            <button
              onClick={() => setActiveTab('trades')}
              className={`px-6 py-4 font-medium transition-colors border-b-2 ${
                activeTab === 'trades'
                  ? 'border-blue-600 text-blue-600 bg-blue-50'
                  : 'border-transparent text-gray-500 hover:text-gray-700 hover:bg-gray-50'
              }`}
            >
              История трейдов
            </button>
            <button
              onClick={() => setActiveTab('coefficients')}
              className={`px-6 py-4 font-medium transition-colors border-b-2 ${
                activeTab === 'coefficients'
                  ? 'border-blue-600 text-blue-600 bg-blue-50'
                  : 'border-transparent text-gray-500 hover:text-gray-700 hover:bg-gray-50'
              }`}
            >
              Коэффициенты
            </button>
            <button
              onClick={() => setActiveTab('settings')}
              className={`px-6 py-4 font-medium transition-colors border-b-2 ${
                activeTab === 'settings'
                  ? 'border-blue-600 text-blue-600 bg-blue-50'
                  : 'border-transparent text-gray-500 hover:text-gray-700 hover:bg-gray-50'
              }`}
            >
              Настройки
            </button>
          </div>
        </div>
      </div>

      <div className="container mx-auto max-w-7xl p-6">
        {/* Вкладка: История трейдов */}
        {activeTab === 'trades' && (
          <div>
            {/* Статистика */}
            {tradeStats && (
              <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-6">
                <div className="bg-gradient-to-br from-blue-500 to-blue-600 text-white rounded-lg shadow-lg p-6">
                  <div className="text-sm opacity-90 mb-1">Всего трейдов</div>
                  <div className="text-3xl font-bold">{tradeStats.total || 0}</div>
                </div>
                <div className="bg-gradient-to-br from-green-500 to-green-600 text-white rounded-lg shadow-lg p-6">
                  <div className="text-sm opacity-90 mb-1">За 24 часа</div>
                  <div className="text-3xl font-bold">{tradeStats.last_24h || 0}</div>
                </div>
                <div className="bg-gradient-to-br from-yellow-500 to-yellow-600 text-white rounded-lg shadow-lg p-6">
                  <div className="text-sm opacity-90 mb-1">За 7 дней</div>
                  <div className="text-3xl font-bold">{tradeStats.last_7d || 0}</div>
                </div>
                <div className="bg-gradient-to-br from-purple-500 to-purple-600 text-white rounded-lg shadow-lg p-6">
                  <div className="text-sm opacity-90 mb-1">По типам</div>
                  <div className="text-sm mt-1">
                    {tradeStats.by_type && Object.entries(tradeStats.by_type).map(([type, count]) => (
                      <div key={type}>
                        {type === 'two-team' ? '2 команды' : 'Мульти'}: {count}
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            )}

            {/* Фильтры */}
            <div className="bg-white rounded-lg shadow-md p-6 mb-6">
              <h3 className="text-lg font-semibold mb-4 text-gray-800">Фильтры</h3>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">Период:</label>
                  <select
                    value={filters.timePeriod}
                    onChange={(e) => setFilters({...filters, timePeriod: e.target.value})}
                    className="w-full border border-gray-300 rounded-lg px-4 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                  >
                    <option value="all">Все время</option>
                    <option value="24h">Последние 24 часа</option>
                    <option value="7d">Последние 7 дней</option>
                    <option value="30d">Последние 30 дней</option>
                  </select>
                </div>
                
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">Тип трейда:</label>
                  <select
                    value={filters.tradeType}
                    onChange={(e) => setFilters({...filters, tradeType: e.target.value})}
                    className="w-full border border-gray-300 rounded-lg px-4 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                  >
                    <option value="all">Все типы</option>
                    <option value="two-team">2 команды</option>
                    <option value="multi-team">Мультикомандный</option>
                  </select>
                </div>
                
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">Лимит записей:</label>
                  <select
                    value={filters.limit}
                    onChange={(e) => setFilters({...filters, limit: parseInt(e.target.value)})}
                    className="w-full border border-gray-300 rounded-lg px-4 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                  >
                    <option value="50">50</option>
                    <option value="100">100</option>
                    <option value="200">200</option>
                    <option value="500">500</option>
                  </select>
                </div>
              </div>
            </div>

            {/* Таблица логов */}
            <div className="bg-white rounded-lg shadow-md overflow-hidden">
              <div className="px-6 py-4 border-b bg-gray-50">
                <h3 className="text-lg font-semibold text-gray-800">История трейдов</h3>
              </div>
              
              {loadingLogs ? (
                <div className="text-center py-12 text-gray-500">
                  <div className="inline-block animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600"></div>
                  <div className="mt-2">Загрузка...</div>
                </div>
              ) : tradeLogs.length === 0 ? (
                <div className="text-center py-12 text-gray-500">
                  <svg className="mx-auto h-12 w-12 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                  </svg>
                  <div className="mt-2">Нет записей</div>
                </div>
              ) : (
                <div className="overflow-x-auto">
                  <table className="min-w-full divide-y divide-gray-200">
                    <thead className="bg-gray-50">
                      <tr>
                        <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Дата/Время</th>
                        <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Тип</th>
                        <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Команды</th>
                        <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Игроки</th>
                        <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Период</th>
                        <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Δ Z-score</th>
                        <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">IP</th>
                      </tr>
                    </thead>
                    <tbody className="bg-white divide-y divide-gray-200">
                      {tradeLogs.map((log) => (
                        <tr 
                          key={log.id} 
                          className="hover:bg-blue-50 transition-colors cursor-pointer"
                          onClick={() => setSelectedTrade(log)}
                        >
                          <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900">{formatDate(log.timestamp)}</td>
                          <td className="px-6 py-4 whitespace-nowrap">
                            <span className={`inline-flex px-2 py-1 text-xs font-semibold rounded-full ${
                              log.trade_type === 'two-team' 
                                ? 'bg-blue-100 text-blue-800' 
                                : 'bg-purple-100 text-purple-800'
                            }`}>
                              {log.trade_type === 'two-team' ? '2 команды' : 'Мульти'}
                            </span>
                          </td>
                          <td className="px-6 py-4 text-sm text-gray-900">
                            <div className="max-w-xs">
                              {log.team_names && log.team_names.length > 0 ? (
                                <div className="truncate" title={log.team_names.join(', ')}>
                                  {log.team_names.join(', ')}
                                </div>
                              ) : (
                                <span className="text-gray-400">-</span>
                              )}
                            </div>
                          </td>
                          <td className="px-6 py-4 text-sm text-gray-900">
                            {log.trade_type === 'two-team' ? (
                              <div className="space-y-1">
                                <div className="text-red-600 font-medium">Отдает: {log.players_involved?.give?.length || 0}</div>
                                <div className="text-green-600 font-medium">Получает: {log.players_involved?.receive?.length || 0}</div>
                              </div>
                            ) : (
                              <div className="text-gray-600">
                                {Array.isArray(log.players_involved) ? log.players_involved.length : 0} команд
                              </div>
                            )}
                          </td>
                          <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">{log.period || '-'}</td>
                          <td className="px-6 py-4 whitespace-nowrap text-sm">
                            {log.result_delta !== null && log.result_delta !== undefined ? (
                              <span className={`font-semibold ${
                                log.result_delta > 0 ? 'text-green-600' : log.result_delta < 0 ? 'text-red-600' : 'text-gray-600'
                              }`}>
                                {log.result_delta > 0 ? '+' : ''}{log.result_delta.toFixed(2)}
                              </span>
                            ) : (
                              <span className="text-gray-400">-</span>
                            )}
                          </td>
                          <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500 font-mono">{log.ip_address || '-'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </div>
        )}

        {/* Вкладка: Коэффициенты */}
        {activeTab === 'coefficients' && (
          <div className="space-y-6">
            <div className="bg-white rounded-lg shadow-md p-6">
              <div className="mb-6">
                <h2 className="text-xl font-semibold mb-2 text-gray-800">Управление коэффициентами</h2>
                <p className="text-sm text-gray-600">
                  Настройте коэффициенты взвешенного периода. Изменения применяются ко всем расчетам в системе.
                </p>
              </div>
              <CoefficientsManager />
            </div>
            
            <div className="bg-white rounded-lg shadow-md p-6">
              <div className="mb-6">
                <h2 className="text-xl font-semibold mb-2 text-gray-800">Оптимизатор трейдов</h2>
                <p className="text-sm text-gray-600">
                  Подберите оптимальные коэффициенты для конкретного трейда, при которых обе команды получают выгоду.
                </p>
              </div>
              <TradeOptimizer />
            </div>
          </div>
        )}

        {/* Вкладка: Настройки */}
        {activeTab === 'settings' && (
          <div className="max-w-2xl">
            <div className="bg-white rounded-lg shadow-md p-8">
              <h2 className="text-2xl font-bold mb-6 text-gray-800">Настройки</h2>
              
              {/* Глобальные настройки лиги */}
              <div className="border-b pb-6 mb-6">
                <h3 className="text-lg font-semibold mb-4 text-gray-800">Глобальные настройки лиги</h3>
                
                <div className="space-y-4">
                  {/* Переключатель режима */}
                  <div className="flex items-center justify-between p-4 bg-gray-50 rounded-lg">
                    <div>
                      <div className="font-medium text-gray-800">Принудительный режим периода</div>
                      <div className="text-sm text-gray-600">
                        Если включено, все пользователи будут использовать только выбранный ниже режим периода.
                        Выбор других периодов в настройках будет скрыт.
                      </div>
                    </div>
                    <label className="relative inline-flex items-center cursor-pointer">
                      <input 
                        type="checkbox" 
                        className="sr-only peer"
                        checked={leagueSettings.force_weighted_mode}
                        onChange={(e) => handleLeagueSettingChange('force_weighted_mode', e.target.checked)}
                      />
                      <div className="w-11 h-6 bg-gray-200 peer-focus:outline-none peer-focus:ring-4 peer-focus:ring-blue-300 rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-blue-600"></div>
                    </label>
                  </div>

                  {/* Выбор периода (показывается только если включен режим) */}
                  {leagueSettings.force_weighted_mode && (
                    <div className="flex items-center justify-between p-4 bg-blue-50 border border-blue-100 rounded-lg transition-all">
                      <div>
                        <div className="font-medium text-blue-900">Период для принудительного режима</div>
                        <div className="text-sm text-blue-700">
                          Выберите период, который будет установлен у всех пользователей.
                        </div>
                      </div>
                      <select
                        className="bg-white border border-blue-300 text-gray-900 text-sm rounded-lg focus:ring-blue-500 focus:border-blue-500 block p-2.5 min-w-[200px]"
                        value={leagueSettings.forced_period || '2026_weighted'}
                        onChange={(e) => handleLeagueSettingChange('forced_period', e.target.value)}
                      >
                        <option value="2026_total">Весь сезон</option>
                        <option value="2026_last_30">Последние 30 дней</option>
                        <option value="2026_last_15">Последние 15 дней</option>
                        <option value="2026_last_7">Последние 7 дней</option>
                        <option value="2026_weighted">Взвешенный (Универсальный)</option>
                      </select>
                    </div>
                  )}
                </div>
              </div>
              
              {/* Смена пароля */}
              <div className="border-b pb-6 mb-6">
                <h3 className="text-lg font-semibold mb-4 text-gray-800">Смена пароля администратора</h3>
                
                <form onSubmit={handleChangePassword} className="space-y-4">
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-2">
                      Новый пароль:
                    </label>
                    <input
                      type="password"
                      value={newPassword}
                      onChange={(e) => setNewPassword(e.target.value)}
                      className="w-full border border-gray-300 rounded-lg px-4 py-3 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                      placeholder="Введите новый пароль"
                      disabled={loading}
                    />
                  </div>

                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-2">
                      Подтвердите пароль:
                    </label>
                    <input
                      type="password"
                      value={confirmPassword}
                      onChange={(e) => setConfirmPassword(e.target.value)}
                      className="w-full border border-gray-300 rounded-lg px-4 py-3 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                      placeholder="Повторите новый пароль"
                      disabled={loading}
                    />
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
                    type="submit"
                    className="w-full bg-blue-600 text-white px-6 py-3 rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed font-medium transition-colors"
                    disabled={loading || !newPassword || !confirmPassword}
                  >
                    {loading ? 'Изменение...' : 'Изменить пароль'}
                  </button>
                </form>
              </div>

              {/* Информация */}
              <div>
                <h3 className="text-lg font-semibold mb-4 text-gray-800">Информация</h3>
                <div className="space-y-3 text-gray-600 bg-gray-50 rounded-lg p-4">
                  <div className="flex justify-between">
                    <span className="font-semibold">Статус:</span>
                    <span className="text-green-600 font-medium">Активна</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="font-semibold">База данных:</span>
                    <span className="font-mono text-sm">admin.db</span>
                  </div>
                  <div className="pt-3 border-t border-gray-200 mt-3">
                    <p className="text-sm text-gray-500 mb-2">
                      <span className="font-semibold">Дефолтный пароль:</span> Если в базе данных нет администраторов, используется пароль <code className="bg-gray-200 px-2 py-1 rounded font-mono">admin123</code>
                    </p>
                    <p className="text-sm text-gray-500">
                      После изменения пароля он сохраняется в базе данных и дефолтный пароль больше не будет работать.
                    </p>
                  </div>
                </div>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Модальное окно детального просмотра трейда */}
      {selectedTrade && (
        <TradeDetailModal trade={selectedTrade} onClose={() => setSelectedTrade(null)} />
      )}
    </div>
  );
};

// Модальное окно для детального просмотра трейда
const TradeDetailModal = ({ trade, onClose }) => {
  if (!trade) return null;

  const formatDate = (dateString) => {
    try {
      const date = new Date(dateString);
      // Используем московское время (UTC+3)
      return date.toLocaleString('ru-RU', {
        timeZone: 'Europe/Moscow',
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit'
      });
    } catch (e) {
      return dateString;
    }
  };

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50" onClick={onClose}>
      <div 
        className="bg-white rounded-lg shadow-xl max-w-4xl w-full max-h-[90vh] overflow-y-auto m-4" 
        onClick={e => e.stopPropagation()}
      >
        <div className="p-6">
          {/* Заголовок */}
          <div className="flex justify-between items-start mb-6">
            <div>
              <h2 className="text-2xl font-bold text-gray-800">
                Детали трейда #{trade.id}
              </h2>
              <div className="mt-2 text-sm text-gray-600">
                <span className={`inline-flex px-3 py-1 text-xs font-semibold rounded-full ${
                  trade.trade_type === 'two-team' 
                    ? 'bg-blue-100 text-blue-800' 
                    : 'bg-purple-100 text-purple-800'
                }`}>
                  {trade.trade_type === 'two-team' ? '2 команды' : 'Мультикомандный'}
                </span>
                <span className="ml-3">{formatDate(trade.timestamp)}</span>
              </div>
            </div>
            <button
              onClick={onClose}
              className="text-gray-400 hover:text-gray-600 text-2xl font-bold"
            >
              ×
            </button>
          </div>

          {/* Основная информация */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mb-6">
            <div className="bg-gray-50 rounded-lg p-4">
              <h3 className="font-semibold text-gray-700 mb-2">Команды</h3>
              <div className="space-y-1">
                {trade.team_names && trade.team_names.length > 0 ? (
                  trade.team_names.map((name, idx) => (
                    <div key={idx} className="text-sm text-gray-800">
                      {idx + 1}. {name} (ID: {trade.teams_involved[idx]})
                    </div>
                  ))
                ) : (
                  <span className="text-gray-400 text-sm">-</span>
                )}
              </div>
            </div>

            <div className="bg-gray-50 rounded-lg p-4">
              <h3 className="font-semibold text-gray-700 mb-2">Параметры</h3>
              <div className="space-y-1 text-sm">
                <div><span className="font-medium">Период:</span> {trade.period || '-'}</div>
                <div><span className="font-medium">Режим области:</span> {trade.scope_mode || '-'}</div>
                {trade.result_delta !== null && trade.result_delta !== undefined && (
                  <div>
                    <span className="font-medium">Δ Z-score:</span>{' '}
                    <span className={`font-semibold ${
                      trade.result_delta > 0 ? 'text-green-600' : trade.result_delta < 0 ? 'text-red-600' : 'text-gray-600'
                    }`}>
                      {trade.result_delta > 0 ? '+' : ''}{trade.result_delta.toFixed(2)}
                    </span>
                  </div>
                )}
                <div><span className="font-medium">IP адрес:</span> <span className="font-mono">{trade.ip_address || '-'}</span></div>
              </div>
            </div>
          </div>

          {/* Игроки */}
          <div className="mb-6">
            <h3 className="font-semibold text-gray-800 mb-4">Игроки в трейде</h3>
            
            {trade.trade_type === 'two-team' ? (
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div className="bg-red-50 rounded-lg p-4 border border-red-200">
                  <h4 className="font-semibold text-red-800 mb-3">Отдает ({trade.players_involved?.give?.length || 0}):</h4>
                  <div className="space-y-1">
                    {trade.players_involved?.give && trade.players_involved.give.length > 0 ? (
                      trade.players_involved.give.map((player, idx) => (
                        <div key={idx} className="text-sm text-gray-700 bg-white rounded px-2 py-1">
                          {player}
                        </div>
                      ))
                    ) : (
                      <span className="text-gray-400 text-sm">Нет игроков</span>
                    )}
                  </div>
                </div>

                <div className="bg-green-50 rounded-lg p-4 border border-green-200">
                  <h4 className="font-semibold text-green-800 mb-3">Получает ({trade.players_involved?.receive?.length || 0}):</h4>
                  <div className="space-y-1">
                    {trade.players_involved?.receive && trade.players_involved.receive.length > 0 ? (
                      trade.players_involved.receive.map((player, idx) => (
                        <div key={idx} className="text-sm text-gray-700 bg-white rounded px-2 py-1">
                          {player}
                        </div>
                      ))
                    ) : (
                      <span className="text-gray-400 text-sm">Нет игроков</span>
                    )}
                  </div>
                </div>
              </div>
            ) : (
              <div className="space-y-4">
                {Array.isArray(trade.players_involved) && trade.players_involved.map((teamTrade, idx) => (
                  <div key={idx} className="bg-gray-50 rounded-lg p-4 border border-gray-200">
                    <h4 className="font-semibold text-gray-800 mb-3">
                      Команда {idx + 1} (ID: {teamTrade.team_id})
                    </h4>
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                      <div>
                        <div className="text-sm font-medium text-red-700 mb-2">Отдает ({teamTrade.give?.length || 0}):</div>
                        <div className="space-y-1">
                          {teamTrade.give && teamTrade.give.length > 0 ? (
                            teamTrade.give.map((player, pIdx) => (
                              <div key={pIdx} className="text-sm text-gray-700 bg-white rounded px-2 py-1">
                                {player}
                              </div>
                            ))
                          ) : (
                            <span className="text-gray-400 text-sm">Нет игроков</span>
                          )}
                        </div>
                      </div>
                      <div>
                        <div className="text-sm font-medium text-green-700 mb-2">Получает ({teamTrade.receive?.length || 0}):</div>
                        <div className="space-y-1">
                          {teamTrade.receive && teamTrade.receive.length > 0 ? (
                            teamTrade.receive.map((player, pIdx) => (
                              <div key={pIdx} className="text-sm text-gray-700 bg-white rounded px-2 py-1">
                                {player}
                              </div>
                            ))
                          ) : (
                            <span className="text-gray-400 text-sm">Нет игроков</span>
                          )}
                        </div>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Полный результат */}
          {trade.full_result && (
            <div className="mb-6">
              <h3 className="font-semibold text-gray-800 mb-4">Результаты анализа</h3>
              <div className="bg-gray-50 rounded-lg p-4 border border-gray-200">
                <pre className="text-xs overflow-x-auto text-gray-700">
                  {JSON.stringify(trade.full_result, null, 2)}
                </pre>
              </div>
            </div>
          )}

          {/* Кнопка закрытия */}
          <div className="flex justify-end">
            <button
              onClick={onClose}
              className="px-6 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 font-medium transition-colors"
            >
              Закрыть
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};

export default AdminPanel;

