"use client";

import { useRef, useState } from "react";
import { CopyIcon, KeyRoundIcon, PlusIcon, Trash2Icon } from "lucide-react";

import { ConfirmationDialog } from "@/components/confirmation-dialog";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useActiveOrgRole } from "@/features/organizations/hooks/use-active-org-role";

import { useSshCredentials } from "../hooks/use-ssh";
import type { SshCredential, SshServer } from "../schemas";

function KeyEditor({
  credential,
  canManage,
  onClose,
}: {
  credential?: SshCredential;
  canManage: boolean;
  onClose: () => void;
}) {
  const { mutation } = useSshCredentials();
  const form = useRef<HTMLFormElement>(null);
  const [source, setSource] = useState("generate");
  const [name, setName] = useState(credential?.name ?? "");
  const [mode, setMode] = useState(credential?.mode ?? "restricted");
  const [enabled, setEnabled] = useState(credential?.enabled ?? true);
  const [servers, setServers] = useState<SshServer[]>(
    credential?.servers ?? [],
  );
  const [privateKey, setPrivateKey] = useState("");
  const [passphrase, setPassphrase] = useState("");
  const [dirty, setDirty] = useState(false);
  const [discard, setDiscard] = useState(false);
  const [saved, setSaved] = useState<SshCredential | undefined>(undefined);
  const [copyStatus, setCopyStatus] = useState("");
  const view = saved ?? credential;
  const readonly = !canManage || Boolean(saved);
  const close = () => (dirty && !saved ? setDiscard(true) : onClose());
  function changeServer(index: number, value: Partial<SshServer>) {
    setDirty(true);
    setServers((current) =>
      current.map((server, i) =>
        i === index ? { ...server, ...value } : server,
      ),
    );
  }
  async function save() {
    if (!form.current?.reportValidity()) return;
    const response = await mutation.mutateAsync({
      id: credential?.id,
      data: {
        name,
        mode,
        servers,
        ...(credential
          ? { enabled, expectedRevision: credential.revision }
          : {
              source,
              ...(source === "import"
                ? { privateKey, passphrase: passphrase || undefined }
                : {}),
            }),
      },
    });
    if (response?.data) {
      setSaved(response.data as SshCredential);
      setPrivateKey("");
      setPassphrase("");
      setDirty(false);
    }
  }
  return (
    <>
      <Dialog
        open
        onOpenChange={(open) => {
          if (!open && !mutation.isPending) close();
        }}
      >
        <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-xl">
          <DialogHeader>
            <DialogTitle>
              {saved
                ? "SSH credential saved"
                : credential
                  ? credential.name
                  : "Add SSH credential"}
            </DialogTitle>
            <DialogDescription>
              Private keys stay in Agent Barn. Members who manage an Agent’s
              credentials can attach these keys.
            </DialogDescription>
          </DialogHeader>
          <form
            ref={form}
            onChange={() => setDirty(true)}
            onSubmit={(event) => {
              event.preventDefault();
              void save().catch(() => {});
            }}
            className="space-y-4"
          >
            {view && (
              <div className="rounded-xl border p-4 space-y-3">
                <p className="text-xs text-muted-foreground">
                  Install this public key in the remote account’s
                  authorized_keys.
                </p>
                <pre
                  className="whitespace-pre-wrap break-all text-xs"
                  aria-label="SSH public key"
                >
                  {view.publicKey}
                </pre>
                <p className="break-all font-mono text-xs">
                  {view.fingerprint}
                </p>
                <button
                  type="button"
                  className="af-btn af-btn-sm"
                  onClick={() => {
                    void navigator.clipboard.writeText(view.publicKey).then(
                      () => setCopyStatus("Public key copied"),
                      () =>
                        setCopyStatus(
                          "Copy failed; select the public key above",
                        ),
                    );
                  }}
                >
                  <CopyIcon size={14} /> Copy public key
                </button>
                <span role="status" className="text-xs">
                  {copyStatus}
                </span>
              </div>
            )}
            <fieldset
              disabled={readonly || mutation.isPending}
              className="space-y-4"
            >
              <label className="block text-sm">
                Name
                <input
                  className="af-input mt-1 w-full"
                  required
                  maxLength={120}
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                />
              </label>
              {!credential && !saved && (
                <>
                  <label className="block text-sm">Key setup</label>
                  <Select
                    value={source}
                    onValueChange={(value) => {
                      setSource(value);
                      setDirty(true);
                    }}
                  >
                    <SelectTrigger aria-label="Key setup">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectGroup>
                        <SelectItem value="generate">
                          Generate Ed25519 key
                        </SelectItem>
                        <SelectItem value="import">
                          Import existing private key
                        </SelectItem>
                      </SelectGroup>
                    </SelectContent>
                  </Select>
                  {source === "import" && (
                    <>
                      <label className="block text-sm">
                        Private key
                        <textarea
                          className="af-input mt-1 min-h-32 w-full font-mono text-xs"
                          required
                          maxLength={65536}
                          autoComplete="off"
                          value={privateKey}
                          onChange={(e) => setPrivateKey(e.target.value)}
                        />
                      </label>
                      <label className="block text-sm">
                        Passphrase (optional)
                        <input
                          className="af-input mt-1 w-full"
                          type="password"
                          autoComplete="new-password"
                          value={passphrase}
                          onChange={(e) => setPassphrase(e.target.value)}
                        />
                      </label>
                    </>
                  )}
                </>
              )}
              <label className="block text-sm">
                Where this key can be used
              </label>
              <Select
                value={mode}
                onValueChange={(value) => {
                  setMode(value as typeof mode);
                  setDirty(true);
                }}
              >
                <SelectTrigger aria-label="Where this key can be used">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectGroup>
                    <SelectItem value="restricted">Specific servers</SelectItem>
                    <SelectItem value="unrestricted">Unrestricted</SelectItem>
                  </SelectGroup>
                </SelectContent>
              </Select>
              <p className="text-xs text-muted-foreground">
                {mode === "restricted"
                  ? "Only the verified server keys and usernames below can authenticate. An empty list denies all use."
                  : "This key can authenticate wherever it is accepted. It can also sign other SSH-agent requests. Server profiles below are optional connection shortcuts."}
              </p>
              {credential && (
                <label className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={enabled}
                    onChange={(e) => setEnabled(e.target.checked)}
                  />{" "}
                  Enabled for signing
                </label>
              )}
              {servers.map((server, index) => (
                <div key={index} className="space-y-3 rounded-xl border p-4">
                  <div className="flex justify-between items-center">
                    <span className="text-sm font-medium">
                      Server {index + 1}
                    </span>
                    <button
                      type="button"
                      aria-label={`Remove server ${index + 1}`}
                      className="af-btn af-btn-ghost af-btn-icon"
                      onClick={() => {
                        setDirty(true);
                        setServers(servers.filter((_, i) => i !== index));
                      }}
                    >
                      <Trash2Icon size={14} />
                    </button>
                  </div>
                  <label className="block text-sm">
                    Server name
                    <input
                      required
                      pattern="[a-z0-9][a-z0-9-]*"
                      className="af-input mt-1 w-full"
                      value={server.name}
                      onChange={(e) =>
                        changeServer(index, { name: e.target.value })
                      }
                    />
                  </label>
                  <label className="block text-sm">
                    Hostname or IP address
                    <input
                      required
                      className="af-input mt-1 w-full"
                      value={server.hostname}
                      onChange={(e) =>
                        changeServer(index, { hostname: e.target.value })
                      }
                    />
                  </label>
                  <div className="grid grid-cols-2 gap-3">
                    <label className="block text-sm">
                      Username
                      <input
                        required
                        className="af-input mt-1 w-full"
                        value={server.username}
                        onChange={(e) =>
                          changeServer(index, { username: e.target.value })
                        }
                      />
                    </label>
                    <label className="block text-sm">
                      Port
                      <input
                        type="number"
                        min={1}
                        max={65535}
                        required
                        className="af-input mt-1 w-full"
                        value={server.port}
                        onChange={(e) =>
                          changeServer(index, { port: Number(e.target.value) })
                        }
                      />
                    </label>
                  </div>
                  <label className="block text-sm">
                    Verified host public keys
                    <textarea
                      required
                      className="af-input mt-1 min-h-20 w-full font-mono text-xs"
                      value={server.hostKeys.join("\n")}
                      onChange={(e) =>
                        changeServer(index, {
                          hostKeys: e.target.value.split("\n"),
                        })
                      }
                    />
                  </label>
                  <p className="text-xs text-muted-foreground">
                    One public key per line, verified with the server
                    administrator. A network scan alone does not establish
                    trust.
                  </p>
                </div>
              ))}
              <button
                type="button"
                className="af-btn af-btn-sm"
                disabled={servers.length >= 64}
                onClick={() => {
                  setDirty(true);
                  setServers([
                    ...servers,
                    {
                      name: "",
                      hostname: "",
                      port: 22,
                      username: "",
                      hostKeys: [""],
                    },
                  ]);
                }}
              >
                <PlusIcon size={14} /> Add server
              </button>
            </fieldset>
            {mutation.error && (
              <p role="alert" className="text-sm text-destructive">
                {mutation.error.message}
              </p>
            )}
            <div className="flex justify-end gap-2">
              <button
                type="button"
                className="af-btn"
                disabled={mutation.isPending}
                onClick={close}
              >
                {readonly ? "Close" : "Cancel"}
              </button>
              {!readonly && (
                <button
                  type="submit"
                  className="af-btn af-btn-primary"
                  disabled={mutation.isPending}
                >
                  {mutation.isPending ? "Saving…" : "Save SSH credential"}
                </button>
              )}
            </div>
          </form>
        </DialogContent>
      </Dialog>
      <ConfirmationDialog
        open={discard}
        onOpenChange={setDiscard}
        title="Discard SSH credential changes?"
        description="Your unsaved changes will be lost."
        confirmLabel="Discard changes"
        variant="destructive"
        onConfirm={onClose}
      />
    </>
  );
}

export function SshCredentialsPanel() {
  const { canManage } = useActiveOrgRole();
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const query = useSshCredentials(page, search);
  const [editor, setEditor] = useState<{ credential?: SshCredential } | null>(
    null,
  );
  const [deleting, setDeleting] = useState<SshCredential | null>(null);
  return (
    <section className="mt-8 space-y-4" aria-label="SSH credentials">
      <div className="flex flex-wrap justify-between items-center gap-3">
        <div>
          <h2 className="flex items-center gap-2 text-lg font-semibold">
            <KeyRoundIcon size={19} /> SSH credentials
          </h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Share access to servers while keeping private keys outside Agents.
          </p>
        </div>
        {canManage && (
          <button
            className="af-btn af-btn-primary"
            onClick={() => setEditor({})}
          >
            <PlusIcon size={15} /> Add SSH credential
          </button>
        )}
      </div>
      <input
        aria-label="Search SSH credentials"
        placeholder="Search SSH credentials…"
        className="af-input w-full"
        value={search}
        onChange={(e) => {
          setSearch(e.target.value);
          setPage(1);
        }}
      />
      {query.isLoading ? (
        <p role="status">Loading SSH credentials…</p>
      ) : query.error ? (
        <div role="alert">
          Could not load SSH credentials.{" "}
          <button
            className="af-btn af-btn-sm"
            onClick={() => void query.refetch()}
          >
            Retry
          </button>
        </div>
      ) : (
        <>
          {!query.credentials.length && (
            <p className="rounded-xl border border-dashed p-6 text-sm text-muted-foreground">
              No SSH credentials found. Add a key, install its public key on a
              server, then attach it to an Agent.
            </p>
          )}
          {query.credentials.map((key) => (
            <div
              key={key.id}
              className="flex items-center gap-3 rounded-xl border px-4 py-3"
            >
              <button
                className="min-w-0 flex-1 text-left"
                onClick={() => setEditor({ credential: key })}
              >
                <span className="font-medium">{key.name}</span>
                <span className="mt-1 block truncate font-mono text-xs text-muted-foreground">
                  {key.fingerprint}
                </span>
              </button>
              <span className="text-xs text-muted-foreground">
                {!key.enabled
                  ? "Disabled"
                  : key.mode === "unrestricted"
                    ? "Unrestricted"
                    : `${key.servers.length} servers`}{" "}
                · {key.agentCount} Agents
              </span>
              {canManage && (
                <button
                  className="af-btn af-btn-ghost af-btn-icon"
                  aria-label={`Delete SSH credential ${key.name}`}
                  onClick={() => setDeleting(key)}
                >
                  <Trash2Icon size={15} />
                </button>
              )}
            </div>
          ))}
          {query.total > 100 && (
            <div className="flex items-center justify-end gap-3 text-sm">
              <button
                className="af-btn af-btn-sm"
                disabled={page === 1}
                onClick={() => setPage(page - 1)}
              >
                Previous
              </button>
              <span>Page {page}</span>
              <button
                className="af-btn af-btn-sm"
                disabled={page * 100 >= query.total}
                onClick={() => setPage(page + 1)}
              >
                Next
              </button>
            </div>
          )}
        </>
      )}
      {editor && (
        <KeyEditor
          credential={editor.credential}
          canManage={canManage}
          onClose={() => setEditor(null)}
        />
      )}
      <ConfirmationDialog
        open={Boolean(deleting)}
        onOpenChange={(open) => {
          if (!open) {
            setDeleting(null);
            query.mutation.reset();
          }
        }}
        title="Delete SSH credential?"
        description="Detach this key from all Agents first. Deletion does not remove its public key from remote servers."
        confirmLabel="Delete credential"
        variant="destructive"
        isPending={query.mutation.isPending}
        onConfirm={async () => {
          await query.mutation.mutateAsync({ id: deleting?.id, remove: true });
          setDeleting(null);
        }}
      >
        {query.mutation.error && (
          <p role="alert" className="mt-3 text-sm text-destructive">
            {query.mutation.error.message}
          </p>
        )}
      </ConfirmationDialog>
    </section>
  );
}
