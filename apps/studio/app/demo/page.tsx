import { Suspense } from "react";
import { GuidedDemo } from "@/components/guided-demo";
export default function Page() {
  return (
    <Suspense
      fallback={
        <div className="page-content loading-state">
          Opening the walkthrough…
        </div>
      }
    >
      <GuidedDemo />
    </Suspense>
  );
}
