import React, { useState, useEffect } from 'react';
import Analytics from './components/Analytics';
import Simulation from './components/Simulation';
import FreeAgents from './components/FreeAgents';
import AllPlayers from './components/AllPlayers';
import PlayerModal from './components/PlayerModal';
import TradeAnalyzer from './components/TradeAnalyzer';

function App() {
  const [activeTab, setActiveTab] = useState('analytics');
  const [selectedPlayer, setSelectedPlayer] = useState(null);

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

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="bg-blue-900 text-white p-4 shadow-md">
        <h1 className="text-2xl font-bold">NBA Fantasy Analytics</h1>
      </header>

      <main className="container mx-auto mt-4 p-4">
        <div className="flex border-b mb-4 overflow-x-auto">
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

      {selectedPlayer && <PlayerModal player={selectedPlayer} onClose={closeModal} />}
    </div>
  );
}

export default App;
