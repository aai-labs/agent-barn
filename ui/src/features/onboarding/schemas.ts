import { z } from "zod";

export const OnboardingSchema = z.object({
  required: z.boolean(),
  completedAt: z.string().nullable().optional(),
  organizationId: z.string().uuid().nullable().optional(),
  creditUsd: z.number().nullable().optional(),
  agentId: z.string().uuid().nullable().optional(),
  agentName: z.string().nullable().optional(),
  agentStatus: z.string().nullable().optional(),
  connectionId: z.string().uuid().nullable().optional(),
  telegramBotUsername: z.string().nullable().optional(),
});

export const TrialSettingsSchema = z.object({
  creditUsd: z.number(),
  agentLimit: z.number().int(),
  // Null: no cap on how many trials may be active at once.
  maxActiveTrials: z.number().int().nullable().optional(),
  activeTrials: z.number().int().optional(),
  updatedAt: z.string().nullable().optional(),
});

export type Onboarding = z.infer<typeof OnboardingSchema>;
export type TrialSettings = z.infer<typeof TrialSettingsSchema>;

// Why a Google sign-in came back without a session. The API sends one of these as
// `?error=` on the page the sign-in started from.
export const SIGN_IN_ERRORS: Record<string, string> = {
  cancelled: "Google sign-in was cancelled. Nothing was created. Try again.",
  failed: "Google sign-in didn't work. Nothing was created. Try again.",
  unavailable: "Google sign-in isn't available right now. Try again in a few minutes.",
  unverified: "Google hasn't verified the email address on that account. Verify it with Google, then try again.",
  signup_closed: "Sign-up is closed right now. If you already have an account, sign in with it.",
  trial_used: "This email has already had a free trial.",
  trials_full: "We've reached our limit of free trials for now. Try again later.",
};
