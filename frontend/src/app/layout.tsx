import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Sunwise — Vitamin D exposure estimate",
  description: "A weather-aware, educational guide to today's potential sun exposure window.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
