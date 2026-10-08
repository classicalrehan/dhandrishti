import Link from "next/link";
import { Card } from "@/components/ui/card";

export default function NotFound() {
  return (
    <Card className="mx-auto mt-10 max-w-md p-8 text-center">
      <h1 className="text-lg font-semibold">Page not found</h1>
      <p className="mt-1 text-sm text-muted">This page does not exist or is planned for a later release.</p>
      <Link href="/" className="mt-4 inline-block text-sm text-brand hover:underline">
        Back to dashboard
      </Link>
    </Card>
  );
}
