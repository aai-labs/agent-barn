// Links and names for setting up SharePoint on an agent's Microsoft Teams app.
//
// SharePoint signs in on the Teams app as a public client, so the customer changes three
// things on that app registration: a redirect URI under "Mobile and desktop applications",
// "Allow public client flows", and the delegated Graph permission (plus administrator
// approval where the organization requires it). Every link opens the exact page.

const ENTRA_APP_BLADE = "https://entra.microsoft.com/#view/Microsoft_AAD_RegisteredApps/ApplicationMenuBlade/~";

export function entraAppLinks(appId: string) {
  const id = encodeURIComponent(appId);
  return {
    overview: `${ENTRA_APP_BLADE}/Overview/appId/${id}`,
    authentication: `${ENTRA_APP_BLADE}/Authentication/appId/${id}`,
    apiPermissions: `${ENTRA_APP_BLADE}/CallAnAPI/appId/${id}`,
  };
}

export const MICROSOFT_GUIDES = {
  redirectUri: "https://learn.microsoft.com/en-us/entra/identity-platform/how-to-add-redirect-uri",
  publicClientFlows:
    "https://learn.microsoft.com/en-us/entra/identity-platform/scenario-desktop-app-configuration#enable-public-client-flow",
  graphPermission:
    "https://learn.microsoft.com/en-us/entra/identity-platform/quickstart-configure-app-access-web-apis#delegated-permission-to-microsoft-graph",
  adminConsent: "https://learn.microsoft.com/en-us/entra/identity/enterprise-apps/grant-admin-consent",
} as const;

export function sharepointPermission(readOnly: boolean): string {
  return readOnly ? "Sites.Read.All" : "Sites.ReadWrite.All";
}
