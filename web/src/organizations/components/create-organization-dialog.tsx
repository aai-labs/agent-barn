"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Field,
  FieldDescription,
  FieldError,
  FieldGroup,
  FieldLabel,
} from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { useOrganizationActions } from "@/organizations/hooks/use-organization-actions";
import {
  OrganizationCreate,
  OrganizationCreateSchema,
} from "@/organizations/schemas";

export function CreateOrganizationDialog({
  open,
  onOpenChange,
  onCreated,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreated: (organizationId: string) => void;
}) {
  const { createOrganization, isCreatingOrganization } =
    useOrganizationActions();

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<OrganizationCreate>({
    resolver: zodResolver(OrganizationCreateSchema),
    defaultValues: {
      name: "",
      description: "",
    },
  });

  const onCreateOrganization = (values: OrganizationCreate) => {
    createOrganization(values, {
      onSuccess: (organization) => {
        toast.success("Organization created successfully.");
        onCreated(organization.id);
        onOpenChange(false);
        reset();
      },
      onError: (error) => {
        toast.error(error.message || "Unable to create organization.");
      },
    });
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Create organization</DialogTitle>
          <DialogDescription>
            Add a new organization to your account.
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={handleSubmit(onCreateOrganization)}>
          <FieldGroup>
            <Field data-invalid={!!errors.name}>
              <FieldLabel htmlFor="organization-name">Name</FieldLabel>
              <Input
                id="organization-name"
                placeholder="Acme Inc"
                aria-invalid={!!errors.name}
                {...register("name")}
              />
              <FieldError errors={[errors.name]} />
            </Field>
            <Field data-invalid={!!errors.description}>
              <FieldLabel htmlFor="organization-description">
                Description
              </FieldLabel>
              <Input
                id="organization-description"
                placeholder="Optional description"
                aria-invalid={!!errors.description}
                {...register("description")}
              />
              <FieldDescription>
                This can be updated later from organization settings.
              </FieldDescription>
              <FieldError errors={[errors.description]} />
            </Field>
            <Field>
              <Button type="submit" disabled={isCreatingOrganization}>
                {isCreatingOrganization ? "Creating..." : "Create"}
              </Button>
            </Field>
          </FieldGroup>
        </form>
      </DialogContent>
    </Dialog>
  );
}
