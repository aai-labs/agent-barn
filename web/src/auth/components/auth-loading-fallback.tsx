export function AuthLoadingFallback({ message }: { message: string }) {
  return (
    <div className="flex min-h-svh items-center justify-center p-6 text-sm text-muted-foreground">
      {message}
    </div>
  );
}

