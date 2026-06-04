import { useState, useEffect } from 'react';
import { getAvailableModels } from '../services/api';

export default function SettingsPanel({ settings, onSettingsChange }) {
  const [models, setModels] = useState([]);
  const [isExpanded, setIsExpanded] = useState(false);

  useEffect(() => {
    const loadModels = async () => {
      try {
        const data = await getAvailableModels();
        setModels(data.models || []);
      } catch (err) {
        console.error('Failed to load models:', err);
      }
    };
    loadModels();
  }, []);

  const handleChange = (key, value) => {
    onSettingsChange({ ...settings, [key]: value });
  };

  return (
    <div className="settings-panel">
      <button
        className="settings-toggle"
        onClick={() => setIsExpanded(!isExpanded)}
      >
        ⚙️ Configuración {isExpanded ? '▼' : '▶'}
      </button>

      {isExpanded && (
        <div className="settings-content">
          <div className="setting-group">
            <label>Modelo</label>
            <select
              value={settings.model || ''}
              onChange={(e) => handleChange('model', e.target.value)}
            >
              <option value="">Por defecto</option>
              {models.map(m => (
                <option key={m.id} value={m.id}>{m.name}</option>
              ))}
            </select>
          </div>

          <div className="setting-group">
            <label>
              Modo Estricto
              <span className="setting-hint">Solo respuestas verificadas</span>
            </label>
            <div className="toggle-switch">
              <input
                type="checkbox"
                id="strictMode"
                checked={settings.strictMode || false}
                onChange={(e) => handleChange('strictMode', e.target.checked)}
              />
              <label htmlFor="strictMode" className="toggle-slider">
                <span className="toggle-on">ON</span>
                <span className="toggle-off">OFF</span>
              </label>
            </div>
          </div>

          <div className="setting-group">
            <label>
              Temperatura
              <span className="setting-hint">{settings.temperature ?? 0.5}</span>
            </label>
            <input
              type="range"
              min="0"
              max="1"
              step="0.1"
              value={settings.temperature ?? 0.5}
              onChange={(e) => handleChange('temperature', parseFloat(e.target.value))}
              disabled={settings.strictMode}
            />
            <div className="range-labels">
              <span>Preciso</span>
              <span>Creativo</span>
            </div>
          </div>

          <div className="setting-group">
            <label>
              Max Tokens
              <span className="setting-hint">{settings.max_tokens ?? 1024}</span>
            </label>
            <input
              type="range"
              min="256"
              max="4096"
              step="256"
              value={settings.max_tokens ?? 1024}
              onChange={(e) => handleChange('max_tokens', parseInt(e.target.value))}
            />
            <div className="range-labels">
              <span>256</span>
              <span>4096</span>
            </div>
          </div>

          <div className="setting-group">
            <label>
              Top P
              <span className="setting-hint">{settings.top_p ?? 0.95}</span>
            </label>
            <input
              type="range"
              min="0"
              max="1"
              step="0.05"
              value={settings.top_p ?? 0.95}
              onChange={(e) => handleChange('top_p', parseFloat(e.target.value))}
              disabled={settings.strictMode}
            />
            <div className="range-labels">
              <span>0</span>
              <span>1</span>
            </div>
          </div>

          <button
            className="reset-settings"
            onClick={() => onSettingsChange({
              model: '',
              strictMode: false,
              temperature: 0.5,
              max_tokens: 1024,
              top_p: 0.95
            })}
          >
            Restablecer valores
          </button>
        </div>
      )}

      <style>{`
        .settings-panel {
          background: #1a1a2e;
          border-radius: 8px;
          margin-bottom: 16px;
          border: 1px solid #2d2d44;
          overflow: hidden;
        }
        
        .settings-toggle {
          width: 100%;
          background: #252540;
          border: none;
          color: #a0a0c0;
          padding: 12px 16px;
          text-align: left;
          cursor: pointer;
          font-size: 13px;
          display: flex;
          align-items: center;
          justify-content: space-between;
        }
        
        .settings-toggle:hover {
          background: #2d2d4c;
        }
        
        .settings-content {
          padding: 16px;
          border-top: 1px solid #2d2d44;
        }
        
        .setting-group {
          margin-bottom: 16px;
        }
        
        .setting-group:last-of-type {
          margin-bottom: 0;
        }
        
        .setting-group label {
          display: flex;
          justify-content: space-between;
          align-items: center;
          color: #c0c0d0;
          font-size: 12px;
          margin-bottom: 6px;
        }
        
        .setting-hint {
          color: #707090;
          font-size: 10px;
        }
        
        .setting-group select {
          width: 100%;
          background: #252540;
          border: 1px solid #3d3d5c;
          color: #e0e0f0;
          padding: 8px 12px;
          border-radius: 6px;
          font-size: 12px;
        }
        
        .setting-group select:focus {
          outline: none;
          border-color: #5060a0;
        }
        
        .setting-group input[type="range"] {
          width: 100%;
          height: 6px;
          background: #3d3d5c;
          border-radius: 3px;
          -webkit-appearance: none;
        }
        
        .setting-group input[type="range"]::-webkit-slider-thumb {
          -webkit-appearance: none;
          width: 16px;
          height: 16px;
          background: #5060a0;
          border-radius: 50%;
          cursor: pointer;
        }
        
        .setting-group input[type="range"]:disabled {
          opacity: 0.5;
          cursor: not-allowed;
        }
        
        .range-labels {
          display: flex;
          justify-content: space-between;
          color: #505070;
          font-size: 9px;
          margin-top: 4px;
        }
        
        .toggle-switch {
          position: relative;
        }
        
        .toggle-switch input {
          position: absolute;
          opacity: 0;
        }
        
        .toggle-slider {
          display: flex;
          background: #3d3d5c;
          border-radius: 20px;
          padding: 2px;
          cursor: pointer;
          width: 50%;
          justify-content: space-between;
        }
        
        .toggle-slider span {
          padding: 4px 10px;
          font-size: 10px;
          border-radius: 16px;
          color: #808090;
          transition: all 0.3s;
        }
        
        .toggle-on {
          background: transparent;
        }
        
        .toggle-off {
          background: #505070;
          color: #c0c0d0;
        }
        
        .toggle-switch input:checked + .toggle-slider .toggle-on {
          background: #4caf50;
          color: white;
        }
        
        .toggle-switch input:checked + .toggle-slider .toggle-off {
          background: transparent;
          color: #808090;
        }
        
        .reset-settings {
          width: 100%;
          background: transparent;
          border: 1px solid #3d3d5c;
          color: #808090;
          padding: 8px;
          border-radius: 6px;
          cursor: pointer;
          font-size: 11px;
          margin-top: 16px;
        }
        
        .reset-settings:hover {
          background: #252540;
          color: #a0a0c0;
        }
      `}</style>
    </div>
  );
}
