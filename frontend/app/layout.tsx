import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Kite — Local video library",
  description: "A calm, local-first workspace for Tunisian video transcripts.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body>
        {children}
      </body>
    </html>
  );
}
