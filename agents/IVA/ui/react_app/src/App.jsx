import React, { useState, useEffect } from 'react';
import AppHeader from './components/AppHeader';
import HistoryPanel from './components/HistoryPanel';
import PortfolioSummaryPanel from './components/PortfolioSummaryPanel';
import SettingsMenu from './components/SettingsMenu';
import ResizablePanelGroup from './components/ResizablePanelGroup';
import LiveReadinessModal from './components/LiveReadinessModal';
import ModeSelectorModal from './components/ModeSelectorModal';
import LiveDataValidationPanel from './components/LiveDataValidationPanel';
import AlgorithmsPage from './pages/AlgorithmsPage';
import HistoryPage from './pages/HistoryPage';
import PortfolioPage from './pages/PortfolioPage';
import MemoryPage from './pages/MemoryPage';
import ProfilePage from './pages/ProfilePage';
import ReadinessPage from './pages/ReadinessPage';
import ResearchLabPage from './pages/ResearchLabPage';
import AgentsPage from './pages/AgentsPage';
import OrchestrationPage from './pages/OrchestrationPage';
import { api } from './services/api';

const SUPPORTED_PAGES = ['trading', 'history', 'algorithms', 'portfolio', 'memory', 'profile', 'readiness', 'research', 'agents', 'orchestration'];

export default function App() {
  const [currentPage, setCurrentPage] = useState(() => {
    const path = window.location.pathname.replace('/', '') || 'trading';
    return SUPPORTED_PAGES.includes(path) ? path : 'trading';
  });

  const [selectedEpoch, setSelectedEpoch] = useState(() => {
    const saved = localStorage.getItem('agi_v5_epoch');
    if (saved) return saved;
    return 'epoch_100k';
  });

  const [customEpochs, setCustomEpochs] = useState(() => {
    try {
      const saved = localStorage.getItem('agi_v5_custom_epochs');
      return saved ? JSON.parse(saved) : [];
    } catch {
      return [];
    }
  });

  const [isHistoryOpen, setIsHistoryOpen] = useState(false);
  const [isPortfolioOpen, setIsPortfolioOpen] = useState(false);
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
  const [isLiveModalOpen, setIsLiveModalOpen] = useState(false);
  const [isModeModalOpen, setIsModeModalOpen] = useState(false);
  const [isLiveDataModalOpen, setIsLiveDataModalOpen] = useState(false);
  const [resetSignal, setResetSignal] = useState(0);
  const [statusData, setStatusData] = useState(null);
  const [historyRange, setHistoryRange] = useState('today');
  const currentMode = statusData?.operating_mode?.current_mode || statusData?.mode || localStorage.getItem('agi_v5_mode') || 'LIVE_EXECUTION';
  const isLive = currentMode === 'LIVE_EXECUTION';

  // Sync selectedEpoch to localStorage
  useEffect(() => {
    localStorage.setItem('agi_v5_epoch', selectedEpoch);
  }, [selectedEpoch]);

  // Sync browser path navigation
  useEffect(() => {
    function onPopState() {
      const path = window.location.pathname.replace('/', '') || 'trading';
      setCurrentPage(SUPPORTED_PAGES.includes(path) ? path : 'trading');
    }
    window.addEventListener('popstate', onPopState);
    return () => window.removeEventListener('popstate', onPopState);
  }, []);

  const navigateTo = (pageId) => {
    const target = SUPPORTED_PAGES.includes(pageId) ? pageId : 'trading';
    setCurrentPage(target);
    window.history.pushState({}, '', `/${target}`);
    setIsHistoryOpen(false);
    setIsPortfolioOpen(false);
    setIsSettingsOpen(false);
  };

  const loadStatus = async () => {
    try {
      const data = await api.getStatus();
      if (data) {
        setStatusData(data);
        const backendMode = data?.operating_mode?.current_mode || data?.mode;
        if (backendMode) {
          localStorage.setItem('agi_v5_mode', backendMode);
        }
      }
    } catch (err) {
      // Suppress transient poll errors
    }
  };

  // Poll status from backend
  useEffect(() => {
    let active = true;
    loadStatus();
    const interval = setInterval(() => {
      if (active) loadStatus();
    }, 5000);
    return () => {
      active = false;
      clearInterval(interval);
    };
  }, []);

  const handleSelectMode = async (modeId) => {
    try {
      localStorage.setItem('agi_v5_mode', modeId);
      await api.setOperatingMode(modeId, 'Operator selected from header');
      await loadStatus();
      if (modeId === 'LIVE_DATA_VALIDATION') {
        setIsLiveDataModalOpen(true);
      }
    } catch (err) {
      // If blocked (e.g. LIVE_EXECUTION 403), open the mode selector modal with full details
      setIsModeModalOpen(true);
      await loadStatus();
    }
  };

  const handleEmergencyStop = async () => {
    try {
      await api.triggerEmergencyStop('Operator header STOP button');
      await loadStatus();
    } catch (err) {
      console.error('Emergency stop error:', err);
    }
  };

  const handleResetLayout = () => {
    setResetSignal((prev) => prev + 1);
  };

  return (
    <div className="flex flex-col h-full w-full max-h-full max-w-full min-h-0 min-w-0 overflow-hidden bg-slate-950 text-slate-100 font-sans antialiased">
      {/* 1. Minimal Application Header with 6 Principal Controls */}
      <AppHeader
        activePage={currentPage}
        onNavigate={navigateTo}
        onOpenHistory={() => {
          setIsHistoryOpen((prev) => !prev);
          setIsPortfolioOpen(false);
          setIsSettingsOpen(false);
        }}
        onOpenPortfolio={() => {
          setIsPortfolioOpen((prev) => !prev);
          setIsHistoryOpen(false);
          setIsSettingsOpen(false);
        }}
        onToggleSettings={() => {
          setIsSettingsOpen((prev) => !prev);
          setIsHistoryOpen(false);
          setIsPortfolioOpen(false);
        }}
        onOpenLiveReadiness={() => setIsLiveModalOpen(true)}
        onOpenModeSelector={() => setIsModeModalOpen(true)}
        onOpenLiveDataValidation={() => setIsLiveDataModalOpen(true)}
        onSelectMode={handleSelectMode}
        onEmergencyStop={handleEmergencyStop}
        isSettingsOpen={isSettingsOpen}
        isHistoryOpen={isHistoryOpen}
        isPortfolioOpen={isPortfolioOpen}
        statusData={statusData}
        selectedEpoch={selectedEpoch}
      />

      {/* Settings Dropdown */}
      <SettingsMenu
        isOpen={isSettingsOpen}
        onClose={() => setIsSettingsOpen(false)}
        onResetLayout={handleResetLayout}
        onNavigateSettings={() => navigateTo('portfolio')}
      />

      {/* History Popover Panel */}
      <HistoryPanel
        isOpen={isHistoryOpen}
        onClose={() => setIsHistoryOpen(false)}
        selectedRange={historyRange}
        onSelectRange={(rangeId) => {
          setHistoryRange(rangeId);
        }}
        onOpenFullHistory={() => {
          navigateTo('history');
        }}
      />

      {/* Portfolio Summary Popover Panel */}
      <PortfolioSummaryPanel
        isOpen={isPortfolioOpen}
        onClose={() => setIsPortfolioOpen(false)}
        statusData={statusData}
        onNavigatePortfolio={() => navigateTo('portfolio')}
        selectedEpoch={selectedEpoch}
        onSelectEpoch={setSelectedEpoch}
        customEpochs={customEpochs}
      />

      {/* Live Trading Readiness 10-Gate Audit Modal */}
      <LiveReadinessModal
        isOpen={isLiveModalOpen}
        onClose={() => setIsLiveModalOpen(false)}
        onNavigateToReadiness={() => navigateTo('readiness')}
      />

      {/* Operating Mode Selector Modal */}
      <ModeSelectorModal
        isOpen={isModeModalOpen}
        onClose={() => setIsModeModalOpen(false)}
        currentMode={statusData?.operating_mode?.current_mode || statusData?.mode || 'PAPER'}
        onModeChanged={() => loadStatus()}
        onOpenLiveDataValidation={() => setIsLiveDataModalOpen(true)}
      />

      {/* Live Market Data Feed Diagnostic Panel */}
      <LiveDataValidationPanel
        isOpen={isLiveDataModalOpen}
        onClose={() => setIsLiveDataModalOpen(false)}
        onSwitchToPaper={() => loadStatus()}
      />

      {/* Main Content Workspace */}
      <div className="flex-1 min-h-0 min-w-0 flex flex-col h-full w-full max-h-full max-w-full overflow-hidden relative">
        {currentPage === 'trading' && (
          <ResizablePanelGroup
            resetSignal={resetSignal}
            selectedEpoch={selectedEpoch}
            currentMode={statusData?.operating_mode?.current_mode || statusData?.mode || 'PAPER'}
          />
        )}

        {currentPage === 'history' && (
          <HistoryPage
            onBackToTrading={() => navigateTo('trading')}
            selectedEpoch={selectedEpoch}
            customEpochs={customEpochs}
            initialRange={historyRange}
            currentMode={currentMode}
            isLive={isLive}
            statusData={statusData}
          />
        )}

        {currentPage === 'algorithms' && (
          <AlgorithmsPage onBackToTrading={() => navigateTo('trading')} />
        )}

        {currentPage === 'portfolio' && (
          <PortfolioPage
            onBackToTrading={() => navigateTo('trading')}
            statusData={statusData}
            currentMode={currentMode}
            isLive={isLive}
            selectedEpoch={selectedEpoch}
            onSelectEpoch={setSelectedEpoch}
            customEpochs={customEpochs}
            setCustomEpochs={setCustomEpochs}
          />
        )}

        {currentPage === 'memory' && (
          <MemoryPage onBackToTrading={() => navigateTo('trading')} />
        )}

        {currentPage === 'profile' && (
          <ProfilePage
            onBackToTrading={() => navigateTo('trading')}
            selectedEpoch={selectedEpoch}
            onSelectEpoch={setSelectedEpoch}
            customEpochs={customEpochs}
            currentMode={currentMode}
            isLive={isLive}
            statusData={statusData}
            onOpenLiveReadiness={() => setIsLiveModalOpen(true)}
          />
        )}

        {currentPage === 'readiness' && (
          <ReadinessPage
            onBackToTrading={() => navigateTo('trading')}
          />
        )}

        {currentPage === 'research' && (
          <ResearchLabPage
            onBackToTrading={() => navigateTo('trading')}
            selectedEpoch={selectedEpoch}
          />
        )}

        {currentPage === 'agents' && (
          <AgentsPage
            onBackToTrading={() => navigateTo('trading')}
          />
        )}

        {currentPage === 'orchestration' && (
          <OrchestrationPage
            onBackToTrading={() => navigateTo('trading')}
          />
        )}
      </div>
    </div>
  );
}
