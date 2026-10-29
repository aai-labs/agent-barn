import { expect, test, type Page } from "@playwright/test";

import { TEST_ORG_ID } from "../constants";
import { WORKFLOW_ID, workflowDraft } from "../fixtures/workflows";
import { WorkflowsPage } from "../pages/workflows-page.po";
import {
  MOCK_AGENT_ID,
  mockAgent,
} from "../pages/data-support/agent-data-support.po";
import { DataSupport } from "../pages/data-support/data-support.po";
import { WorkflowDataSupport } from "../pages/data-support/workflow-data-support.po";

/** A section of the Agent in the navigation panel beside the page. */
const section = (page: Page, name: string) =>
  page.getByRole("complementary").getByRole("link", { name, exact: true });

test.describe("WF01 workflow authoring", () => {
  test.use({ storageState: { cookies: [], origins: [] } });
  let support: WorkflowDataSupport;
  test.beforeEach(async ({ page }) => {
    const data = new DataSupport(page);
    await data.auth.interceptRefreshRequest();
    await data.users.interceptGetUserContextRequest();
    await data.users.interceptGetOrganizationsRequest();
    await data.agents.interceptGetAgentRequest({ body: mockAgent });
    support = new WorkflowDataSupport(page);
    await support.intercept(MOCK_AGENT_ID);
  });
  for (const legacy of [false, true]) {
    test(`disabled workflows hides the tab and saved content through ${legacy ? "legacy" : "Agent tab"} links`, async ({ page }) => {
      const data = new DataSupport(page);
      await data.agents.interceptGetAgentRequest({
        body: { ...mockAgent, allowed_actions: ["agent.read"] },
      });
      await support.intercept(MOCK_AGENT_ID, { saved: true, authoring: false });
      const capability = page.waitForResponse((response) => response.url().endsWith("/workflow-capabilities"));
      if (legacy) {
        await page.goto(`/dashboard/${TEST_ORG_ID}/agents/${MOCK_AGENT_ID}/workflows?workflow=${WORKFLOW_ID}`);
      } else {
        await new WorkflowsPage(page).goto(MOCK_AGENT_ID, TEST_ORG_ID, WORKFLOW_ID);
      }
      await expect(section(page, "Overview")).toBeVisible();
      expect((await (await capability).json()).authoring).toBe(false);
      await expect(section(page, "Workflows")).toHaveCount(0);
      await expect(section(page, "Overview")).toHaveAttribute("aria-current", "page");
      await expect(page.getByRole("heading", { name: "Weekly pipeline report", exact: true })).toHaveCount(0);
      expect(support.reads).toEqual({ list: 0, detail: 0, versions: 0 });
    });
  }
  test("save file inputs and output descriptions without format switches", async ({ page }) => {
    const workflows = new WorkflowsPage(page);
    await workflows.goto(MOCK_AGENT_ID, TEST_ORG_ID);
    await workflows.create("Transform an uploaded file");
    await workflows.buildExample();
    await workflows.useFileInput();
    await workflows.selectStep(1);
    await expect(page.getByRole("checkbox", { name: /Require a downloadable/ })).toHaveCount(0);
    await workflows.selectSection("Review destination");
    await expect(page.getByRole("checkbox", { name: /Require a downloadable/ })).toHaveCount(0);
    await workflows.save();
    await expect(page.getByText("Saved v1", { exact: false }).first()).toBeVisible();
    expect(support.saveRequests[0]).toMatchObject({
      inputs: [{ type: "file" }],
      steps: [{ artifact_description: "Source data" }, {}],
    });
    await workflows.selectStep(1);
    await expect(page.getByText("Source data", { exact: true })).toBeVisible();
    await workflows.selectSection("Review destination");
    await expect(page.getByText("Web review", { exact: true })).toBeVisible();
  });
  test("create, edit, reorder, remove, undo and save an immutable plan", async ({
    page,
  }) => {
    const workflows = new WorkflowsPage(page);
    await workflows.goto(MOCK_AGENT_ID, TEST_ORG_ID);
    await workflows.create("Summarize weekly pipeline changes");
    await workflows.buildExample();
    await expect(page.getByLabel("Workflow name")).toHaveValue(
      "Weekly pipeline report",
    );
    await workflows.selectStep(1);
    await workflows
      .step(1)
      .getByRole("button", { name: "↓ Move down" })
      .click();
    await workflows.selectStep(1);
    await expect(page.getByLabel("Step 1", { exact: true })).toHaveValue(
      "Prepare summary",
    );
    await workflows.selectStep(2);
    await workflows
      .step(2)
      .getByRole("button", { name: "Remove step" })
      .click();
    await page.getByRole("button", { name: "Undo removal" }).click();
    await expect(
      workflows.step(2).getByLabel("Output from this step (optional)"),
    ).toHaveValue("Source data");
    await page.getByRole("button", { name: "Add a step" }).click();
    await workflows
      .step(3)
      .getByLabel("Step 3", { exact: true })
      .fill("Review report");
    await workflows
      .step(3)
      .getByLabel("What should the Agent do?")
      .fill("Review the report for clarity");
    await expect(workflows.step(3).getByText("Include any specific criteria for success in the instructions.")).toBeVisible();
    await workflows.save();
    await expect(
      page.getByText("Saved v1", { exact: false }).first(),
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Run workflow" }),
    ).toBeDisabled();
    expect(support.saveRequests).toHaveLength(1);
    expect(
      (support.saveRequests[0].steps as { name: string }[]).map((s) => s.name),
    ).toEqual(["Prepare summary", "Read pipeline", "Review report"]);
    await page.getByRole("button", { name: "All workflows" }).click();
    await expect(
      page.getByRole("button", { name: "Open Weekly pipeline report" }),
    ).toBeVisible();
  });
  test("Create workflow opens the editor directly with no repeated outcome screen", async ({
    page,
  }) => {
    const workflows = new WorkflowsPage(page);
    await workflows.goto(MOCK_AGENT_ID, TEST_ORG_ID);
    await page.getByRole("button", { name: "+ Create workflow" }).click();
    await expect(page.getByLabel("Workflow name")).toBeVisible();
    await expect(page.getByLabel("Description (optional)")).toHaveCount(1);
    await page.getByLabel("Workflow name").fill("My workflow");
    await page.getByLabel("Description (optional)").fill("My original outcome");
    await workflows.selectStep(1);
    await workflows.selectSection("Workflow details");
    await expect(page.getByLabel("Description (optional)")).toHaveValue(
      "My original outcome",
    );
    await expect(
      page.getByRole("button", { name: /Generate plan|Build Workflow/ }),
    ).toHaveCount(0);
    expect(support.saveRequests).toHaveLength(0);
  });
  test("workflow cards show the outcome and plan summary and open the saved workflow", async ({
    page,
  }) => {
    await support.intercept(MOCK_AGENT_ID, { saved: true });
    const workflows = new WorkflowsPage(page);
    await workflows.goto(MOCK_AGENT_ID, TEST_ORG_ID);
    const card = page.getByRole("button", {
      name: "Open Weekly pipeline report",
      exact: true,
    });
    await expect(card).toContainText("Summarize weekly pipeline changes");
    await expect(card).toContainText("2 steps");
    await expect(card).toContainText("1 input");
    await page.setViewportSize({ width: 390, height: 844 });
    await expect(card).toBeVisible();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBe(true);
    await card.focus();
    await page.keyboard.press("Enter");
    await workflows.selectSection("Required inputs");
    await expect(
      page.getByText("Reporting period", { exact: true }),
    ).toBeVisible();
    await expect(page.getByText(/^Key:/)).toHaveCount(0);
  });
  test("input keys follow labels and persist with hyphen separators", async ({
    page,
  }) => {
    const workflows = new WorkflowsPage(page);
    await workflows.goto(MOCK_AGENT_ID, TEST_ORG_ID);
    await workflows.create("Prepare a report");
    await workflows.buildExample();
    await workflows.selectSection("Required inputs");
    await page.getByLabel("Input 1 label").fill("Reporting Period");
    await expect(page.getByLabel("Input 1 key")).toHaveCount(0);
    await page.getByLabel("Input 1 label").fill("  Sales   Region  ");
    await expect(
      page.getByText(/Set automatically from the label/),
    ).toHaveCount(0);
    await workflows.save();
    await expect(
      page.getByText("Saved v1", { exact: false }).first(),
    ).toBeVisible();
    expect((support.saveRequests[0].inputs as { key: string }[])[0].key).toBe(
      "sales-region",
    );
  });
  test("labels with punctuation and numbers save, and similar labels name the colliding input", async ({
    page,
  }) => {
    const workflows = new WorkflowsPage(page);
    await workflows.goto(MOCK_AGENT_ID, TEST_ORG_ID);
    await workflows.create("Prepare a report");
    await workflows.buildExample();
    await workflows.selectSection("Required inputs");
    await page.getByRole("button", { name: "+ Add an input" }).click();
    await page.getByLabel("Input 2 label").fill("Reporting-period!");
    await page.getByLabel("Input 2 description").fill("The report owner");
    await workflows.selectSection("Workflow details");
    await workflows.save();
    const error = page.getByRole("alert", { name: "Workflow error" });
    await expect(error).toContainText(
      "Input 2 · Label: Matches input 1 once case, accents and punctuation are ignored",
    );
    await expect(page.getByLabel("Input 2 label")).toHaveValue(
      "Reporting-period!",
    );
    expect(support.saveRequests).toHaveLength(0);
    await page.getByLabel("Input 2 label").fill("2nd owner's e-mail (Café)");
    await workflows.save();
    await expect(
      page.getByText("Saved v1", { exact: false }).first(),
    ).toBeVisible();
    expect(
      (support.saveRequests[0].inputs as { key: string }[]).map((i) => i.key),
    ).toEqual(["reporting-period", "input-2nd-owners-e-mail-cafe"]);
    await workflows.selectSection("Required inputs");
    await expect(
      page.getByText("2nd owner's e-mail (Café)", { exact: true }),
    ).toBeVisible();
    await expect(page.getByText(/input-2nd/)).toHaveCount(0);
  });
  test("long and non-Latin input labels retain distinct valid internal keys", async ({
    page,
  }) => {
    const workflows = new WorkflowsPage(page);
    await workflows.goto(MOCK_AGENT_ID, TEST_ORG_ID);
    await workflows.create("Prepare a report");
    await workflows.buildExample();
    await workflows.selectSection("Required inputs");
    const labels = [
      `${"a".repeat(190)} first`,
      `${"a".repeat(190)} second`,
      "客户名称",
      "客户地区",
    ];
    for (const [index, label] of labels.entries()) {
      if (index)
        await page.getByRole("button", { name: "+ Add an input" }).click();
      await page.getByLabel(`Input ${index + 1} label`).fill(label);
      await page
        .getByLabel(`Input ${index + 1} description`)
        .fill(`Information for input ${index + 1}`);
    }
    await workflows.save();
    await expect(
      page.getByText("Saved v1", { exact: false }).first(),
    ).toBeVisible();
    const inputs = support.saveRequests[0].inputs as {
      key: string;
      label: string;
    }[];
    expect(inputs.map((input) => input.label)).toEqual(labels);
    expect(new Set(inputs.map((input) => input.key)).size).toBe(labels.length);
    for (const input of inputs)
      expect(input.key).toMatch(/^[a-z][a-z0-9_-]{0,63}$/);
    await workflows.selectSection("Required inputs");
    await expect(page.getByText("客户名称", { exact: true })).toBeVisible();
    await expect(page.getByText("客户地区", { exact: true })).toBeVisible();
  });
  test("fields explain problems once left, without waiting for save", async ({
    page,
  }) => {
    const workflows = new WorkflowsPage(page);
    await workflows.goto(MOCK_AGENT_ID, TEST_ORG_ID);
    await workflows.create("Prepare a report");
    const name = page.getByLabel("Workflow name");
    await expect(name).not.toHaveAttribute("aria-invalid", "true");
    await name.focus();
    await page.keyboard.press("Tab");
    await expect(name).toHaveAttribute("aria-invalid", "true");
    await expect(name).toHaveAccessibleDescription("Enter a name");
    await expect(page.getByLabel("Description (optional)")).not.toHaveAttribute(
      "aria-invalid",
      "true",
    );
    await name.fill("Weekly report");
    await expect(name).not.toHaveAttribute("aria-invalid", "true");
    await expect(page.getByText("Enter a name", { exact: true })).toHaveCount(
      0,
    );
    expect(support.saveRequests).toHaveLength(0);
  });
  test("all steps removed disables saving, and undo preserves edited fields", async ({
    page,
  }) => {
    const workflows = new WorkflowsPage(page);
    await workflows.goto(MOCK_AGENT_ID, TEST_ORG_ID);
    await workflows.create("Prepare report");
    await workflows.buildExample();
    await workflows.selectStep(1);
    await workflows
      .step(1)
      .getByRole("button", { name: "Remove step" })
      .click();
    await expect(
      page.getByRole("button", { name: "Undo removal" }),
    ).toBeFocused();
    await page.getByLabel("Step 1", { exact: true }).fill("Edited summary");
    await workflows
      .step(1)
      .getByRole("button", { name: "Remove step" })
      .click();
    await expect(
      page.getByRole("heading", { name: "Add your first step" }),
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Save workflow", exact: true }),
    ).toBeDisabled();
    await page.getByRole("button", { name: "Undo removal" }).click();
    await expect(page.getByLabel("Step 1", { exact: true })).toHaveValue(
      "Edited summary",
    );
  });
  test("validation and save conflicts retain edits and recover explicitly", async ({
    page,
  }) => {
    await support.intercept(MOCK_AGENT_ID, { saved: true });
    const workflows = new WorkflowsPage(page);
    await workflows.goto(MOCK_AGENT_ID, TEST_ORG_ID, WORKFLOW_ID);
    await page.getByRole("button", { name: "Edit workflow" }).click();
    await page.getByLabel("Workflow name").fill("");
    await workflows.save();
    await expect(
      page.getByRole("alert", { name: "Workflow error" }),
    ).toContainText("Enter a name");
    await page.getByLabel("Workflow name").fill("My edited report");
    support.conflictSave = true;
    await workflows.save();
    await expect(
      page.getByRole("alert", { name: "Workflow error" }),
    ).toContainText("Workflow changed");
    await expect(page.getByLabel("Workflow name")).toHaveValue(
      "My edited report",
    );
    await page
      .getByRole("button", { name: "Load current revision and keep my edits" })
      .click();
    await workflows.save();
    await expect(
      page.getByRole("heading", { name: "My edited report" }),
    ).toBeVisible();
    expect(support.saveRequests.at(-1)?.expected_revision).toBe(2);
    await workflows.history();
    await page.getByRole("button", { name: "View v1" }).first().click();
    await expect(
      page.getByRole("heading", { name: "Weekly pipeline report" }),
    ).toBeVisible();
  });
  test("loading the current revision names what another save changed", async ({
    page,
  }) => {
    await support.intercept(MOCK_AGENT_ID, { saved: true });
    const workflows = new WorkflowsPage(page);
    await workflows.goto(MOCK_AGENT_ID, TEST_ORG_ID, WORKFLOW_ID);
    await page.getByRole("button", { name: "Edit workflow" }).click();
    await page.getByLabel("Workflow name").fill("My edited report");
    support.conflictSave = true;
    support.conflictDescription = "Owner rewrote the outcome";
    await workflows.save();
    await page
      .getByRole("button", { name: "Load current revision and keep my edits" })
      .click();
    const notice = page.getByRole("status").filter({
      hasText: "Current revision loaded",
    });
    await expect(notice).toContainText("Owner rewrote the outcome");
    await expect(
      page.getByRole("alert", { name: "Workflow error" }),
    ).toHaveCount(0);
  });
  test("a failed capabilities refresh keeps the tab and the draft", async ({
    page,
  }) => {
    await support.intercept(MOCK_AGENT_ID, { saved: true });
    const workflows = new WorkflowsPage(page);
    await workflows.goto(MOCK_AGENT_ID, TEST_ORG_ID, WORKFLOW_ID);
    await page.getByRole("button", { name: "Edit workflow" }).click();
    await page.getByLabel("Workflow name").fill("My edited report");
    support.failCapabilities = true;
    support.conflictSave = true;
    await workflows.save();
    // The refresh is retried before it reports failure.
    await expect(
      page.getByText("We couldn’t load authoring availability"),
    ).toBeVisible();
    await expect(section(page, "Workflows")).toBeVisible();
    await expect(page.getByLabel("Workflow name")).toHaveValue(
      "My edited report",
    );
  });
  test("losing save authority disables Save after the first refusal", async ({
    page,
  }) => {
    await support.intercept(MOCK_AGENT_ID);
    const workflows = new WorkflowsPage(page);
    await workflows.goto(MOCK_AGENT_ID, TEST_ORG_ID);
    await workflows.create("Summarize weekly pipeline changes");
    await workflows.buildExample();
    support.forbidSave = true;
    await new DataSupport(page).agents.interceptGetAgentRequest({
      body: { ...mockAgent, allowed_actions: ["agent.read"] },
    });
    await workflows.save();
    await expect(
      page.getByRole("button", { name: "Save workflow", exact: true }),
    ).toBeDisabled();
    await expect(page.getByLabel("Workflow name")).toBeDisabled();
    expect(support.saveRequests).toHaveLength(1);
  });
  test("opens a definition whose text uses the API's code-point limit", async ({
    page,
  }) => {
    await support.intercept(MOCK_AGENT_ID, {
      saved: true,
      viewer: true,
      description: "😀".repeat(4000),
    });
    await new WorkflowsPage(page).goto(MOCK_AGENT_ID, TEST_ORG_ID, WORKFLOW_ID);
    await expect(
      page.getByRole("heading", { name: "Weekly pipeline report" }),
    ).toBeVisible();
    await expect(page.getByText("Response validation failed")).toHaveCount(0);
  });
  test("reads only visible views and reuses the save response instead of rereading", async ({
    page,
  }) => {
    await support.intercept(MOCK_AGENT_ID, { saved: true });
    const workflows = new WorkflowsPage(page);
    await workflows.goto(MOCK_AGENT_ID, TEST_ORG_ID, WORKFLOW_ID);
    await expect(
      page.getByRole("heading", { name: "Weekly pipeline report" }),
    ).toBeVisible();
    expect(support.reads).toEqual({ list: 0, detail: 1, versions: 0 });
    await workflows.history();
    await expect(page.getByRole("button", { name: "View v1" })).toBeVisible();
    expect(support.reads.versions).toBe(1);
    await page.getByRole("tab", { name: "Overview" }).click();
    await page.getByRole("button", { name: "Edit workflow" }).click();
    await page.getByLabel("Workflow name").fill("Renamed report");
    await workflows.save();
    await expect(
      page.getByRole("heading", { name: "Renamed report" }),
    ).toBeVisible();
    await expect(
      page.getByText("Saved v2", { exact: false }).first(),
    ).toBeVisible();
    expect(support.reads).toEqual({ list: 0, detail: 1, versions: 1 });
    await workflows.history();
    await expect(page.getByRole("button", { name: "View v2" })).toBeVisible();
    expect(support.reads.versions).toBe(2);
    await page.getByRole("button", { name: "All workflows" }).click();
    const card = page.getByRole("button", { name: "Open Renamed report" });
    await expect(card).toContainText("v2");
    await expect(card).toContainText("2 steps");
    expect(support.reads.list).toBe(1);
    await card.click();
    await expect(
      page.getByRole("heading", { name: "Renamed report" }),
    ).toBeVisible();
    expect(support.reads.detail).toBe(1);
  });
  test("list pagination survives reload and returning from a workflow", async ({
    page,
  }) => {
    await support.intercept(MOCK_AGENT_ID, { saved: true, paginated: true });
    const workflows = new WorkflowsPage(page);
    await workflows.goto(MOCK_AGENT_ID, TEST_ORG_ID);
    await expect(
      page.getByRole("button", { name: "Open Account briefs" }),
    ).toBeVisible();
    await page.getByRole("button", { name: "Next", exact: true }).click();
    await expect(page).toHaveURL(/workflowPage=2/);
    await expect(
      page.getByRole("button", { name: "Open Weekly pipeline report" }),
    ).toBeVisible();
    await page.reload();
    await expect(page.getByText("Page 2", { exact: true })).toBeVisible();
    expect(support.readPages.list.at(-1)).toBe(2);
    await page
      .getByRole("button", { name: "Open Weekly pipeline report" })
      .click();
    await expect(
      page.getByRole("heading", { name: "Weekly pipeline report" }),
    ).toBeVisible();
    await page.getByRole("button", { name: "All workflows" }).click();
    await expect(page.getByText("Page 2", { exact: true })).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Next", exact: true }),
    ).toBeDisabled();
    await page.getByRole("button", { name: "Previous", exact: true }).click();
    await expect(
      page.getByRole("button", { name: "Open Account briefs" }),
    ).toBeVisible();
    await expect(page).not.toHaveURL(/workflowPage=/);
    await page.goto(
      `/dashboard/${TEST_ORG_ID}/agents/${MOCK_AGENT_ID}?tab=workflows&workflowPage=99`,
    );
    await expect(
      page.getByRole("heading", { name: "No workflows on this page" }),
    ).toBeVisible();
    await page.getByRole("button", { name: "Return to first page" }).click();
    await expect(
      page.getByRole("button", { name: "Open Account briefs" }),
    ).toBeVisible();
    await expect(page).not.toHaveURL(/workflowPage=/);
  });
  test("history pagination survives reload and invalid page parameters use page one", async ({
    page,
  }) => {
    await support.intercept(MOCK_AGENT_ID, { saved: true, paginated: true });
    const workflows = new WorkflowsPage(page);
    await workflows.goto(MOCK_AGENT_ID, TEST_ORG_ID, WORKFLOW_ID);
    await workflows.history();
    await page.getByRole("button", { name: "Next versions" }).click();
    await expect(page).toHaveURL(/workflowVersionPage=2/);
    await expect(page.getByRole("button", { name: "View v1" })).toBeVisible();
    await page.reload();
    await workflows.history();
    await expect(page.getByText("Page 2", { exact: true })).toBeVisible();
    expect(support.readPages.versions.at(-1)).toBe(2);
    await page.goto(
      `/dashboard/${TEST_ORG_ID}/agents/${MOCK_AGENT_ID}?tab=workflows&workflowPage=-2&workflowVersionPage=9007199254740992&workflow=${WORKFLOW_ID}`,
    );
    await workflows.history();
    await expect(page.getByText("Page 1", { exact: true })).toBeVisible();
    expect(support.readPages.versions.at(-1)).toBe(1);
    await page.getByRole("button", { name: "All workflows" }).click();
    await expect(
      page.getByRole("button", { name: "Open Account briefs" }),
    ).toBeVisible();
    expect(support.readPages.list.at(-1)).toBe(1);
  });
  test("Viewer inspects history with no authoring controls", async ({
    page,
  }) => {
    const data = new DataSupport(page);
    await data.agents.interceptGetAgentRequest({
      body: {
        ...mockAgent,
        allowed_actions: ["agent.read", "activity.read", "cost.read"],
      },
    });
    await support.intercept(MOCK_AGENT_ID, { saved: true, viewer: true });
    const workflows = new WorkflowsPage(page);
    await workflows.goto(MOCK_AGENT_ID, TEST_ORG_ID, WORKFLOW_ID);
    await expect(
      page.getByText("Read-only access.", { exact: false }),
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Edit workflow" }),
    ).toHaveCount(0);
    await workflows.history();
    await expect(page.getByRole("button", { name: "View v1" })).toBeVisible();
  });
  test("mobile and keyboard editing use branded discard confirmation", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    const workflows = new WorkflowsPage(page);
    await workflows.goto(MOCK_AGENT_ID, TEST_ORG_ID);
    await workflows.create("A report");
    await page.getByLabel("Workflow name").focus();
    await page.keyboard.type("Keyboard plan");
    await page.getByRole("button", { name: "Discard", exact: true }).click();
    await expect(page.getByRole("dialog")).toContainText(
      "Discard unsaved changes?",
    );
    await page
      .getByRole("dialog")
      .getByRole("button", { name: "Cancel", exact: true })
      .click();
    await expect(page.getByLabel("Workflow name")).toHaveValue("Keyboard plan");
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBe(true);
  });
  test("in-app Organization switching drops drafts and cannot reuse cached definitions", async ({
    page,
  }) => {
    const otherId = "99999999-9999-4999-8999-999999999999";
    await support.enableOrganizationSwitch(otherId);
    await new DataSupport(page).agents.interceptGetAgentsRequest();
    await support.intercept(MOCK_AGENT_ID, {
      saved: true,
      organizationId: TEST_ORG_ID,
    });
    const other = new WorkflowDataSupport(page);
    await other.intercept(MOCK_AGENT_ID, {
      saved: false,
      organizationId: otherId,
    });
    const workflows = new WorkflowsPage(page);
    await workflows.goto(MOCK_AGENT_ID, TEST_ORG_ID);
    await expect(
      page.getByRole("button", { name: "Open Weekly pipeline report" }),
    ).toBeVisible();
    await workflows.create("Private unsaved outcome");
    await workflows.switchOrganization("Globex");
    // An Agent's page names the old Organization's Agent, so the switch lands on the team.
    await expect(page).toHaveURL(new RegExp(`/dashboard/${otherId}$`));
    await expect(page.getByLabel("Description (optional)")).toHaveCount(0);
    // Back to the same Agent in the other Organization, in-app so the query cache stays.
    await page.getByRole("link", { name: "View Maya", exact: true }).click();
    await section(page, "Workflows").click();
    await expect(
      page.getByRole("heading", { name: "No workflows yet" }),
    ).toBeVisible();
    await expect(page.getByLabel("Description (optional)")).toHaveCount(0);
    await expect(
      page.getByRole("button", { name: "Open Weekly pipeline report" }),
    ).toHaveCount(0);
  });
  test("archive retains history and removes authoring controls", async ({
    page,
  }) => {
    await support.intercept(MOCK_AGENT_ID, { saved: true });
    const workflows = new WorkflowsPage(page);
    await workflows.goto(MOCK_AGENT_ID, TEST_ORG_ID, WORKFLOW_ID);
    await workflows.archive();
    await page
      .getByRole("dialog")
      .getByRole("button", { name: "Archive workflow", exact: true })
      .click();
    await expect(
      page.getByText("Saved v1 · Archived", { exact: false }),
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Edit workflow" }),
    ).toHaveCount(0);
    await workflows.history();
    await expect(page.getByRole("button", { name: "View v1" })).toBeVisible();
  });
  test("lost access replaces protected workflow detail", async ({ page }) => {
    await support.intercept(MOCK_AGENT_ID, { saved: true });
    const workflows = new WorkflowsPage(page);
    await workflows.goto(MOCK_AGENT_ID, TEST_ORG_ID, WORKFLOW_ID);
    await expect(
      page.getByRole("heading", { name: "Weekly pipeline report" }),
    ).toBeVisible();
    support.denyAccess = true;
    await page.reload();
    await expect(
      page.getByText("We couldn’t load workflows", { exact: true }),
    ).toBeVisible();
    await expect(
      page.getByRole("heading", { name: "Weekly pipeline report" }),
    ).toHaveCount(0);
  });
  test("API-compatible GUID step identities render for saved versions", async ({
    page,
  }) => {
    await support.intercept(MOCK_AGENT_ID, {
      saved: true,
      stepId: "11111111-1111-1111-1111-111111111111",
    });
    const workflows = new WorkflowsPage(page);
    await workflows.goto(MOCK_AGENT_ID, TEST_ORG_ID, WORKFLOW_ID);
    await expect(
      page.getByRole("heading", { name: "Weekly pipeline report" }),
    ).toBeVisible();
    await page.getByRole("button", { name: "Edit workflow" }).click();
    await expect(page.getByLabel("Workflow name")).toHaveValue(
      "Weekly pipeline report",
    );
  });
  test("URL changes cannot redirect a new draft into an existing workflow", async ({
    page,
  }) => {
    await support.intercept(MOCK_AGENT_ID, { saved: true });
    const workflows = new WorkflowsPage(page);
    await workflows.goto(MOCK_AGENT_ID, TEST_ORG_ID, WORKFLOW_ID);
    await page.getByRole("button", { name: "Edit workflow" }).click();
    await page.getByRole("button", { name: "Discard", exact: true }).click();
    await page
      .getByRole("dialog")
      .getByRole("button", { name: "Discard changes" })
      .click();
    await page.getByRole("button", { name: "All workflows" }).click();
    await workflows.create("A separate new report");
    await workflows.buildExample();
    await expect(page.getByLabel("Workflow name")).toBeVisible();
    await page.evaluate((id) => {
      const query = new URLSearchParams(window.location.search);
      query.set("workflow", id);
      window.history.pushState(
        null,
        "",
        `${window.location.pathname}?${query}`,
      );
    }, WORKFLOW_ID);
    await workflows.save();
    expect(support.savePaths.at(-1)).toMatch(/\/workflows$/);
    expect(support.saveRequests.at(-1)).not.toHaveProperty("expected_revision");
  });
  test("focused sections retain edits and reordered step identity in the saved plan", async ({
    page,
  }) => {
    await support.intercept(MOCK_AGENT_ID, { saved: true });
    const workflows = new WorkflowsPage(page);
    await workflows.goto(MOCK_AGENT_ID, TEST_ORG_ID, WORKFLOW_ID);
    await expect(
      page.getByRole("heading", { name: "Read pipeline", exact: true }),
    ).toBeVisible();
    const second = page
      .getByRole("navigation", { name: "Workflow sections" })
      .getByRole("button", { name: "Step 2: Prepare summary" });
    await second.focus();
    await page.keyboard.press("Enter");
    await expect(
      page.getByRole("heading", { name: "Prepare summary", exact: true }),
    ).toBeVisible();
    await expect(second).toHaveAttribute("aria-current", "step");
    await page.getByRole("button", { name: "Edit workflow" }).click();
    await workflows.selectStep(1);
    await workflows
      .step(1)
      .getByLabel("What should the Agent do?")
      .fill("Collect this week's pipeline changes");
    await workflows.selectSection("Required inputs");
    await page.getByLabel("Input 1 label").fill("Week to report");
    await workflows.selectStep(1);
    await workflows.step(1).getByLabel("Output from this step (optional)").fill("A reviewed weekly summary");
    await workflows.selectStep(1);
    await expect(
      workflows.step(1).getByLabel("What should the Agent do?"),
    ).toHaveValue("Collect this week's pipeline changes");
    await workflows
      .step(1)
      .getByRole("button", { name: "↓ Move down" })
      .click();
    await expect(
      page.getByRole("button", { name: "Step 2: Read pipeline" }),
    ).toHaveAttribute("aria-current", "step");
    await expect(
      workflows.step(2).getByLabel("What should the Agent do?"),
    ).toHaveValue("Collect this week's pipeline changes");
    await workflows.save();
    await workflows.selectStep(2);
    await expect(
      page.getByText("Collect this week's pipeline changes", { exact: true }),
    ).toBeVisible();
    await workflows.selectSection("Required inputs");
    await expect(
      page.getByRole("heading", { name: "Week to report" }),
    ).toBeVisible();
    await workflows.selectStep(2);
    await expect(
      page.getByText("A reviewed weekly summary", { exact: true }),
    ).toBeVisible();
    expect(support.saveRequests.at(-1)).toMatchObject({
      draft: {
        inputs: [{ label: "Week to report" }],
        steps: [{}, { artifact_description: "A reviewed weekly summary" }],
      },
    });
  });
  test("save opens the hidden invalid step with human field labels and retains edits", async ({
    page,
  }) => {
    const workflows = new WorkflowsPage(page);
    await workflows.goto(MOCK_AGENT_ID, TEST_ORG_ID);
    await workflows.create("Report pipeline changes");
    await workflows.buildExample();
    await page.getByRole("button", { name: "Add a step" }).click();
    await workflows
      .step(3)
      .getByLabel("Step 3", { exact: true })
      .fill("Review the summary");
    await workflows.selectSection("Workflow details");
    await workflows.save();
    const error = page.getByRole("alert", { name: "Workflow error" });
    await expect(error).toContainText("Step 3 · What should the Agent do?");
    await expect(
      workflows.step(3).getByLabel("Step 3", { exact: true }),
    ).toHaveValue("Review the summary");
    await expect(
      page.getByRole("button", { name: "Step 3: Review the summary" }),
    ).toHaveAttribute("aria-current", "step");
    await expect(
      workflows.step(3).getByLabel("What should the Agent do?"),
    ).toHaveAccessibleDescription("Enter a description");
    expect(support.saveRequests).toHaveLength(0);
    await workflows
      .step(3)
      .getByLabel("What should the Agent do?")
      .fill("Review changes for clarity");
    await workflows.save();
    expect(support.saveRequests).toHaveLength(1);
  });
  test("input and output errors link to their hidden panels without submitting", async ({
    page,
  }) => {
    const workflows = new WorkflowsPage(page);
    await workflows.goto(MOCK_AGENT_ID, TEST_ORG_ID);
    await workflows.create("Prepare a report");
    await workflows.buildExample();
    await workflows.selectSection("Required inputs");
    await page.getByRole("button", { name: "+ Add an input" }).click();
    await page.getByLabel("Input 2 description").fill("The report owner");
    await workflows.selectSection("Workflow details");
    await workflows.save();
    const error = page.getByRole("alert", { name: "Workflow error" });
    await expect(error).toContainText("Input 2 · Label: Enter a name");
    await expect(page.getByLabel("Input 2 label")).toBeVisible();
    await expect(page.getByLabel("Input 2 label")).toHaveAttribute(
      "aria-invalid",
      "true",
    );
    await error.getByRole("button", { name: /^Input 2 · Label:/ }).click();
    expect(support.saveRequests).toHaveLength(0);
    await page.getByLabel("Input 2 label").fill("Owner");
    await workflows.save();
    expect(support.saveRequests).toHaveLength(1);
  });
  test("server validation errors use the same panel labels and preserve the draft", async ({
    page,
  }) => {
    await support.intercept(MOCK_AGENT_ID, { saved: true });
    const workflows = new WorkflowsPage(page);
    await workflows.goto(MOCK_AGENT_ID, TEST_ORG_ID, WORKFLOW_ID);
    await page.getByRole("button", { name: "Edit workflow" }).click();
    support.validationSaveErrors = [
      {
        loc: ["body", "draft", "steps", 1, "goal"],
        msg: "Clarify the goal",
      },
    ];
    await workflows.save();
    await expect(
      page.getByRole("alert", { name: "Workflow error" }),
    ).toContainText(
      "Step 2 · What should the Agent do?: Clarify the goal",
    );
    await expect(
      workflows.step(2).getByLabel("What should the Agent do?"),
    ).toHaveValue(workflowDraft.steps[1].goal);
    await workflows
      .step(2)
      .getByLabel("What should the Agent do?")
      .fill("All changes and risks are clearly summarized");
    await workflows.save();
    expect(support.saveRequests).toHaveLength(2);
    expect(support.saveRequests[1]).toMatchObject({
      draft: { inputs: [{ key: "period", label: "Reporting period" }] },
    });
  });
  test("an old blank completion criterion does not block editing and saving", async ({ page }) => {
    await support.intercept(MOCK_AGENT_ID, { saved: true, emptyCriteria: true });
    const workflows = new WorkflowsPage(page);
    await workflows.goto(MOCK_AGENT_ID, TEST_ORG_ID, WORKFLOW_ID);
    await page.getByRole("button", { name: "Edit workflow" }).click();
    await workflows.save();
    expect(support.saveRequests).toHaveLength(1);
    await expect(page.getByRole("alert", { name: "Workflow error" })).toHaveCount(0);
  });
  test("loss of save authority disables edits while retaining draft section navigation", async ({
    page,
  }) => {
    await support.intercept(MOCK_AGENT_ID, { saved: true });
    const workflows = new WorkflowsPage(page);
    await workflows.goto(MOCK_AGENT_ID, TEST_ORG_ID, WORKFLOW_ID);
    await page.getByRole("button", { name: "Edit workflow" }).click();
    await workflows.selectStep(2);
    await workflows
      .step(2)
      .getByLabel("What should the Agent do?")
      .fill("My retained summary instructions");
    support.conflictSave = true;
    await workflows.save();
    support.saveAllowed = false;
    await page
      .getByRole("button", { name: "Load current revision and keep my edits" })
      .click();
    await workflows.selectSection("Workflow details");
    await expect(page.getByLabel("Workflow name")).toBeDisabled();
    await workflows.selectStep(2);
    await expect(
      workflows.step(2).getByLabel("What should the Agent do?"),
    ).toHaveValue("My retained summary instructions");
    await expect(
      workflows.step(2).getByLabel("What should the Agent do?"),
    ).toBeDisabled();
    await expect(
      page.getByRole("button", { name: "Save workflow", exact: true }),
    ).toBeDisabled();
    await expect(page.getByRole("button", { name: "Add a step" })).toHaveCount(
      0,
    );
    expect(support.saveRequests).toHaveLength(1);
  });
  test("Workflows lives in the Agent tab bar and existing links preserve the selected workflow", async ({
    page,
  }) => {
    await support.intercept(MOCK_AGENT_ID, { saved: true });
    await page.goto(
      `/dashboard/${TEST_ORG_ID}/agents/${MOCK_AGENT_ID}/workflows?workflow=${WORKFLOW_ID}`,
    );
    await expect(page).toHaveURL(
      new RegExp(`tab=workflows&workflow=${WORKFLOW_ID}`),
    );
    await expect(section(page, "Workflows")).toHaveAttribute("aria-current", "page");
    await expect(section(page, "Memory")).toBeVisible();
    await expect(
      page.getByRole("heading", {
        name: "Weekly pipeline report",
        exact: true,
      }),
    ).toBeVisible();
    await section(page, "Overview").click();
    await expect(page).not.toHaveURL(/workflow=/);
    await section(page, "Workflows").click();
    await expect(
      page.getByRole("button", { name: "Open Weekly pipeline report" }),
    ).toBeVisible();
  });
  test("Agent read permission exposes Workflows without requiring activity access", async ({
    page,
  }) => {
    const data = new DataSupport(page);
    await data.agents.interceptGetAgentRequest({
      body: { ...mockAgent, allowed_actions: ["agent.read"] },
    });
    await support.intercept(MOCK_AGENT_ID, { saved: true, viewer: true });
    const workflows = new WorkflowsPage(page);
    await workflows.goto(MOCK_AGENT_ID, TEST_ORG_ID, WORKFLOW_ID);
    await expect(section(page, "Workflows")).toHaveAttribute("aria-current", "page");
    await expect(section(page, "Memory")).toHaveCount(0);
    await expect(
      page.getByRole("heading", {
        name: "Weekly pipeline report",
        exact: true,
      }),
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Edit workflow" }),
    ).toHaveCount(0);
  });
});
