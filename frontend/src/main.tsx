import ReactDOM from 'react-dom/client';
import App from './App';
import { fetchSiteSettings } from './theme';
import './index.css';

async function bootstrap() {
  const settings = await fetchSiteSettings();
  const root = document.getElementById('root');
  if (!root) return;
  ReactDOM.createRoot(root).render(<App initialSettings={settings} />);
}

void bootstrap();
