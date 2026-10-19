"use client";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { CustomApiConnection } from "../schemas";
type EditableHeader = Omit<CustomApiConnection["headers"][number], "value"> & {
  value: string;
};
export function ConnectionHeaders({
  prefix,
  headers,
  savedHeaders,
  setHeaders,
}: {
  prefix: string;
  headers: EditableHeader[];
  savedHeaders?: CustomApiConnection["headers"];
  setHeaders: (headers: EditableHeader[]) => void;
}) {
  return (
    <div className="space-y-3">
      <p className="text-sm font-medium">Additional headers</p>
      {headers.map((header, index) => (
        <div key={index} className="flex flex-wrap items-end gap-2">
          <div className="min-w-40 flex-1">
            <Label htmlFor={`${prefix}-header-name-${index}`}>
              Header name
            </Label>
            <Input
              id={`${prefix}-header-name-${index}`}
              required
              maxLength={128}
              value={header.name}
              onChange={(e) =>
                setHeaders(
                  headers.map((h, i) =>
                    i === index ? { ...h, name: e.target.value } : h,
                  ),
                )
              }
            />
          </div>
          <div className="min-w-40 flex-1">
            <Label htmlFor={`${prefix}-header-value-${index}`}>
              Header value
            </Label>
            <Input
              id={`${prefix}-header-value-${index}`}
              type={header.secret ? "password" : "text"}
              autoComplete="off"
              maxLength={8192}
              required={
                header.secret &&
                !savedHeaders?.some(
                  (saved) =>
                    saved.secret &&
                    saved.name.toLowerCase() === header.name.toLowerCase(),
                )
              }
              value={header.value}
              placeholder={
                header.secret &&
                savedHeaders?.some(
                  (saved) =>
                    saved.secret &&
                    saved.name.toLowerCase() === header.name.toLowerCase(),
                )
                  ? "Blank keeps saved secret"
                  : ""
              }
              onChange={(e) =>
                setHeaders(
                  headers.map((h, i) =>
                    i === index ? { ...h, value: e.target.value } : h,
                  ),
                )
              }
            />
          </div>
          <div className="flex items-center gap-2">
            <Checkbox
              id={`${prefix}-header-secret-${index}`}
              checked={header.secret}
              onCheckedChange={(checked) =>
                setHeaders(
                  headers.map((h, i) =>
                    i === index ? { ...h, secret: checked === true } : h,
                  ),
                )
              }
            />
            <Label htmlFor={`${prefix}-header-secret-${index}`}>Secret</Label>
          </div>
          <Button
            type="button"
            variant="ghost"
            aria-label={`Remove header ${index + 1}`}
            onClick={() => setHeaders(headers.filter((_, i) => i !== index))}
          >
            Remove
          </Button>
        </div>
      ))}
      <Button
        type="button"
        variant="outline"
        disabled={headers.length >= 32}
        onClick={() =>
          setHeaders([...headers, { name: "", value: "", secret: false }])
        }
      >
        Add header
      </Button>
    </div>
  );
}
