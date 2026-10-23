/**
 * AGI 1.7 OMEGA COMMAND — UI V4 MASTER APPLICATION BOOTSTRAPPER
 * Orchestrates multi-page lifecycle, page registration, background sync loop, and global state.
 */

import { api } from './api.js';
import { store } from './state.js';
import { router } from './router.js';
import { headerController } from './header.js';
import { modalController } from './modal.js';

// Import all 10 dedicated page controllers
import { pageTrading } from './pages/page_trading.js';
import { pageMarket } from './pages/page_market.js';
import { pageOptions } from './pages/page_options.js';
import { pageIntelligence } from './pages/page_intelligence.js';
import { pagePortfolio } from './pages/page_portfolio.js';
import { pageActivity } from './pages/page_activity.js';
import { pageStrategies } from './pages/page_strategies.js';
import { pageMemory } from './pages/page_memory.js';
import { pageSystem } from './pages/page_system.js';
import { pageSettings } from './pages/page_settings.js';
import { pageAlgorithms } from './pages/page_algorithms.js';

class ApplicationRoot {
    constructor() {
        this.pollInterval = null;
        this.pageControllers = {
            trading: pageTrading,
            algorithms: pageAlgorithms,
            market: pageMarket,
            options: pageOptions,
            intelligence: pageIntelligence,
            portfolio: pagePortfolio,
            activity: pageActivity,
            strategies: pageStrategies,
            memory: pageMemory,
            system: pageSystem,
            settings: pageSettings
        };
    }

    async start() {
        console.log('[AGI 1.7 UI V4] Bootstrapping Multi-Page Quantitative Terminal...');

        // 1. Initialize Global Header & Modals
        headerController.init();
        modalController.init();

        // 2. Initialize and Register All 10 Pages
        Object.entries(this.pageControllers).forEach(([pageId, controller]) => {
            try {
                controller.init();
                router.registerPageHandler(pageId, () => controller.init());
            } catch (err) {
                console.error(`[AGI 1.7] Failed to init page controller for '${pageId}':`, err);
            }
        });

        // 3. Initialize Router (resolves URL / pathname)
        router.init();

        // 4. Responsive Window Resize Handler
        window.addEventListener('resize', () => {
            store.emit('viewport_resized', {
                width: window.innerWidth,
                height: window.innerHeight
            });
        });

        // 5. Initial Hydration & Controlled Background Polling
        await this.hydrateInitialData();
        this.startBackgroundSync();

        console.log('[AGI 1.7 UI V4] All 10 pages mounted successfully. Execution: STRICTLY PAPER ONLY.');
    }

    async hydrateInitialData() {
        try {
            const [status, pos] = await Promise.all([
                api.fetchStatus(),
                api.fetchPaperPositions()
            ]);
            if (status) {
                store.set('statusData', status);
                store.emit('status_updated', { value: status });
            }
            if (pos) {
                store.set('positionsData', pos);
                store.emit('positions_updated', { value: pos });
            }
        } catch (err) {
            console.warn('[AGI 1.7] Initial data hydration encountered network delay.');
        }
    }

    startBackgroundSync() {
        if (this.pollInterval) clearInterval(this.pollInterval);

        const freq = store.get('settings')?.refreshIntervalMs || 3500;
        this.pollInterval = setInterval(async () => {
            try {
                const status = await api.fetchStatus();
                if (status) {
                    store.set('statusData', status);
                    store.emit('status_updated', { value: status });
                }
            } catch (err) {
                // Background catch
            }
        }, freq);
    }
}

export const app = new ApplicationRoot();
window.router = router;
window.store = store;
window.api = api;

// DOM Ready Bootstrapper
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => app.start());
} else {
    app.start();
}
