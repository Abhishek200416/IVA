/**
 * AGI 1.7 OMEGA COMMAND — UI V4 MULTI-PAGE APPLICATION ROUTER
 * Client-Side Routing with HTML5 History API, Direct URL Access, and Browser History
 */

import { store } from './state.js';

export const PAGE_CONFIG = {
    trading: {
        path: '/trading',
        title: 'Trading Desk — AGI 1.7 OMEGA COMMAND',
        label: 'Trading Desk',
        icon: '📈',
        breadcrumb: 'Executive 3-Panel Trading Desk'
    },
    algorithms: {
        path: '/algorithms',
        title: 'Quantitative Algorithms — AGI 1.7 OMEGA COMMAND',
        label: 'Algorithms Catalog',
        icon: '⚙️',
        breadcrumb: 'Mathematical Models & Risk Verification Engine'
    },
    market: {
        path: '/market',
        title: 'Market Explorer — AGI 1.7 OMEGA COMMAND',
        label: 'Market Explorer',
        icon: '🌐',
        breadcrumb: 'Underlyings & Institutional Open Interest'
    },
    options: {
        path: '/options',
        title: 'Options Workspace — AGI 1.7 OMEGA COMMAND',
        label: 'Options Workspace',
        icon: '⚡',
        breadcrumb: 'Full-Depth Option Chain & Volatility Surface'
    },
    intelligence: {
        path: '/intelligence',
        title: 'AI Intelligence — AGI 1.7 OMEGA COMMAND',
        label: 'AI Intelligence',
        icon: '🧠',
        breadcrumb: 'Operator Console & Multi-Agent Coordination Floor'
    },
    portfolio: {
        path: '/portfolio',
        title: 'Portfolio & Risk — AGI 1.7 OMEGA COMMAND',
        label: 'Portfolio & Risk',
        icon: '🛡️',
        breadcrumb: 'Institutional Capital Accounting & 14-Gate Risk Protocol'
    },
    activity: {
        path: '/activity',
        title: 'Orders & Trade History — AGI 1.7 OMEGA COMMAND',
        label: 'Activity & Orders',
        icon: '📋',
        breadcrumb: 'Paper Orders, Reconciled Fills & Audit Trail'
    },
    strategies: {
        path: '/strategies',
        title: 'Strategy Lab — AGI 1.7 OMEGA COMMAND',
        label: 'Strategy Lab',
        icon: '🔬',
        breadcrumb: 'Quantitative Models Catalog & Volatility Experiments'
    },
    memory: {
        path: '/memory',
        title: 'Memory & Learning — AGI 1.7 OMEGA COMMAND',
        label: 'Memory & Learning',
        icon: '💾',
        breadcrumb: '4-Tier Memory Architecture & Calibration Trajectory'
    },
    system: {
        path: '/system',
        title: 'System & Data Health — AGI 1.7 OMEGA COMMAND',
        label: 'System Health',
        icon: '🔋',
        breadcrumb: 'Microservice Daemons & Paytm Quarantine Audit'
    },
    settings: {
        path: '/settings',
        title: 'Settings & Integrations — AGI 1.7 OMEGA COMMAND',
        label: 'Settings',
        icon: '⚙️',
        breadcrumb: 'Preferences, Diagnostics & Environment Safeguards'
    }
};

export class MultiPageRouter {
    constructor() {
        this.pages = Object.keys(PAGE_CONFIG);
        this.pageCallbacks = new Map();
    }

    init() {
        // Listen to browser Back/Forward navigation
        window.addEventListener('popstate', (e) => {
            const pageId = e.state?.page || this.resolveCurrentPath();
            this.navigate(pageId, false);
        });

        // Listen for hash change fallbacks
        window.addEventListener('hashchange', () => {
            const hashPage = window.location.hash.replace('#', '').toLowerCase();
            if (this.pages.includes(hashPage)) {
                this.navigate(hashPage, false);
            }
        });

        // Intercept internal link clicks with data-navigate
        document.addEventListener('click', (e) => {
            const target = e.target.closest('[data-navigate]');
            if (target) {
                e.preventDefault();
                const targetPage = target.getAttribute('data-navigate');
                if (targetPage) {
                    this.navigate(targetPage, true);
                }
            }
        });

        // Resolve initial route from pathname or hash
        const initialPage = this.resolveCurrentPath();
        this.navigate(initialPage, false);

        // Keep state store in sync
        store.subscribe('activePage', ({ value }) => {
            this.updateDom(value);
        });
    }

    registerPageHandler(pageId, handlerFn) {
        this.pageCallbacks.set(pageId, handlerFn);
    }

    resolveCurrentPath() {
        const path = window.location.pathname.toLowerCase();
        for (const [key, config] of Object.entries(PAGE_CONFIG)) {
            if (path === config.path || path.startsWith(config.path + '/')) {
                return key;
            }
        }
        // Fallback to hash
        const hash = window.location.hash.replace('#', '').toLowerCase();
        if (this.pages.includes(hash)) {
            return hash;
        }
        return 'trading';
    }

    navigate(target, pushState = true) {
        let pageId = (target || '').toString().trim().replace(/^\//, '').toLowerCase();
        if (!this.pages.includes(pageId)) {
            pageId = 'trading';
        }

        const config = PAGE_CONFIG[pageId];

        // Update browser URL and title via HTML5 History API
        if (pushState && window.location.pathname !== config.path) {
            window.history.pushState({ page: pageId }, config.title, config.path);
        }
        document.title = config.title;

        // Update central store
        store.set('activePage', pageId);
        store.set('mobileMenuOpen', false);

        // Execute registered page mount handler if any
        if (this.pageCallbacks.has(pageId)) {
            try {
                this.pageCallbacks.get(pageId)();
            } catch (err) {
                console.error(`[Router] Error executing page handler for '${pageId}':`, err);
            }
        }

        this.updateDom(pageId);
    }

    updateDom(pageId) {
        const config = PAGE_CONFIG[pageId];

        // 0. Toggle trading desk body class (hides outer sidebar on Trading Desk)
        document.body.classList.toggle('on-trading-desk', pageId === 'trading');

        // 1. Update navigation active states
        document.querySelectorAll('.nav-tab-btn, .mobile-nav-item, [data-navigate]').forEach(el => {
            const dest = el.getAttribute('data-navigate') || el.getAttribute('data-page') || el.getAttribute('data-workspace');
            if (dest === pageId) {
                el.classList.add('active');
            } else {
                el.classList.remove('active');
            }
        });

        // 2. Update page container visibility
        document.querySelectorAll('.page-pane').forEach(pane => {
            const id = pane.id.replace('page-', '');
            if (id === pageId) {
                pane.classList.add('active');
            } else {
                pane.classList.remove('active');
            }
        });

        // 3. Update breadcrumbs and title
        const breadcrumbEl = document.getElementById('shellBreadcrumbText');
        if (breadcrumbEl && config) {
            breadcrumbEl.textContent = `${config.icon} ${config.label} • ${config.breadcrumb}`;
        }

        // 4. Close mobile navigation menu if open
        const mobileMenu = document.getElementById('mobileNavDrawer');
        if (mobileMenu) {
            mobileMenu.classList.remove('open');
        }
        const backdrop = document.getElementById('mobileNavBackdrop');
        if (backdrop) {
            backdrop.classList.remove('active');
        }

        // 5. Scroll container to top
        window.scrollTo({ top: 0, behavior: 'instant' });
    }
}

export const router = new MultiPageRouter();
