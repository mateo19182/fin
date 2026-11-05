import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";
import { App } from "./App";
import { BASE } from "./lib/base";
import { PrivacyProvider } from "./lib/privacy";
import "./index.css";

const qc = new QueryClient({
  defaultOptions: { queries: { staleTime: 30_000, retry: 1, refetchOnWindowFocus: true } },
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={qc}>
      <PrivacyProvider>
        <BrowserRouter basename={BASE}>
          <App />
        </BrowserRouter>
      </PrivacyProvider>
    </QueryClientProvider>
  </StrictMode>,
);
