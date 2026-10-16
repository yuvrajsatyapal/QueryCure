import { DemoDetailView } from "@/components/demo/DemoDetailView";

// Reads the slug and the API in the browser, like the app pages; see app/layout.tsx.
export const instant = false;

export default async function DemoDetailPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  return <DemoDetailView slug={slug} />;
}
