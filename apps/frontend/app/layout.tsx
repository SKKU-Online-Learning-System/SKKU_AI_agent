import type { Metadata } from "next";
import Script from "next/script";
import { AuthProvider } from "./components/auth/auth-provider";
import "./globals.css";
import "./shell.css";
import "./pages.css";
import "./statistics.css";
import "./course-agent.css";
import "./study.css";

export const metadata: Metadata = {
  title: "SKKU Course Agent",
  description: "Course-specific RAG assistant MVP"
};

export default function RootLayout({
  children
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="ko">
      <body>
        <link
          href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/pretendardvariable-dynamic-subset.min.css"
          rel="stylesheet"
        />
        <Script id="mathjax-config" strategy="beforeInteractive">
          {`window.MathJax = { tex: { inlineMath: [["$","$"]], displayMath: [["$$","$$"]] } };`}
        </Script>
        <Script
          src="https://cdn.jsdelivr.net/npm/mathjax@3.2.2/es5/tex-chtml.js"
          strategy="afterInteractive"
        />
        <AuthProvider>{children}</AuthProvider>
      </body>
    </html>
  );
}
