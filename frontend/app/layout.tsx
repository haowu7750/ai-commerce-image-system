import type { Metadata } from "next";
import type { ReactNode } from "react";

import "@/app/globals.css";
import { SessionProvider } from "@/lib/session";

export const metadata: Metadata = {
  title: "商策 AI 工作台",
  description: "AI 电商运营助手系统",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="zh-CN">
      <body>
        <SessionProvider>{children}</SessionProvider>
      </body>
    </html>
  );
}
