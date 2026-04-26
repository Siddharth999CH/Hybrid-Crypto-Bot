import React, { useState, useEffect, useRef } from 'react';
import { api, WS_URL } from '../lib/api';
import { Zap, Activity, Crosshair, AlertTriangle, ShieldCheck } from 'lucide-react';

export default function TradingScreen({ status }) {
  const [activeTrades, setActiveTrades] = useState([]);
  const [liveTelemetry, setLiveTelemetry] = useState({ exposure: 0, pnl: 0, trades: {} });
  const [loading, setLoading] = useState(true);
  const [wsStatus, setWsStatus] = useState('connecting');
  const wsRef = useRef(null);

  // 1. Fetch initial baseline trade records
  useEffect(() => {
    let isMounted = true;
    const fetchBaseline = async () => {
      try {
        const data = await api.get(`/api/trades?status=OPEN`);
        if (isMounted && Array.isArray(data)) {
          setActiveTrades(data);
          // Calculate initial static exposure/pnl before WS kicks in
          const initialExposure = data.reduce((sum, t) => sum + (t.position_size_usdt || 0), 0);
          const initialPnl = data.reduce((sum, t) => sum + (t.pnl_usdt || 0), 0);
          setLiveTelemetry(prev => ({ ...prev, exposure: initialExposure, pnl: initialPnl }));
        }
      } catch (err) {
        console.error("Failed to fetch baseline trades", err);
      } finally {
        if (isMounted) setLoading(false);
      }
    };

    fetchBaseline();
    
    // Safety fallback: Poll every 15s in case WS drops
    const interval = setInterval(fetchBaseline, 15000);
    return () => {
      isMounted = false;
      clearInterval(interval);
    };
  }, []);

  // 2. Real-Time WebSocket Telemetry
  useEffect(() => {
    function connectTelemetry() {
      const ws = new WebSocket(WS_URL);
      wsRef.current = ws;

      ws.onopen = () => setWsStatus('live');
      
      ws.onmessage = (e) => {
        try {
          const { type, data } = JSON.parse(e.data);
          
          if (type === 'price_update') {
            const updatesMap = {};
            data.trades.forEach(t => { updatesMap[t.trade_id] = t; });
            
            setLiveTelemetry({
              exposure: data.total_exposure,
              pnl: data.total_pnl,
              trades: updatesMap
            });
          } else if (type === 'trade_opened' || type === 'trade_closed') {
            // Instantly refresh base list if structure changes
            api.get(`/api/trades?status=OPEN`).then(res => {
              if (Array.isArray(res)) setActiveTrades(res);
            });
          }
        } catch (err) {
          console.error("Telemetry parse error", err);
        }
      };

      ws.onclose = () => {
        setWsStatus('offline');
        setTimeout(connectTelemetry, 3000); // Auto-reconnect
      };
    }

    connectTelemetry();
    return () => wsRef.current?.close();
  }, []);

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center h-64 space-y-4">
        <Zap className="text-purple-500 animate-pulse" size={48} />
        <div className="text-purple-500 font-mono tracking-widest animate-pulse">CONNECTING_EXCHANGE_FEED...</div>
      </div>
    );
  }

  return (
    <div className="space-y-6 max-w-7xl mx-auto">
      {/* Header & Global Risk Metrics */}
      <div className="flex flex-col md:flex-row items-start md:items-center justify-between border-b border-purple-900/30 pb-4 gap-4">
        <h2 className="text-2xl font-black text-transparent bg-clip-text bg-gradient-to-r from-purple-400 to-cyan-500 uppercase tracking-wide flex items-center gap-3">
          <Zap size={24} className="text-purple-400" />
          Live Execution Terminal
        </h2>
        
        <div className="flex flex-wrap items-center gap-3 font-mono">
          {/* WS Status Badge */}
          <div className="bg-[#0D0E12] border border-gray-800 px-3 py-1.5 rounded-lg flex items-center gap-2">
            <span className="text-[10px] text-gray-500 uppercase">Feed</span>
            <span className={`w-2 h-2 rounded-full ${wsStatus === 'live' ? 'bg-emerald-400 animate-pulse shadow-[0_0_8px_rgba(52,211,153,0.8)]' : 'bg-red-500'}`}></span>
          </div>

          <div className="bg-[#0D0E12] border border-gray-800 px-4 py-1.5 rounded-lg flex items-center gap-3">
            <span className="text-[10px] text-gray-500 uppercase">Exposure</span>
            <span className="text-white font-bold">${liveTelemetry.exposure.toLocaleString()}</span>
          </div>
          
          <div className={`border px-4 py-1.5 rounded-lg flex items-center gap-3 transition-colors duration-300 ${liveTelemetry.pnl >= 0 ? 'bg-emerald-900/10 border-emerald-900/50' : 'bg-red-900/10 border-red-900/50'}`}>
            <span className={`text-[10px] uppercase ${liveTelemetry.pnl >= 0 ? 'text-emerald-500/80' : 'text-red-500/80'}`}>Net P&L</span>
            <span className={`font-bold ${liveTelemetry.pnl >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
              {liveTelemetry.pnl >= 0 ? '+' : ''}{liveTelemetry.pnl.toFixed(2)} USDT
            </span>
          </div>
        </div>
      </div>

      {/* Empty State */}
      {activeTrades.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-32 border border-dashed border-purple-900/30 rounded-xl bg-gradient-to-b from-[#0D0E12] to-[#0A0B0E] shadow-[inset_0_0_50px_rgba(168,85,247,0.05)]">
          <Activity size={48} className="text-purple-900 mb-4" />
          <p className="text-purple-700/50 font-mono tracking-widest text-sm">NO_ACTIVE_POSITIONS</p>
        </div>
      ) : (
        /* Active Trades Grid */
        <div className="grid gap-4">
          {activeTrades.map(trade => {
            // Merge static DB data with live WS telemetry
            const liveData = liveTelemetry.trades[trade.id] || {};
            const currentPrice = liveData.current_price;
            const currentPnl = liveData.pnl_usdt !== undefined ? liveData.pnl_usdt : (trade.pnl_usdt || 0);
            const currentPnlPct = liveData.pnl_pct !== undefined ? liveData.pnl_pct : (trade.pnl_pct || 0);

            return (
              <div key={trade.id} className="relative bg-[#0D0E12] border border-purple-900/30 hover:border-purple-500/50 rounded-xl p-5 flex flex-col lg:flex-row items-center justify-between shadow-[0_8px_30px_rgba(0,0,0,0.4)] transition-all duration-300 overflow-hidden group">
                
                {/* Neon accent line */}
                <div className={`absolute top-0 left-0 w-1 h-full shadow-[0_0_15px_rgba(0,0,0,0.5)] ${trade.direction === 'LONG' || trade.direction === 'BUY' ? 'bg-emerald-500 shadow-emerald-500/50' : 'bg-red-500 shadow-red-500/50'}`}></div>

                {/* Asset Info */}
                <div className="flex items-center gap-4 w-full lg:w-1/3 mb-4 lg:mb-0 pl-2">
                  <div className="p-3 bg-purple-500/10 border border-purple-500/20 rounded-lg group-hover:bg-purple-500/20 transition-colors">
                    <Activity size={24} className="text-purple-400" />
                  </div>
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="text-2xl font-black text-white tracking-tight">{trade.coin}<span className="text-gray-600 text-base font-medium">/USDT</span></span>
                      <span className={`text-[10px] px-2 py-0.5 rounded font-bold border ${trade.direction === 'LONG' || trade.direction === 'BUY' ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30' : 'bg-red-500/10 text-red-400 border-red-500/30'}`}>
                        {trade.direction}
                      </span>
                      {trade.is_paper && (
                        <span className="text-[10px] px-2 py-0.5 rounded font-bold border bg-amber-500/10 text-amber-400 border-amber-500/30 shadow-[0_0_10px_rgba(245,158,11,0.2)]">
                          PAPER
                        </span>
                      )}
                    </div>
                    <div className="flex items-center gap-3 mt-1 font-mono text-[11px]">
                      <span className="text-cyan-600 flex items-center gap-1">
                        <Crosshair size={10}/> Entry: ${trade.entry_price?.toLocaleString() || '---'}
                      </span>
                      <span className="text-purple-400 flex items-center gap-1 transition-all duration-300">
                        <Zap size={10}/> Live: ${currentPrice ? currentPrice.toLocaleString() : 'FETCHING...'}
                      </span>
                    </div>
                  </div>
                </div>

                {/* Targets Grid */}
                <div className="flex gap-3 w-full lg:w-1/3 justify-center mb-4 lg:mb-0 font-mono">
                  <div className="bg-[#0A0B0E] px-4 py-2 rounded-lg border border-gray-800 text-center w-28">
                    <span className="block text-[9px] text-gray-500 mb-1 uppercase">Target</span>
                    <span className="text-sm text-emerald-400/80">${trade.tp1 ? trade.tp1.toLocaleString() : '—'}</span>
                  </div>
                  <div className="bg-[#0A0B0E] px-4 py-2 rounded-lg border border-gray-800 text-center w-28 relative overflow-hidden">
                    <div className="absolute top-0 right-0 p-1 opacity-10"><AlertTriangle size={24}/></div>
                    <span className="block text-[9px] text-gray-500 mb-1 uppercase">Stop Loss</span>
                    <span className="text-sm text-red-400/80">${trade.stop_loss ? trade.stop_loss.toLocaleString() : '—'}</span>
                  </div>
                </div>

                {/* Live P&L */}
                <div className="flex items-center gap-6 w-full lg:w-1/3 justify-end text-right">
                  <div className="font-mono">
                    <p className="text-[9px] text-gray-500 uppercase">Position</p>
                    <p className="text-base font-bold text-gray-300">${trade.position_size_usdt?.toLocaleString() || 0}</p>
                  </div>
                  <div className="font-mono min-w-[140px]">
                    <p className="text-[9px] text-gray-500 uppercase mb-1">Unrealized P&L</p>
                    <div className={`inline-flex items-center gap-2 px-3 py-1.5 rounded-lg border shadow-lg transition-colors duration-300 ${currentPnl >= 0 ? 'bg-emerald-500/10 border-emerald-500/40 text-emerald-400 shadow-emerald-900/20' : 'bg-red-500/10 border-red-500/40 text-red-400 shadow-red-900/20'}`}>
                      <span className={`w-1.5 h-1.5 rounded-full ${currentPnl >= 0 ? 'bg-emerald-400 animate-pulse' : 'bg-red-400 animate-pulse'}`}></span>
                      <span className="text-lg font-bold">
                        {currentPnl >= 0 ? '+' : ''}{currentPnl.toFixed(2)}
                      </span>
                      <span className="text-[10px] opacity-70 ml-1">
                        ({currentPnlPct > 0 ? '+' : ''}{currentPnlPct.toFixed(2)}%)
                      </span>
                    </div>
                  </div>
                </div>

              </div>
            );
          })}
        </div>
      )}
      
      {/* Risk Metrics Footer */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 pt-4">
        <div className="p-4 bg-gray-900/40 border border-gray-800 rounded-lg flex items-center justify-between">
          <div>
            <p className="text-[10px] text-gray-500 uppercase font-bold">Max Drawdown Limit</p>
            <p className="text-sm font-mono text-white">{status?.settings?.daily_drawdown_limit || 5}%</p>
          </div>
          <ShieldCheck className="text-emerald-500/50" size={24} />
        </div>
        <div className="p-4 bg-gray-900/40 border border-gray-800 rounded-lg flex items-center justify-between">
          <div>
            <p className="text-[10px] text-gray-500 uppercase font-bold">Trailing SL</p>
            <p className="text-sm font-mono text-white">{status?.settings?.trailing_sl ? 'ACTIVE' : 'DISABLED'}</p>
          </div>
          <Activity className={status?.settings?.trailing_sl ? 'text-cyan-500/50' : 'text-gray-600'} size={24} />
        </div>
      </div>
    </div>
  );
}