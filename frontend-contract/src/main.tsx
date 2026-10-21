import '@fontsource/ibm-plex-sans/cyrillic-400.css';
import '@fontsource/ibm-plex-sans/cyrillic-500.css';
import '@fontsource/ibm-plex-sans/cyrillic-600.css';
import '@fontsource/ibm-plex-sans/latin-400.css';
import '@fontsource/ibm-plex-sans/latin-500.css';
import '@fontsource/ibm-plex-sans/latin-600.css';
import '@fontsource/ibm-plex-serif/latin-500.css';
import './styles/tokens.css';
import './styles/app.css';
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { App } from './App';
import { ErrorBoundary } from './components/ErrorBoundary';
import { initExtras } from './extensions/flags';
import './state/recording';
import { boot } from './state/session';
import { initNotify } from './state/notify';
import { initWakeWord } from './state/wake';

initExtras();
initWakeWord();
initNotify();
void boot();

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  </StrictMode>,
);
