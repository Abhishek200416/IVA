/**
 * AGI 1.7 OMEGA COMMAND — UI V4 HEADER & NAVIGATION MODULE
 * Global Navigation Bar, Mobile Drawer Controller, Live IST Clock, and Account Metrics Ribbon
 */

import { store } from './state.js';
import { router, PAGE_CONFIG } from './router.js';

export class HeaderController {
    constructor() {
        this.clockTimer = null;
    }

    init() {
        this.setupNavEventListeners();
        this.setupSidebar();
        this.setupSettingsDropdown();
        this.setupMobileMenu();
        this.setupBottomNav();
        this.setupEpochDropdown();
        this.startClock();
        this.subscribeToState();
    }

    setupSidebar() {
        const desktopToggle = document.getElementById('btnToggleSidebarDesktop');
        const collapseBtn = document.getElementById('btnSidebarCollapse');
        const sidebar = document.getElementById('appSidebar');

        const toggleSidebar = () => {
            if (!sidebar) return;
            const isCollapsed = sidebar.classList.toggle('collapsed');
            store.set('sidebarCollapsed', isCollapsed);
            if (collapseBtn) {
                const icon = collapseBtn.querySelector('.collapse-icon');
                const label = collapseBtn.querySelector('.collapse-label');
                if (icon) icon.textContent = isCollapsed ? '▶' : '◀';
                if (label) label.textContent = isCollapsed ? 'Expand' : 'Collapse Menu';
            }
            // Trigger window resize event so canvas chart adapts immediately
            setTimeout(() => {
                window.dispatchEvent(new Event('resize'));
            }, 250);
        };

        if (desktopToggle) desktopToggle.addEventListener('click', toggleSidebar);
        if (collapseBtn) collapseBtn.addEventListener('click', toggleSidebar);
    }

    setupSettingsDropdown() {
        const toggleBtn = document.getElementById('btnSettingsToggle');
        const menu = document.getElementById('settingsDropdownMenu');
        if (!toggleBtn || !menu) return;

        const openMenu = () => {
            menu.classList.add('active');
            toggleBtn.setAttribute('aria-expanded', 'true');
        };

        const closeMenu = () => {
            menu.classList.remove('active');
            toggleBtn.setAttribute('aria-expanded', 'false');
        };

        toggleBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            if (menu.classList.contains('active')) {
                closeMenu();
            } else {
                openMenu();
            }
        });

        // Close on outside click
        document.addEventListener('click', (e) => {
            if (!menu.contains(e.target) && e.target !== toggleBtn) {
                closeMenu();
            }
        });

        // Close on Escape key
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && menu.classList.contains('active')) {
                closeMenu();
                toggleBtn.focus();
            }
        });

        // Action handlers
        const resetBtn = document.getElementById('btnMenuResetLayout');
        if (resetBtn) {
            resetBtn.addEventListener('click', () => {
                closeMenu();
                store.emit('reset_trading_layout');
            });
        }

        const profileBtn = document.getElementById('btnMenuProfile');
        if (profileBtn) {
            profileBtn.addEventListener('click', () => {
                closeMenu();
                store.emit('open_modal', { modalId: 'modalProfile' });
            });
        }

        const reportBtn = document.getElementById('btnMenuReport');
        if (reportBtn) {
            reportBtn.addEventListener('click', () => {
                closeMenu();
                store.emit('open_modal', { modalId: 'modalReport' });
            });
        }

        const motionBtn = document.getElementById('btnMenuReducedMotion');
        const motionDesc = document.getElementById('motionStatusDesc');
        if (motionBtn) {
            motionBtn.addEventListener('click', () => {
                const isReduced = document.body.classList.toggle('reduce-motion');
                if (motionDesc) {
                    motionDesc.textContent = isReduced ? 'Reduced Motion (Active)' : 'Standard Animations (Active)';
                }
            });
        }

        const systemBtn = document.getElementById('btnMenuSystemHealth');
        if (systemBtn) {
            systemBtn.addEventListener('click', () => {
                closeMenu();
                router.navigate('system', true);
            });
        }

        const settingsPageBtn = document.getElementById('btnMenuSettingsPage');
        if (settingsPageBtn) {
            settingsPageBtn.addEventListener('click', () => {
                closeMenu();
                router.navigate('settings', true);
            });
        }
    }

    setupBottomNav() {
        const moreBtn = document.getElementById('btnBottomNavMore');
        const drawer = document.getElementById('mobileNavDrawer');
        const backdrop = document.getElementById('mobileNavBackdrop');

        if (moreBtn && drawer && backdrop) {
            moreBtn.addEventListener('click', (e) => {
                e.preventDefault();
                drawer.classList.add('open');
                backdrop.classList.add('active');
                store.set('mobileMenuOpen', true);
            });
        }

        document.querySelectorAll('.bottom-nav-item[data-navigate]').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.preventDefault();
                const target = btn.getAttribute('data-navigate');
                if (target) {
                    router.navigate(target, true);
                }
            });
        });
    }

    setupNavEventListeners() {
        // Desktop and tablet nav buttons
        document.querySelectorAll('.nav-tab-btn, [data-navigate]').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.preventDefault();
                const target = btn.getAttribute('data-navigate') || btn.getAttribute('data-workspace') || btn.getAttribute('data-page');
                if (target) {
                    router.navigate(target, true);
                }
            });
        });

        const startTradeBtn = document.getElementById('btnStartTradeHeader');
        if (startTradeBtn) {
            startTradeBtn.addEventListener('click', () => {
                store.emit('open_modal', { modalId: 'modalWizard' });
            });
        }
    }

    setupMobileMenu() {
        const toggleBtn = document.getElementById('btnMobileNavToggle');
        const drawer = document.getElementById('mobileNavDrawer');
        const backdrop = document.getElementById('mobileNavBackdrop');
        const closeBtn = document.getElementById('btnCloseMobileNav');

        const openMenu = () => {
            if (drawer) drawer.classList.add('open');
            if (backdrop) backdrop.classList.add('active');
            store.set('mobileMenuOpen', true);
        };

        const closeMenu = () => {
            if (drawer) drawer.classList.remove('open');
            if (backdrop) backdrop.classList.remove('active');
            store.set('mobileMenuOpen', false);
        };

        if (toggleBtn) toggleBtn.addEventListener('click', openMenu);
        if (closeBtn) closeBtn.addEventListener('click', closeMenu);
        if (backdrop) backdrop.addEventListener('click', closeMenu);

        // Mobile drawer navigation clicks
        document.querySelectorAll('.mobile-nav-item').forEach(item => {
            item.addEventListener('click', (e) => {
                e.preventDefault();
                const target = item.getAttribute('data-navigate');
                if (target) {
                    router.navigate(target, true);
                    closeMenu();
                }
            });
        });
    }

    setupEpochDropdown() {
        const epochSelect = document.getElementById('epochSelect');
        if (epochSelect) {
            epochSelect.addEventListener('change', (e) => {
                const newEpoch = e.target.value;
                store.set('selectedEpoch', newEpoch);
                store.emit('epoch_changed', { epoch: newEpoch });
            });
        }
    }

    startClock() {
        const clockEl = document.getElementById('liveClockText');
        const updateClock = () => {
            if (clockEl) {
                const now = new Date();
                const istTime = now.toLocaleTimeString('en-IN', { timeZone: 'Asia/Kolkata', hour12: false });
                clockEl.textContent = `${istTime} IST`;
            }
        };
        updateClock();
        this.clockTimer = setInterval(updateClock, 1000);
    }

    subscribeToState() {
        store.subscribe('status_updated', ({ value }) => {
            this.renderStatusMetrics(value);
        });

        store.subscribe('positions_updated', ({ value }) => {
            this.renderAccountingMetrics(value);
        });

        store.subscribe('epoch_changed', () => {
            this.renderAccountingMetrics();
        });
    }

    renderStatusMetrics(data) {
        if (!data) return;

        const statusText = document.getElementById('mktStatusText');
        const statusDot = document.getElementById('mktStatusDot');
        if (statusText && statusDot) {
            if (data.market_session_active) {
                statusText.textContent = 'Mkt Open (Live)';
                statusDot.style.backgroundColor = '#10b981';
            } else {
                statusText.textContent = 'Mkt Closed (15:30 IST)';
                statusDot.style.backgroundColor = '#ef4444';
            }
        }

        const niftyPriceEl = document.getElementById('headerNiftyPrice');
        const niftyChgEl = document.getElementById('headerNiftyChg');
        const sessionBadgeEl = document.getElementById('headerSessionBadge');

        const ltp = store.get('selectedContractLtp') || 22622.70;
        const chg = store.get('selectedContractChg') || -99.25;
        const pct = store.get('selectedContractChgPct') || -0.44;

        if (niftyPriceEl) niftyPriceEl.textContent = `₹${Number(ltp).toLocaleString('en-IN', { minimumFractionDigits: 2 })}`;
        if (niftyChgEl) {
            const sign = chg >= 0 ? '+' : '';
            niftyChgEl.textContent = `${sign}${Number(chg).toFixed(2)} (${sign}${Number(pct).toFixed(2)}%)`;
            niftyChgEl.className = chg >= 0 ? 'spot-change profit' : 'spot-change loss';
            niftyChgEl.style.color = chg >= 0 ? '#10b981' : '#f87171';
        }
        if (sessionBadgeEl) {
            if (data.market_session_active) {
                sessionBadgeEl.textContent = 'MKT LIVE';
                sessionBadgeEl.className = 'badge badge-green header-session-badge';
            } else {
                sessionBadgeEl.textContent = 'CLOSED • EOD Verified Snapshot';
                sessionBadgeEl.className = 'badge badge-amber header-session-badge';
            }
        }
    }

    renderAccountingMetrics(posData) {
        const baseCapEl = document.getElementById('ribbonBaseCapital');
        const reserveEl = document.getElementById('ribbonSavedReserve');
        const deployedEl = document.getElementById('ribbonCapitalDeployed');
        const pnlEl = document.getElementById('ribbonNetPnl');
        const equityEl = document.getElementById('ribbonEquity');

        const activeEpoch = store.get('selectedEpoch') || '100K';

        if (activeEpoch.includes('10K')) {
            if (baseCapEl) baseCapEl.textContent = '₹10,000.00';
            if (reserveEl) reserveEl.textContent = '₹2,652.50 (26.5%)';
            if (deployedEl) deployedEl.textContent = '₹7,347.50 (73.5%)';
            if (pnlEl) {
                pnlEl.textContent = '-₹48.00 (-0.48%)';
                pnlEl.className = 'metric-val loss';
            }
            if (equityEl) equityEl.textContent = '₹9,952.00';
        } else if (activeEpoch.includes('50K')) {
            if (baseCapEl) baseCapEl.textContent = '₹50,000.00';
            if (reserveEl) reserveEl.textContent = '₹18,500.00 (37.0%)';
            if (deployedEl) deployedEl.textContent = '₹31,500.00 (63.0%)';
            if (pnlEl) {
                pnlEl.textContent = '+₹1,680.45 (+3.36%)';
                pnlEl.className = 'metric-val profit';
            }
            if (equityEl) equityEl.textContent = '₹52,265.45';
        } else {
            // Standard ₹1,00,000 Multi-Asset Paper Session
            if (baseCapEl) baseCapEl.textContent = '₹1,00,000.00';
            if (reserveEl) reserveEl.textContent = '₹36,225.00 (36.2%)';
            if (deployedEl) deployedEl.textContent = '₹63,775.00 (63.8%)';
            if (pnlEl) {
                pnlEl.textContent = '+₹3,310.50 (+3.31%)';
                pnlEl.className = 'metric-val profit';
            }
            if (equityEl) equityEl.textContent = '₹1,03,310.50';
        }
    }
}

export const headerController = new HeaderController();
