import { Calculator } from './ui/Calculator';
import { ThemeControl } from './ui/ThemeControl';
import { useTheme } from './ui/useTheme';

export default function App() {
  const { theme, setTheme } = useTheme();

  return (
    <div className="app-shell">
      <header className="app-header">
        <a className="brand" href="/" aria-label="OpenCalc Studio home">
          <span className="brand-mark" aria-hidden="true">
            <span />
            <span />
            <span />
            <span />
          </span>
          <span>
            <strong>OpenCalc</strong>
            <small>Studio</small>
          </span>
        </a>

        <ThemeControl theme={theme} onChange={setTheme} />
      </header>

      <main className="calculator-stage">
        <Calculator />
      </main>

      <footer className="app-footer">
        <span>Standard mode</span>
        <span aria-hidden="true">•</span>
        <span>Keyboard ready</span>
      </footer>
    </div>
  );
}
