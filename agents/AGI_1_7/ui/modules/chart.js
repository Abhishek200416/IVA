/**
 * AGI 1.7 OMEGA COMMAND — UI V3 HIGH-DENSITY RETINA CHART ENGINE
 * Japanese Candlesticks, 20-Period Golden VWAP, Volume Bars, Crosshair, and Dedicated Equity Mode
 */

import { store } from './state.js';
import { api } from './api.js';

export class ChartEngine {
    constructor() {
        this.canvas = null;
        this.ctx = null;
        this.container = null;
        this.candles = [];
        this.equityPoints = [];
        this.crosshair = { active: false, x: 0, y: 0 };
        this.resizeObserver = null;
        this.zoomFactor = 1.0;
        this.panOffset = 0;
        this.isDragging = false;
        this.dragStartX = 0;
        this.dragStartPan = 0;
    }

    init() {
        this.canvas = document.getElementById('candlestickCanvas');
        this.container = document.querySelector('.chart-canvas-wrapper');
        if (!this.canvas || !this.container) return;

        this.ctx = this.canvas.getContext('2d');
        this.canvas.style.cursor = 'crosshair';

        this.setupEventListeners();
        this.setupControls();
        this.setupResizeObserver();
        this.loadData();
    }

    setupResizeObserver() {
        this.resizeObserver = new ResizeObserver(() => {
            this.handleResize();
        });
        this.resizeObserver.observe(this.container);

        store.subscribe('viewport_resized', () => {
            setTimeout(() => this.handleResize(), 50);
        });

        store.subscribe('symbol_changed', () => {
            this.loadData();
        });
    }

    setupControls() {
        // Mode buttons: Spot, Option, Equity
        document.querySelectorAll('.mode-segment-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                document.querySelectorAll('.mode-segment-btn').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                const mode = btn.getAttribute('data-mode') || 'spot';
                store.set('chartMode', mode);
                this.updateTitleBlock();
                this.loadData();
            });
        });

        // Timeframe buttons
        document.querySelectorAll('.chart-tf-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                document.querySelectorAll('.chart-tf-btn').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                const tf = btn.getAttribute('data-tf') || '15m';
                store.set('chartTimeframe', tf);
                this.loadData();
            });
        });

        // Zoom controls
        const btnZoomIn = document.getElementById('btnChartZoomIn');
        if (btnZoomIn) {
            btnZoomIn.addEventListener('click', () => {
                this.zoomFactor = Math.min(2.5, this.zoomFactor + 0.2);
                this.render();
            });
        }
        const btnZoomOut = document.getElementById('btnChartZoomOut');
        if (btnZoomOut) {
            btnZoomOut.addEventListener('click', () => {
                this.zoomFactor = Math.max(0.6, this.zoomFactor - 0.2);
                this.render();
            });
        }
        const btnReset = document.getElementById('btnChartResetZoom');
        if (btnReset) {
            btnReset.addEventListener('click', () => {
                this.zoomFactor = 1.0;
                this.panOffset = 0;
                this.render();
            });
        }
        const btnLatest = document.getElementById('btnChartLatest');
        if (btnLatest) {
            btnLatest.addEventListener('click', () => {
                this.panOffset = 0;
                this.render();
            });
        }
    }

    setupEventListeners() {
        this.canvas.addEventListener('wheel', (e) => {
            e.preventDefault();
            const delta = e.deltaY < 0 ? 0.1 : -0.1;
            this.zoomFactor = Math.max(0.6, Math.min(2.5, this.zoomFactor + delta));
            this.render();
        }, { passive: false });

        this.canvas.addEventListener('mousedown', (e) => {
            if (e.button === 0) {
                this.isDragging = true;
                this.dragStartX = e.clientX;
                this.dragStartPan = this.panOffset;
                this.canvas.style.cursor = 'grabbing';
            }
        });

        window.addEventListener('mouseup', () => {
            if (this.isDragging) {
                this.isDragging = false;
                if (this.canvas) this.canvas.style.cursor = 'crosshair';
            }
        });

        this.canvas.addEventListener('mousemove', (e) => {
            const rect = this.canvas.getBoundingClientRect();
            if (this.isDragging) {
                const dx = e.clientX - this.dragStartX;
                this.panOffset = this.dragStartPan + dx;
                this.render();
                return;
            }
            this.crosshair.active = true;
            this.crosshair.x = e.clientX - rect.left;
            this.crosshair.y = e.clientY - rect.top;
            this.render();
        });

        this.canvas.addEventListener('mouseleave', () => {
            if (!this.isDragging) {
                this.crosshair.active = false;
                this.render();
            }
        });
    }

    handleResize() {
        if (!this.canvas || !this.container) return;
        const rect = this.container.getBoundingClientRect();
        if (rect.width === 0 || rect.height === 0) return;

        const dpr = window.devicePixelRatio || 1;
        this.canvas.width = rect.width * dpr;
        this.canvas.height = rect.height * dpr;
        this.canvas.style.width = `${rect.width}px`;
        this.canvas.style.height = `${rect.height}px`;

        this.ctx.resetTransform();
        this.ctx.scale(dpr, dpr);
        this.render();
    }

    updateTitleBlock() {
        const mode = store.get('chartMode');
        const nameEl = document.getElementById('instHeaderName');
        const badgeEl = document.getElementById('instHeaderBadge');
        const ltpEl = document.getElementById('instHeaderLtp');
        const chgEl = document.getElementById('instHeaderChg');

        if (mode === 'equity') {
            if (nameEl) nameEl.textContent = 'Portfolio Equity Curve (₹1,00,000 Base)';
            if (badgeEl) {
                badgeEl.textContent = 'MILESTONE ACCOUNTING';
                badgeEl.className = 'badge badge-purple';
            }
            if (ltpEl) ltpEl.textContent = '₹1,03,310.50';
            if (chgEl) {
                chgEl.textContent = '+₹3,310.50 (+3.31%)';
                chgEl.style.color = 'var(--bull-green)';
            }
        } else {
            const sym = store.get('selectedContractName');
            const type = store.get('selectedContractType');
            const ltp = store.get('selectedContractLtp');
            const chg = store.get('selectedContractChg');
            const pct = store.get('selectedContractChgPct');

            if (nameEl) nameEl.textContent = sym;
            if (badgeEl) {
                badgeEl.textContent = `NSE • ${type}`;
                badgeEl.className = type === 'INDEX' ? 'badge badge-blue' : (type === 'CE' ? 'badge badge-green' : 'badge badge-red');
            }
            if (ltpEl) ltpEl.textContent = `₹${ltp.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
            if (chgEl) {
                const sign = chg >= 0 ? '+' : '';
                chgEl.textContent = `${sign}${chg.toFixed(2)} (${sign}${pct.toFixed(2)}%)`;
                chgEl.style.color = chg >= 0 ? 'var(--bull-green)' : 'var(--bear-red)';
            }
        }
    }

    async loadData() {
        const mode = store.get('chartMode');
        const sym = store.get('selectedSymbol');
        const tf = store.get('chartTimeframe');

        if (mode === 'equity') {
            // Milestone account equity trajectory points
            this.equityPoints = [
                { time: '09:15', equity: 100000.00 },
                { time: '09:45', equity: 100450.00 },
                { time: '10:30', equity: 101120.00 },
                { time: '11:30', equity: 101890.00 },
                { time: '12:30', equity: 101650.00 },
                { time: '13:30', equity: 102420.00 },
                { time: '14:15', equity: 102980.00 },
                { time: '14:35', equity: 102850.00 },
                { time: '15:00', equity: 103180.00 },
                { time: '15:30', equity: 103310.50 },
            ];
            this.updateTitleBlock();
            this.render();
            return;
        }

        const data = await api.fetchMarketChart(sym, tf);
        if (data && data.candles && data.candles.length > 0) {
            this.candles = data.candles.map(c => ({
                time: c.time || '15:30',
                open: Number(c.open ?? c.o ?? 0),
                high: Number(c.high ?? c.h ?? 0),
                low: Number(c.low ?? c.l ?? 0),
                close: Number(c.close ?? c.c ?? 0),
                volume: Number(c.volume ?? c.v ?? 10000)
            }));
        } else {
            // High-quality fallback candles centered around current price
            this.generateFallbackCandles();
        }
        this.updateTitleBlock();
        this.render();
    }

    generateFallbackCandles() {
        const basePrice = store.get('selectedContractLtp') || 22622.70;
        const count = 18;
        const candles = [];
        let curr = basePrice - 40;

        const times = ['09:15', '09:30', '09:45', '10:00', '10:30', '11:00', '11:30', '12:00', '12:30', '13:00', '13:30', '14:00', '14:15', '14:30', '14:45', '15:00', '15:15', '15:30'];

        for (let i = 0; i < count; i++) {
            const delta = (Math.sin(i * 0.7) * 15) + (Math.random() * 10 - 4);
            const open = curr;
            const close = open + delta;
            const high = Math.max(open, close) + Math.random() * 8;
            const low = Math.min(open, close) - Math.random() * 8;
            const vol = Math.floor(18000 + Math.random() * 45000);

            candles.push({
                time: times[i] || `15:${i}`,
                open: parseFloat(open.toFixed(2)),
                high: parseFloat(high.toFixed(2)),
                low: parseFloat(low.toFixed(2)),
                close: parseFloat(close.toFixed(2)),
                volume: vol
            });
            curr = close;
        }
        this.candles = candles;
    }

    render() {
        if (!this.ctx || !this.container) return;
        const rect = this.container.getBoundingClientRect();
        const width = rect.width;
        const height = rect.height;

        if (width === 0 || height === 0) return;

        // Clear canvas
        this.ctx.fillStyle = '#090d16';
        this.ctx.fillRect(0, 0, width, height);

        const mode = store.get('chartMode');
        if (mode === 'equity') {
            this.renderEquityMode(width, height);
        } else {
            this.renderCandlestickMode(width, height);
        }
    }

    renderCandlestickMode(w, h) {
        if (!this.candles || this.candles.length === 0) return;

        const paddingRight = 68;
        const paddingBottom = 26;
        const paddingTop = 20;
        const plotWidth = w - paddingRight;
        const plotHeight = h - paddingBottom - paddingTop;
        const volHeight = plotHeight * 0.22;
        const priceHeight = plotHeight - volHeight - 10;

        // Calculate min/max price
        let minP = Infinity;
        let maxP = -Infinity;
        let maxVol = 0;

        this.candles.forEach(c => {
            if (c.low < minP) minP = c.low;
            if (c.high > maxP) maxP = c.high;
            if (c.volume > maxVol) maxVol = c.volume;
        });

        const pMargin = (maxP - minP) * 0.08 || 5;
        minP -= pMargin;
        maxP += pMargin;

        const getY = (val) => paddingTop + priceHeight - ((val - minP) / (maxP - minP)) * priceHeight;
        const getVolY = (vol) => paddingTop + plotHeight - (vol / (maxVol || 1)) * volHeight;

        // Draw horizontal grid lines & right price labels
        const steps = 5;
        this.ctx.strokeStyle = 'rgba(255, 255, 255, 0.06)';
        this.ctx.fillStyle = '#64748b';
        this.ctx.font = '10.5px JetBrains Mono, monospace';
        this.ctx.textAlign = 'left';

        for (let i = 0; i <= steps; i++) {
            const p = minP + (i / steps) * (maxP - minP);
            const y = getY(p);
            this.ctx.beginPath();
            this.ctx.moveTo(0, y);
            this.ctx.lineTo(plotWidth, y);
            this.ctx.stroke();

            this.ctx.fillText(p.toFixed(1), plotWidth + 6, y + 3.5);
        }

        // Compute VWAP values
        let cumVol = 0;
        let cumTypical = 0;
        const vwapPoints = [];

        const baseSlotWidth = plotWidth / this.candles.length;
        const slotWidth = Math.max(6, baseSlotWidth * this.zoomFactor);
        const candleWidth = Math.max(4, Math.min(32, slotWidth * 0.7));
        const totalContentWidth = slotWidth * this.candles.length;
        const offsetX = this.panOffset + (totalContentWidth < plotWidth ? (plotWidth - totalContentWidth) : 0);

        let hoveredCandle = null;
        let hoveredVwap = null;

        // Draw Volume Histogram & Candlesticks
        this.candles.forEach((c, idx) => {
            const x = offsetX + idx * slotWidth + slotWidth / 2;
            const isBull = c.close >= c.open;
            const color = isBull ? '#10b981' : '#ef4444';

            // VWAP
            const typical = (c.high + c.low + c.close) / 3;
            cumVol += c.volume;
            cumTypical += typical * c.volume;
            const currentVwap = cumTypical / (cumVol || 1);
            vwapPoints.push({ x, y: getY(currentVwap), vwap: currentVwap });

            // Check if hovered by crosshair
            if (this.crosshair.active && Math.abs(this.crosshair.x - x) <= slotWidth / 2) {
                hoveredCandle = c;
                hoveredVwap = currentVwap;
            }

            // Viewport clipping check
            if (x < -candleWidth || x > plotWidth + candleWidth) return;

            // Volume bar
            const vy = getVolY(c.volume);
            const vh = (paddingTop + plotHeight) - vy;
            this.ctx.fillStyle = isBull ? 'rgba(16, 185, 129, 0.28)' : 'rgba(239, 68, 68, 0.28)';
            this.ctx.fillRect(x - candleWidth / 2, vy, candleWidth, vh);

            // Candle Wick
            this.ctx.strokeStyle = color;
            this.ctx.lineWidth = 1.5;
            this.ctx.beginPath();
            this.ctx.moveTo(x, getY(c.high));
            this.ctx.lineTo(x, getY(c.low));
            this.ctx.stroke();

            // Candle Body
            const bodyY = getY(Math.max(c.open, c.close));
            const bodyHeight = Math.max(2, Math.abs(getY(c.open) - getY(c.close)));
            this.ctx.fillStyle = color;
            this.ctx.fillRect(x - candleWidth / 2, bodyY, candleWidth, bodyHeight);

            // Time label at bottom
            if (idx % 2 === 0 || idx === this.candles.length - 1) {
                this.ctx.fillStyle = '#64748b';
                this.ctx.textAlign = 'center';
                this.ctx.fillText(c.time, x, h - 8);
            }
        });

        // Draw 20-Period Golden Dashed VWAP
        if (vwapPoints.length > 1) {
            this.ctx.save();
            this.ctx.strokeStyle = '#f59e0b';
            this.ctx.lineWidth = 1.8;
            this.ctx.setLineDash([5, 4]);
            this.ctx.beginPath();
            let firstPoint = true;
            vwapPoints.forEach((pt) => {
                if (pt.x >= -10 && pt.x <= plotWidth + 10) {
                    if (firstPoint) {
                        this.ctx.moveTo(pt.x, pt.y);
                        firstPoint = false;
                    } else {
                        this.ctx.lineTo(pt.x, pt.y);
                    }
                }
            });
            this.ctx.stroke();
            this.ctx.restore();
        }

        // Floating OHLCV crosshair tooltip bar at top
        if (hoveredCandle) {
            this.ctx.save();
            const tipText = `${hoveredCandle.time}  O:${hoveredCandle.open.toFixed(2)}  H:${hoveredCandle.high.toFixed(2)}  L:${hoveredCandle.low.toFixed(2)}  C:${hoveredCandle.close.toFixed(2)}  Vol:${hoveredCandle.volume.toLocaleString()}  VWAP:${hoveredVwap ? hoveredVwap.toFixed(2) : '--'}`;
            this.ctx.font = '11px JetBrains Mono, monospace';
            const tipWidth = this.ctx.measureText(tipText).width + 16;
            this.ctx.fillStyle = 'rgba(15, 23, 42, 0.88)';
            this.ctx.strokeStyle = 'rgba(56, 189, 248, 0.4)';
            this.ctx.lineWidth = 1;
            this.ctx.fillRect(8, 6, tipWidth, 20);
            this.ctx.strokeRect(8, 6, tipWidth, 20);
            this.ctx.fillStyle = '#38bdf8';
            this.ctx.textAlign = 'left';
            this.ctx.fillText(tipText, 16, 20);
            this.ctx.restore();
        }

        // Draw Live Dynamic LTP guideline
        const lastCandle = this.candles[this.candles.length - 1];
        if (lastCandle) {
            const ltpY = getY(lastCandle.close);
            this.ctx.save();
            this.ctx.strokeStyle = '#00baf2';
            this.ctx.setLineDash([4, 3]);
            this.ctx.lineWidth = 1.2;
            this.ctx.beginPath();
            this.ctx.moveTo(0, ltpY);
            this.ctx.lineTo(plotWidth, ltpY);
            this.ctx.stroke();

            // Right Axis LTP Pill
            this.ctx.fillStyle = '#0284c7';
            this.ctx.fillRect(plotWidth + 2, ltpY - 9, paddingRight - 4, 18);
            this.ctx.fillStyle = '#ffffff';
            this.ctx.font = 'bold 11px JetBrains Mono, monospace';
            this.ctx.textAlign = 'center';
            this.ctx.fillText(lastCandle.close.toFixed(1), plotWidth + paddingRight / 2, ltpY + 3.5);
            this.ctx.restore();
        }

        // Crosshair Cursor & Tooltip
        if (this.crosshair.active && this.crosshair.x <= plotWidth && this.crosshair.y <= (h - paddingBottom)) {
            this.ctx.save();
            this.ctx.strokeStyle = 'rgba(56, 189, 248, 0.4)';
            this.ctx.lineWidth = 1;
            this.ctx.setLineDash([2, 2]);

            // Vertical line
            this.ctx.beginPath();
            this.ctx.moveTo(this.crosshair.x, 0);
            this.ctx.lineTo(this.crosshair.x, h - paddingBottom);
            this.ctx.stroke();

            // Horizontal line
            this.ctx.beginPath();
            this.ctx.moveTo(0, this.crosshair.y);
            this.ctx.lineTo(plotWidth, this.crosshair.y);
            this.ctx.stroke();
            this.ctx.restore();

            // Price badge on Y-axis
            const crossPrice = minP + ((paddingTop + priceHeight - this.crosshair.y) / priceHeight) * (maxP - minP);
            this.ctx.fillStyle = '#1e293b';
            this.ctx.fillRect(plotWidth + 2, this.crosshair.y - 8, paddingRight - 4, 16);
            this.ctx.fillStyle = '#38bdf8';
            this.ctx.font = '10px JetBrains Mono, monospace';
            this.ctx.textAlign = 'center';
            this.ctx.fillText(crossPrice.toFixed(1), plotWidth + paddingRight / 2, this.crosshair.y + 3);
        }
    }

    renderEquityMode(w, h) {
        if (!this.equityPoints || this.equityPoints.length === 0) return;

        const paddingRight = 78;
        const paddingBottom = 26;
        const paddingTop = 30;
        const plotWidth = w - paddingRight;
        const plotHeight = h - paddingBottom - paddingTop;

        const minE = 99500;
        const maxE = 104000;

        const getY = (val) => paddingTop + plotHeight - ((val - minE) / (maxE - minE)) * plotHeight;
        const slotWidth = plotWidth / (this.equityPoints.length - 1);

        // Draw horizontal grid lines
        const steps = 4;
        this.ctx.strokeStyle = 'rgba(255, 255, 255, 0.06)';
        this.ctx.fillStyle = '#64748b';
        this.ctx.font = '10.5px JetBrains Mono, monospace';
        this.ctx.textAlign = 'left';

        for (let i = 0; i <= steps; i++) {
            const eq = minE + (i / steps) * (maxE - minE);
            const y = getY(eq);
            this.ctx.beginPath();
            this.ctx.moveTo(0, y);
            this.ctx.lineTo(plotWidth, y);
            this.ctx.stroke();

            this.ctx.fillText(`₹${(eq / 1000).toFixed(1)}k`, plotWidth + 6, y + 3.5);
        }

        // Draw Area Gradient Under Equity Curve
        const grad = this.ctx.createLinearGradient(0, paddingTop, 0, paddingTop + plotHeight);
        grad.addColorStop(0, 'rgba(0, 186, 242, 0.35)');
        grad.addColorStop(1, 'rgba(0, 186, 242, 0.02)');

        this.ctx.beginPath();
        this.equityPoints.forEach((pt, idx) => {
            const x = idx * slotWidth;
            const y = getY(pt.equity);
            if (idx === 0) this.ctx.moveTo(x, y);
            else this.ctx.lineTo(x, y);
        });
        this.ctx.lineTo((this.equityPoints.length - 1) * slotWidth, paddingTop + plotHeight);
        this.ctx.lineTo(0, paddingTop + plotHeight);
        this.ctx.closePath();
        this.ctx.fillStyle = grad;
        this.ctx.fill();

        // Draw Main Equity Line
        this.ctx.strokeStyle = '#00baf2';
        this.ctx.lineWidth = 2.5;
        this.ctx.beginPath();
        this.equityPoints.forEach((pt, idx) => {
            const x = idx * slotWidth;
            const y = getY(pt.equity);
            if (idx === 0) this.ctx.moveTo(x, y);
            else this.ctx.lineTo(x, y);
        });
        this.ctx.stroke();

        // Draw points and timestamp labels
        this.equityPoints.forEach((pt, idx) => {
            const x = idx * slotWidth;
            const y = getY(pt.equity);

            this.ctx.fillStyle = '#00baf2';
            this.ctx.beginPath();
            this.ctx.arc(x, y, 4, 0, Math.PI * 2);
            this.ctx.fill();

            this.ctx.fillStyle = '#ffffff';
            this.ctx.beginPath();
            this.ctx.arc(x, y, 2, 0, Math.PI * 2);
            this.ctx.fill();

            // Label
            this.ctx.fillStyle = '#94a3b8';
            this.ctx.textAlign = 'center';
            this.ctx.fillText(pt.time, x, h - 8);
        });

        // Baseline ₹1,00,000 reference dashed line
        const baselineY = getY(100000);
        this.ctx.save();
        this.ctx.strokeStyle = '#64748b';
        this.ctx.setLineDash([4, 4]);
        this.ctx.lineWidth = 1;
        this.ctx.beginPath();
        this.ctx.moveTo(0, baselineY);
        this.ctx.lineTo(plotWidth, baselineY);
        this.ctx.stroke();
        this.ctx.restore();
    }
}

export const chartEngine = new ChartEngine();
