import Link from "next/link";
import { redirect } from "next/navigation";
import { auth, signOut } from "@/auth";
import { Avatar, Wordmark } from "@/components/ui";

export default async function AppLayout({ children }: LayoutProps<"/">) {
  const session = await auth();
  if (!session?.user) redirect("/signin");
  const user = session.user;

  return (
    <div className="flex-1 flex flex-col">
      <header className="border-b border-rule bg-paper">
        <div className="mx-auto max-w-6xl px-4 sm:px-6 h-14 flex items-center justify-between gap-4">
          <Link href="/projects" className="rounded-sm">
            <Wordmark />
          </Link>
          <div className="flex items-center gap-3">
            <span className="hidden sm:flex flex-col items-end leading-tight">
              <span className="text-sm">{user.name}</span>
              <span className="text-[12px] text-ink-faint">{user.email}</span>
            </span>
            <Avatar name={user.name ?? user.email ?? "?"} src={user.image} />
            <form
              action={async () => {
                "use server";
                await signOut({ redirectTo: "/signin" });
              }}
            >
              <button className="text-[13px] text-ink-muted hover:text-ink underline-offset-4 hover:underline">
                Sign out
              </button>
            </form>
          </div>
        </div>
      </header>
      <div className="flex-1">{children}</div>
    </div>
  );
}
