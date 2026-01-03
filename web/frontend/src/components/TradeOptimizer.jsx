import React, { useState, useEffect } from 'react';
import api from '../api';

const TradeOptimizer = () => {
  const [teams, setTeams] = useState([]);
  const [myTeam, setMyTeam] = useState('');
  const [theirTeam, setTheirTeam] = useState('');
  const [myPlayers, setMyPlayers] = useState([]);
  const [theirPlayers, setTheirPlayers] = useState([]);
  const [selectedGive, setSelectedGive] = useState([]);
  const [selectedReceive, setSelectedReceive] = useState([]);
  
  const [coefficients, setCoefficients] = useState({
    total: 0.40,
    last_30: 0.30,
    last_15: 0.20,
    last_7: 0.10
  });
  
  const [analysisResult, setAnalysisResult] = useState(null);
  const [autoSearchResults, setAutoSearchResults] = useState(null);
  const [loading, setLoading] = useState(false);
  const [searching, setSearching] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [autoSearchMode, setAutoSearchMode] = useState('avg'); // 'avg' или 'z_score'

  useEffect(() => {
    api.get('/teams').then(res => setTeams(res.data));
    loadCoefficients();
  }, []);

  const loadCoefficients = async () => {
    try {
      const response = await api.get('/admin/weighted-coefficients');
      setCoefficients(response.data);
    } catch (err) {
      console.error('Error loading coefficients:', err);
    }
  };

  useEffect(() => {
    if (myTeam) {
      api.get(`/analytics/${myTeam}?period=2026_weighted&exclude_ir=false`)
        .then(res => setMyPlayers(res.data.players || []))
        .catch(err => console.error(err));
    } else {
      setMyPlayers([]);
    }
  }, [myTeam]);

  useEffect(() => {
    if (theirTeam) {
      api.get(`/analytics/${theirTeam}?period=2026_weighted&exclude_ir=false`)
        .then(res => setTheirPlayers(res.data.players || []))
        .catch(err => console.error(err));
    } else {
      setTheirPlayers([]);
    }
  }, [theirTeam]);

  const handleCoefficientChange = (key, value) => {
    const numValue = parseFloat(value) || 0;
    setCoefficients(prev => {
      const updated = { ...prev, [key]: numValue };
      const sum = updated.total + updated.last_30 + updated.last_15 + updated.last_7;
      if (sum > 0) {
        const factor = 1.0 / sum;
        return {
          total: updated.total * factor,
          last_30: updated.last_30 * factor,
          last_15: updated.last_15 * factor,
          last_7: updated.last_7 * factor
        };
      }
      return updated;
    });
  };

  const handleAnalyze = async () => {
    if (!myTeam || !theirTeam || selectedGive.length === 0 || selectedReceive.length === 0) {
      setError('Выберите команды и игроков для трейда');
      return;
    }

    setLoading(true);
    setError('');
    
    try {
      const response = await api.post('/admin/trade-optimization', {
        my_team_id: parseInt(myTeam),
        their_team_id: parseInt(theirTeam),
        i_give: selectedGive,
        i_receive: selectedReceive,
        custom_coefficients: {
          '2026_total': coefficients.total,
          '2026_last_30': coefficients.last_30,
          '2026_last_15': coefficients.last_15,
          '2026_last_7': coefficients.last_7
        },
        period: '2026_weighted',
        simulation_mode: 'top_n',
        top_n_players: 13
      });
      
      setAnalysisResult(response.data);
    } catch (err) {
      setError(err.response?.data?.detail || 'Ошибка анализа трейда');
      setAnalysisResult(null);
    } finally {
      setLoading(false);
    }
  };

  const handleAutoSearch = async () => {
    if (!myTeam || !theirTeam || selectedGive.length === 0 || selectedReceive.length === 0) {
      setError('Выберите команды и игроков для трейда');
      return;
    }

    setSearching(true);
    setError('');
    setAutoSearchResults(null);
    
    try {
      const response = await api.post('/admin/trade-optimization/auto-search', {
        my_team_id: parseInt(myTeam),
        their_team_id: parseInt(theirTeam),
        i_give: selectedGive,
        i_receive: selectedReceive,
        period: '2026_weighted',
        simulation_mode: 'top_n',
        top_n_players: 13,
        step: 0.1,
        search_mode: autoSearchMode // 'avg' или 'z_score'
      });
      
      setAutoSearchResults(response.data);
    } catch (err) {
      setError(err.response?.data?.detail || 'Ошибка автопоиска');
    } finally {
      setSearching(false);
    }
  };

  const togglePlayer = (playerName, isGive) => {
    if (isGive) {
      setSelectedGive(prev => 
        prev.includes(playerName) 
          ? prev.filter(p => p !== playerName)
          : [...prev, playerName]
      );
    } else {
      setSelectedReceive(prev => 
        prev.includes(playerName) 
          ? prev.filter(p => p !== playerName)
          : [...prev, playerName]
      );
    }
  };


  return (
    <div className="space-y-6">
      <div className="bg-white rounded-lg shadow-md p-6">
        <h2 className="text-2xl font-bold mb-6 text-gray-800">Оптимизатор трейдов</h2>
        
        {/* Выбор команд и игроков */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mb-6">
          <div className="border rounded p-4">
            <label className="block font-bold mb-2">Моя команда:</label>
            <select 
              className="border p-2 rounded w-full mb-4" 
              value={myTeam} 
              onChange={e => setMyTeam(e.target.value)}
            >
              <option value="">Выберите команду</option>
              {teams.map(t => (
                <option key={t.team_id} value={t.team_id}>{t.team_name}</option>
              ))}
            </select>
            {myTeam && (
              <>
                <h3 className="font-bold mb-2">Я отдаю:</h3>
                <div className="space-y-1 max-h-64 overflow-y-auto">
                  {myPlayers.map(player => (
                    <label 
                      key={player.name} 
                      className={`flex items-center gap-2 p-2 rounded cursor-pointer ${
                        selectedGive.includes(player.name) ? 'bg-red-100' : 'hover:bg-gray-100'
                      }`}
                    >
                      <input 
                        type="checkbox" 
                        checked={selectedGive.includes(player.name)} 
                        onChange={() => togglePlayer(player.name, true)} 
                      />
                      <span>{player.name}</span>
                    </label>
                  ))}
                </div>
              </>
            )}
          </div>

          <div className="border rounded p-4">
            <label className="block font-bold mb-2">Их команда:</label>
            <select 
              className="border p-2 rounded w-full mb-4" 
              value={theirTeam} 
              onChange={e => setTheirTeam(e.target.value)}
            >
              <option value="">Выберите команду</option>
              {teams.map(t => (
                <option key={t.team_id} value={t.team_id}>{t.team_name}</option>
              ))}
            </select>
            {theirTeam && (
              <>
                <h3 className="font-bold mb-2">Я получаю:</h3>
                <div className="space-y-1 max-h-64 overflow-y-auto">
                  {theirPlayers.map(player => (
                    <label 
                      key={player.name} 
                      className={`flex items-center gap-2 p-2 rounded cursor-pointer ${
                        selectedReceive.includes(player.name) ? 'bg-green-100' : 'hover:bg-gray-100'
                      }`}
                    >
                      <input 
                        type="checkbox" 
                        checked={selectedReceive.includes(player.name)} 
                        onChange={() => togglePlayer(player.name, false)} 
                      />
                      <span>{player.name}</span>
                    </label>
                  ))}
                </div>
              </>
            )}
          </div>
        </div>

        {/* Настройка коэффициентов */}
        <div className="bg-gray-50 rounded-lg p-6 mb-6">
          <h3 className="text-lg font-semibold mb-4 text-gray-800">Коэффициенты для анализа:</h3>
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
                {(() => {
                  const sum = coefficients.total + coefficients.last_30 + coefficients.last_15 + coefficients.last_7;
                  return sum > 0 ? `${((coefficients.total / sum) * 100).toFixed(1)}%` : '0%';
                })()}
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
                {(() => {
                  const sum = coefficients.total + coefficients.last_30 + coefficients.last_15 + coefficients.last_7;
                  return sum > 0 ? `${((coefficients.last_30 / sum) * 100).toFixed(1)}%` : '0%';
                })()}
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
                {(() => {
                  const sum = coefficients.total + coefficients.last_30 + coefficients.last_15 + coefficients.last_7;
                  return sum > 0 ? `${((coefficients.last_15 / sum) * 100).toFixed(1)}%` : '0%';
                })()}
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
                {(() => {
                  const sum = coefficients.total + coefficients.last_30 + coefficients.last_15 + coefficients.last_7;
                  return sum > 0 ? `${((coefficients.last_7 / sum) * 100).toFixed(1)}%` : '0%';
                })()}
              </div>
            </div>
          </div>
          <div className={`mt-4 p-4 rounded-lg ${Math.abs((coefficients.total + coefficients.last_30 + coefficients.last_15 + coefficients.last_7) - 1.0) < 0.001 ? 'bg-green-50 border border-green-200' : 'bg-yellow-50 border border-yellow-200'}`}>
            <div className="flex justify-between items-center">
              <span className="font-medium text-gray-700">Сумма коэффициентов:</span>
              <span className={`font-bold ${Math.abs((coefficients.total + coefficients.last_30 + coefficients.last_15 + coefficients.last_7) - 1.0) < 0.001 ? 'text-green-600' : 'text-yellow-600'}`}>
                {(coefficients.total + coefficients.last_30 + coefficients.last_15 + coefficients.last_7).toFixed(3)} {Math.abs((coefficients.total + coefficients.last_30 + coefficients.last_15 + coefficients.last_7) - 1.0) < 0.001 ? '✓' : '(должна быть 1.000)'}
              </span>
            </div>
          </div>
        </div>

        {/* Кнопки действий */}
        <div className="mb-6">
          <div className="flex gap-4 mb-4">
            <button
              onClick={handleAnalyze}
              disabled={loading || !myTeam || !theirTeam || selectedGive.length === 0 || selectedReceive.length === 0}
              className="flex-1 bg-blue-600 text-white px-6 py-3 rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed font-medium"
            >
              {loading ? 'Анализ...' : 'Анализировать с текущими коэффициентами'}
            </button>
            <button
              onClick={handleAutoSearch}
              disabled={searching || !myTeam || !theirTeam || selectedGive.length === 0 || selectedReceive.length === 0}
              className="flex-1 bg-purple-600 text-white px-6 py-3 rounded-lg hover:bg-purple-700 disabled:opacity-50 disabled:cursor-not-allowed font-medium"
            >
              {searching ? 'Поиск...' : 'Автопоиск оптимальных коэффициентов'}
            </button>
          </div>
          {/* Выбор режима для автопоиска */}
          <div className="bg-gray-50 rounded-lg p-4">
            <label className="block text-sm font-medium text-gray-700 mb-2">
              Режим автопоиска:
            </label>
            <div className="inline-flex rounded-lg border border-gray-300 bg-white p-1">
              <button
                onClick={() => setAutoSearchMode('avg')}
                className={`px-4 py-2 rounded-md text-sm font-medium transition-colors ${
                  autoSearchMode === 'avg'
                    ? 'bg-blue-600 text-white'
                    : 'text-gray-700 hover:bg-gray-100'
                }`}
              >
                По симуляции (avg)
              </button>
              <button
                onClick={() => setAutoSearchMode('z_score')}
                className={`px-4 py-2 rounded-md text-sm font-medium transition-colors ${
                  autoSearchMode === 'z_score'
                    ? 'bg-blue-600 text-white'
                    : 'text-gray-700 hover:bg-gray-100'
                }`}
              >
                По Z-Score
              </button>
            </div>
          </div>
        </div>

        {error && (
          <div className="p-4 bg-red-50 border border-red-200 text-red-700 rounded-lg mb-6">
            {error}
          </div>
        )}

        {success && (
          <div className="p-4 bg-green-50 border border-green-200 text-green-700 rounded-lg mb-6">
            {success}
          </div>
        )}

        {/* Результаты анализа */}
        {analysisResult && (
          <div className="bg-white border rounded-lg p-6">
            <h3 className="text-lg font-semibold mb-4 text-gray-800">Результат анализа:</h3>
            
            {/* Симуляция по avg (основной результат) */}
            {analysisResult.simulation_avg && (
              <div className="mb-6">
                <h4 className="font-semibold mb-3 text-gray-700">Симуляция по среднему (места в рейтинге):</h4>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div className="bg-blue-50 rounded-lg p-4">
                    <h5 className="font-semibold mb-2">Моя команда:</h5>
                    <div className="space-y-1 text-sm">
                      <div>До: {analysisResult.simulation_avg.my_team.before !== null ? `Место ${analysisResult.simulation_avg.my_team.before}` : 'N/A'}</div>
                      <div>После: {analysisResult.simulation_avg.my_team.after !== null ? `Место ${analysisResult.simulation_avg.my_team.after}` : 'N/A'}</div>
                      {analysisResult.simulation_avg.my_team.delta !== null && (
                        <div className={`font-bold ${analysisResult.simulation_avg.my_team.delta <= 0 ? 'text-green-600' : 'text-red-600'}`}>
                          Δ: {analysisResult.simulation_avg.my_team.delta > 0 ? '+' : ''}{analysisResult.simulation_avg.my_team.delta} {analysisResult.simulation_avg.my_team.delta <= 0 ? '(улучшение)' : '(ухудшение)'}
                        </div>
                      )}
                    </div>
                  </div>
                  <div className="bg-green-50 rounded-lg p-4">
                    <h5 className="font-semibold mb-2">Их команда:</h5>
                    <div className="space-y-1 text-sm">
                      <div>До: {analysisResult.simulation_avg.their_team.before !== null ? `Место ${analysisResult.simulation_avg.their_team.before}` : 'N/A'}</div>
                      <div>После: {analysisResult.simulation_avg.their_team.after !== null ? `Место ${analysisResult.simulation_avg.their_team.after}` : 'N/A'}</div>
                      {analysisResult.simulation_avg.their_team.delta !== null && (
                        <div className={`font-bold ${analysisResult.simulation_avg.their_team.delta <= 0 ? 'text-green-600' : 'text-red-600'}`}>
                          Δ: {analysisResult.simulation_avg.their_team.delta > 0 ? '+' : ''}{analysisResult.simulation_avg.their_team.delta} {analysisResult.simulation_avg.their_team.delta <= 0 ? '(улучшение)' : '(ухудшение)'}
                        </div>
                      )}
                    </div>
                  </div>
                </div>
                {analysisResult.simulation_avg.my_team.delta !== null && analysisResult.simulation_avg.their_team.delta !== null && 
                 analysisResult.simulation_avg.my_team.delta <= 0 && analysisResult.simulation_avg.their_team.delta <= 0 && (
                  <div className="mt-4 p-4 bg-green-100 border border-green-300 rounded-lg text-green-800 font-semibold">
                    ✓ Трейд выгоден обеим командам (обе улучшают место в рейтинге)!
                  </div>
                )}
              </div>
            )}
            
            {/* Z-score (дополнительная информация) */}
            <div className="border-t pt-4">
              <h4 className="font-semibold mb-3 text-gray-700">Z-Score (дополнительно):</h4>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div className="bg-blue-50 rounded-lg p-4">
                  <h5 className="font-semibold mb-2">Моя команда:</h5>
                  <div className="space-y-1 text-sm">
                    <div>До: {analysisResult.my_team.before}</div>
                    <div>После: {analysisResult.my_team.after}</div>
                    <div className={`font-bold ${analysisResult.my_team.delta >= 0 ? 'text-green-600' : 'text-red-600'}`}>
                      Δ: {analysisResult.my_team.delta >= 0 ? '+' : ''}{analysisResult.my_team.delta}
                    </div>
                  </div>
                </div>
                <div className="bg-green-50 rounded-lg p-4">
                  <h5 className="font-semibold mb-2">Их команда:</h5>
                  <div className="space-y-1 text-sm">
                    <div>До: {analysisResult.their_team.before}</div>
                    <div>После: {analysisResult.their_team.after}</div>
                    <div className={`font-bold ${analysisResult.their_team.delta >= 0 ? 'text-green-600' : 'text-red-600'}`}>
                      Δ: {analysisResult.their_team.delta >= 0 ? '+' : ''}{analysisResult.their_team.delta}
                    </div>
                  </div>
                </div>
              </div>
              {analysisResult.both_positive && (
                <div className="mt-4 p-4 bg-green-100 border border-green-300 rounded-lg text-green-800 font-semibold">
                  ✓ Трейд выгоден обеим командам по Z-score!
                </div>
              )}
            </div>
          </div>
        )}

        {/* Результаты автопоиска */}
        {autoSearchResults && (
          <div className="bg-white border rounded-lg p-6">
            <h3 className="text-lg font-semibold mb-4 text-gray-800">
              Результаты автопоиска ({autoSearchMode === 'avg' ? 'по симуляции avg' : 'по Z-Score'}): найдено {autoSearchResults.found} комбинаций
            </h3>
            {autoSearchResults.best && (
              <div className="mb-4 p-4 bg-yellow-50 border border-yellow-300 rounded-lg">
                <h4 className="font-semibold mb-2">Лучшая комбинация:</h4>
                <div className="text-sm space-y-1">
                  <div>Season: {autoSearchResults.best.coefficients.total.toFixed(2)}</div>
                  <div>Last 30: {autoSearchResults.best.coefficients.last_30.toFixed(2)}</div>
                  <div>Last 15: {autoSearchResults.best.coefficients.last_15.toFixed(2)}</div>
                  <div>Last 7: {autoSearchResults.best.coefficients.last_7.toFixed(2)}</div>
                  {autoSearchResults.best.simulation_avg && (
                    <div className="mt-2 font-semibold">
                      Симуляция по avg:
                      <div className="ml-2">
                        Моя: {autoSearchResults.best.simulation_avg.my_team.delta !== null ? 
                          `${autoSearchResults.best.simulation_avg.my_team.delta > 0 ? '+' : ''}${autoSearchResults.best.simulation_avg.my_team.delta} (${autoSearchResults.best.simulation_avg.my_team.before} → ${autoSearchResults.best.simulation_avg.my_team.after})` : 'N/A'} | 
                        Их: {autoSearchResults.best.simulation_avg.their_team.delta !== null ? 
                          `${autoSearchResults.best.simulation_avg.their_team.delta > 0 ? '+' : ''}${autoSearchResults.best.simulation_avg.their_team.delta} (${autoSearchResults.best.simulation_avg.their_team.before} → ${autoSearchResults.best.simulation_avg.their_team.after})` : 'N/A'}
                      </div>
                    </div>
                  )}
                  <div className="mt-2 font-semibold">
                    Z-Score: Моя Δ: {autoSearchResults.best.my_delta >= 0 ? '+' : ''}{autoSearchResults.best.my_delta.toFixed(2)} | 
                    Их Δ: {autoSearchResults.best.their_delta >= 0 ? '+' : ''}{autoSearchResults.best.their_delta.toFixed(2)}
                    {autoSearchResults.best.both_positive_z && (
                      <span className="ml-2 text-green-600">✓ Обе улучшились</span>
                    )}
                  </div>
                </div>
              </div>
            )}
            {autoSearchResults.results && autoSearchResults.results.length > 0 && (
              <div className="max-h-96 overflow-y-auto">
                <table className="min-w-full divide-y divide-gray-200">
                  <thead className="bg-gray-50">
                    <tr>
                      <th className="px-4 py-2 text-left text-xs font-medium text-gray-500">Season</th>
                      <th className="px-4 py-2 text-left text-xs font-medium text-gray-500">Last 30</th>
                      <th className="px-4 py-2 text-left text-xs font-medium text-gray-500">Last 15</th>
                      <th className="px-4 py-2 text-left text-xs font-medium text-gray-500">Last 7</th>
                      <th className="px-4 py-2 text-left text-xs font-medium text-gray-500">Симуляция avg</th>
                      <th className="px-4 py-2 text-left text-xs font-medium text-gray-500">Z-Score</th>
                    </tr>
                  </thead>
                  <tbody className="bg-white divide-y divide-gray-200">
                    {autoSearchResults.results.map((result, idx) => (
                      <tr key={idx} className={`hover:bg-gray-50 ${
                        autoSearchMode === 'avg' 
                          ? (result.both_positive_avg ? 'bg-green-50' : '') 
                          : (result.both_positive_z ? 'bg-green-50' : '')
                      }`}>
                        <td className="px-4 py-2 text-sm">{result.coefficients.total.toFixed(2)}</td>
                        <td className="px-4 py-2 text-sm">{result.coefficients.last_30.toFixed(2)}</td>
                        <td className="px-4 py-2 text-sm">{result.coefficients.last_15.toFixed(2)}</td>
                        <td className="px-4 py-2 text-sm">{result.coefficients.last_7.toFixed(2)}</td>
                        <td className="px-4 py-2 text-sm">
                          {result.simulation_avg ? (
                            <div className="text-xs">
                              <div>Моя: {result.simulation_avg.my_team.delta !== null ? 
                                <span className={result.simulation_avg.my_team.delta <= 0 ? 'text-green-600 font-semibold' : 'text-red-600'}>
                                  {result.simulation_avg.my_team.delta > 0 ? '+' : ''}{result.simulation_avg.my_team.delta} ({result.simulation_avg.my_team.before}→{result.simulation_avg.my_team.after})
                                </span> : 'N/A'}
                              </div>
                              <div>Их: {result.simulation_avg.their_team.delta !== null ? 
                                <span className={result.simulation_avg.their_team.delta <= 0 ? 'text-green-600 font-semibold' : 'text-red-600'}>
                                  {result.simulation_avg.their_team.delta > 0 ? '+' : ''}{result.simulation_avg.their_team.delta} ({result.simulation_avg.their_team.before}→{result.simulation_avg.their_team.after})
                                </span> : 'N/A'}
                              </div>
                              {result.both_positive_avg && (
                                <div className="text-green-600 font-semibold mt-1">✓ Обе улучшают</div>
                              )}
                            </div>
                          ) : (
                            <span className="text-gray-400">N/A</span>
                          )}
                        </td>
                        <td className="px-4 py-2 text-sm">
                          <div className="text-xs">
                            <div>Моя: <span className={result.my_delta >= 0 ? 'text-green-600' : 'text-red-600'}>
                              {result.my_delta >= 0 ? '+' : ''}{result.my_delta.toFixed(2)}
                            </span></div>
                            <div>Их: <span className={result.their_delta >= 0 ? 'text-green-600' : 'text-red-600'}>
                              {result.their_delta >= 0 ? '+' : ''}{result.their_delta.toFixed(2)}
                            </span></div>
                            {result.both_positive_z && (
                              <div className="text-green-600 font-semibold mt-1">✓ Обе улучшились</div>
                            )}
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
};

export default TradeOptimizer;

