import { createContext, useContext, useState, type ReactNode } from 'react';

interface PollingCtx {
  intervalMs: number;
  setIntervalMs: (ms: number) => void;
}

const PollingContext = createContext<PollingCtx>({
  intervalMs: 10_000,
  setIntervalMs: () => {},
});

export function PollingProvider({ children }: { children: ReactNode }) {
  const [intervalMs, setIntervalMs] = useState(10_000);
  return (
    <PollingContext.Provider value={{ intervalMs, setIntervalMs }}>
      {children}
    </PollingContext.Provider>
  );
}

export function usePollingInterval(): PollingCtx {
  return useContext(PollingContext);
}
