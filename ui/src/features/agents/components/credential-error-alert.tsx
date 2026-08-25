import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { AlertCircleIcon } from "@/components/icons";

export function CredentialErrorAlert({
  message,
  title = "Credential validation failed",
}: {
  message: string;
  title?: string;
}) {
  return (
    <Alert
      variant="destructive"
      className="px-3 py-2.5"
      style={{
        background: "var(--err-soft)",
        borderColor: "color-mix(in srgb, var(--err) 30%, transparent)",
        color: "var(--err)",
      }}
    >
      <AlertCircleIcon
        size={15}
        style={{ color: "var(--err)", marginTop: 1 }}
      />
      <AlertTitle
        className="text-[0.8125rem]"
        style={{ color: "var(--err)" }}
      >
        {title}
      </AlertTitle>
      <AlertDescription
        className="text-[0.75rem] leading-[1.4]"
        style={{ color: "var(--err)" }}
      >
        {message}
      </AlertDescription>
    </Alert>
  );
}
