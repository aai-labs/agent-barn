import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

function LoadingCard() {
  return (
    <Card className="animate-pulse">
      <CardHeader>
        <Skeleton className="h-5 w-40" />
        <Skeleton className="h-4 w-56" />
      </CardHeader>
      <CardContent className="space-y-3">
        <Skeleton className="h-4 w-full" />
        <Skeleton className="h-4 w-5/6" />
      </CardContent>
    </Card>
  );
}

export function DashboardRouteLoading({
  title = "Loading dashboard",
  description = "Preparing your workspace.",
}: {
  title?: string;
  description?: string;
}) {
  return (
    <div className="space-y-6 p-4 pt-2 md:p-6 md:pt-2">
      <div className="space-y-2">
        <Skeleton className="h-7 w-52" />
        <Skeleton className="h-4 w-80 max-w-full" />
      </div>

      <div className="sr-only" aria-live="polite">
        {title}. {description}
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <LoadingCard />
        <LoadingCard />
      </div>
    </div>
  );
}
