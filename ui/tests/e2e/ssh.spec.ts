import { expect, test } from "@playwright/test";

import { sshCredential } from "../fixtures/ssh";
import { SshDataSupport } from "../pages/data-support/ssh-data-support.po";
import { SshPage } from "../pages/ssh-page.po";

test.describe("Shared SSH access", () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  test("generates a restricted key and shows only the public identity", async ({
    page,
  }) => {
    const data = new SshDataSupport(page);
    const ui = new SshPage(page);
    await data.setup();
    await data.openSettings();
    await ui.addGenerated("Deployment key");
    await ui.save();
    await expect(
      page.getByRole("dialog", { name: "SSH credential saved" }),
    ).toBeVisible();
    await expect(page.getByLabel("SSH public key")).toContainText(
      sshCredential.public_key,
    );
    expect(data.requests).toEqual([
      {
        name: "Deployment key",
        source: "generate",
        mode: "restricted",
        servers: [],
      },
    ]);
    await expect(
      page.getByRole("textbox", { name: "Private key", exact: true }),
    ).toHaveCount(0);
  });

  test("retains imported fields after rejection and clears secrets after success", async ({
    page,
  }) => {
    const data = new SshDataSupport(page);
    const ui = new SshPage(page);
    await data.setup();
    await data.openSettings();
    await ui.addGenerated("Imported key");
    await ui.chooseImport();
    await ui
      .editor()
      .getByRole("textbox", { name: "Private key", exact: true })
      .fill("test-private-input");
    await ui
      .editor()
      .getByLabel("Passphrase (optional)")
      .fill("test-passphrase");
    await ui.chooseUnrestricted();
    data.failure = "Invalid private key";
    await ui.save();
    await expect(ui.editor().getByRole("alert")).toContainText(
      "Invalid private key",
    );
    await expect(
      ui.editor().getByRole("textbox", { name: "Private key", exact: true }),
    ).toHaveValue("test-private-input");
    data.failure = "";
    await ui.save();
    await expect(
      page.getByRole("dialog", { name: "SSH credential saved" }),
    ).toBeVisible();
    await expect(
      page.getByRole("textbox", { name: "Private key", exact: true }),
    ).toHaveCount(0);
    expect(data.requests[1]).toMatchObject({
      source: "import",
      mode: "unrestricted",
      private_key: "test-private-input",
      passphrase: "test-passphrase",
    });
  });

  test("members can inspect shared keys but cannot create or change them", async ({
    page,
  }) => {
    const data = new SshDataSupport(page);
    await data.setup({ member: true, assigned: true });
    await data.openSettings();
    await expect(
      page.getByRole("button", { name: "Production deployment", exact: false }),
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Add SSH credential", exact: true }),
    ).toHaveCount(0);
  });

  test("assignment apply confirms a restart and preserves edits on conflict", async ({
    page,
  }) => {
    const data = new SshDataSupport(page);
    const ui = new SshPage(page);
    await data.setup({ assigned: true });
    await data.openAgent();
    await ui
      .section()
      .getByRole("button", { name: "Edit", exact: true })
      .click();
    await ui.section().getByRole("checkbox").uncheck();
    data.failure = "SSH assignments changed; refresh and try again";
    await ui.applyAssignments();
    await expect(ui.section().getByRole("alert")).toContainText(
      "SSH assignments changed",
    );
    await expect(ui.section().getByRole("checkbox")).not.toBeChecked();
    expect(data.assignmentRequests[0]).toEqual({
      credential_ids: [],
      expected_revision: 1,
      restart: true,
    });
  });

  test("applying SSH changes to an errored Bot explains the shared restart and succeeds", async ({ page }, testInfo) => {
    const data = new SshDataSupport(page);
    const ui = new SshPage(page);
    async function capture(name: string) {
      const path = testInfo.outputPath(`${name}.png`);
      await page.screenshot({ path, animations: "disabled" });
      await testInfo.attach(name, { path, contentType: "image/png" });
    }
    await data.setup({ assigned: true, bot: true });
    await data.openAgent();
    await ui.section().getByRole("button", { name: "Edit", exact: true }).click();
    await capture("01-bot-ssh-selection");
    await ui.section().getByRole("button", { name: "Apply & Restart", exact: true }).click();
    await expect(page.getByRole("dialog")).toContainText("Parent Agent and all of its Bots");
    await capture("02-bot-shared-restart-confirmation");
    await page.getByRole("dialog").getByRole("button", { name: "Apply & Restart", exact: true }).click();
    await expect(ui.section().getByRole("button", { name: "Edit", exact: true })).toBeVisible();
    await capture("03-bot-ssh-applied");
    expect(data.assignmentRequests).toEqual([{
      credential_ids: [sshCredential.id], expected_revision: 1, restart: true,
    }]);
  });

  test("Bot SSH changes cannot restart a Parent Agent the member can only read", async ({ page }) => {
    const data = new SshDataSupport(page);
    const ui = new SshPage(page);
    await data.setup({ assigned: true, bot: true, parentCanRestart: false });
    await data.openAgent();
    await ui.section().getByRole("button", { name: "Edit", exact: true }).click();
    await expect(ui.section().getByRole("button", { name: "Apply & Restart", exact: true })).toBeDisabled();
    expect(data.assignmentRequests).toEqual([]);
  });
});
