import Link from "next/link";

const links = [
  ["Dashboard", "/"],
  ["Sources", "/sources"],
  ["Jobs", "/jobs"],
] as const;

export function Nav() {
  return (
    <header className="topbar">
      <Link className="brand" href="/">
        <span className="brandMark">J</span>
        <span>
          <strong>JOSE</strong>
          <small>Job Opportunity Search Engine</small>
        </span>
      </Link>
      <nav aria-label="Primary navigation">
        {links.map(([label, href]) => (
          <Link href={href} key={href}>
            {label}
          </Link>
        ))}
      </nav>
    </header>
  );
}
