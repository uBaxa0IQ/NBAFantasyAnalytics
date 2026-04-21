import React, { useState, useEffect } from 'react';
import api from './api';
import Dashboard from './components/Dashboard';
import Analytics from './components/Analytics';
import Simulation from './components/Simulation';
import PlayersTab from './components/PlayersTab';
import PlayerModal from './components/PlayerModal';
import TradeAnalyzer from './components/TradeAnalyzer';
import PlayoffAnalysis from './components/PlayoffAnalysis';
import ComparisonBar from './components/ComparisonBar';
import PlayerComparisonModal from './components/PlayerComparisonModal';
import SettingsModal from './components/SettingsModal';
import AdminPanel from './components/AdminPanel';
import AdminPasswordModal from './components/AdminPasswordModal';
import { useArrowSequence } from './hooks/useArrowSequence';

function App() {
  const [activeTab, setActiveTab] = useState('dashboard');
  const [selectedPlayer, setSelectedPlayer] = useState(null);
  const [comparisonPlayers, setComparisonPlayers] = useState([]);
  const [showComparisonModal, setShowComparisonModal] = useState(false);
  const [showSettingsModal, setShowSettingsModal] = useState(false);
  const [isAdmin, setIsAdmin] = useState(false);
  const [showAdminPasswordModal, setShowAdminPasswordModal] = useState(false);
  const [isPlayoff, setIsPlayoff] = useState(false);
  
  // Глобальные настройки лиги
  const [leagueSettings, setLeagueSettings] = useState({
    force_weighted_mode: false,
    forced_period: '2026_weighted'
  });

  // Загрузка глобальных настроек с периодическим обновлением
  useEffect(() => {
    const fetchLeagueSettings = async () => {
      try {
        const response = await api.get('/settings');
        if (response.data) {
          setLeagueSettings(prevSettings => {
            // Обновляем только если данные изменились, чтобы избежать лишних ререндеров
            if (JSON.stringify(prevSettings) !== JSON.stringify(response.data)) {
              return response.data;
            }
            return prevSettings;
          });
          
          // Если включен принудительный режим, устанавливаем выбранный период
          // Делаем это при каждом обновлении настроек, чтобы перехватить изменение "на лету"
          if (response.data.force_weighted_mode) {
            const forcedPeriod = response.data.forced_period || '2026_weighted';
            setPeriod(current => current !== forcedPeriod ? forcedPeriod : current);
          }
        }
      } catch (error) {
        console.error('Error fetching league settings:', error);
      }
    };
    
    // Первичная загрузка
    fetchLeagueSettings();

    // Периодическое обновление каждые 30 секунд
    const intervalId = setInterval(fetchLeagueSettings, 30000);

    return () => clearInterval(intervalId);
  }, []);

  // Общие настройки для всех вкладок с сохранением в localStorage
  const [period, setPeriod] = useState(() => {
    // Если режим принудительный (мы пока не знаем при инициализации, поэтому проверим в useEffect)
    // но пока берем из localStorage
    return localStorage.getItem('period') || '2026_total';
  });

  const [puntCategories, setPuntCategories] = useState(() => {
    const saved = localStorage.getItem('puntCategories');
    return saved ? JSON.parse(saved) : [];
  });

  const [colorByTrend, setColorByTrend] = useState(() => {
    const saved = localStorage.getItem('colorByTrend');
    return saved === 'true';
  });

  const [simulationMode, setSimulationMode] = useState(() => {
    const saved = localStorage.getItem('simulationMode');
    return saved || 'top_n';
  });

  const [mainTeam, setMainTeam] = useState(() => {
    return localStorage.getItem('mainTeam') || '';
  });

  // Сохранение в localStorage при изменении
  useEffect(() => {
    // Не сохраняем в localStorage если включен принудительный режим и период взвешенный
    // Или сохраняем, но при загрузке он все равно перезапишется
    // Но лучше сохранять, чтобы при отключении режима вернулся последний выбранный?
    // Нет, лучше сохранять всегда.
    localStorage.setItem('period', period);
  }, [period]);

  useEffect(() => {
    localStorage.setItem('puntCategories', JSON.stringify(puntCategories));
  }, [puntCategories]);

  useEffect(() => {
    localStorage.setItem('simulationMode', simulationMode);
  }, [simulationMode]);

  useEffect(() => {
    localStorage.setItem('mainTeam', mainTeam);
  }, [mainTeam]);

  useEffect(() => {
    localStorage.setItem('colorByTrend', colorByTrend.toString());
  }, [colorByTrend]);

  // Отслеживаем переход в плей-офф по данным с бэкенда
  useEffect(() => {
    const fetchPlayoffState = async () => {
      try {
        const response = await api.get('/playoff/state');
        if (response.data) {
          setIsPlayoff(!!response.data.is_playoff);
        }
      } catch (error) {
        console.error('Error fetching playoff state:', error);
      }
    };

    fetchPlayoffState();
    const intervalId = setInterval(fetchPlayoffState, 60000);

    return () => clearInterval(intervalId);
  }, []);

  const handleSaveSettings = (settings) => {
    setPeriod(settings.period);
    setPuntCategories(settings.puntCategories);
    setSimulationMode(settings.simulationMode);
    setMainTeam(settings.mainTeam);
    if (settings.colorByTrend !== undefined) {
      setColorByTrend(settings.colorByTrend);
    }
  };

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

  // Секретная комбинация стрелочек: ↑ ↑ ↓ ↓ →
  const arrowSequence = ['ArrowUp', 'ArrowUp', 'ArrowDown', 'ArrowDown', 'ArrowRight'];
  
  const handleArrowSequenceComplete = () => {
    setShowAdminPasswordModal(true);
  };

  useArrowSequence(arrowSequence, handleArrowSequenceComplete);

  const handleAdminLoginSuccess = () => {
    setIsAdmin(true);
    setActiveTab('admin');
  };

  const handleExitAdmin = () => {
    setIsAdmin(false);
    setActiveTab('dashboard');
  };

  // Если админ вошел, показываем админ панель
  if (isAdmin) {
    return (
      <div className="min-h-screen bg-gray-50">
        <header className="bg-blue-900 text-white p-4 shadow-md">
          <div className="container mx-auto max-w-7xl flex justify-between items-center">
            <h1 className="text-2xl font-bold">Админ-панель</h1>
            <button
              onClick={handleExitAdmin}
              className="px-4 py-2 bg-white text-blue-900 rounded hover:bg-gray-100 font-medium"
            >
              Выйти
            </button>
          </div>
        </header>
        <main className="container mx-auto mt-4 p-4 max-w-7xl">
          <AdminPanel />
        </main>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="bg-blue-900 text-white p-4 shadow-md">
        <h1 className="text-2xl font-bold text-center">NBA Fantasy Analytics</h1>
      </header>

      <div className="sticky top-0 bg-white z-10 border-b shadow-sm">
        <div className="container mx-auto max-w-7xl">
          <div className="flex items-center">
            <div className="grid grid-cols-5 gap-0 overflow-x-auto flex-1">
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
                className={`py-2 px-4 font-medium whitespace-nowrap ${activeTab === 'dashboard' ? 'border-b-2 border-blue-600 text-blue-600' : 'text-gray-500 hover:text-gray-700'}`}
                onClick={() => setActiveTab('dashboard')}
              >
                Dashboard
              </button>
              <button
                className={`py-2 px-4 font-medium whitespace-nowrap ${activeTab === 'players' ? 'border-b-2 border-blue-600 text-blue-600' : 'text-gray-500 hover:text-gray-700'}`}
                onClick={() => setActiveTab('players')}
              >
                Игроки
              </button>
              <button
                className={`py-2 px-4 font-medium whitespace-nowrap ${activeTab === 'trade' ? 'border-b-2 border-blue-600 text-blue-600' : 'text-gray-500 hover:text-gray-700'}`}
                onClick={() => setActiveTab('trade')}
              >
                {isPlayoff ? 'Плей-офф' : 'Анализ трейдов'}
              </button>
            </div>
            <button
              onClick={() => setShowSettingsModal(true)}
              className="ml-4 p-2 text-gray-500 hover:text-gray-700 hover:bg-gray-100 rounded"
              title="Настройки"
            >
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
              </svg>
            </button>
          </div>
        </div>
      </div>

      <main className="container mx-auto mt-4 p-4 max-w-7xl" style={{ paddingBottom: comparisonPlayers.length >= 2 ? '120px' : '0' }}>
        <div className="bg-white rounded shadow p-4 min-h-[500px]">
          {activeTab === 'dashboard' && (
            <Dashboard
              period={period}
              puntCategories={puntCategories}
              mainTeam={mainTeam}
              simulationMode={simulationMode}
              isPlayoff={isPlayoff}
            />
          )}
          {activeTab === 'analytics' && (
            <Analytics
              onPlayerClick={handlePlayerClick}
              period={period}
              puntCategories={puntCategories}
              colorByTrend={colorByTrend}
            />
          )}
          {activeTab === 'simulation' && (
            <Simulation
              period={period}
              simulationMode={simulationMode}
              mainTeam={mainTeam}
            />
          )}
          {activeTab === 'players' && (
            <PlayersTab
              onPlayerClick={handlePlayerClick}
              period={period}
              puntCategories={puntCategories}
              simulationMode={simulationMode}
              colorByTrend={colorByTrend}
            />
          )}
          {activeTab === 'trade' && (
            isPlayoff ? (
              <PlayoffAnalysis
                period={period}
                mainTeam={mainTeam}
                simulationMode={simulationMode}
              />
            ) : (
              <TradeAnalyzer
                period={period}
                puntCategories={puntCategories}
                simulationMode={simulationMode}
                mainTeam={mainTeam}
              />
            )
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

      <SettingsModal
        isOpen={showSettingsModal}
        onClose={() => setShowSettingsModal(false)}
        onSave={handleSaveSettings}
        initialSettings={{
          period,
          puntCategories,
          simulationMode,
          mainTeam,
          colorByTrend
        }}
        leagueSettings={leagueSettings}
      />

      <AdminPasswordModal
        isOpen={showAdminPasswordModal}
        onClose={() => setShowAdminPasswordModal(false)}
        onSuccess={handleAdminLoginSuccess}
      />
    </div>
  );
}

export default App;
