import type { Metadata } from "next";
import { Bricolage_Grotesque, JetBrains_Mono, Newsreader } from "next/font/google";
import "./globals.css";

// The three faces stand for the three sides of the product: the human
// document, the engine, and the machine output.
const display = Bricolage_Grotesque({
  subsets: ["latin"],
  weight: ["600", "700", "800"],
  variable: "--font-display",
  display: "swap",
});

const body = Newsreader({
  subsets: ["latin"],
  weight: ["300", "400", "500"],
  variable: "--font-body",
  display: "swap",
});

const mono = JetBrains_Mono({
  subsets: ["latin"],
  weight: ["400", "500", "700"],
  variable: "--font-mono",
  display: "swap",
});

export const metadata: Metadata = {
  title: "Papyrus — any file in, agent-ready Markdown out",
  description:
    "A universal document ingestion engine. PDF, Word, PowerPoint, Excel, HTML, EPUB and more become clean Markdown with page anchors, provenance and embedding-ready chunks. Runs entirely on your own machine.",
  openGraph: {
    title: "Papyrus — any file in, agent-ready Markdown out",
    description:
      "Universal document ingestion for AI agents. Deterministic, local, no LLM in the conversion path.",
    type: "website",
  },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${display.variable} ${body.variable} ${mono.variable}`}>
      <body>{children}</body>
    </html>
  );
}
