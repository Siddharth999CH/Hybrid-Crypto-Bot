import { useState, useEffect } from 'react';
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from 'recharts';
import { api } from '../lib/api';
import { TrendingUp, TrendingDown, Activity, Zap, AlertTriangle, Play, Pause, X } from 'lucide-react';

const fmt = (n, prefix='$') => n == null ? '—' : `${prefix}${Math.abs(n).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2})}`;
const sign = (n) => n >= 0 ? `+${fmt(n)}` : `-${fmt(n)}`;

export default function Dashboard({ status, showToast, fetchStatus }) {
  const [stats, setStats] = useState(null);
  const [openTrades, setOpenTrades] = useState([]);
  const [recentSignals, setRecentSignals] = useState([]);

  useEffect(() => {
    api.get('/api/trades/stats').then(setStats).catch(()=>{});
    api.get('/api/trades?limit=5').then(d => setOpenTrades(d.filter(t=>t.status==='OPEN'))).catch(()=>{});
    api.get('/api/signals?limit=5').then(setRecentSignals).catch(()=>{});
  }, [status]);

  const toggle = async () => {
    try {
      await api.post('/api/toggle');
      fetchStatus();
    } catch(e) { showToast('Failed to toggle bot', 'danger'); }
  };

  const resume = async () => {
    try {
      await api.post('/api/resume');
      fetchStatus();
      showToast('Bot resumed.', 'success');
    } catch {}
  };

  const chartData = stats?.daily_pnl
    ? Object.entries(stats.daily_pnl).map(([day, pnl]) => ({ day, pnl: parseFloat(pnl.toFixed(2)) }))
    : [];

  return (
    <div className="space-y-6">
      {/* Kill switch banner */}
      {status?.kill_switch_active && (
        <div className="bg-red-950/50 border border-red-700/50 rounded-lg p-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <AlertTriangle size={16} className="text-red-400" />
            <div>
              <div className="text-sm font-medium text-red-300">Kill Switch Active</div>
              <div className="text-xs text-red-500 mt-0.5">{status.kill_switch_reason}</div>
            </div>
          </div>
          <button onClick={resume} className="text-xs px-3 py-1.5 bg-red-500/20 border border-red-500/40 rounded text-red-300 hover:bg-red-500/30 transition">
            Resume
          </button>
        </div>
      )}

      {/* Metrics */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {[
          {
            label: "Today's P&L",
            value: status?.daily_pnl != null ? sign(status.daily_pnl) : '—',
            sub: `${status?.open_trades_count || 0} open positions`,
            color: status?.daily_pnl >= 0 ? 'text-emerald-400' : 'text-red-400',
            Icon: status?.daily_pnl >= 0 ? TrendingUp : TrendingDown,
          },
          {
            label: 'Win Rate',
            value: stats?.win_rate != null ? `${stats.win_rate}%` : '—',
            sub: stats ? `${stats.wins} / ${stats.total_trades} trades` : 'No trades yet',
            color: 'text-blue-400',
            Icon: Activity,
          },
          {
            label: 'Portfolio',
            value: fmt(status?.portfolio_balance),
            sub: status?.paper_mode ? 'Paper trading' : 'Live trading',
            color: 'text-purple-400',
            Icon: Zap,
          },
          {
            label: 'Total P&L',
            value: stats?.total_pnl != null ? sign(stats.total_pnl) : '—',
            sub: stats?.best_channel ? `Best: ${stats.best_channel}` : 'All time',
            color: stats?.total_pnl >= 0 ? 'text-emerald-400' : 'text-red-400',
            Icon: TrendingUp,
          },
        ].map(({ label, value, sub, color, Icon }) => (
          <div key={label} className="bg-[#0D0E12] border border-gray-800 rounded-xl p-4">
            <div className="flex items-center justify-between mb-3">
              <span className="text-[11px] text-gray-500 uppercase tracking-wider">{label}</span>
              <Icon size={12} className={color} />
            </div>
            <div className={`text-xl font-bold ${color}`}>{value}</div>
            <div className="text-[11px] text-gray-600 mt-1">{sub}</div>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Weekly chart */}
        <div className="bg-[#0D0E12] border border-gray-800 rounded-xl p-4">
          <div className="text-xs text-gray-400 mb-4 uppercase tracking-wider">Weekly P&L</div>
          {chartData.length > 0 ? (
            <ResponsiveContainer width="100%" height={140}>
              <BarChart data={chartData} margin={{top:0,right:0,left:0,bottom:0}}>
                <XAxis dataKey="day" tick={{fontSize:10,fill:'#6b7280'}} axisLine={false} tickLine={false} />
                <YAxis tick={{fontSize:10,fill:'#6b7280'}} axisLine={false} tickLine={false} width={40} />
                <Tooltip
                  contentStyle={{background:'#1a1b20',border:'1px solid #374151',borderRadius:'6px',fontSize:'12px'}}
                  formatter={(v) => [sign(v), 'P&L']}
                />
                <Bar dataKey="pnl" radius={[3,3,0,0]}>
                  {chartData.map((e, i) => (
                    <Cell key={i} fill={e.pnl >= 0 ? '#10b981' : '#ef4444'} fillOpacity={0.8} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <div className="h-36 flex items-center justify-center text-xs text-gray-600">No closed trades yet</div>
          )}
        </div>

        {/* Recent signals */}
        <div className="bg-[#0D0E12] border border-gray-800 rounded-xl p-4">
          <div className="text-xs text-gray-400 mb-4 uppercase tracking-wider">Recent Signals</div>
          {recentSignals.length === 0
            ? <div className="text-xs text-gray-600 py-8 text-center">No signals yet — start the bot below</div>
            : recentSignals.map(s => (
              <div key={s.id} className="flex items-center gap-3 py-2.5 border-b border-gray-800/50 last:border-0">
                <span className={`text-[10px] font-bold px-2 py-0.5 rounded border
                  ${s.direction === 'LONG'
                    ? 'text-emerald-400 border-emerald-500/30 bg-emerald-500/10'
                    : 'text-red-400 border-red-500/30 bg-red-500/10'
                  }`}>
                  {s.direction}
                </span>
                <div className="flex-1">
                  <span className="text-xs font-medium text-gray-200">{s.coin}</span>
                  <span className="text-[10px] text-purple-400/80 ml-2">{s.is_aggregated ? 'AI Aggregated' : 'AI Model'}</span>
                </div>
                {s.confidence != null && (
                  <div className="text-right">
                    <div className={`text-xs font-medium ${s.confidence >= 0.75 ? 'text-emerald-400' : s.confidence >= 0.5 ? 'text-amber-400' : 'text-red-400'}`}>
                      {(s.confidence * 100).toFixed(0)}%
                    </div>
                    <div className="w-12 h-1 bg-gray-800 rounded mt-1">
                      <div className="h-1 rounded" style={{
                        width: `${s.confidence * 100}%`,
                        background: s.confidence >= 0.75 ? '#10b981' : s.confidence >= 0.5 ? '#f59e0b' : '#ef4444'
                      }} />
                    </div>
                  </div>
                )}
              </div>
            ))
          }
        </div>
      </div>

      {/* Open positions */}
      {openTrades.length > 0 && (
        <div className="bg-[#0D0E12] border border-gray-800 rounded-xl p-4">
          <div className="text-xs text-gray-400 mb-4 uppercase tracking-wider">Open Positions</div>
          <div className="space-y-2">
            {openTrades.map(t => (
              <div key={t.id} className="flex items-center gap-4 py-2 border-b border-gray-800/40 last:border-0 text-xs">
                <span className={`px-2 py-0.5 rounded border text-[10px] font-bold
                  ${t.direction === 'LONG' ? 'text-emerald-400 border-emerald-500/30' : 'text-red-400 border-red-500/30'}`}>
                  {t.direction}
                </span>
                <span className="font-medium text-gray-200 w-20">{t.coin}</span>
                <span className="text-gray-500 flex-1">Entry ${t.entry_price?.toLocaleString()}</span>
                {t.is_paper && <span className="text-amber-400/60 text-[10px]">PAPER</span>}
                <span className="text-blue-400 px-2 py-0.5 bg-blue-500/10 rounded border border-blue-500/20 text-[10px]">
                  OPEN
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Bot control */}
      <div className="bg-[#0D0E12] border border-gray-800 rounded-xl p-4 flex items-center justify-between">
        <div>
          <div className="text-sm font-medium text-gray-200">
            {status?.is_active ? '🟢 Bot is running' : '🔴 Bot is paused'}
          </div>
          <div className="text-xs text-gray-600 mt-0.5">
            {status?.paper_mode ? 'Paper mode — no real orders' : 'Live mode — real orders on Binance'}
          </div>
        </div>
        <button
          onClick={toggle}
          disabled={status?.kill_switch_active}
          className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-all
            ${status?.is_active
              ? 'bg-red-500/10 border border-red-500/30 text-red-400 hover:bg-red-500/20'
              : 'bg-emerald-500/10 border border-emerald-500/30 text-emerald-400 hover:bg-emerald-500/20'
            } disabled:opacity-40 disabled:cursor-not-allowed`}
        >
          {status?.is_active ? <><Pause size={14} /> Pause</> : <><Play size={14} /> Start</>}
        </button>
      </div>
    </div>
  );
}
