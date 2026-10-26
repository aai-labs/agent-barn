import type { CustomApiConnection, CustomApiWrite } from "../schemas";

export type ConnectionDraft = {
  key: string;
  connection?: CustomApiConnection;
  value: CustomApiWrite;
  changed: boolean;
};

export function connectionDraft(connection?: CustomApiConnection): ConnectionDraft {
  return {
    key: connection?.id ?? crypto.randomUUID(),
    connection,
    changed: !connection,
    value: {
      name: connection?.name ?? "",
      baseUrl: connection?.baseUrl ?? "",
      isolated: connection?.isolated ?? false,
      auth: {
        type: connection?.authType ?? "none",
        ...(connection?.authHeaderName ? { headerName: connection.authHeaderName } : {}),
        ...(connection?.authTokenUrl ? { tokenUrl: connection.authTokenUrl } : {}),
      },
      headers: connection?.headers.map((header) => ({ ...header, value: header.value ?? "" })) ?? [],
    },
  };
}

export function connectionPayload(value: CustomApiWrite): CustomApiWrite {
  return {
    ...value,
    auth: Object.fromEntries(Object.entries(value.auth).filter(([, value]) => value !== "")) as CustomApiWrite["auth"],
    headers: value.headers.map(({ name, secret, value }) => ({ name, secret, ...(!secret || value ? { value } : {}) })),
  };
}
