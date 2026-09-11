import type { Metadata } from "next";
import { headers } from "next/headers";
import { IBM_Plex_Mono, IBM_Plex_Sans } from "next/font/google";
import { AppShell } from "@/components/shell/AppShell";
import { Providers } from "@/components/shell/Providers";
import { loadPublicEnv } from "@/lib/env";
import "./globals.css";

const publicEnv = loadPublicEnv();

const plexSans = IBM_Plex_Sans({
  subsets: ["latin"],
  weight: ["400", "500"],
  variable: "--font-kern-sans",
});

const plexMono = IBM_Plex_Mono({
  subsets: ["latin"],
  weight: ["400", "500"],
  variable: "--font-kern-mono",
});

export const metadata: Metadata = {
  metadataBase: new URL(publicEnv.NEXT_PUBLIC_SITE_URL),
  title: publicEnv.NEXT_PUBLIC_APP_NAME,
  description: "Multi-source knowledge hub",
  icons: {
    icon: [
      { url: "/brand/kernector-tab.png", type: "image/png", sizes: "48x48" },
      { url: "/brand/favicon.ico", type: "image/x-icon" },
    ],
    shortcut: "/brand/kernector-tab.png",
    apple: [
      {
        url: "/brand/apple-touch-icon.png",
        sizes: "180x180",
        type: "image/png",
      },
    ],
  },
  openGraph: {
    title: publicEnv.NEXT_PUBLIC_APP_NAME,
    description: "Multi-source knowledge hub",
    images: [{ url: "/brand/opengraph.png", alt: "Kernector" }],
  },
};

export default async function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  // Reading headers opts the root into dynamic rendering so next-themes can
  // receive the per-request CSP nonce. Middleware owns the policy; this is
  // only the ThemeProvider hand-off.
  const nonce = (await headers()).get("x-nonce") ?? undefined;
  return (
    <html lang="en" suppressHydrationWarning>
      <body className={`${plexSans.variable} ${plexMono.variable}`}>
        <Providers nonce={nonce}>
          <AppShell>{children}</AppShell>
        </Providers>
      </body>
    </html>
  );
}
