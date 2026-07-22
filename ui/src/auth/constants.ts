// Routes that render without the authenticated providers (no /auth/me, no
// redirect-to-login). Invite/reset links are followed while logged out, so they must be
// public — otherwise the account gate bounces the user to /login before the form shows.
export const PUBLIC_PATHS = [
  "/login",
  "/signup",
  "/set-password",
  "/reset-password",
  "/forgot-password",
];
