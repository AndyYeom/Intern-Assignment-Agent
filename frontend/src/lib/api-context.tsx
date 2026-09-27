"use client";

import { createContext, useContext, useMemo } from "react";
import { createApiClient, type ApiClient } from "./api";

const ApiBaseContext = createContext<string | null>(null);

export function ApiBaseProvider({
  apiBaseUrl,
  children,
}: {
  apiBaseUrl: string;
  children: React.ReactNode;
}) {
  return (
    <ApiBaseContext.Provider value={apiBaseUrl}>
      {children}
    </ApiBaseContext.Provider>
  );
}

export function useApiBaseUrl(): string {
  const value = useContext(ApiBaseContext);
  if (!value) {
    throw new Error("useApiBaseUrl must be used within an ApiBaseProvider");
  }
  return value;
}

export function useApi(): ApiClient {
  const baseUrl = useApiBaseUrl();
  return useMemo(() => createApiClient(baseUrl), [baseUrl]);
}
