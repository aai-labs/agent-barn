import * as z from "zod";
import { OrganizationSchema } from "@/features/organizations/schemas";

export const strongPasswordSchema = z
  .string()
  .min(8, { message: "Password must be at least 8 characters" })
  .regex(/[A-Z]/, {
    message: "Password must include at least one uppercase letter",
  })
  .regex(/[a-z]/, {
    message: "Password must include at least one lowercase letter",
  })
  .regex(/[0-9]/, {
    message: "Password must include at least one number",
  });

export const TokenSchema = z.object({
  accessToken: z.string().min(1, { message: "Access token is required" }),
  refreshToken: z.string().optional(),
  tokenType: z.string().min(1, { message: "Token type is required" }),
});

export const LoginSchema = z.object({
  email: z.string().email({ message: "Invalid email address" }),
  password: z.string().min(1, { message: "Password is required" }),
});

export const SignupSchema = z.object({
  email: z.string().email({ message: "Invalid email address" }),
  fullName: z.string().min(1, { message: "Name is required" }),
  password: strongPasswordSchema,
});

export const SignupFormSchema = SignupSchema.extend({
  confirmPassword: z.string().min(1, { message: "Confirm your password" }),
}).refine((data) => data.password === data.confirmPassword, {
  message: "Passwords do not match",
  path: ["confirmPassword"],
});

export const OrganizationUserReadSchema = z.object({
  id: z.string().uuid(),
  createdAt: z.string(),
  updatedAt: z.string(),
  userId: z.string().uuid(),
  organizationId: z.string().uuid(),
  role: z.enum(["ADMIN", "MEMBER", "OWNER"]),
  organization: OrganizationSchema,
});

export const CurrentUserSchema = z.object({
  id: z.string().uuid(),
  email: z.string().email(),
  fullName: z.string().nullable(),
  isSuperuser: z.boolean(),
  emailVerifiedAt: z.string().nullable().optional(),
  organizationUsers: z.array(OrganizationUserReadSchema).nullable().optional(),
});

export const CurrentUserContextSchema = CurrentUserSchema;

export type Token = z.infer<typeof TokenSchema>;
export type Signup = z.infer<typeof SignupSchema>;
export type LoginFormData = z.infer<typeof LoginSchema>;
export type SignupFormData = z.infer<typeof SignupFormSchema>;
export type CurrentUserContext = z.infer<typeof CurrentUserContextSchema>;
