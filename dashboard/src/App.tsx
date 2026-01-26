import { useMetrics } from './hooks/useMetrics';
import { MetricsDisplay } from './components/MetricsDisplay';
import { ControlPanel } from './components/ControlPanel';
import { ConfigPanel } from './components/ConfigPanel';
import './App.css';

function App() {
  const { metrics, connected, error } = useMetrics();

  return (
    <div style={{
      minHeight: '100vh',
      background: '#0f0f1a',
      color: 'white',
      padding: '2rem',
    }}>
      <header style={{
        marginBottom: '2rem',
        borderBottom: '1px solid #1a1a2e',
        paddingBottom: '1rem',
      }}>
        <h1 style={{ margin: 0, fontSize: '1.5rem' }}>
          Polymarket Arb Bot Dashboard
        </h1>
        {error && (
          <p style={{ color: '#ff6b6b', marginTop: '0.5rem', fontSize: '0.9rem' }}>
            {error}
          </p>
        )}
      </header>

      <div style={{
        display: 'grid',
        gridTemplateColumns: '1fr 300px',
        gap: '2rem',
        maxWidth: '1400px',
      }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '2rem' }}>
          <MetricsDisplay metrics={metrics} connected={connected} />
          <ConfigPanel />
        </div>
        <div>
          <ControlPanel />
        </div>
      </div>
    </div>
  );
}

export default App;
