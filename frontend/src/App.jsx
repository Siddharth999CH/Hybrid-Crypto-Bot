import { useState, useEffect, useCallback, useRef } from 'react';
import { WS_URL, api } from './lib/api';
import Dashboard from './pages/Dashboard';
import Signals from './pages/Signals';
import TradingScreen from './pages/TradingScreen';
import Ingestion from './pages/Ingestion';
import Trades from './pages/Trades';
import Settings from './pages/Settings';
import { 
  Activity, 
  Radio, 
  FileText, 
  BarChart2, 
  Settings as SettingsIcon, 
  Zap 
} from 'lucide-react';

const TABS = [
  { id: 'dashboard', label: 'Dashboard', icon: Activity },
  { id: 'signals',   label: 'Signals & Approvals', icon: Radio },
  { id: 'trading',   label: 'Live Terminal', icon: Zap },
  { id: 'trades',    label: 'Trade History', icon: BarChart2 },
  { id: 'ingestion', label: 'Data Ingestion', icon: FileText },
  { id: 'settings',  label: 'Settings', icon: SettingsIcon },
];

export default function App() {
  const [tab, setTab] = useState('dashboard');
  const [status, setStatus] = useState(null);
  const [pendingApprovals, setPendingApprovals] = useState([]);
  const [wsConnected, setWsConnected] = useState(false);
  const [toast, setToast] = useState(null);
  const wsRef = useRef(null);

  const showToast = useCallback((msg, type = 'info') => {
    setToast({ msg, type });
    setTimeout(() => setToast(null), 4000);
  }, []);

  const fetchStatus = useCallback(async () => {
    try {
      const data = await api.get('/api/status');
      setStatus(data);
    } catch (err) {
      console.error("Status fetch failed", err);
    }
  }, []);

  const fetchApprovals = useCallback(async () => {
    try {
      const data = await api.get('/api/approvals');
      setPendingApprovals(data);
    } catch (err) {
      console.error("Approvals fetch failed", err);
    }
  }, []);

  // WebSocket Logic
  useEffect(() => {
    function connect() {
      const ws = new WebSocket(WS_URL);
      wsRef.current = ws;

      ws.onopen = () => setWsConnected(true);
      ws.onclose = () => {
        setWsConnected(false);
        setTimeout(connect, 3000);
      };
      ws.onmessage = (e) => {
        const { type, data } = JSON.parse(e.data);
        if (type === 'init') {
          setStatus(data);
        } else if (type === 'approval_requested') {
          setPendingApprovals(prev => {
            const exists = prev.find(a => a.signal_id === data.signal_id);
            return exists ? prev : [data, ...prev];
          });
          showToast(`🔔 New signal: ${data.coin} ${data.direction}`, 'approval');
        } else if (type === 'trade_opened') {
          showToast(`✅ Trade opened: ${data.coin}`, 'success');
          fetchStatus();
        } else if (type === 'trade_closed') {
          const sign = data.pnl_usdt >= 0 ? '+' : '';
          showToast(`🎯 ${data.coin} closed: ${sign}$${data.pnl_usdt?.toFixed(2)}`, data.pnl_usdt >= 0 ? 'success' : 'danger');
          fetchStatus();
        } else if (type === 'signal_expired') {
          setPendingApprovals(prev => prev.filter(a => a.signal_id !== data.signal_id));
        } else if (type === 'status_changed') {
          setStatus(prev => ({ ...prev, ...data }));
        }
      };
    }
    connect();
    return () => wsRef.current?.close();
  }, [showToast, fetchStatus]);

  useEffect(() => {
    fetchStatus();
    fetchApprovals();
    const interval = setInterval(fetchStatus, 10000);
    return () => clearInterval(interval);
  }, [fetchStatus, fetchApprovals]);

  const pageProps = { 
    status, 
    pendingApprovals, 
    setPendingApprovals, 
    showToast, 
    fetchStatus 
  };

  return (
    <div className="min-h-screen bg-[#0A0B0E] text-gray-100 font-mono">
      {/* Header / Navbar */}
      <header className="border-b border-gray-800 bg-[#0D0E12] sticky top-0 z-50">
        <div className="max-w-7xl mx-auto px-4 h-14 flex items-center gap-6">
          <div className="flex items-center gap-2 mr-4">
            <Zap size={16} className="text-emerald-400" />
            <span className="text-sm font-bold tracking-widest text-white uppercase">
              Signal<span className="text-emerald-400">Bot</span>
            </span>
          </div>

          <nav className="flex gap-1 flex-1">
            {TABS.map(({ id, label, icon: Icon }) => (
              <button
                key={id}
                onClick={() => setTab(id)}
                className={`relative flex items-center gap-1.5 px-3 py-1.5 text-xs rounded transition-all
                  ${tab === id
                    ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
                    : 'text-gray-500 hover:text-gray-300 hover:bg-white/5'
                  }`}
              >
                <Icon size={12} />
                {label}
                {/* Fixed Badge Logic for Signals Tab */}
                {id === 'signals' && pendingApprovals.length > 0 && (
                  <span className="absolute -top-1 -right-1 bg-amber-500 text-black text-[9px] font-bold rounded-full w-4 h-4 flex items-center justify-center shadow-lg">
                    {pendingApprovals.length}
                  </span>
                )}
              </button>
            ))}
          </nav>

          <div className="flex items-center gap-3 ml-auto">
            {status?.paper_mode && (
              <span className="text-[10px] px-2 py-0.5 rounded border border-amber-500/30 text-amber-400 bg-amber-500/10 font-bold">
                PAPER
              </span>
            )}
            <div className={`flex items-center gap-1.5 text-xs ${wsConnected ? 'text-emerald-400' : 'text-gray-600'}`}>
              <span className={`w-1.5 h-1.5 rounded-full ${wsConnected ? 'bg-emerald-400 animate-pulse' : 'bg-gray-600'}`} />
              {wsConnected ? 'Live' : 'Offline'}
            </div>
          </div>
        </div>
      </header>

      {/* Main Content Area */}
      <main className="max-w-7xl mx-auto px-4 py-6">
        {tab === 'dashboard' && <Dashboard {...pageProps} />}
        {tab === 'signals'   && <Signals {...pageProps} />} 
        {tab === 'trading'   && <TradingScreen {...pageProps} />} 
        {tab === 'trades'    && <Trades {...pageProps} />}
        {tab === 'ingestion' && <Ingestion {...pageProps} />}
        {tab === 'settings'  && <Settings {...pageProps} />}
      </main>

      {/* Toast Notifications */}
      {toast && (
        <div className={`fixed bottom-6 right-6 z-50 px-4 py-3 rounded-lg text-sm border shadow-2xl transition-all animate-in slide-in-from-bottom-5
          ${toast.type === 'success' ? 'bg-emerald-950 border-emerald-700 text-emerald-300' :
            toast.type === 'danger'  ? 'bg-red-950 border-red-700 text-red-300' :
            toast.type === 'approval'? 'bg-amber-950 border-amber-700 text-amber-300' :
            'bg-gray-900 border-gray-700 text-gray-300'}`}>
          {toast.msg}
        </div>
      )}
    </div>
  );
}