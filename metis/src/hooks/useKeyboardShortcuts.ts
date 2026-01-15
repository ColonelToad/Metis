import { useEffect } from 'react';

export interface KeyboardShortcut {
  key: string;
  ctrlKey?: boolean;
  shiftKey?: boolean;
  altKey?: boolean;
  handler: () => void;
  description: string;
}

export function useKeyboardShortcuts(shortcuts: KeyboardShortcut[]) {
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      for (const shortcut of shortcuts) {
        const ctrlMatch = shortcut.ctrlKey === undefined || e.ctrlKey === shortcut.ctrlKey;
        const shiftMatch = shortcut.shiftKey === undefined || e.shiftKey === shortcut.shiftKey;
        const altMatch = shortcut.altKey === undefined || e.altKey === shortcut.altKey;
        const keyMatch = e.key.toLowerCase() === shortcut.key.toLowerCase();

        if (ctrlMatch && shiftMatch && altMatch && keyMatch) {
          e.preventDefault();
          shortcut.handler();
          break;
        }
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [shortcuts]);
}

export const defaultShortcuts = {
  OVERVIEW: { key: '1', ctrlKey: true, description: 'Go to Overview' },
  SIGNALS: { key: '2', ctrlKey: true, description: 'Go to Signals' },
  PORTFOLIO: { key: '3', ctrlKey: true, description: 'Go to Portfolio' },
  EXPLAINER: { key: '4', ctrlKey: true, description: 'Go to Explainer' },
  SETTINGS: { key: '5', ctrlKey: true, description: 'Go to Settings' },
  COMMAND_PALETTE: { key: 'k', ctrlKey: true, description: 'Open Command Palette' },
  REFRESH: { key: 'r', ctrlKey: true, description: 'Refresh Current View' },
  ESCAPE: { key: 'Escape', description: 'Close Modal/Dismiss' },
};
