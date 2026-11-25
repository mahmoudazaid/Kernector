"use client";

import { ThemeProvider as NextThemesProvider } from "next-themes";
import { Suspense, type ReactNode } from "react";
import { AuthGate } from "@/components/auth/AuthGate";
import { AuthProvider } from "@/components/auth/AuthProvider";
import { LoadingState } from "@/components/states/LoadingState";

type ProvidersProps = {
  children: ReactNode;
  nonce?: string;
};

export function Providers({ children, nonce }: ProvidersProps) {
  return (
    <NextThemesProvider
      attribute="data-theme"
      defaultTheme="system"
      enableSystem
      disableTransitionOnChange
      nonce={nonce}
    >
      <AuthProvider>
        <Suspense
          fallback={
            <div className="kern-content-state" aria-busy="true">
              <LoadingState label="Loading" />
            </div>
          }
        >
          <AuthGate>{children}</AuthGate>
        </Suspense>
      </AuthProvider>
    </NextThemesProvider>
  );
}
