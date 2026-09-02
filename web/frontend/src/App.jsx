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
import DraftAssistant from './components/DraftAssistant';
import { getSeasonConfig, normalizeSavedPeriod, saveSeasonConfig } from './utils/periods';

function App() {
  const [activeTab, setActiveTab] = useState('dashboard');
  const [selectedPlayer, setSelectedPlayer] = useState(null);
  const [comparisonPlayers, setComparisonPlayers] = useState([]);
  const [showComparisonModal, setShowComparisonModal] = useState(false);
  const [showSettingsModal, setShowSettingsModal] = useState(false);
  const [isPlayoff, setIsPlayoff] = useState(false);
  const [draftState, setDraftState] = useState(null);
  const [seasonConfig, setSeasonConfig] = useState(getSeasonConfig);

  // Общие настройки для всех вкладок с сохранением в localStorage
  const [period, setPeriod] = useState(() => {
    const season = getSeasonConfig();
    return normalizeSavedPeriod(localStorage.getItem('period'), season.periods);
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

  const [calculationEngine, setCalculationEngine] = useState(() => {
    return localStorage.getItem('calculationEngine') || 'calendar';
  });

  // Сохранение в localStorage при изменении
  useEffect(() => {
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

  useEffect(() => {
    localStorage.setItem('calculationEngine', calculationEngine);
  }, [calculationEngine]);

  useEffect(() => {
    let cancelled = false;
    const loadSeasonSettings = async () => {
      try {
        const response = await api.get('/settings');
        const season = response.data?.season;
        if (!cancelled && season?.periods) {
          const previousSeason = getSeasonConfig();
          const leagueChanged = String(previousSeason?.league_id || '') !== String(season.league_id || '');
          const defaultTeamChanged = String(previousSeason?.default_team_id || '') !== String(season.default_team_id || '');
          saveSeasonConfig(season);
          setSeasonConfig(season);
          setPeriod(current => normalizeSavedPeriod(current, season.periods));
          setPuntCategories(current => current.filter(category => (season.categories || []).includes(category)));

          const teamsResponse = await api.get('/teams');
          if (cancelled) return;
          const teamIds = (teamsResponse.data || []).map(team => String(team.team_id));
          setMainTeam(current => {
            const preferred = season.default_team_id ? String(season.default_team_id) : '';
            if ((leagueChanged || defaultTeamChanged) && teamIds.includes(preferred)) return preferred;
            if (teamIds.includes(String(current))) return String(current);
            return teamIds.includes(preferred) ? preferred : (teamIds[0] || '');
          });
        }
      } catch (error) {
        console.error('Error fetching season settings:', error);
      }
    };
    loadSeasonSettings();
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    let timeoutId;
    let cancelled = false;
    const refreshDraftState = async () => {
      try {
        const response = await api.get('/draft/state');
        if (!cancelled) setDraftState(response.data);
        const delay = response.data?.status === 'live' ? 3000 : 15000;
        if (!cancelled) timeoutId = setTimeout(refreshDraftState, delay);
      } catch (error) {
        console.error('Error fetching draft state:', error);
        if (!cancelled) timeoutId = setTimeout(refreshDraftState, 30000);
      }
    };
    refreshDraftState();
    return () => {
      cancelled = true;
      clearTimeout(timeoutId);
    };
  }, []);

  // Отслеживаем переход в плей-офф по данным с бэкенда
  useEffect(() => {
    const fetchPlayoffState = async () => {
      try {
        const response = await api.get('/playoff/state');
        if (response.data) {
          const playoffActive = !!response.data.is_playoff;
          setIsPlayoff(playoffActive);
          if (!playoffActive) {
            setActiveTab(current => current === 'playoff' ? 'dashboard' : current);
          }
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
    setCalculationEngine(settings.calculationEngine);
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

  if (draftState?.status === 'live' || draftState?.status === 'upcoming' || draftState?.postdraft) {
    return (
      <div className="min-h-screen bg-gray-50">
        <header className="bg-blue-900 text-white p-4 shadow-md">
          <h1 className="text-2xl font-bold text-center">NBA Fantasy Analytics</h1>
        </header>
        <main
          className="container mx-auto p-4 max-w-7xl"
          style={{ paddingBottom: comparisonPlayers.length >= 2 ? '120px' : undefined }}
        >
          <DraftAssistant
            draftState={draftState}
            mainTeam={mainTeam}
            puntCategories={puntCategories}
            projectedPeriod={seasonConfig.periods.projected}
            leagueId={seasonConfig.league_id}
            onPuntCategoriesChange={setPuntCategories}
            onOpenSettings={() => setShowSettingsModal(true)}
            onPlayerClick={handlePlayerClick}
          />
        </main>
        {selectedPlayer && (
          <PlayerModal
            player={selectedPlayer}
            onClose={closeModal}
            onAddToComparison={addToComparison}
            onRemoveFromComparison={removeFromComparison}
            isInComparison={comparisonPlayers.some(player => player.name === selectedPlayer.name)}
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
          initialSettings={{ period, puntCategories, simulationMode, mainTeam, colorByTrend, calculationEngine }}
          seasonConfig={seasonConfig}
        />
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
            <div className={`grid ${isPlayoff ? 'grid-cols-6' : 'grid-cols-5'} gap-0 overflow-x-auto flex-1`}>
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
                Анализ трейдов
              </button>
              {isPlayoff && (
                <button
                  className={`py-2 px-4 font-medium whitespace-nowrap ${activeTab === 'playoff' ? 'border-b-2 border-blue-600 text-blue-600' : 'text-gray-500 hover:text-gray-700'}`}
                  onClick={() => setActiveTab('playoff')}
                >
                  Плей-офф
                </button>
              )}
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
              mainTeam={mainTeam}
              simulationMode={simulationMode}
              isPlayoff={isPlayoff}
              calculationEngine={calculationEngine}
              puntCategories={puntCategories}
              onApplyPuntStrategy={setPuntCategories}
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
              calculationEngine={calculationEngine}
            />
          )}
          {activeTab === 'players' && (
            <PlayersTab
              onPlayerClick={handlePlayerClick}
              period={period}
              puntCategories={puntCategories}
              simulationMode={simulationMode}
              colorByTrend={colorByTrend}
              mainTeam={mainTeam}
              calculationEngine={calculationEngine}
            />
          )}
          {activeTab === 'trade' && (
            <TradeAnalyzer
              period={period}
              puntCategories={puntCategories}
              simulationMode={simulationMode}
              mainTeam={mainTeam}
              calculationEngine={calculationEngine}
            />
          )}
          {activeTab === 'playoff' && isPlayoff && (
            <PlayoffAnalysis
              period={period}
              mainTeam={mainTeam}
              simulationMode={simulationMode}
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

      <SettingsModal
        isOpen={showSettingsModal}
        onClose={() => setShowSettingsModal(false)}
        onSave={handleSaveSettings}
        initialSettings={{
          period,
          puntCategories,
          simulationMode,
          mainTeam,
          colorByTrend,
          calculationEngine
        }}
        seasonConfig={seasonConfig}
      />
    </div>
  );
}

export default App;
