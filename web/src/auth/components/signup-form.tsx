"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import { toast } from "sonner";

import { cn } from "@/lib/utils";
import { useAuthActions } from "@/auth/hooks/use-auth-actions";
import { SignupFormData, SignupFormSchema } from "@/auth/schemas";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Field,
  FieldDescription,
  FieldError,
  FieldGroup,
  FieldLabel,
} from "@/components/ui/field";
import { Input } from "@/components/ui/input";

export function SignupForm({
  className,
  ...props
}: React.ComponentProps<"div">) {
  const router = useRouter();
  const { signup, isSigningUp } = useAuthActions();
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<SignupFormData>({
    resolver: zodResolver(SignupFormSchema),
    defaultValues: {
      fullName: "",
      email: "",
      password: "",
      confirmPassword: "",
    },
  });

  const onSubmit = (values: SignupFormData) => {
    signup({
      email: values.email,
      fullName: values.fullName,
      password: values.password,
      onSuccess: () => {
        toast.success("Account created successfully.");
        router.push("/dashboard");
      },
      onError: (error) => {
        toast.error(error.message || "Unable to sign up.");
      },
    });
  };

  return (
    <div className={cn("flex flex-col gap-6", className)} {...props}>
      <Card>
        <CardHeader className="text-center">
          <CardTitle className="text-xl">Create your account</CardTitle>
          <CardDescription>Enter your details to get started.</CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit(onSubmit)}>
            <FieldGroup>
              <Field data-invalid={!!errors.fullName}>
                <FieldLabel htmlFor="name">Full Name</FieldLabel>
                <Input
                  id="name"
                  type="text"
                  placeholder="John Doe"
                  aria-invalid={!!errors.fullName}
                  {...register("fullName")}
                />
                <FieldError errors={[errors.fullName]} />
              </Field>
              <Field data-invalid={!!errors.email}>
                <FieldLabel htmlFor="email">Email</FieldLabel>
                <Input
                  id="email"
                  type="email"
                  placeholder="m@example.com"
                  aria-invalid={!!errors.email}
                  {...register("email")}
                />
                <FieldError errors={[errors.email]} />
              </Field>
              <Field
                data-invalid={!!errors.password || !!errors.confirmPassword}
              >
                <Field data-invalid={!!errors.password}>
                  <FieldLabel htmlFor="password">Password</FieldLabel>
                  <Input
                    id="password"
                    type="password"
                    aria-invalid={!!errors.password}
                    {...register("password")}
                  />
                  <FieldError errors={[errors.password]} />
                </Field>
                <Field data-invalid={!!errors.confirmPassword}>
                  <FieldLabel htmlFor="confirm-password">
                    Confirm Password
                  </FieldLabel>
                  <Input
                    id="confirm-password"
                    type="password"
                    aria-invalid={!!errors.confirmPassword}
                    {...register("confirmPassword")}
                  />
                  <FieldError errors={[errors.confirmPassword]} />
                </Field>
                <FieldDescription>
                  Must be at least 8 characters long.
                </FieldDescription>
              </Field>
              <Field>
                <Button type="submit" disabled={isSigningUp}>
                  {isSigningUp ? "Creating account..." : "Create Account"}
                </Button>
                <FieldDescription className="text-center">
                  Already have an account? <Link href="/login">Sign in</Link>
                </FieldDescription>
              </Field>
            </FieldGroup>
          </form>
        </CardContent>
      </Card>
      <FieldDescription className="px-6 text-center">
        By clicking continue, you agree to our{" "}
        <Link href="#">Terms of Service</Link> and{" "}
        <Link href="#">Privacy Policy</Link>.
      </FieldDescription>
    </div>
  );
}
