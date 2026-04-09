import "./globals.css";

import type { ReactNode } from "react";

export const metadata = {
  title: "Novel Autogrowth Workbench",
  description: "A four-panel workbench for an evolving story engine.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}

