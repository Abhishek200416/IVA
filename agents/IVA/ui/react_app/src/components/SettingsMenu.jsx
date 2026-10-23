import React, { useEffect, useRef } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import { RotateCcw, User, Sliders, ShieldCheck, Activity, Info, X } from 'lucide-react';

export default function SettingsMenu({ isOpen, onClose, onResetLayout, onNavigateSettings }) {
  const menuRef = useRef(null);

  useEffect(() => {
    function handleClickOutside(e) {
      if (menuRef.current && !menuRef.current.contains(e.target)) {
        onClose();
      }
    }
    function handleKeyDown(e) {
      if (e.key === 'Escape') onClose();
    }
    if (isOpen) {
      document.addEventListener('mousedown', handleClickOutside);
      document.addEventListener('keydown', handleKeyDown);
    }
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  return (
    <AnimatePresence>
      <motion.div
        ref={menuRef}
        initial={{ opacity: 0, y: -6, scale: 0.96 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        exit={{ opacity: 0, y: -6, scale: 0.96 }}
        transition={{ duration: 0.12, ease: 'easeOut' }}
        className="absolute right-3 top-14 z-50 w-72 bg-slate-900 border border-slate-700/80 rounded-xl shadow-2xl p-2 text-slate-200"
      >
        <div className="flex items-center justify-between px-3 py-2 border-b border-slate-800 text-xs font-bold text-slate-400">
          <span>SETTINGS & WORKSPACE</span>
          <button onClick={onClose} className="p-0.5 hover:text-slate-100 rounded">
            <X className="w-3.5 h-3.5" />
          </button>
        </div>

        <div className="py-1 space-y-0.5 text-xs">
          {/* Reset Layout */}
          <button
            onClick={() => {
              onResetLayout();
              onClose();
            }}
            className="flex items-center gap-2.5 w-full px-3 py-2 text-left rounded-lg hover:bg-slate-800 text-cyan-300 font-medium transition"
          >
            <RotateCcw className="w-4 h-4 text-cyan-400" />
            <div>
              <div className="font-semibold">Reset Panel Layout</div>
              <div className="text-[10px] text-slate-400">Restore default 300px / 340px / 360px split</div>
            </div>
          </button>

          {/* Operator Profile */}
          <div className="flex items-center gap-2.5 px-3 py-2 rounded-lg bg-slate-950/40 text-slate-300">
            <User className="w-4 h-4 text-slate-400" />
            <div>
              <div className="font-semibold text-slate-200">Operator Abhi</div>
              <div className="text-[10px] text-slate-400">Role: Primary Commander • Manager Mode</div>
            </div>
          </div>

          {/* Security & Gate Status */}
          <div className="flex items-center gap-2.5 px-3 py-2 rounded-lg bg-slate-950/40 text-slate-300">
            <ShieldCheck className="w-4 h-4 text-emerald-400" />
            <div>
              <div className="font-semibold text-emerald-400">Strictly Paper Boundary</div>
              <div className="text-[10px] text-slate-400">Live order routes permanently blocked (403)</div>
            </div>
          </div>

          {/* API Health */}
          <button
            onClick={() => {
              if (onNavigateSettings) onNavigateSettings();
              onClose();
            }}
            className="flex items-center gap-2.5 w-full px-3 py-2 text-left rounded-lg hover:bg-slate-800 text-slate-200 transition"
          >
            <Activity className="w-4 h-4 text-amber-400" />
            <div>
              <div className="font-semibold">System & API Health</div>
              <div className="text-[10px] text-slate-400">Inspection diagnostics on port 8088</div>
            </div>
          </button>

          {/* Version Info */}
          <div className="px-3 py-2 border-t border-slate-800/80 text-[10px] text-slate-500 flex items-center justify-between">
            <span>AGI 1.7 OMEGA COMMAND</span>
            <span className="font-mono text-slate-400">v5.0.0-react-omega</span>
          </div>
        </div>
      </motion.div>
    </AnimatePresence>
  );
}
