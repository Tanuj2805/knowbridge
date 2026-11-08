import NextAuth from "next-auth";
import type { Provider } from "next-auth/providers";
import Credentials from "next-auth/providers/credentials";
import GitHub from "next-auth/providers/github";
import Google from "next-auth/providers/google";
import { personaById } from "@/lib/personas";

export const demoMode = process.env.DEMO_MODE === "true";

const providers: Provider[] = [];
if (process.env.AUTH_GITHUB_ID) providers.push(GitHub);
if (process.env.AUTH_GOOGLE_ID) providers.push(Google);
if (demoMode) {
  providers.push(
    Credentials({
      id: "demo",
      name: "Demo persona",
      credentials: { persona: { type: "text" } },
      authorize(credentials) {
        const persona = personaById(String(credentials?.persona ?? ""));
        if (!persona) return null;
        return { id: persona.id, name: persona.name, email: persona.email };
      },
    }),
  );
}

export const oauthProviders = providers
  .map((p) => (typeof p === "function" ? p() : p))
  .filter((p) => p.type === "oauth" || p.type === "oidc")
  .map((p) => ({ id: p.id, name: p.name }));

export const { handlers, auth, signIn, signOut } = NextAuth({
  providers,
  session: { strategy: "jwt", maxAge: 60 * 60 * 12 },
  pages: { signIn: "/signin" },
  callbacks: {
    jwt({ token, account }) {
      if (account) token.provider = account.provider;
      return token;
    },
    session({ session, token }) {
      session.provider = String(token.provider ?? "unknown");
      return session;
    },
  },
});

declare module "next-auth" {
  interface Session {
    provider: string;
  }
}
