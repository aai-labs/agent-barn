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
      ui.savedDialog(),
    ).toBeVisible();
    await expect(ui.publicKey()).toContainText(
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
      ui.privateKey(),
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
    await ui.enterPrivateKey("test-private-input", "test-passphrase");
    await ui.chooseUnrestricted();
    data.failure = "Invalid private key";
    await ui.save();
    await expect(ui.editorError()).toContainText(
      "Invalid private key",
    );
    await expect(
      ui.privateKey(),
    ).toHaveValue("test-private-input");
    data.failure = "";
    await ui.save();
    await expect(
      ui.savedDialog(),
    ).toBeVisible();
    await expect(
      ui.privateKey(),
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
    const ui = new SshPage(page);
    await data.setup({ member: true, assigned: true });
    await data.openSettings();
    await expect(
      ui.credentialButton("Production deployment"),
    ).toBeVisible();
    await expect(
      ui.addButton(),
    ).toHaveCount(0);
  });

  test("assignment apply confirms a restart and preserves edits on conflict", async ({
    page,
  }) => {
    const data = new SshDataSupport(page);
    const ui = new SshPage(page);
    await data.setup({ assigned: true });
    await data.openAgent();
    await ui.editAssignments();
    await ui.detachKey();
    data.failure = "SSH assignments changed; refresh and try again";
    await ui.applyAssignments();
    await expect(ui.assignmentError()).toContainText(
      "SSH assignments changed",
    );
    await expect(ui.assignmentCheckbox()).not.toBeChecked();
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
    await ui.editAssignments();
    await capture("01-bot-ssh-selection");
    await ui.requestApply();
    await expect(ui.restartDialog()).toContainText("Parent Agent and all of its Bots");
    await capture("02-bot-shared-restart-confirmation");
    await ui.confirmRestart();
    await expect(ui.editButton()).toBeVisible();
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
    await ui.editAssignments();
    await expect(ui.applyButton()).toBeDisabled();
    expect(data.assignmentRequests).toEqual([]);
  });
});
