import { createContext, useContext, useState, ReactNode } from 'react';
import enUS from '../locales/en-US.json';
import zhCN from '../locales/zh-CN.json';

type Locale = 'en-US' | 'zh-CN';

interface LocaleContextType {
  locale: Locale;
  setLocale: (locale: Locale) => void;
  messages: Record<string, any>;
}

const LocaleContext = createContext<LocaleContextType | undefined>(undefined);

const messages: Record<Locale, Record<string, any>> = {
  'en-US': enUS,
  'zh-CN': zhCN,
};

export function LocaleProvider({ children }: { children: ReactNode }) {
  const [locale, setLocale] = useState<Locale>('en-US');

  return (
    <LocaleContext.Provider value={{ locale, setLocale, messages: messages[locale] }}>
      {children}
    </LocaleContext.Provider>
  );
}

export function useLocale() {
  const context = useContext(LocaleContext);
  if (!context) {
    throw new Error('useLocale must be used within LocaleProvider');
  }
  return context;
}
