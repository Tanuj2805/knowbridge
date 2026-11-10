import { redirect } from "next/navigation";
import { auth } from "@/auth";
import { TopNav } from "@/components/top-nav";

/** Every page in here needs a signed-in person, and shares the bar across the top. */
export default async function AppLayout({ children }: LayoutProps<"/">) {
  const session = await auth();
  if (!session?.user) redirect("/signin");
  const { name, email, image } = session.user;

  return (
    <div className="flex flex-1 flex-col">
      <TopNav me={{ name: name ?? email ?? "", email: email ?? "", image }} />
      <div className="flex flex-1 flex-col">{children}</div>
      <footer className="border-t border-rule py-5 print:hidden">
        <p className="mx-auto max-w-[80rem] px-4 text-[12px] text-ink-faint sm:px-6">
          KnowBridge · every claim linked to its source, nothing shared without a person&apos;s approval.
        </p>
      </footer>
    </div>
  );
}
