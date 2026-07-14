import type { Metadata } from "next";
import { AuthProvider } from "./components/auth/auth-provider";
import "./globals.css";

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
        <AuthProvider>{children}</AuthProvider>
      </body>
    </html>
  );
}
