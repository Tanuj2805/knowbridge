import NextAuth, { CredentialsSignin } from "next-auth";
import type { Provider } from "next-auth/providers";
import Credentials from "next-auth/providers/credentials";
import { accountsApi } from "@/lib/accounts";
import { personaById } from "@/lib/personas";

export const demoMode = process.env.DEMO_MODE === "true";
/** Sign in as any email, for trying the app as a teammate on your own machine. Never in production. */
export const devLogin = process.env.DEV_LOGIN === "true" && process.env.NODE_ENV !== "production";

/** A failed email sign-in, with why (the page shows a message for each): invalid, unverified, locked,
 * invalid_code_<tries left>, too_many, expired. */
class PasswordSignin extends CredentialsSignin {
  constructor(code: string) {
    super();
    this.code = code;
  }
}

type Account = { id: string; email: string; name: string };
const providers: Provider[] = [];

// Email and password: the API checks the password (scrypt hash) and that the email was confirmed.
providers.push(
  Credentials({
    id: "password",
    name: "Email and password",
    credentials: { email: { type: "email" }, password: { type: "password" } },
    async authorize(credentials) {
      const r = await accountsApi<Account>("/auth/login", {
        email: String(credentials?.email ?? ""),
        password: String(credentials?.password ?? ""),
      });
      if (r.ok) return { id: r.data.id, email: r.data.email, name: r.data.name };
      throw new PasswordSignin(r.code === "unreachable" ? "unreachable" : r.code || "invalid");
    },
  }),
  // The 6-digit code from the sign-up email: the API confirms the address, and that signs them in.
  Credentials({
    id: "email-code",
    name: "Email code",
    credentials: { email: { type: "email" }, code: { type: "text" } },
    async authorize(credentials) {
      const r = await accountsApi<Account>("/auth/verify", {
        email: String(credentials?.email ?? ""),
        code: String(credentials?.code ?? ""),
      });
      if (r.ok) return { id: r.data.id, email: r.data.email, name: r.data.name };
      const left = r.code === "invalid_code" ? /(\d+) tr/.exec(r.message)?.[1] : undefined;
      throw new PasswordSignin(left ? `invalid_code_${left}` : r.code || "invalid_code");
    },
  }),
);
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

if (devLogin) {
  providers.push(
    Credentials({
      id: "dev",
      name: "Local test sign-in",
      credentials: { email: { type: "email" } },
      authorize(credentials) {
        const email = String(credentials?.email ?? "").trim().toLowerCase();
        if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) return null;
        return { id: email, name: email.split("@")[0], email };
      },
    }),
  );
}

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
