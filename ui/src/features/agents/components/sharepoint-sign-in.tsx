"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { useCommunicationConnections } from "@/features/communication-connections/hooks/use-communication-connections";
import { useOrganizationContext } from "@/features/organizations/providers/organization-provider";
import { useCopyToClipboard } from "@/hooks/use-copy-to-clipboard";

import {
  useAdministratorApproval,
  useSharePointAccess,
  useSharePointSetup,
  useSharePointSignIn,
  type SharePointMode,
  type SharePointSetup,
} from "../hooks/use-sharepoint-sign-in";
import { isOAuthConnected, type IntegrationDraft, type IntegrationProvider } from "../integrations";
import {
  MICROSOFT_GUIDES,
  SELECTED_SITES_PERMISSION,
  SITE_GRANT_PERMISSION,
  entraAppLinks,
  sharepointPermission,
} from "../sharepoint-setup";
import { normalizeSiteUrl } from "../sharepoint-sites";
import { CredentialErrorAlert } from "./credential-error-alert";
import { IntegrationFields } from "./integration-fields";

function MicrosoftGlyph({ size = 16 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 18 18" aria-hidden focusable="false">
      <path fill="#F25022" d="M0 0h8.5v8.5H0z" />
      <path fill="#7FBA00" d="M9.5 0H18v8.5H9.5z" />
      <path fill="#00A4EF" d="M0 9.5h8.5V18H0z" />
      <path fill="#FFB900" d="M9.5 9.5H18V18H9.5z" />
    </svg>
  );
}

function Note({ children }: { children: React.ReactNode }) {
  return (
    <p className="text-[0.75rem] leading-[1.5]" style={{ color: "var(--ink-3)" }}>
      {children}
    </p>
  );
}

function ExternalLink({ href, children }: { href: string; children: React.ReactNode }) {
  return (
    <a href={href} target="_blank" rel="noreferrer" className="text-[0.75rem] underline">
      {children}
    </a>
  );
}

function CopyButton({ value, label }: { value: string; label: string }) {
  const { isCopied, copyToClipboard } = useCopyToClipboard({ copiedDuration: 2000 });
  return (
    <button
      type="button"
      className="af-btn af-btn-sm shrink-0"
      aria-label={label}
      onClick={() => copyToClipboard(value)}
    >
      {isCopied ? "Copied" : "Copy"}
    </button>
  );
}

function Step({ n, title, children }: { n: number; title: string; children: React.ReactNode }) {
  return (
    <li className="flex gap-3 items-start">
      <span
        className="w-5 h-5 rounded-full flex-shrink-0 grid place-items-center text-[0.656rem] font-bold mt-0.5"
        style={{ background: "var(--bg-elev)", border: "1px solid var(--line)", color: "var(--ink-3)" }}
        aria-hidden
      >
        {n}
      </span>
      <div className="flex flex-col gap-1.5 min-w-0">
        <span className="font-medium text-[0.8125rem]" style={{ color: "var(--ink)" }}>
          {title}
        </span>
        {children}
      </div>
    </li>
  );
}

function Links({ children }: { children: React.ReactNode }) {
  return <div className="flex flex-wrap gap-x-3 gap-y-1">{children}</div>;
}

/**
 * The one-time setup on the agent's Teams app, as numbered steps that link straight to each
 * page in Microsoft Entra and to Microsoft's own guide for it.
 */
function TeamsAppSetupGuide({
  setup,
  readOnly,
  mode,
}: {
  setup: SharePointSetup;
  readOnly: boolean;
  mode: SharePointMode;
}) {
  const links = entraAppLinks(setup.appId);
  const selectedSites = mode === "selected_sites";
  const permission = selectedSites ? SELECTED_SITES_PERMISSION : sharepointPermission(readOnly);
  const approvalUrl = selectedSites
    ? setup.appPermissionConsentUrl
    : readOnly
      ? setup.readOnlyAdminConsentUrl
      : setup.adminConsentUrl;
  const { approve, isApproving } = useAdministratorApproval();
  const [approved, setApproved] = useState(false);
  const [approvalError, setApprovalError] = useState<string | null>(null);

  async function handleApprove() {
    setApprovalError(null);
    try {
      await approve(approvalUrl);
      setApproved(true);
    } catch (err) {
      setApprovalError(err instanceof Error ? err.message : "Approval didn't finish.");
    }
  }

  return (
    <div
      className="flex flex-col gap-3 rounded-md p-3"
      style={{ background: "var(--bg-elev)", border: "1px solid var(--line)" }}
    >
      <div className="flex flex-col gap-1">
        <span className="text-[0.844rem] font-medium" style={{ color: "var(--ink)" }}>
          Set up the agent&apos;s Microsoft Teams app (once)
        </span>
        <Note>
          Someone who can manage this app in Microsoft Entra does these steps once; they all happen on the
          app itself.
        </Note>
      </div>

      <ol aria-label="Set up the Microsoft Teams app" className="flex flex-col gap-3.5 list-none p-0 m-0">
        <Step n={1} title="Open the app">
          <Note>
            Application (client) ID <code className="break-all">{setup.appId}</code>
          </Note>
          <Links>
            <ExternalLink href={links.overview}>Open the app in Microsoft Entra</ExternalLink>
          </Links>
        </Step>

        <Step n={2} title="Add this redirect URI">
          <Note>
            Under <strong>Authentication</strong>, select <strong>Add a platform</strong> (or{" "}
            <strong>Add redirect URI</strong>) → <strong>Mobile and desktop applications</strong>, paste it as a
            custom redirect URI and select <strong>Configure</strong>. It must be under Mobile and desktop
            applications, not Web.
          </Note>
          <div className="flex items-start gap-2">
            <code
              className="flex-1 min-w-0 font-mono text-[0.75rem] leading-[1.5] rounded px-2 py-1.5 break-all"
              style={{ background: "var(--bg-soft)", border: "1px solid var(--line)", color: "var(--ink-2)" }}
            >
              {setup.redirectUri}
            </code>
            <CopyButton value={setup.redirectUri} label="Copy redirect URI" />
          </div>
          <Links>
            <ExternalLink href={links.authentication}>Open Authentication</ExternalLink>
            <ExternalLink href={MICROSOFT_GUIDES.redirectUri}>Microsoft&apos;s guide</ExternalLink>
          </Links>
        </Step>

        <Step n={3} title="Allow public client flows">
          <Note>
            On the same <strong>Authentication</strong> page, set <strong>Allow public client flows</strong> to{" "}
            <strong>Yes</strong> and select <strong>Save</strong>.
          </Note>
          <Links>
            <ExternalLink href={links.authentication}>Open Authentication</ExternalLink>
            <ExternalLink href={MICROSOFT_GUIDES.publicClientFlows}>Microsoft&apos;s guide</ExternalLink>
          </Links>
        </Step>

        <Step n={4} title={selectedSites ? "Add the SharePoint permissions" : "Add the SharePoint permission"}>
          <Note>
            Under <strong>API permissions</strong>, select <strong>Add a permission</strong> →{" "}
            <strong>Microsoft Graph</strong> →{" "}
            <strong>{selectedSites ? "Application permissions" : "Delegated permissions"}</strong>, tick{" "}
            <code>{permission}</code> and select <strong>Add permissions</strong>.
            {selectedSites && " On its own it reaches no site until an administrator grants each one below."}
          </Note>
          {selectedSites && (
            <Note>
              Then add a second one: <strong>Add a permission</strong> → <strong>Microsoft Graph</strong> →{" "}
              <strong>Delegated permissions</strong>, tick <code>{SITE_GRANT_PERMISSION}</code> and select{" "}
              <strong>Add permissions</strong>. Only the administrator&apos;s sign-in uses it, to grant the sites;
              the agent never gets it.
            </Note>
          )}
          <Links>
            <ExternalLink href={links.apiPermissions}>Open API permissions</ExternalLink>
            <ExternalLink
              href={selectedSites ? MICROSOFT_GUIDES.applicationPermission : MICROSOFT_GUIDES.graphPermission}
            >
              Microsoft&apos;s guide
            </ExternalLink>
          </Links>
        </Step>

        <Step n={5} title={selectedSites ? "Approve them for your organization" : "Approve it for your organization"}>
          <Note>
            {selectedSites
              ? "A Microsoft 365 administrator must approve both: they select "
              : "If your organization only lets administrators approve apps, a Microsoft 365 administrator selects "}
            <strong>Grant admin consent</strong> on the API permissions page, or opens this approval link. Send it
            to them, or approve here if you are one.
          </Note>
          <div className="flex flex-wrap items-center gap-2">
            <CopyButton value={approvalUrl} label="Copy approval link" />
            <button
              type="button"
              className="af-btn af-btn-sm"
              onClick={() => void handleApprove()}
              disabled={isApproving}
            >
              {isApproving ? "Waiting for Microsoft…" : "Approve as an administrator"}
            </button>
            {approved && (
              <span className="text-[0.75rem] font-medium" style={{ color: "var(--ok, #2f855a)" }}>
                ✓ Approved for your organization
              </span>
            )}
          </div>
          {approvalError && <CredentialErrorAlert title="Approval didn't finish" message={approvalError} />}
          <Links>
            <ExternalLink href={links.apiPermissions}>Open API permissions</ExternalLink>
            <ExternalLink href={MICROSOFT_GUIDES.adminConsent}>Microsoft&apos;s guide</ExternalLink>
          </Links>
        </Step>

        {selectedSites && (
          <Step n={6} title="Keep the app limited">
            <Note>
              The agent can use the app&apos;s own permissions, so give the app only these permissions and
              nothing else. Block device code sign-in for the app with a Conditional Access policy, so the
              agent can&apos;t get an administrator&apos;s access by asking someone to sign in on its behalf.
            </Note>
            <Links>
              <ExternalLink href={MICROSOFT_GUIDES.blockDeviceCode}>Microsoft&apos;s guide</ExternalLink>
            </Links>
          </Step>
        )}
      </ol>
    </div>
  );
}

/**
 * The sites an administrator's next sign-in leaves the agent with. Sites not yet granted, and
 * granted ones taken off the list, are marked until that sign-in happens.
 */
function SiteList({
  sites,
  granted,
  onChange,
  disabled,
}: {
  sites: string[];
  granted: string[];
  onChange: (sites: string[]) => void;
  disabled?: boolean;
}) {
  const [input, setInput] = useState("");
  const [inputError, setInputError] = useState<string | null>(null);
  const removed = granted.filter((site) => !sites.includes(site));

  function add() {
    const site = normalizeSiteUrl(input);
    if (!site) {
      setInputError("That isn't a SharePoint site address. It looks like https://contoso.sharepoint.com/sites/team.");
      return;
    }
    setInputError(null);
    setInput("");
    if (!sites.includes(site)) onChange([...sites, site]);
  }

  return (
    <div className="flex flex-col gap-2">
      <span className="text-[0.8125rem] font-medium" style={{ color: "var(--ink)" }}>
        Sites
      </span>
      {(sites.length > 0 || removed.length > 0) && (
        <ul aria-label="SharePoint sites" className="flex flex-col gap-1.5 list-none p-0 m-0">
          {sites.map((site) => (
            <li key={site} className="flex items-center gap-2 min-w-0">
              <span className="text-[0.75rem] break-all" style={{ color: "var(--ink-1)" }}>
                {site}
              </span>
              {!granted.includes(site) && (
                <span className="text-[0.6875rem] shrink-0" style={{ color: "var(--ink-4)" }}>
                  Not granted yet
                </span>
              )}
              <button
                type="button"
                className="af-btn af-btn-sm shrink-0 ml-auto"
                aria-label={`Remove ${site}`}
                onClick={() => onChange(sites.filter((s) => s !== site))}
                disabled={disabled}
              >
                Remove
              </button>
            </li>
          ))}
          {removed.map((site) => (
            <li key={site} className="flex items-center gap-2 min-w-0">
              <span className="text-[0.75rem] break-all line-through" style={{ color: "var(--ink-4)" }}>
                {site}
              </span>
              <span className="text-[0.6875rem] shrink-0" style={{ color: "var(--ink-4)" }}>
                Access ends at the next administrator sign-in
              </span>
              <button
                type="button"
                className="af-btn af-btn-sm shrink-0 ml-auto"
                aria-label={`Keep ${site}`}
                onClick={() => onChange([...sites, site])}
                disabled={disabled}
              >
                Keep
              </button>
            </li>
          ))}
        </ul>
      )}
      <div className="flex items-start gap-2">
        <input
          className="af-input flex-1 min-w-0"
          aria-label="SharePoint site address"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              add();
            }
          }}
          placeholder="https://contoso.sharepoint.com/sites/finance"
          autoComplete="off"
          disabled={disabled}
        />
        <button type="button" className="af-btn af-btn-sm shrink-0" onClick={add} disabled={disabled || !input.trim()}>
          Add site
        </button>
      </div>
      {inputError && (
        <span role="alert" className="text-[0.75rem]" style={{ color: "var(--danger, #c53030)" }}>
          {inputError}
        </span>
      )}
      <Note>Paste any address inside a site; it&apos;s reduced to the site itself.</Note>
    </div>
  );
}

/**
 * Connects SharePoint by signing in with Microsoft on the agent's Microsoft Teams app. The
 * sign-in saves the credential itself, so on success the draft is only marked as signed in;
 * nothing from here is submitted with the rest of the form.
 */
export function SharePointSignIn({
  agentId,
  provider,
  draft,
  onFieldChange,
  onSignedIn,
  disabled,
}: {
  agentId: string;
  provider: IntegrationProvider;
  draft: IntegrationDraft;
  onFieldChange: (key: string, value: string) => void;
  onSignedIn: (patch: Record<string, string>) => void;
  disabled?: boolean;
}) {
  const { selectedOrganization } = useOrganizationContext();
  const connections = useCommunicationConnections(agentId);
  const { signIn, isSigningIn } = useSharePointSignIn(agentId);
  const access = useSharePointAccess(agentId);
  const [error, setError] = useState<string | null>(null);
  // Unset until the person picks one: the agent's current mode, or only chosen sites by default.
  const [chosenMode, setChosenMode] = useState<SharePointMode | null>(null);
  // Sites granted so far, as last confirmed by Microsoft through a sign-in.
  const [grantedOverride, setGrantedOverride] = useState<{ email: string; sites: string[] } | null>(null);
  // The sites the next administrator sign-in should leave the agent with; unset means "as granted".
  const [chosenSites, setChosenSites] = useState<string[] | null>(null);

  const channelsHref = `/dashboard/${selectedOrganization?.id ?? ""}/agents/${agentId}/configuration?section=channels`;
  const teamsApps = (connections.data ?? []).filter((c) => c.platformKey === "teams");
  // An agent has at most one active connection per platform.
  const teamsApp = teamsApps.find((c) => c.enabled);
  const setup = useSharePointSetup(agentId, teamsApp?.id);
  const readOnly = draft.content.readOnly;
  const hasAccessLevel = readOnly === "true" || readOnly === "false";
  const signedIn = isOAuthConnected(draft);
  const email = typeof draft.content.email === "string" ? draft.content.email : "";
  const current = access.data ?? null;
  const mode: SharePointMode = chosenMode ?? current?.mode ?? "selected_sites";
  const selectedSites = mode === "selected_sites";
  const granted =
    grantedOverride ??
    (current?.mode === "selected_sites" ? { email: current.email, sites: current.sites } : { email: "", sites: [] });
  const wantedSites = chosenSites ?? granted.sites;
  // Granted sites stay on the Teams app until an administrator removes them, so the agent keeps
  // track of them until then: no switching to a person's sign-in, and no removing SharePoint.
  const holdsSites = granted.sites.length > 0;
  const accessReadOnly = current ? (current.readOnly ? "true" : "false") : undefined;

  // Start from the agent's current access level, so a grant can be changed without re-picking it.
  useEffect(() => {
    if (!hasAccessLevel && accessReadOnly) onFieldChange("readOnly", accessReadOnly);
  }, [hasAccessLevel, accessReadOnly, onFieldChange]);

  if (connections.isPending) {
    return <Note>Checking the agent&apos;s Microsoft Teams connection…</Note>;
  }

  if (!teamsApp) {
    return (
      <div className="flex flex-col gap-1.5">
        <span className="text-[0.8125rem] font-medium" style={{ color: "var(--ink)" }}>
          {teamsApps.length === 0
            ? "Connect this agent to Microsoft Teams first"
            : "Turn on this agent's Microsoft Teams connection first"}
        </span>
        <Note>SharePoint signs in through the agent&apos;s Microsoft Teams app.</Note>
        <Link href={channelsHref} className="text-[0.75rem] underline self-start">
          {teamsApps.length === 0 ? "Add a Microsoft Teams connection" : "Open messaging connections"}
        </Link>
      </div>
    );
  }

  const connectionId = teamsApp.id;

  async function handleSignIn() {
    setError(null);
    try {
      const result = await signIn({
        connectionId,
        readOnly: readOnly === "true",
        mode,
        sites: selectedSites ? wantedSites : [],
      });
      if (!result) return;
      if (result.mode === "selected_sites") {
        setGrantedOverride({ email: result.email, sites: result.sites });
        setChosenSites(null);
      }
      onSignedIn({
        signedIn: "true",
        email: result.email,
        readOnly: result.readOnly ? "true" : "false",
        connectionId,
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sign-in failed.");
    }
  }

  async function handleRemoveAll() {
    setError(null);
    try {
      await signIn({ connectionId, readOnly: readOnly === "true", removeAll: true });
      setGrantedOverride({ email: "", sites: [] });
      setChosenSites(null);
      onSignedIn({ signedIn: "", email: "" });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sign-in failed.");
    }
  }

  const signInLabel = selectedSites
    ? "Sign in as an administrator to grant sites"
    : signedIn
      ? "Sign in again"
      : "Sign in with Microsoft";
  const canSignIn = hasAccessLevel && (!selectedSites || wantedSites.length > 0);
  const showGuide = selectedSites ? granted.sites.length === 0 : !signedIn;

  return (
    <div className="flex flex-col gap-3.5">
      <fieldset className="flex flex-col gap-2 border-0 p-0 m-0">
        <legend className="text-[0.8125rem] font-medium mb-1" style={{ color: "var(--ink)" }}>
          What the agent can reach
        </legend>
        {(
          [
            ["selected_sites", "Only sites you choose"],
            ["delegated", "Everything the person signing in can open"],
          ] as const
        ).map(([value, label]) => (
          <label key={value} className="flex items-center gap-2 cursor-pointer">
            <input
              type="radio"
              name={`sharepoint-${agentId}-mode`}
              value={value}
              checked={mode === value}
              onChange={() => setChosenMode(value)}
              disabled={disabled || isSigningIn || (value === "delegated" && holdsSites)}
              className="accent-[var(--blue-9)]"
            />
            <span className="text-[13px]" style={{ color: "var(--ink-1)" }}>
              {label}
            </span>
          </label>
        ))}
        {selectedSites && (
          <Note>
            A Microsoft 365 administrator signs in to grant the agent each site below, and again whenever the
            list changes. Editing Excel workbooks in place isn&apos;t available this way; the agent can still
            download and upload them.
          </Note>
        )}
        {holdsSites && (
          <Note>
            To switch to a person&apos;s sign-in or remove SharePoint, remove all sites first, so none stay
            granted to the agent&apos;s Microsoft Teams app.
          </Note>
        )}
      </fieldset>

      {showGuide && setup.data && (
        <TeamsAppSetupGuide setup={setup.data} readOnly={readOnly === "true"} mode={mode} />
      )}
      {showGuide && setup.error && (
        <CredentialErrorAlert
          title="Couldn't load the Teams app details"
          message={setup.error instanceof Error ? setup.error.message : "Please try again."}
        />
      )}

      <IntegrationFields
        provider={provider}
        draft={draft}
        namePrefix={`sharepoint-${agentId}-`}
        onFieldChange={onFieldChange}
        onListChange={() => undefined}
        disabled={disabled || isSigningIn}
      />

      {selectedSites && (
        <SiteList
          sites={wantedSites}
          granted={granted.sites}
          onChange={setChosenSites}
          disabled={disabled || isSigningIn}
        />
      )}

      <Note>
        Signing in saves SharePoint access for this agent straight away, even if you don&apos;t apply
        your other changes. It takes effect when the agent restarts, which Apply does for you. To take
        it away later,{" "}
        {selectedSites ? "remove all sites." : <>remove SharePoint from the agent&apos;s Integrations.</>}
      </Note>

      <button
        type="button"
        className="af-btn af-btn-sm flex items-center gap-2 self-start"
        onClick={() => void handleSignIn()}
        disabled={disabled || isSigningIn || !canSignIn}
      >
        <MicrosoftGlyph size={15} />
        {isSigningIn ? "Waiting for Microsoft…" : signInLabel}
      </button>
      {selectedSites && holdsSites && (
        <button
          type="button"
          className="af-btn af-btn-sm af-btn-ghost self-start"
          onClick={() => void handleRemoveAll()}
          disabled={disabled || isSigningIn}
        >
          Remove all sites
        </button>
      )}
      {selectedSites && granted.email && !isSigningIn && (
        <span className="text-[0.75rem] font-medium" style={{ color: "var(--ok, #2f855a)" }}>
          ✓ Sites granted by {granted.email}
        </span>
      )}
      {!selectedSites && signedIn && !isSigningIn && (
        <span className="text-[0.75rem] font-medium" style={{ color: "var(--ok, #2f855a)" }}>
          ✓ {email ? `Signed in as ${email}` : "Signed in"}
        </span>
      )}
      {!hasAccessLevel && !isSigningIn && (
        <span className="text-[0.75rem]" style={{ color: "var(--ink-4)" }}>
          Choose an access level before signing in.
        </span>
      )}
      {error && <CredentialErrorAlert title="Microsoft sign-in failed" message={error} />}
    </div>
  );
}
