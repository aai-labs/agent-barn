import { expect, test, type Page } from "@playwright/test";

import { mockCommunicationConnection, mockCommunicationPlatforms } from "../fixtures/communication-connections";
import { MOCK_AGENT_ID, mockAgent } from "../pages/data-support/agent-data-support.po";
import { DataSupport } from "../pages/data-support/data-support.po";
import { AgentDetailPage } from "../pages/agent-detail-page.po";

const CONNECTION_ID = "dddddddd-dddd-4ddd-8ddd-dddddddddddd";
const CONNECTIONS = `**/api/v1/organizations/*/agents/${MOCK_AGENT_ID}/connections`;
const PAIRING = `${CONNECTIONS}/${CONNECTION_ID}/whatsapp-pairing`;
const PNG_1PX = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=";

const whatsAppPlatform = {
  key: "whatsapp",
  display_name: "WhatsApp",
  setup_hint: "Use a dedicated phone number.",
  schema_version: 1,
  capabilities: ["attachments", "mentions"],
  settings_schema: {
    type: "object",
    properties: {
      mode: { default: "bot", pattern: "^(bot|self_chat)$", title: "Mode", type: "string" },
      dm_policy: { default: "allowlist", pattern: "^(off|open|allowlist)$", title: "Direct messages", type: "string" },
      allowed_numbers: { items: { type: "string" }, title: "Allowed numbers", type: "array" },
      group_policy: { default: "off", pattern: "^(off|open|allowlist)$", title: "Group access", type: "string" },
      allowed_group_ids: { items: { type: "string" }, title: "Allowed groups", type: "array" },
      require_mention: { default: true, title: "Require @mention", type: "boolean" },
    },
  },
  credentials_schema: { type: "object", properties: {} },
};

const whatsAppConnection = {
  ...mockCommunicationConnection,
  id: CONNECTION_ID,
  platform_key: "whatsapp",
  display_name: "WhatsApp",
  settings: { dm_policy: "allowlist", allowed_numbers: ["15551234567"], group_policy: "off" },
  external_identity: null,
  observed_status: "ERROR",
  last_error_code: "whatsapp_not_paired",
  last_error_message: null,
};

function sse(...events: object[]) {
  return events.map((event) => `data: ${JSON.stringify(event)}\n\n`).join("");
}

async function openMessaging(page: Page, agent: Record<string, unknown>, connections: unknown[]) {
  const dataSupport = new DataSupport(page);
  const agentDetailPage = new AgentDetailPage(page);
  await dataSupport.auth.interceptRefreshRequest();
  await dataSupport.users.interceptGetUserContextRequest();
  await dataSupport.users.interceptGetOrganizationsRequest();
  await dataSupport.agents.interceptGetAgentRequest({ body: { ...mockAgent, ...agent } });
  await dataSupport.agents.interceptGetAgentTemplateRequest();
  await dataSupport.agents.interceptGetConversationChannelsRequest();
  await dataSupport.agents.interceptGetTemplatesRequest();
  await dataSupport.agents.interceptGetAgentConfigurationRequest();
  await dataSupport.agents.interceptGetModelsRequest();
  await dataSupport.communicationConnections.interceptChannelsRequests({ agentId: MOCK_AGENT_ID });
  await page.route("**/api/v1/organizations/*/communication-platforms", (route) =>
    route.fulfill({ json: [...mockCommunicationPlatforms, whatsAppPlatform] }),
  );
  await page.route(CONNECTIONS, (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    return route.fulfill({ json: connections });
  });
  await agentDetailPage.goto(MOCK_AGENT_ID);
  await agentDetailPage.configureButton().click();
  await agentDetailPage.openConfigurationSection("Messaging");
  return agentDetailPage;
}

test.describe("WhatsApp phone linking", () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  for (const agentType of ["hermes", "openclaw"]) {
    test(`offers WhatsApp to a${agentType === "hermes" ? " Hermes" : "n OpenClaw"} Agent`, async ({ page }) => {
      const agentDetailPage = await openMessaging(page, { agent_type: agentType }, []);
      await agentDetailPage.addConnectionButton().click();
      await agentDetailPage.selectPlatformButton("WhatsApp").click();
      await expect(page.getByText(/Link the phone with a QR code once the connection is saved/)).toBeVisible();

      const create = agentDetailPage.waitForConnectionMutation("POST");
      await agentDetailPage.connectPlatformButton("WhatsApp").click();
      expect((await create).postDataJSON()).toMatchObject({
        platform_key: "whatsapp",
        display_name: "WhatsApp",
        settings: { dm_policy: "allowlist", group_policy: "off", require_mention: true },
        credentials: {},
      });
    });
  }

  test("shows a Bot why it can't have WhatsApp", async ({ page }) => {
    const agentDetailPage = await openMessaging(
      page,
      { agent_type: "hermes", parent_agent_id: "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee" },
      [],
    );
    await agentDetailPage.addConnectionButton().click();

    const tile = agentDetailPage.selectPlatformButton("WhatsApp");
    await expect(tile).toBeDisabled();
    await expect(tile).toHaveAccessibleDescription(/Add WhatsApp to the Parent Agent/);
  });

  test("tells people how to reach a Bot-mode Agent", async ({ page }) => {
    await openMessaging(page, { agent_type: "openclaw" }, [
      {
        ...whatsAppConnection,
        settings: { mode: "bot", dm_policy: "allowlist", allowed_numbers: ["15551234567"], group_policy: "open" },
      },
    ]);

    const reach = page.getByRole("region", { name: "How people reach this Agent" });
    await expect(reach.getByText("Direct messages from 1 allowed number are answered; others are ignored.")).toBeVisible();
    await expect(reach.getByText(/Add the linked number to a group; it answers there when @mentioned/)).toBeVisible();
    await expect(reach.getByText(/message it from another phone/)).toBeVisible();
  });

  test("tells the owner how to talk to a Self Chat Agent", async ({ page }) => {
    await openMessaging(page, { agent_type: "hermes" }, [
      { ...whatsAppConnection, settings: { ...whatsAppConnection.settings, mode: "self_chat" } },
    ]);

    const reach = page.getByRole("region", { name: "How to talk to this Agent" });
    await expect(reach.getByText(/New chat → Message yourself/)).toBeVisible();
    await expect(reach.getByText(/its replies start with 🤖/)).toBeVisible();
  });

  test("links a phone by QR code, then offers to restart the Agent", async ({ page }) => {
    await openMessaging(page, { agent_type: "hermes", status: "RUNNING" }, [whatsAppConnection]);
    await page.route(PAIRING, (route) =>
      route.fulfill({
        contentType: "text/event-stream",
        body: sse(
          { event: "qr", qr: "https://wa.me/settings/linked_devices#2@abc" },
          { event: "connected", phone: "+15551234567" },
          { event: "linked" },
        ),
      }),
    );
    await expect(page.getByText("No phone is linked yet.")).toBeVisible();

    const pairing = page.waitForRequest((request) => request.url().includes("/whatsapp-pairing"));
    await page.getByRole("button", { name: "Link phone" }).click();

    expect((await pairing).method()).toBe("POST");
    const dialog = page.getByRole("dialog", { name: "Link a WhatsApp phone" });
    await expect(dialog.getByText("+15551234567 is linked.")).toBeVisible();
    await expect(dialog.getByRole("button", { name: "Restart Agent" })).toBeEnabled();
    await expect(dialog.getByRole("button", { name: "Restart later" })).toBeVisible();
  });

  const qrFrames = {
    hermes: { event: "qr", qr: "https://wa.me/settings/linked_devices#2@abc" },
    openclaw: { event: "qr_image", image: `data:image/png;base64,${PNG_1PX}` },
  };
  for (const [agentType, frame] of Object.entries(qrFrames)) {
    test(`shows the ${agentType} QR code while waiting for the scan`, async ({ page }) => {
      // A routed response always ends, which ends the attempt; this stream stays open
      // after its QR code, as the real one does until the phone scans it.
      await page.addInitScript((qrFrame: string) => {
        const realFetch = window.fetch.bind(window);
        window.fetch = (input, init) => {
          if (!String(input instanceof Request ? input.url : input).includes("/whatsapp-pairing")) {
            return realFetch(input, init);
          }
          const body = new ReadableStream<Uint8Array>({
            start(controller) {
              controller.enqueue(new TextEncoder().encode(qrFrame));
            },
          });
          return Promise.resolve(new Response(body, { headers: { "Content-Type": "text/event-stream" } }));
        };
      }, sse(frame));
      await openMessaging(page, { agent_type: agentType, status: "RUNNING" }, [whatsAppConnection]);

      await page.getByRole("button", { name: "Link phone" }).click();

      const dialog = page.getByRole("dialog", { name: "Link a WhatsApp phone" });
      await expect(dialog.getByRole("img", { name: "QR code that links the phone" })).toBeVisible();
      await expect(dialog.getByText(/refreshes every 20 seconds/)).toBeVisible();
      await expect(dialog.getByRole("button", { name: "Waiting for scan…" })).toBeDisabled();
    });
  }

  test("warns that linking an OpenClaw Agent unlinks any current phone at once", async ({ page }) => {
    // OpenClaw doesn't report whether a phone is linked, so the warning always shows.
    await openMessaging(page, { agent_type: "openclaw", status: "RUNNING" }, [
      { ...whatsAppConnection, observed_status: "CONNECTED", last_error_code: null },
    ]);
    await page.route(PAIRING, (route) =>
      route.fulfill({ contentType: "text/event-stream", body: sse({ event: "expired" }) }),
    );

    await expect(page.getByText("Link the phone this Agent answers as, or link again to change it.")).toBeVisible();
    await page.getByRole("button", { name: "Link phone" }).click();

    const dialog = page.getByRole("dialog", { name: "Link a WhatsApp phone" });
    await expect(dialog.getByText(/unlinks the current phone straight away/)).toBeVisible();
  });

  test("offers another try when the QR code expires", async ({ page }) => {
    await openMessaging(page, { agent_type: "hermes", status: "RUNNING" }, [whatsAppConnection]);
    let attempts = 0;
    await page.route(PAIRING, (route) => {
      attempts += 1;
      return route.fulfill({ contentType: "text/event-stream", body: sse({ event: "expired" }) });
    });

    await page.getByRole("button", { name: "Link phone" }).click();
    const dialog = page.getByRole("dialog", { name: "Link a WhatsApp phone" });
    await expect(dialog.getByText("The QR code expired before it was scanned.")).toBeVisible();
    await dialog.getByRole("button", { name: "Try again" }).click();
    await expect.poll(() => attempts).toBe(2);
  });

  test("says whether a Hermes phone is linked only once the runtime reports it", async ({ page }) => {
    await openMessaging(page, { agent_type: "hermes", status: "RUNNING" }, [
      { ...whatsAppConnection, observed_status: "PENDING", last_error_code: null },
    ]);
    await expect(page.getByText("Link the phone this Agent answers as, or link again to change it.")).toBeVisible();
    await expect(page.getByRole("button", { name: "Link phone" })).toBeVisible();

    await openMessaging(page, { agent_type: "hermes", status: "RUNNING" }, [
      { ...whatsAppConnection, observed_status: "CONNECTED", last_error_code: null },
    ]);
    await expect(page.getByRole("button", { name: "Link again" })).toBeVisible();
  });

  test("asks to start a stopped Agent before linking", async ({ page }) => {
    await openMessaging(page, { agent_type: "hermes", status: "STOPPED" }, [whatsAppConnection]);

    await expect(page.getByRole("button", { name: "Link phone" })).toBeDisabled();
    await expect(page.getByText("Start the Agent to link a phone.")).toBeVisible();
  });
});
