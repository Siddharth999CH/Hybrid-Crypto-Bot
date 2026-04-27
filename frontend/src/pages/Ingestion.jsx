import React, { useState, useEffect } from 'react';
import { api } from '../lib/api';
import { Database, Plus, Globe, MessageSquare, BarChart, Trash2, BrainCircuit, X, Link, Key } from 'lucide-react';

export default function Ingestion({ showToast }) {
  const [sources, setSources] = useState([]);
  const [loading, setLoading] = useState(true);
  
  // Modal & Form State
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [sourceType, setSourceType] = useState('telegram'); // 'telegram' or 'api'
  const [formData, setFormData] = useState({
    name: '',
    username: '',      // Used for Telegram Handle OR API URL
    trust_weight: 0.5,
    api_key: ''        // Used for secure APIs
  });

  useEffect(() => {
    fetchSources();
  }, []);

  const fetchSources = async () => {
    try {
      const data = await api.get('/api/channels');
      setSources(data);
    } catch (err) {
      console.error("Failed to fetch channels", err);
      showToast("Failed to fetch data sources", "danger");
    } finally {
      setLoading(false);
    }
  };

  const deleteSource = async (id, sourceType) => {
    try {
      const q = sourceType ? `?source_type=${sourceType}` : '';
      await api.delete(`/api/channels/${id}${q}`);
      showToast("🗑️ Data source removed", "info");
      setSources(prev => prev.filter(s => !(s.id === id && s.source_type === sourceType)));
    } catch (err) {
      showToast("❌ Failed to remove data source", "danger");
    }
  };

  const handleAddSource = async (e) => {
    e.preventDefault();
    try {
      // The backend will automatically route to ApiSource or TelegramSource 
      // based on whether the username string starts with "http"
      const payload = {
        name: formData.name,
        username: formData.username.toLowerCase(),
        trust_weight: parseFloat(formData.trust_weight),
        api_key: formData.api_key || undefined
      };

      await api.post('/api/channels', payload);
      showToast("✅ Data Source successfully linked to AI Memory", "success");
      
      // Reset and close
      setIsModalOpen(false);
      setFormData({ name: '', username: '', trust_weight: 0.5, api_key: '' });
      fetchSources();
    } catch (err) {
      showToast("❌ Failed to add source. Might already exist.", "danger");
    }
  };

  return (
    <div className="space-y-6 relative">
      <div className="flex justify-between items-center border-b border-blue-900/30 pb-4">
        <h2 className="text-2xl font-black text-transparent bg-clip-text bg-gradient-to-r from-blue-400 to-purple-500 uppercase tracking-wide flex items-center gap-3">
          <Database size={24} className="text-blue-400" /> 
          Data Aggregation Pipeline
        </h2>
        <button 
          onClick={() => setIsModalOpen(true)}
          className="flex items-center gap-2 bg-blue-600/20 border border-blue-500/50 hover:bg-blue-500/30 text-blue-400 font-bold px-4 py-2 rounded-lg text-sm transition-all shadow-[0_0_15px_rgba(59,130,246,0.3)] hover:shadow-[0_0_25px_rgba(59,130,246,0.5)]"
        >
          <Plus size={16} /> ADD DATA STREAM
        </button>
      </div>

      {/* AI Pipeline Banner */}
      <div className="bg-[#0D0E12] border border-purple-500/30 rounded-xl p-5 flex items-center justify-between shadow-[0_4px_20px_rgba(168,85,247,0.15)]">
         <div className="flex items-center gap-4">
           <div className="p-3 bg-purple-500/10 border border-purple-500/30 rounded-lg">
             <BrainCircuit className="text-purple-400" size={24} />
           </div>
           <div>
             <h3 className="text-lg font-bold text-white tracking-tight">AI Memory Context Engine</h3>
             <p className="text-xs text-gray-500 font-mono mt-1">Data streams below are actively ingested, normalized, and mapped to the master LLM context.</p>
           </div>
         </div>
         <div className="flex items-center gap-2 text-[10px] uppercase tracking-widest font-bold text-emerald-400 border border-emerald-500/30 bg-emerald-500/10 px-3 py-1.5 rounded-lg">
           <span className="w-1.5 h-1.5 bg-emerald-400 rounded-full animate-ping"></span>
           INGESTING LIVE
         </div>
      </div>

      {/* Active Sources Table */}
      <div className="bg-[#0D0E12] border border-gray-800 rounded-xl overflow-hidden shadow-[0_8px_30px_rgba(0,0,0,0.4)]">
        <div className="p-4 border-b border-gray-800 bg-[#0a0a0f]">
          <h3 className="text-sm font-bold text-gray-300 font-mono uppercase">Active Telemetry Streams</h3>
        </div>
        <div className="divide-y divide-gray-800/50">
          {loading ? (
            <div className="p-10 text-center text-blue-500 font-mono animate-pulse">SCANNING_DATABASE...</div>
          ) : sources.length === 0 ? (
            <div className="p-12 text-center flex flex-col items-center">
              <Database size={48} className="text-gray-700 mb-4" />
              <p className="text-gray-500 font-mono">NO_DATA_STREAMS_FOUND</p>
            </div>
          ) : (
            sources.map(source => {
              const isApi = source.username.startsWith('http');
              return (
                <div key={`${source.source_type || 'telegram'}-${source.id}`} className="flex items-center justify-between p-5 hover:bg-white/[0.02] transition-colors group">
                  <div className="flex items-center gap-4">
                    <div className="p-2 bg-gray-900 rounded-lg border border-gray-800 group-hover:border-blue-500/30 transition-colors">
                      {isApi ? <Globe className="text-blue-400" size={20}/> : <MessageSquare className="text-emerald-400" size={20}/>}
                    </div>
                    <div>
                      <p className="text-base font-bold text-white flex items-center gap-2">
                        {source.name}
                        <span className={`text-[9px] px-1.5 py-0.5 rounded border uppercase ${isApi ? 'bg-blue-500/10 text-blue-400 border-blue-500/30' : 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30'}`}>
                          {isApi ? 'REST API' : 'TELEGRAM'}
                        </span>
                      </p>
                      <p className="text-[11px] font-mono text-gray-500 mt-1">
                        Target: <span className="text-gray-400">{source.username || 'n/a'}</span> <span className="mx-2 text-gray-700">|</span> 
                        Context Weight: <span className={source.trust_weight > 0.6 ? 'text-emerald-400/80' : 'text-amber-400/80'}>{(source.trust_weight * 100).toFixed(0)}%</span>
                      </p>
                    </div>
                  </div>
                  <button onClick={() => deleteSource(source.id, source.source_type)} className="text-gray-600 hover:text-red-400 hover:bg-red-500/10 p-2 rounded-lg transition-all border border-transparent hover:border-red-500/30">
                    <Trash2 size={18} />
                  </button>
                </div>
              );
            })
          )}
        </div>
      </div>

      {/* --- ADD SOURCE MODAL OVERLAY --- */}
      {isModalOpen && (
        <div className="fixed inset-0 bg-black/80 backdrop-blur-sm flex items-center justify-center z-50 p-4">
          <div className="bg-[#0D0E12] border border-blue-500/30 rounded-2xl w-full max-w-md overflow-hidden shadow-[0_0_50px_rgba(59,130,246,0.15)] animate-in fade-in zoom-in-95 duration-200">
            
            {/* Modal Header */}
            <div className="p-5 border-b border-gray-800 flex justify-between items-center bg-[#0a0a0f]">
              <h3 className="text-lg font-bold text-white flex items-center gap-2">
                <Database size={18} className="text-blue-400"/> Map New Data Stream
              </h3>
              <button onClick={() => setIsModalOpen(false)} className="text-gray-500 hover:text-white transition-colors">
                <X size={20} />
              </button>
            </div>

            <form onSubmit={handleAddSource} className="p-5 space-y-5">
              
              {/* Type Selector */}
              <div className="flex gap-2 p-1 bg-gray-900 border border-gray-800 rounded-lg">
                <button type="button" onClick={() => { setSourceType('telegram'); setFormData({...formData, username: '', api_key: ''}); }} className={`flex-1 flex items-center justify-center gap-2 py-2 text-xs font-bold rounded uppercase transition-colors ${sourceType === 'telegram' ? 'bg-[#0D0E12] text-emerald-400 shadow border border-gray-700' : 'text-gray-500 hover:text-gray-300'}`}>
                  <MessageSquare size={14}/> Telegram
                </button>
                <button type="button" onClick={() => { setSourceType('api'); setFormData({...formData, username: 'https://'}); }} className={`flex-1 flex items-center justify-center gap-2 py-2 text-xs font-bold rounded uppercase transition-colors ${sourceType === 'api' ? 'bg-[#0D0E12] text-blue-400 shadow border border-gray-700' : 'text-gray-500 hover:text-gray-300'}`}>
                  <Globe size={14}/> Custom API
                </button>
              </div>

              {/* Form Fields */}
              <div className="space-y-4">
                <div>
                  <label className="block text-[10px] text-gray-500 uppercase tracking-wider mb-1.5">Internal Display Name</label>
                  <input required value={formData.name} onChange={e => setFormData({...formData, name: e.target.value})} placeholder={sourceType === 'api' ? "e.g., CoinGlass Orderbook" : "e.g., Binance Killers"} className="w-full bg-gray-900 border border-gray-800 rounded-lg px-4 py-2.5 text-sm text-white placeholder-gray-700 focus:outline-none focus:border-blue-500/50 transition-colors" />
                </div>

                <div>
                  <label className="block text-[10px] text-gray-500 uppercase tracking-wider mb-1.5">
                    {sourceType === 'api' ? 'Endpoint URL' : 'Telegram @Handle'}
                  </label>
                  <div className="relative">
                    <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
                      {sourceType === 'api' ? <Link size={14} className="text-gray-600"/> : <span className="text-gray-600 font-bold">@</span>}
                    </div>
                    <input required value={formData.username} onChange={e => setFormData({...formData, username: e.target.value})} placeholder={sourceType === 'api' ? "https://api.example.com/v1/data" : "username"} className="w-full bg-gray-900 border border-gray-800 rounded-lg pl-9 pr-4 py-2.5 text-sm text-white placeholder-gray-700 focus:outline-none focus:border-blue-500/50 transition-colors font-mono" />
                  </div>
                </div>

                {sourceType === 'api' && (
                  <div>
                    <label className="block text-[10px] text-gray-500 uppercase tracking-wider mb-1.5">API Key (Optional)</label>
                    <div className="relative">
                      <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
                        <Key size={14} className="text-gray-600"/>
                      </div>
                      <input type="password" value={formData.api_key} onChange={e => setFormData({...formData, api_key: e.target.value})} placeholder="Leave blank if public API" className="w-full bg-gray-900 border border-gray-800 rounded-lg pl-9 pr-4 py-2.5 text-sm text-white placeholder-gray-700 focus:outline-none focus:border-blue-500/50 transition-colors font-mono" />
                    </div>
                  </div>
                )}

                <div>
                  <label className="flex justify-between text-[10px] text-gray-500 uppercase tracking-wider mb-1.5">
                    <span>AI Context Weight</span>
                    <span className="text-blue-400 font-bold">{(formData.trust_weight * 100).toFixed(0)}%</span>
                  </label>
                  <input type="range" min="0.1" max="1.0" step="0.1" value={formData.trust_weight} onChange={e => setFormData({...formData, trust_weight: parseFloat(e.target.value)})} className="w-full accent-blue-500 bg-gray-800 h-1.5 rounded-lg appearance-none cursor-pointer" />
                  <p className="text-[10px] text-gray-600 mt-2 leading-relaxed">Determines how much influence this specific data stream has over the LLM's final execution decision.</p>
                </div>
              </div>

              {/* Action Buttons */}
              <div className="flex gap-3 pt-2 border-t border-gray-800">
                <button type="button" onClick={() => setIsModalOpen(false)} className="flex-1 px-4 py-2.5 rounded-lg text-sm font-bold text-gray-500 hover:text-white hover:bg-gray-800 transition-colors">
                  Cancel
                </button>
                <button type="submit" className="flex-1 px-4 py-2.5 bg-blue-600/20 hover:bg-blue-500/30 border border-blue-500/50 text-blue-400 rounded-lg text-sm font-bold transition-all shadow-[0_0_15px_rgba(59,130,246,0.2)]">
                  Map to Memory
                </button>
              </div>

            </form>
          </div>
        </div>
      )}
    </div>
  );
}