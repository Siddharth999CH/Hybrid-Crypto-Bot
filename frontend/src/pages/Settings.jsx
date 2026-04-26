import { useState, useEffect } from 'react';
import { api } from '../lib/api';
import { Settings as SettingsIcon, Shield, Bot, MessageCircle, Zap, Users } from 'lucide-react';

// ── Shared components ──────────────────────────────────────────────────────

function Toggle({ value, onChange }) {
  return (
    <button
      onClick={() => onChange(!value)}
      className={`relative w-10 h-5 rounded-full transition-colors flex-shrink-0
        ${value ? 'bg-emerald-500' : 'bg-gray-700'}`}
    >
      <span className={`absolute top-0.5 w-4 h-4 bg-white rounded-full shadow transition-all
        ${value ? 'left-5' : 'left-0.5'}`} />
    </button>
  );
}

function Row({ label, desc, children }) {
  return (
    <div className="flex items-center gap-4 py-3.5 border-b border-gray-800/50 last:border-0">
      <div className="flex-1">
        <div className="text-sm text-gray-200">{label}</div>
        {desc && <div className="text-[11px] text-gray-600 mt-0.5">{desc}</div>}
      </div>
      <div className="flex-shrink-0">{children}</div>
    </div>
  );
}

function NumInput({ value, onChange, min, max, step = 1, suffix = '' }) {
  return (
    <div className="flex items-center gap-1.5">
      <input
        type="number" min={min} max={max} step={step}
        value={value}
        onChange={e => onChange(parseFloat(e.target.value) || 0)}
        className="w-20 bg-gray-900 border border-gray-700 rounded px-2 py-1 text-sm text-gray-200 text-right focus:outline-none focus:border-emerald-500/50"
      />
      {suffix && <span className="text-xs text-gray-600">{suffix}</span>}
    </div>
  );
}

// ── Tabs ───────────────────────────────────────────────────────────────────

function RiskTab({ s, save }) {
  const [local, setLocal] = useState(s);
  useEffect(() => setLocal(s), [s]);
  const upd = k => v => setLocal(p => ({ ...p, [k]: v }));

  return (
    <div className="space-y-1">
      <Row label="Max risk per trade" desc="Hard cap regardless of AI sizing">
        <NumInput value={local.max_risk_pct} onChange={upd('max_risk_pct')} min={0.1} max={10} step={0.1} suffix="%" />
      </Row>
      <Row label="Daily drawdown limit" desc="Kill switch triggers when daily loss hits this">
        <NumInput value={local.daily_drawdown_limit} onChange={upd('daily_drawdown_limit')} min={1} max={50} step={0.5} suffix="%" />
      </Row>
      <Row label="Max concurrent trades" desc="Open positions at one time">
        <NumInput value={local.max_concurrent_trades} onChange={upd('max_concurrent_trades')} min={1} max={20} />
      </Row>
      <Row label="Approval timeout" desc="Auto-reject if no response within this time">
        <NumInput value={local.approval_timeout} onChange={upd('approval_timeout')} min={60} max={3600} step={60} suffix="sec" />
      </Row>
      <Row label="Max leverage" desc="Futures leverage hard cap">
        <NumInput value={local.max_leverage} onChange={upd('max_leverage')} min={1} max={125} suffix="x" />
      </Row>
      <Row label="Slippage threshold" desc="Skip trade if price moved more than this from signal entry">
        <NumInput value={local.slippage_threshold} onChange={upd('slippage_threshold')} min={0.1} max={10} step={0.1} suffix="%" />
      </Row>
      <div className="pt-4">
        <button onClick={() => save(local)} className="text-xs px-4 py-2 bg-emerald-500/10 border border-emerald-500/30 rounded text-emerald-400 hover:bg-emerald-500/20 transition">
          Save Risk Settings
        </button>
      </div>
    </div>
  );
}

// ─── THE NEW AI-AGNOSTIC BOT TAB ───────────────────────────────────────────
function BotTab({ s, save }) {
  const [local, setLocal] = useState(s);
  useEffect(() => setLocal(s), [s]);
  
  const upd = k => v => { setLocal(p => ({ ...p, [k]: v })); save({ [k]: v }); };
  const updText = k => e => setLocal(p => ({ ...p, [k]: e.target.value }));

  return (
    <div className="space-y-4">
      {/* Dynamic LLM Configuration */}
      <div className="space-y-3 bg-gray-900/40 border border-gray-800 rounded-xl p-4">
        <div className="text-xs text-gray-400 uppercase tracking-wider font-bold mb-2">AI Engine Configuration</div>
        
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-[10px] text-gray-500 uppercase tracking-wider mb-1">Provider</label>
            <select value={local.llm_provider || 'anthropic'} onChange={updText('llm_provider')} className="w-full bg-gray-900 border border-gray-800 rounded-lg px-3 py-2 text-sm text-gray-200 focus:border-emerald-500/40 outline-none">
              <option value="anthropic">Anthropic (Claude)</option>
              <option value="openai">OpenAI (GPT)</option>
              <option value="gemini">Google Gemini</option>
              <option value="groq">Groq (Ultra-Fast)</option>
              <option value="ollama">Ollama (Local Setup)</option>
            </select>
          </div>
          <div>
            <label className="block text-[10px] text-gray-500 uppercase tracking-wider mb-1">Model Name</label>
            <input value={local.llm_model_name || ''} onChange={updText('llm_model_name')} placeholder="e.g. gpt-4o-mini" className="w-full bg-gray-900 border border-gray-800 rounded-lg px-3 py-2 text-sm text-gray-200 placeholder-gray-700 focus:border-emerald-500/40 outline-none" />
          </div>
        </div>

        <div>
          <label className="block text-[10px] text-gray-500 uppercase tracking-wider mb-1">API Key</label>
          <input type="password" value={local.llm_api_key || ''} onChange={updText('llm_api_key')} placeholder="sk-..." className="w-full bg-gray-900 border border-gray-800 rounded-lg px-3 py-2 text-sm text-gray-200 placeholder-gray-700 focus:border-emerald-500/40 outline-none" />
        </div>

        <div className="pt-2">
          <button 
            onClick={() => save({ 
              llm_provider: local.llm_provider, 
              llm_model_name: local.llm_model_name, 
              llm_api_key: local.llm_api_key 
            })} 
            className="text-xs px-4 py-2 bg-purple-500/10 border border-purple-500/30 rounded text-purple-400 hover:bg-purple-500/20 transition w-full"
          >
            Save AI Settings
          </button>
        </div>
      </div>

      {/* Standard Bot Behavior */}
      <div className="space-y-1 pt-2">
        <Row label="Paper trading mode" desc="Simulate trades — no real orders placed">
          <Toggle value={local.paper_mode} onChange={upd('paper_mode')} />
        </Row>
        <Row label="AI mock mode" desc="Use simulated scores without calling API (no cost)">
          <Toggle value={local.ai_mock_mode} onChange={upd('ai_mock_mode')} />
        </Row>
        <Row label="Signal notifications" desc="Log every signal seen, even rejected ones">
          <Toggle value={local.signal_notifications} onChange={upd('signal_notifications')} />
        </Row>
        <Row label="Trailing stop loss" desc="Move SL to breakeven after TP1 is hit">
          <Toggle value={local.trailing_sl} onChange={upd('trailing_sl')} />
        </Row>
      </div>
    </div>
  );
}

function TelegramTab({ showToast }) {
  const [step, setStep] = useState(1);
  const [form, setForm] = useState({ api_id: '', api_hash: '', phone: '', code: '', password: '' });
  const [loading, setLoading] = useState(false);
  const [sessionString, setSessionString] = useState('');
  const [connected, setConnected] = useState(false);
  const [botToken, setBotToken] = useState('');
  const [chatId, setChatId] = useState('');

  const upd = k => e => setForm(f => ({ ...f, [k]: e.target.value }));

  useEffect(() => {
    api.get('/api/settings').then(s => setConnected(s.telegram_connected)).catch(() => {});
  }, []);

  const sendOtp = async () => {
    if (!form.api_id || !form.api_hash || !form.phone) return showToast('Fill all fields.', 'danger');
    setLoading(true);
    try {
      await api.post('/api/telegram/connect', { api_id: form.api_id, api_hash: form.api_hash, phone: form.phone });
      showToast('📱 OTP sent to your phone.', 'success');
      setStep(2);
    } catch (e) { showToast('Failed to send OTP. Check credentials.', 'danger'); }
    finally { setLoading(false); }
  };

  const verify = async () => {
    setLoading(true);
    try {
      const res = await api.post('/api/telegram/verify', { phone: form.phone, code: form.code, password: form.password || undefined });
      setSessionString(res.session_string);
      setStep(3);
      showToast('✅ Telegram connected!', 'success');
    } catch { showToast('Verification failed. Check your code.', 'danger'); }
    finally { setLoading(false); }
  };

  const copySession = () => {
    navigator.clipboard.writeText(`TELEGRAM_SESSION_STRING=${sessionString}`);
    showToast('Copied to clipboard!', 'success');
  };

  const stepDot = (n) => (
    <div className={`w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold flex-shrink-0 border
      ${step > n ? 'bg-emerald-500/20 border-emerald-500/50 text-emerald-400'
      : step === n ? 'bg-gray-800 border-gray-500 text-white'
      : 'bg-gray-900 border-gray-800 text-gray-700'}`}>
      {step > n ? '✓' : n}
    </div>
  );

  return (
    <div className="space-y-5">
      <div className="bg-gray-900/50 border border-gray-800 rounded-xl p-4 flex items-center gap-3">
        <div className={`w-2 h-2 rounded-full ${connected ? 'bg-emerald-400 animate-pulse' : 'bg-gray-600'}`} />
        <div className="flex-1">
          <div className="text-sm text-gray-200">{connected ? 'Scraper account connected' : 'No account connected'}</div>
          <div className="text-[11px] text-gray-600 mt-0.5">
            {connected ? 'Session string found in .env. Listening to configured channels.' : 'Connect a Telegram account to start scraping signals.'}
          </div>
        </div>
        {connected && <span className="text-[10px] px-2 py-0.5 rounded border border-emerald-500/30 bg-emerald-500/10 text-emerald-400">Active</span>}
      </div>

      <div className="bg-amber-950/20 border border-amber-700/30 rounded-lg px-4 py-3 text-[11px] text-amber-500/80 leading-relaxed">
        ⚠️ Use a secondary Telegram account, not your primary one. Automated scraping can trigger spam detection on main accounts.
      </div>

      {/* Step 1 */}
      <div className={`space-y-3 ${step !== 1 ? 'opacity-50 pointer-events-none' : ''}`}>
        <div className="flex items-center gap-3">
          {stepDot(1)}
          <div>
            <div className="text-sm font-medium text-gray-200">API Credentials</div>
            <div className="text-[11px] text-gray-600">Get from <span className="text-emerald-400">my.telegram.org</span> → API development tools</div>
          </div>
        </div>
        <div className="ml-9 grid grid-cols-2 gap-3">
          <div>
            <label className="text-[10px] text-gray-600 uppercase tracking-wider block mb-1">API ID</label>
            <input value={form.api_id} onChange={upd('api_id')} placeholder="12345678"
              className="w-full bg-gray-900 border border-gray-800 rounded-lg px-3 py-2 text-sm text-gray-200 placeholder-gray-700 focus:outline-none focus:border-emerald-500/40" />
          </div>
          <div>
            <label className="text-[10px] text-gray-600 uppercase tracking-wider block mb-1">API Hash</label>
            <input value={form.api_hash} onChange={upd('api_hash')} placeholder="32 char hash"
              className="w-full bg-gray-900 border border-gray-800 rounded-lg px-3 py-2 text-sm text-gray-200 placeholder-gray-700 focus:outline-none focus:border-emerald-500/40" />
          </div>
          <div>
            <label className="text-[10px] text-gray-600 uppercase tracking-wider block mb-1">Phone Number</label>
            <input value={form.phone} onChange={upd('phone')} placeholder="+91 98765 43210"
              className="w-full bg-gray-900 border border-gray-800 rounded-lg px-3 py-2 text-sm text-gray-200 placeholder-gray-700 focus:outline-none focus:border-emerald-500/40" />
          </div>
        </div>
        <div className="ml-9">
          <button onClick={sendOtp} disabled={loading}
            className="text-xs px-4 py-2 bg-emerald-500/10 border border-emerald-500/30 rounded text-emerald-400 hover:bg-emerald-500/20 transition disabled:opacity-40">
            {loading ? 'Sending…' : 'Send OTP →'}
          </button>
        </div>
      </div>

      {/* Step 2 */}
      <div className={`space-y-3 ${step !== 2 ? 'opacity-50 pointer-events-none' : ''}`}>
        <div className="flex items-center gap-3">
          {stepDot(2)}
          <div>
            <div className="text-sm font-medium text-gray-200">Verify OTP</div>
            <div className="text-[11px] text-gray-600">Enter the code Telegram sent to your phone</div>
          </div>
        </div>
        <div className="ml-9 space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-[10px] text-gray-600 uppercase tracking-wider block mb-1">OTP Code</label>
              <input value={form.code} onChange={upd('code')} placeholder="12345" maxLength={5}
                className="w-full bg-gray-900 border border-gray-800 rounded-lg px-3 py-2 text-sm text-gray-200 placeholder-gray-700 focus:outline-none focus:border-emerald-500/40 tracking-widest" />
            </div>
            <div>
              <label className="text-[10px] text-gray-600 uppercase tracking-wider block mb-1">2FA Password (if set)</label>
              <input type="password" value={form.password} onChange={upd('password')} placeholder="Optional"
                className="w-full bg-gray-900 border border-gray-800 rounded-lg px-3 py-2 text-sm text-gray-200 placeholder-gray-700 focus:outline-none focus:border-emerald-500/40" />
            </div>
          </div>
          <button onClick={verify} disabled={loading || form.code.length < 5}
            className="text-xs px-4 py-2 bg-emerald-500/10 border border-emerald-500/30 rounded text-emerald-400 hover:bg-emerald-500/20 transition disabled:opacity-40">
            {loading ? 'Verifying…' : 'Verify & Connect →'}
          </button>
        </div>
      </div>

      {/* Step 3 — Session string */}
      {step === 3 && (
        <div className="space-y-3">
          <div className="flex items-center gap-3">
            {stepDot(3)}
            <div>
              <div className="text-sm font-medium text-emerald-400">Connected! Save your session string</div>
              <div className="text-[11px] text-gray-600">Add this to your .env file to persist the connection</div>
            </div>
          </div>
          <div className="ml-9 space-y-2">
            <div className="bg-gray-900 border border-gray-800 rounded-lg p-3 font-mono text-[10px] text-gray-400 break-all max-h-24 overflow-y-auto">
              TELEGRAM_SESSION_STRING={sessionString}
            </div>
            <button onClick={copySession}
              className="text-xs px-4 py-2 bg-emerald-500/10 border border-emerald-500/30 rounded text-emerald-400 hover:bg-emerald-500/20 transition">
              Copy to clipboard
            </button>
          </div>
        </div>
      )}

      {/* Notification bot */}
      <div className="border-t border-gray-800 pt-5 space-y-3">
        <div className="flex items-center gap-3">
          <div className="w-6 h-6 rounded-full bg-gray-800 border border-gray-700 flex items-center justify-center flex-shrink-0">
            <Bot size={12} className="text-gray-400" />
          </div>
          <div>
            <div className="text-sm font-medium text-gray-200">Notification Bot (optional)</div>
            <div className="text-[11px] text-gray-600">Send trade alerts via a separate Telegram bot. Create via @BotFather.</div>
          </div>
        </div>
        <div className="ml-9 grid grid-cols-2 gap-3">
          <div>
            <label className="text-[10px] text-gray-600 uppercase tracking-wider block mb-1">Bot Token</label>
            <input value={botToken} onChange={e => setBotToken(e.target.value)} placeholder="123456:ABC..."
              className="w-full bg-gray-900 border border-gray-800 rounded-lg px-3 py-2 text-sm text-gray-200 placeholder-gray-700 focus:outline-none focus:border-emerald-500/40" />
          </div>
          <div>
            <label className="text-[10px] text-gray-600 uppercase tracking-wider block mb-1">Your Chat ID</label>
            <input value={chatId} onChange={e => setChatId(e.target.value)} placeholder="738291045"
              className="w-full bg-gray-900 border border-gray-800 rounded-lg px-3 py-2 text-sm text-gray-200 placeholder-gray-700 focus:outline-none focus:border-emerald-500/40" />
          </div>
        </div>
        <div className="ml-9 text-[11px] text-gray-700">Add TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID to your .env file.</div>
      </div>
    </div>
  );
}

function ExchangeTab({ showToast }) {
  const [settings, setSettings] = useState({ binance_connected: false });

  useEffect(() => {
    api.get('/api/settings').then(setSettings).catch(() => {});
  }, []);

  return (
    <div className="space-y-4">
      <div className="bg-gray-900/50 border border-gray-800 rounded-xl p-4 flex items-center gap-3">
        <div className={`w-2 h-2 rounded-full ${settings.binance_connected ? 'bg-emerald-400 animate-pulse' : 'bg-gray-600'}`} />
        <div className="flex-1">
          <div className="text-sm text-gray-200">Binance {settings.BINANCE_TESTNET ? 'Testnet' : 'Live'}</div>
          <div className="text-[11px] text-gray-600 mt-0.5">{settings.binance_connected ? 'API keys loaded from .env' : 'No API keys configured'}</div>
        </div>
        <span className={`text-[10px] px-2 py-0.5 rounded border ${settings.binance_connected ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-400' : 'border-gray-700 text-gray-600'}`}>
          {settings.binance_connected ? 'Connected' : 'Not configured'}
        </span>
      </div>

      <div className="bg-[#0D0E12] border border-gray-800 rounded-xl p-5 space-y-4">
        <div className="text-xs text-gray-400 uppercase tracking-wider">How to set up Binance Testnet</div>
        {[
          ['1', 'Go to testnet.binancefuture.com'],
          ['2', 'Log in and generate API keys'],
          ['3', 'Add BINANCE_API_KEY and BINANCE_SECRET to your .env file'],
          ['4', 'Set BINANCE_TESTNET=true in your .env (already default)'],
          ['5', 'Restart the backend — balance will load automatically'],
        ].map(([n, txt]) => (
          <div key={n} className="flex items-start gap-3 text-xs text-gray-500">
            <span className="w-5 h-5 rounded-full bg-gray-800 border border-gray-700 text-gray-600 text-[10px] flex items-center justify-center flex-shrink-0">{n}</span>
            {txt}
          </div>
        ))}
      </div>

      <div className="bg-[#0D0E12] border border-gray-800 rounded-xl p-4 space-y-2">
        <div className="text-xs text-gray-400 uppercase tracking-wider mb-3">env file reference</div>
        <pre className="text-[11px] text-gray-500 leading-relaxed font-mono bg-gray-900/50 rounded p-3 overflow-x-auto">{`BINANCE_API_KEY=your_key_here
BINANCE_SECRET=your_secret_here
BINANCE_TESTNET=true`}</pre>
      </div>
    </div>
  );
}

function TeamTab() {
  return (
    <div className="bg-[#0D0E12] border border-gray-800 rounded-xl p-8 text-center space-y-3">
      <Users size={24} className="text-gray-700 mx-auto" />
      <div className="text-sm text-gray-500">Team management</div>
      <div className="text-xs text-gray-700 max-w-xs mx-auto leading-relaxed">
        Multi-user accounts, role-based access, and invite links are planned for a future release.
        Currently all team members share the same .env credentials.
      </div>
    </div>
  );
}

// ── Main Settings ──────────────────────────────────────────────────────────

const TABS = [
  { id: 'risk',     label: 'Risk',     icon: Shield },
  { id: 'bot',      label: 'Bot',      icon: Bot },
  { id: 'telegram', label: 'Telegram', icon: MessageCircle },
  { id: 'exchange', label: 'Exchange', icon: Zap },
  { id: 'team',     label: 'Team',     icon: Users },
];

export default function Settings({ showToast }) {
  const [tab, setTab] = useState('risk');
  const [settings, setSettings] = useState({});

  useEffect(() => {
    api.get('/api/settings').then(setSettings).catch(() => {});
  }, []);

  const save = async (patch) => {
    try {
      await api.post('/api/settings', patch);
      setSettings(s => ({ ...s, ...patch }));
      showToast('Settings saved.', 'success');
    } catch { showToast('Failed to save.', 'danger'); }
  };

  return (
    <div className="space-y-4">
      <h1 className="text-sm font-bold text-gray-200 uppercase tracking-wider flex items-center gap-2">
        <SettingsIcon size={14} className="text-emerald-400" /> Settings
      </h1>

      <div className="flex gap-1 border-b border-gray-800 pb-0">
        {TABS.map(({ id, label, icon: Icon }) => (
          <button key={id} onClick={() => setTab(id)}
            className={`flex items-center gap-1.5 px-3 py-2.5 text-xs border-b-2 transition -mb-px
              ${tab === id ? 'border-emerald-500 text-emerald-400' : 'border-transparent text-gray-500 hover:text-gray-300'}`}>
            <Icon size={11} /> {label}
          </button>
        ))}
      </div>

      <div className="bg-[#0D0E12] border border-gray-800 rounded-xl p-5">
        {tab === 'risk'     && <RiskTab s={settings} save={save} />}
        {tab === 'bot'      && <BotTab s={settings} save={save} />}
        {tab === 'telegram' && <TelegramTab showToast={showToast} />}
        {tab === 'exchange' && <ExchangeTab showToast={showToast} />}
        {tab === 'team'     && <TeamTab />}
      </div>
    </div>
  );
}