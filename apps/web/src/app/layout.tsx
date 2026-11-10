import type { Metadata } from "next";
import { Plus_Jakarta_Sans } from "next/font/google";
import { THEME_SCRIPT } from "@/lib/theme";
import "./globals.css";

const text = Plus_Jakarta_Sans({ variable: "--font-jakarta", subsets: ["latin"] });

export const metadata: Metadata = {
  title: { default: "KnowBridge", template: "%s · KnowBridge" },
  description: "Handover documents where every line links to the commit, ticket or message it came from.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    // The theme script sets data-theme before React loads, so the attribute may differ from the server's.
    <html
      lang="en"
      suppressHydrationWarning
      className={`${text.variable} h-full antialiased`}
    >
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_SCRIPT }} />
      </head>
      <body className="min-h-full flex flex-col">{children}</body>
    </html>
  );
}
