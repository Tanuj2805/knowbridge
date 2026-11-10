/** Re-mounts on every move between a project's pages, so each page rises in gently. */
export default function ProjectPageTemplate({ children }: { children: React.ReactNode }) {
  return <div className="animate-rise">{children}</div>;
}
