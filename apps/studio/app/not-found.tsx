import Link from "next/link";
export default function NotFound() {
  return (
    <div className="empty-state">
      <h1>Workspace not found</h1>
      <p>Return to recorded workflows to inspect a valid run.</p>
      <Link className="button primary" href="/runs">
        View workflows
      </Link>
    </div>
  );
}
