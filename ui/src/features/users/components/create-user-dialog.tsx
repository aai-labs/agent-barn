"use client";

import { useState } from "react";
import { zodResolver } from "@hookform/resolvers/zod";
import { Copy, Eye, EyeOff, RefreshCw } from "lucide-react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

import { useAllOrganizations } from "@/features/organizations/hooks/use-all-organizations";

import { useCreateUser } from "../hooks/use-create-user";
import { CreateUserData, CreateUserSchema } from "../schemas";
import { generateStrongPassword } from "../utils";

interface CreateUserDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function CreateUserDialog({ open, onOpenChange }: CreateUserDialogProps) {
  const [showPassword, setShowPassword] = useState(false);
  const createUser = useCreateUser();
  const { organizations } = useAllOrganizations({ enabled: open });

  const {
    register,
    handleSubmit,
    setValue,
    reset,
    formState: { errors },
  } = useForm<CreateUserData>({
    resolver: zodResolver(CreateUserSchema),
    defaultValues: {
      email: "",
      password: "",
      fullName: "",
      organizationId: "",
      role: "MEMBER",
    },
  });

  const onSubmit = (values: CreateUserData) => {
    createUser.mutate(values, {
      onSuccess: () => {
        toast.success("User created successfully");
        reset();
        onOpenChange(false);
      },
      onError: (error) => {
        toast.error(error.message || "Failed to create user");
      },
    });
  };

  const handleGenerate = () => {
    const password = generateStrongPassword();
    setValue("password", password, { shouldValidate: true });
    setShowPassword(true);
  };

  const handleCopy = async () => {
    const field = document.querySelector<HTMLInputElement>('input[name="password"]');
    if (field?.value) {
      await navigator.clipboard.writeText(field.value);
      toast.success("Password copied to clipboard");
    }
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(v) => {
        if (!v) reset();
        onOpenChange(v);
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Create user</DialogTitle>
          <DialogDescription>
            Create an account and add it to an organization.
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit(onSubmit)} className="flex flex-col gap-4">
          <div>
            <label htmlFor="email" className="block font-medium text-[13.5px] mb-1.5" style={{ color: "var(--ink)" }}>
              Email
            </label>
            <input
              id="email"
              type="email"
              placeholder="user@example.com"
              className="af-input"
              aria-invalid={!!errors.email}
              {...register("email")}
            />
            {errors.email && (
              <p className="text-[12.5px] mt-1" style={{ color: "var(--err)" }}>
                {errors.email.message}
              </p>
            )}
          </div>

          <div>
            <label htmlFor="password" className="block font-medium text-[13.5px] mb-1.5" style={{ color: "var(--ink)" }}>
              Password
            </label>
            <div className="flex gap-1.5">
              <div className="relative flex-1">
                <input
                  id="password"
                  type={showPassword ? "text" : "password"}
                  className="af-input w-full pr-9"
                  aria-invalid={!!errors.password}
                  {...register("password")}
                />
                <button
                  type="button"
                  className="absolute right-2 top-1/2 -translate-y-1/2 p-0.5 rounded"
                  style={{ color: "var(--ink-4)" }}
                  onClick={() => setShowPassword((v) => !v)}
                  tabIndex={-1}
                >
                  {showPassword ? <EyeOff width={15} height={15} /> : <Eye width={15} height={15} />}
                </button>
              </div>
              <button
                type="button"
                className="af-btn"
                onClick={handleGenerate}
                title="Generate password"
              >
                <RefreshCw width={14} height={14} />
              </button>
              <button
                type="button"
                className="af-btn"
                onClick={() => void handleCopy()}
                title="Copy password"
              >
                <Copy width={14} height={14} />
              </button>
            </div>
            {errors.password && (
              <p className="text-[12.5px] mt-1" style={{ color: "var(--err)" }}>
                {errors.password.message}
              </p>
            )}
          </div>

          <div>
            <label htmlFor="fullName" className="block font-medium text-[13.5px] mb-1.5" style={{ color: "var(--ink)" }}>
              Full name <span className="font-normal" style={{ color: "var(--ink-4)" }}>(optional)</span>
            </label>
            <input
              id="fullName"
              type="text"
              placeholder="Jane Doe"
              className="af-input"
              {...register("fullName")}
            />
          </div>

          <div className="flex gap-3">
            <div className="flex-1 min-w-0">
              <label htmlFor="organizationId" className="block font-medium text-[13.5px] mb-1.5" style={{ color: "var(--ink)" }}>
                Organization
              </label>
              <select
                id="organizationId"
                className="af-select w-full"
                aria-invalid={!!errors.organizationId}
                {...register("organizationId")}
              >
                <option value="">Select an organization</option>
                {organizations.map((org) => (
                  <option key={org.id} value={org.id}>
                    {org.name}
                  </option>
                ))}
              </select>
              {errors.organizationId && (
                <p className="text-[12.5px] mt-1" style={{ color: "var(--err)" }}>
                  {errors.organizationId.message}
                </p>
              )}
            </div>
            <div className="w-[130px] flex-shrink-0">
              <label htmlFor="role" className="block font-medium text-[13.5px] mb-1.5" style={{ color: "var(--ink)" }}>
                Role
              </label>
              <select id="role" className="af-select w-full" {...register("role")}>
                <option value="MEMBER">Member</option>
                <option value="ADMIN">Admin</option>
              </select>
            </div>
          </div>

          <DialogFooter>
            <button
              type="button"
              className="af-btn"
              onClick={() => onOpenChange(false)}
            >
              Cancel
            </button>
            <button
              type="submit"
              className="af-btn af-btn-primary"
              disabled={createUser.isPending}
            >
              {createUser.isPending ? "Creating…" : "Create"}
            </button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
