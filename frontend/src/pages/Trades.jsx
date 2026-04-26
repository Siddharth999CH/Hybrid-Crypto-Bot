import { useState, useEffect } from 'react';
import { api } from '../lib/api';
import { BarChart2, Download } from 'lucide-react';

export default function Trades({ showToast }) {
  const [trades, setTrades] = useState([]);
  const [stats, setStats] = useState(null);
  const [paperFilter, setPaperFilter] = useState(null);

  useEffect(() => {
    const q = paperFilter !== null ? `&is_paper=${paperFilter}` : '';
    api.get(`/api/trades?limit=100${q}`)
      .then(data => setTrades(Array.isArray(data) ? data : []))
      .catch(()=>{ setTrades([]); });
    api.get('/api/trades/stats').then(setStats).catch(()=>{});
  }, [paperFilter]);

  const exportCsv = () => {
    window.open(`${import.meta.env.VITE_API_URL || 'http://localhost:8001'}/api/trades/export`);
  };

  const statusStyle = {
    OPEN: 'text-blue-400 border-blue-500/30 bg-blue-500/10',
    TP_HIT: 'text-emerald-400 border-emerald-500/30 bg-emerald-500/10',
    SL_HIT: 'text-red-400 border-red-500/30 bg-red-500/10',
    REJECTED: 'text-gray-500 border-gray-700 bg-gray-800/30',
    EXPIRED: 'text-gray-500 border-gray-700 bg-gray-800/30',
    SKIPPED_SLIPPAGE: 'text-amber-400 border-amber-500/30 bg-amber-500/10',
  };

  return (
    <div className="space-y-4">
      {/* Stats */}
      {stats && (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          {[
            { label: 'Total P&L', value: `${stats.total_pnl >= 0 ? '+' : ''}$${stats.total_pnl?.toFixed(2)}`, color: stats.total_pnl >= 0 ? 'text-emerald-400' : 'text-red-400' },
            { label: 'Win Rate', value: `${stats.win_rate}%`, color: 'text-blue-400' },
            { label: 'Total Trades', value: stats.total_trades, color: 'text-gray-200' },
            { label: 'Best Channel', value: stats.best_channel || '—', color: 'text-purple-400' },
          ].map(({ label, value, color }) => (
            <div key={label} className="bg-[#0D0E12] border border-gray-800 rounded-xl p-4">
              <div className="text-[10px] text-gray-600 uppercase tracking-wider mb-2">{label}</div>
              <div className={`text-lg font-bold ${color}`}>{value}</div>
            </div>
          ))}
        </div>
      )}

      {/* Filter + export */}
      <div className="flex items-center justify-between">
        <div className="flex gap-2">
          {[['All', null], ['Paper', true], ['Live', false]].map(([label, val]) => (
            <button key={label} onClick={() => setPaperFilter(val)}
              className={`text-xs px-3 py-1 rounded border transition
                ${paperFilter === val ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-400' : 'border-gray-800 text-gray-500 hover:text-gray-300'}`}>
              {label}
            </button>
          ))}
        </div>
        <button onClick={exportCsv}
          className="flex items-center gap-1.5 text-xs px-3 py-1.5 border border-gray-700 rounded text-gray-400 hover:text-gray-200 transition">
          <Download size={11} /> Export CSV
        </button>
      </div>

      {/* Table */}
      <div className="bg-[#0D0E12] border border-gray-800 rounded-xl overflow-hidden">
        {trades.length === 0
          ? <div className="p-12 text-center text-xs text-gray-600">No trades yet</div>
          : trades.map(t => (
          <div key={t.id} className="flex items-center gap-3 px-4 py-3 border-b border-gray-800/50 last:border-0 hover:bg-white/[0.02] text-xs">
            <span className={`text-[10px] font-bold px-2 py-0.5 rounded border flex-shrink-0
              ${t.direction === 'LONG' ? 'text-emerald-400 border-emerald-500/30' : 'text-red-400 border-red-500/30'}`}>
              {t.direction}
            </span>
            <span className="font-medium text-gray-200 w-20 flex-shrink-0">{t.coin}</span>
            <span className="text-gray-600 flex-1">
              {t.entry_price ? `Entry $${t.entry_price.toLocaleString()}` : '—'}
              {t.tp1 ? ` · TP $${t.tp1.toLocaleString()}` : ''}
            </span>
            {t.is_paper && <span className="text-amber-400/50 text-[10px] flex-shrink-0">PAPER</span>}
            <span className={`font-medium flex-shrink-0 w-24 text-right
              ${t.pnl_usdt == null ? 'text-gray-600'
                : t.pnl_usdt >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
              {t.pnl_usdt != null ? `${t.pnl_usdt >= 0 ? '+' : ''}$${t.pnl_usdt.toFixed(2)}` : '—'}
            </span>
            <span className={`text-[10px] px-2 py-0.5 rounded border flex-shrink-0 ${statusStyle[t.status] || 'text-gray-500 border-gray-700'}`}>
              {t.status.replace('_', ' ')}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
