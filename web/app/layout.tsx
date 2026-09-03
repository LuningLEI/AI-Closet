import type { Metadata } from "next";
import "./globals.css";
import Header from "../components/Header";
import { AuthProvider } from "../lib/auth";

export const metadata: Metadata = {
  title: "AI Closet",
  description: "Wardrobe intelligence demo spanning Next.js, FastAPI, agent skills, and retrieval-ready metadata.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <AuthProvider>
          <div className="app-shell">
            <Header />
            <main className="page-content">{children}</main>
          </div>
        </AuthProvider>
      </body>
    </html>
  );
}
