"use client";

import { AlertCircle } from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { getErrorDisplay } from "@/shared/api/error/get-error-display";

type AppErrorStateProps = {
  error?: unknown;
  title?: string;
  description?: string;
  retryLabel?: string;
  onRetry?: () => void;
  className?: string;
};

export function AppErrorState({
  error,
  title,
  description,
  retryLabel = "Try again",
  onRetry,
  className,
}: AppErrorStateProps) {
  const display = getErrorDisplay(error, {
    title: title ?? "Something went wrong",
    description: description ?? "Please try again in a moment.",
  });

  return (
    <div
      className={cn(
        "flex min-h-[320px] items-center justify-center p-4 md:p-6",
        className,
      )}
    >
      <Card className="w-full max-w-xl">
        <CardHeader>
          <CardTitle>{title ?? display.title}</CardTitle>
          <CardDescription>{description ?? display.description}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <Alert variant="destructive">
            <AlertCircle className="size-4" />
            <AlertTitle>Request failed</AlertTitle>
            <AlertDescription>
              {error instanceof Error ? error.message : display.description}
            </AlertDescription>
          </Alert>
          {onRetry ? (
            <div className="flex justify-start">
              <Button onClick={onRetry}>{retryLabel}</Button>
            </div>
          ) : null}
        </CardContent>
      </Card>
    </div>
  );
}
