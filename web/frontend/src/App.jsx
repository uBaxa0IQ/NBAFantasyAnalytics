import React, { useState, useEffect } from 'react';
import Dashboard from './components/Dashboard';
import Analytics from './components/Analytics';
import Simulation from './components/Simulation';
import FreeAgents from './components/FreeAgents';
import AllPlayers from './components/AllPlayers';
import PlayerModal from './components/PlayerModal';
import TradeAnalyzer from './components/TradeAnalyzer';
import ComparisonBar from './components/ComparisonBar';
import PlayerComparisonModal from './components/PlayerComparisonModal';

function App() {
  const [activeTab, setActiveTab] = useState('dashboard');
  const [selectedPlayer, setSelectedPlayer] = useState(null);
  const [comparisonPlayers, setComparisonPlayers] = useState([]);
  const [showComparisonModal, setShowComparisonModal] = useState(false);

  // Общие настройки для всех вкладок с сохранением в localStorage
  const [period, setPeriod] = useState(() => {
    return localStorage.getItem('period') || '2026_total';
  });

  const [puntCategories, setPuntCategories] = useState(() => {
    const saved = localStorage.getItem('puntCategories');
    return saved ? JSON.parse(saved) : [];
  });

  const [selectedTeam, setSelectedTeam] = useState(() => {
    return localStorage.getItem('selectedTeam') || '';
  });

  // Сохранение в localStorage при изменении
  useEffect(() => {
    localStorage.setItem('period', period);
  }, [period]);

  useEffect(() => {
    localStorage.setItem('puntCategories', JSON.stringify(puntCategories));
  }, [puntCategories]);

  useEffect(() => {
    localStorage.setItem('selectedTeam', selectedTeam);
  }, [selectedTeam]);

  const handlePlayerClick = (player) => {
    setSelectedPlayer(player);
  };

  const closeModal = () => {
    setSelectedPlayer(null);
  };

  const addToComparison = (player) => {
    // Проверяем, не добавлен ли уже игрок
    if (comparisonPlayers.some(p => p.name === player.name)) {
      return;
    }
    
    // Проверяем максимум 5 игроков
    if (comparisonPlayers.length >= 5) {
      alert('Максимум 5 игроков для сравнения');
      return;
    }
    
    setComparisonPlayers([...comparisonPlayers, player]);
  };

  const removeFromComparison = (playerName) => {
    setComparisonPlayers(comparisonPlayers.filter(p => p.name !== playerName));
  };

  const clearComparison = () => {
    setComparisonPlayers([]);
  };

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="bg-blue-900 text-white p-4 shadow-md">
        <h1 className="text-2xl font-bold">NBA Fantasy Analytics</h1>
      </header>

      <main className="container mx-auto mt-4 p-4" style={{ paddingBottom: comparisonPlayers.length >= 2 ? '120px' : '0' }}>
        <div className="flex border-b mb-4 overflow-x-auto">
          <button
            className={`py-2 px-4 font-medium whitespace-nowrap ${activeTab === 'dashboard' ? 'border-b-2 border-blue-600 text-blue-600' : 'text-gray-500 hover:text-gray-700'}`}
            onClick={() => setActiveTab('dashboard')}
          >
            Dashboard
          </button>
          <button
            className={`py-2 px-4 font-medium whitespace-nowrap ${activeTab === 'analytics' ? 'border-b-2 border-blue-600 text-blue-600' : 'text-gray-500 hover:text-gray-700'}`}
            onClick={() => setActiveTab('analytics')}
          >
            Аналитика команды
          </button>
          <button
            className={`py-2 px-4 font-medium whitespace-nowrap ${activeTab === 'simulation' ? 'border-b-2 border-blue-600 text-blue-600' : 'text-gray-500 hover:text-gray-700'}`}
            onClick={() => setActiveTab('simulation')}
          >
            Симуляция матчапов
          </button>
          <button
            className={`py-2 px-4 font-medium whitespace-nowrap ${activeTab === 'free-agents' ? 'border-b-2 border-blue-600 text-blue-600' : 'text-gray-500 hover:text-gray-700'}`}
            onClick={() => setActiveTab('free-agents')}
          >
            Свободные агенты
          </button>
          <button
            className={`py-2 px-4 font-medium whitespace-nowrap ${activeTab === 'all-players' ? 'border-b-2 border-blue-600 text-blue-600' : 'text-gray-500 hover:text-gray-700'}`}
            onClick={() => setActiveTab('all-players')}
          >
            Все игроки
          </button>
          <button
            className={`py-2 px-4 font-medium whitespace-nowrap ${activeTab === 'trade' ? 'border-b-2 border-blue-600 text-blue-600' : 'text-gray-500 hover:text-gray-700'}`}
            onClick={() => setActiveTab('trade')}
          >
            Анализ трейдов
          </button>
        </div>

        <div className="bg-white rounded shadow p-4 min-h-[500px]">
          {activeTab === 'dashboard' && (
            <Dashboard
              period={period}
              setPeriod={setPeriod}
              puntCategories={puntCategories}
              setPuntCategories={setPuntCategories}
              selectedTeam={selectedTeam}
              setSelectedTeam={setSelectedTeam}
            />
          )}
          {activeTab === 'analytics' && (
            <Analytics
              onPlayerClick={handlePlayerClick}
              period={period}
              setPeriod={setPeriod}
              puntCategories={puntCategories}
              setPuntCategories={setPuntCategories}
              selectedTeam={selectedTeam}
              setSelectedTeam={setSelectedTeam}
            />
          )}
          {activeTab === 'simulation' && <Simulation />}
          {activeTab === 'free-agents' && (
            <FreeAgents
              onPlayerClick={handlePlayerClick}
              period={period}
              setPeriod={setPeriod}
              puntCategories={puntCategories}
              setPuntCategories={setPuntCategories}
            />
          )}
          {activeTab === 'all-players' && (
            <AllPlayers
              onPlayerClick={handlePlayerClick}
              period={period}
              setPeriod={setPeriod}
              puntCategories={puntCategories}
              setPuntCategories={setPuntCategories}
            />
          )}
          {activeTab === 'trade' && (
            <TradeAnalyzer
              period={period}
              setPeriod={setPeriod}
              puntCategories={puntCategories}
              setPuntCategories={setPuntCategories}
            />
          )}
        </div>
      </main>

      {selectedPlayer && (
        <PlayerModal 
          player={selectedPlayer} 
          onClose={closeModal}
          onAddToComparison={addToComparison}
          onRemoveFromComparison={removeFromComparison}
          isInComparison={comparisonPlayers.some(p => p.name === selectedPlayer.name)}
        />
      )}

      {comparisonPlayers.length >= 2 && (
        <ComparisonBar
          players={comparisonPlayers}
          onCompare={() => setShowComparisonModal(true)}
          onClear={clearComparison}
          onRemove={removeFromComparison}
        />
      )}

      {showComparisonModal && (
        <PlayerComparisonModal
          players={comparisonPlayers}
          onClose={() => setShowComparisonModal(false)}
        />
      )}
    </div>
  );
}

export default App;
