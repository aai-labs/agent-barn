import { expect, test } from "@playwright/test";

import { TEST_ORG_ID } from "../constants";
import { WORKFLOW_ID, workflowDraft } from "../fixtures/workflows";
import { WorkflowsPage } from "../pages/workflows-page.po";
import {
  MOCK_AGENT_ID,
  mockAgent,
} from "../pages/data-support/agent-data-support.po";
import { DataSupport } from "../pages/data-support/data-support.po";
import { WorkflowDataSupport } from "../pages/data-support/workflow-data-support.po";

const NAME = workflowDraft.name;
type SavedDraft = {
  name: string;
  steps: { name: string; goal: string; artifact_description: string | null }[];
  inputs: { key: string; label: string; type: string }[];
};
const draftOf = (request: Record<string, unknown>) => request.draft as SavedDraft;

test.describe("WF01 Organization workflow authoring", () => {
  test.use({ storageState: { cookies: [], origins: [] } });
  let support: WorkflowDataSupport;
  test.beforeEach(async ({ page }) => {
    const data = new DataSupport(page);
    await data.auth.interceptRefreshRequest();
    await data.users.interceptGetUserContextRequest();
    await data.users.interceptGetOrganizationsRequest();
    await data.agents.interceptGetAgentRequest({ body: mockAgent });
    await data.agents.interceptGetAgentsRequest();
    support = new WorkflowDataSupport(page);
    await support.intercept(MOCK_AGENT_ID);
  });

  test("Workflows is an Organization destination and the Agent keeps only its runs", async ({
    page,
  }) => {
    await support.intercept(MOCK_AGENT_ID, { saved: true });
    const workflows = new WorkflowsPage(page);
    await page.goto(`/dashboard/${TEST_ORG_ID}/agents/${MOCK_AGENT_ID}?tab=workflows`);
    await expect(workflows.sectionLink("Workflows")).toHaveAttribute("aria-current", "page");
    // Workflows are created and edited for the Organization, never on an Agent's page.
    await expect(page.getByRole("button", { name: "New workflow" })).toHaveCount(0);
    await expect(page.getByRole("tab", { name: "Workflows" })).toHaveCount(0);
    await expect(page.getByRole("link", { name: "Run a workflow" })).toHaveAttribute(
      "href",
      new RegExp(`/dashboard/${TEST_ORG_ID}/workflows\\?.*agent=${MOCK_AGENT_ID}`),
    );
    await workflows.railLink().click();
    await expect(page).toHaveURL(new RegExp(`/dashboard/${TEST_ORG_ID}/workflows`));
    await expect(page.getByRole("heading", { name: "Workflows", level: 1 })).toBeVisible();
    await page.getByRole("tab", { name: "Workflows", exact: true }).click();
    await expect(workflows.card(NAME)).toBeVisible();
  });

  test("disabled workflows hide the destination, the Agent section and creation", async ({
    page,
  }) => {
    await support.intercept(MOCK_AGENT_ID, { saved: true, authoring: false });
    const workflows = new WorkflowsPage(page);
    const capability = page.waitForResponse((response) =>
      response.url().endsWith("/workflow-capabilities"),
    );
    await page.goto(`/dashboard/${TEST_ORG_ID}/agents/${MOCK_AGENT_ID}?tab=workflows`);
    await expect(workflows.sectionLink("Overview")).toHaveAttribute("aria-current", "page");
    expect((await (await capability).json()).authoring).toBe(false);
    await expect(workflows.sectionLink("Workflows")).toHaveCount(0);
    await expect(workflows.railLink()).toHaveCount(0);
    await workflows.goto();
    await expect(
      page.getByText("Workflow authoring is disabled for this installation."),
    ).toBeVisible();
    await expect(page.getByRole("button", { name: "New workflow" })).toHaveCount(0);
  });

  test("an old link to an Agent's saved workflow opens it for the Organization", async ({
    page,
  }) => {
    await support.intercept(MOCK_AGENT_ID, { saved: true });
    await page.goto(
      `/dashboard/${TEST_ORG_ID}/agents/${MOCK_AGENT_ID}/workflows?workflow=${WORKFLOW_ID}`,
    );
    await expect(page).toHaveURL(
      new RegExp(`/dashboard/${TEST_ORG_ID}/workflows\\?workflow=${WORKFLOW_ID}`),
    );
    await expect(page.getByRole("heading", { name: NAME })).toBeVisible();
  });

  test("create a workflow from the Organization page with a default Agent", async ({ page }) => {
    const workflows = new WorkflowsPage(page);
    await workflows.goto();
    await workflows.create("Summarize weekly pipeline changes");
    await expect(workflows.editor()).toContainText("New workflow");
    await workflows.buildExample();
    // A step is what the Agent does and produces: no separate output field, no step type.
    await expect(workflows.editor().getByText(/Output from this step/)).toHaveCount(0);
    await expect(workflows.step(1).getByRole("combobox")).toHaveCount(0);
    await expect(workflows.defaultAgent("No default")).toBeChecked();
    await workflows.defaultAgent("Maya").click();
    await workflows.save();
    await expect(page.getByText("Saved v1", { exact: false }).first()).toBeVisible();
    await expect(page.getByRole("heading", { name: NAME })).toBeVisible();
    expect(support.savePaths[0]).toMatch(new RegExp(`/organizations/${TEST_ORG_ID}/workflows$`));
    expect(support.saveRequests[0]).toMatchObject({ default_agent_id: MOCK_AGENT_ID });
    const draft = draftOf(support.saveRequests[0]);
    expect(draft.steps.map((step) => step.name)).toEqual(["Read pipeline", "Prepare summary"]);
    expect(draft.steps.every((step) => step.artifact_description === null)).toBe(true);
    await workflows.backToList();
    await expect(workflows.card(NAME)).toBeVisible();
  });

  test("reorder, remove, undo and save an immutable plan", async ({ page }) => {
    const workflows = new WorkflowsPage(page);
    await workflows.goto();
    await workflows.create("Summarize weekly pipeline changes");
    await workflows.buildExample();
    await workflows.step(1).getByRole("button", { name: "Move step 1 down" }).click();
    await expect(workflows.stepName(1)).toHaveValue("Prepare summary");
    await workflows.step(2).getByRole("button", { name: "Remove step 2" }).click();
    await expect(workflows.step(2)).toHaveCount(0);
    await workflows.editor().getByRole("button", { name: "Undo removal" }).click();
    await expect(workflows.stepInstructions(2)).toHaveValue("Read this week's pipeline");
    await workflows.addStep();
    await workflows.stepName(3).fill("Review report");
    await workflows.stepInstructions(3).fill("Review the report for clarity");
    await workflows.save();
    await expect(page.getByText("Saved v1", { exact: false }).first()).toBeVisible();
    expect(support.saveRequests).toHaveLength(1);
    expect(draftOf(support.saveRequests[0]).steps.map((step) => step.name)).toEqual([
      "Prepare summary",
      "Read pipeline",
      "Review report",
    ]);
  });

  test("removing every step disables saving until one is restored", async ({ page }) => {
    const workflows = new WorkflowsPage(page);
    await workflows.goto();
    await workflows.create("A report");
    await workflows.name().fill("Solo plan");
    await workflows.stepName(1).fill("Only step");
    await workflows.step(1).getByRole("button", { name: "Remove step 1" }).click();
    await expect(workflows.saveButton()).toBeDisabled();
    await expect(workflows.editor()).toContainText("needs at least one step");
    await workflows.editor().getByRole("button", { name: "Undo removal" }).click();
    await expect(workflows.stepName(1)).toHaveValue("Only step");
    await expect(workflows.saveButton()).toBeEnabled();
  });

  test("cards show the plan, its default Agent and the runs the viewer can see", async ({ page }) => {
    support.defaultAgentId = MOCK_AGENT_ID;
    support.runCount = 12;
    await support.intercept(MOCK_AGENT_ID, { saved: true });
    const workflows = new WorkflowsPage(page);
    await workflows.goto();
    const card = workflows.card(NAME);
    await expect(card).toContainText("v1");
    await expect(card).toContainText("Summarize weekly pipeline changes");
    await expect(card).toContainText("Maya");
    await expect(card).toContainText("12 runs");
    await expect(card).not.toContainText("Created by");
    await expect(card.getByRole("button", { name: `Run ${NAME}` })).toHaveText("Run");
    await card.getByRole("button", { name: `Actions for ${NAME}` }).click();
    await expect(page.getByRole("menuitem")).toHaveText([
      "Edit",
      "Duplicate",
      "Open latest run",
      "Archive",
    ]);
    // Rows keep their label on one line rather than wrapping to the trigger's width.
    const latest = await page.getByRole("menuitem", { name: "Open latest run" }).boundingBox();
    const edit = await page.getByRole("menuitem", { name: "Edit" }).boundingBox();
    expect(latest!.height).toBeLessThan(edit!.height * 1.25);
    await page.keyboard.press("Escape");
    await workflows.open(NAME);
    await expect(page.getByRole("heading", { name: NAME })).toBeVisible();
    await expect(page.getByText("Created by Dana Creator", { exact: false })).toBeVisible();
  });

  test("a card without a default Agent offers to assign one when run", async ({ page }) => {
    await support.intercept(MOCK_AGENT_ID, { saved: true });
    const workflows = new WorkflowsPage(page);
    await workflows.goto();
    const card = workflows.card(NAME);
    await expect(card).toContainText("Unassigned");
    await expect(card).toContainText("0 runs");
    await expect(card.getByRole("button", { name: `Run ${NAME}` })).toHaveText("Assign & run");
  });

  test("a Member who did not create a workflow can read, run and duplicate it, not change it", async ({
    page,
  }) => {
    await support.intercept(MOCK_AGENT_ID, { saved: true, viewer: true });
    const workflows = new WorkflowsPage(page);
    await workflows.goto();
    await workflows.card(NAME).getByRole("button", { name: `Actions for ${NAME}` }).click();
    await expect(page.getByRole("menuitem")).toHaveText(["Duplicate", "Open latest run"]);
    await page.keyboard.press("Escape");
    await workflows.open(NAME);
    await expect(page.getByRole("button", { name: "Edit workflow" })).toHaveCount(0);
    await workflows.history();
    await expect(page.getByRole("button", { name: "View v1" })).toBeVisible();
  });

  test("Duplicate opens a copy that saves as a new workflow", async ({ page }) => {
    await support.intercept(MOCK_AGENT_ID, { saved: true, viewer: true });
    const workflows = new WorkflowsPage(page);
    await workflows.goto();
    await workflows.cardAction(NAME, "Duplicate");
    await expect(workflows.editor()).toContainText("Duplicate workflow");
    await expect(workflows.name()).toHaveValue(`${NAME} (copy)`);
    await expect(workflows.stepName(2)).toHaveValue("Prepare summary");
    await workflows.save();
    expect(support.savePaths[0]).toMatch(/\/workflows$/);
    expect(draftOf(support.saveRequests[0]).name).toBe(`${NAME} (copy)`);
  });

  test("editing folds a step's earlier output text into what the Agent does", async ({ page }) => {
    await support.intercept(MOCK_AGENT_ID, { saved: true });
    const workflows = new WorkflowsPage(page);
    await workflows.goto(TEST_ORG_ID, WORKFLOW_ID);
    await workflows.edit();
    await expect(workflows.editor()).toContainText("Refine the workflow");
    await expect(workflows.stepInstructions(1)).toHaveValue(
      "Read this week's pipeline\n\nOutput: Source data",
    );
    await expect(workflows.stepInstructions(2)).toHaveValue("Summarize changes and risks");
    await workflows.name().fill("Renamed report");
    await workflows.save();
    await expect(page.getByRole("heading", { name: "Renamed report" })).toBeVisible();
    await expect(page.getByText("Saved v2", { exact: false }).first()).toBeVisible();
    expect(support.savePaths[0]).toMatch(new RegExp(`/workflows/${WORKFLOW_ID}/versions$`));
    expect(support.saveRequests[0]).toMatchObject({ expected_revision: 1 });
    expect(draftOf(support.saveRequests[0]).steps[0]).toMatchObject({
      goal: "Read this week's pipeline\n\nOutput: Source data",
      artifact_description: null,
    });
    expect(support.updateRequests).toHaveLength(0);
  });

  test("changing only the default Agent saves no new version", async ({ page }) => {
    await support.intercept(MOCK_AGENT_ID, { saved: true });
    const workflows = new WorkflowsPage(page);
    await workflows.goto(TEST_ORG_ID, WORKFLOW_ID);
    await workflows.edit();
    await workflows.defaultAgent("Maya").click();
    await workflows.save();
    await expect(workflows.editor()).toHaveCount(0);
    expect(support.saveRequests).toHaveLength(0);
    expect(support.updateRequests).toEqual([
      { expected_revision: 1, default_agent_id: MOCK_AGENT_ID },
    ]);
    await expect(page.getByText("Saved v1", { exact: false }).first()).toBeVisible();
    // The default is shown again when the editor reopens.
    await workflows.edit();
    await expect(workflows.defaultAgent("Maya")).toBeChecked();
    // Saving with nothing changed sends nothing.
    await workflows.save();
    await expect(workflows.editor()).toHaveCount(0);
    expect(support.updateRequests).toHaveLength(1);
    expect(support.saveRequests).toHaveLength(0);
  });

  test("a changed plan and default Agent save a version, then the default", async ({ page }) => {
    await support.intercept(MOCK_AGENT_ID, { saved: true });
    const workflows = new WorkflowsPage(page);
    await workflows.goto(TEST_ORG_ID, WORKFLOW_ID);
    await workflows.edit();
    await workflows.name().fill("Renamed report");
    await workflows.defaultAgent("Maya").click();
    await workflows.save();
    await expect(page.getByRole("heading", { name: "Renamed report" })).toBeVisible();
    expect(support.saveRequests).toHaveLength(1);
    expect(support.updateRequests).toEqual([
      { expected_revision: 2, default_agent_id: MOCK_AGENT_ID },
    ]);
  });

  test("input keys follow labels and file inputs save", async ({ page }) => {
    const workflows = new WorkflowsPage(page);
    await workflows.goto();
    await workflows.create("Prepare a report");
    await workflows.buildExample();
    await expect(workflows.editor().getByLabel("Input 1 key")).toHaveCount(0);
    await workflows.editor().getByLabel("Input 1 label").fill("  Sales   Region  ");
    await workflows.useFileInput();
    await workflows.save();
    await expect(page.getByText("Saved v1", { exact: false }).first()).toBeVisible();
    expect(draftOf(support.saveRequests[0]).inputs[0]).toMatchObject({
      key: "sales-region",
      type: "file",
    });
  });

  test("similar labels name the colliding input, and distinct ones save", async ({ page }) => {
    const workflows = new WorkflowsPage(page);
    await workflows.goto();
    await workflows.create("Prepare a report");
    await workflows.buildExample();
    await workflows.addInput();
    await workflows.editor().getByLabel("Input 2 label").fill("Reporting-period!");
    await workflows.editor().getByLabel("Input 2 description").fill("The report owner");
    await workflows.save();
    await expect(workflows.error()).toContainText(
      "Input 2 · Label: Matches input 1 once case, accents and punctuation are ignored",
    );
    await expect(workflows.editor().getByLabel("Input 2 label")).toHaveValue("Reporting-period!");
    expect(support.saveRequests).toHaveLength(0);
    await workflows.editor().getByLabel("Input 2 label").fill("2nd owner's e-mail (Café)");
    await workflows.save();
    await expect(page.getByText("Saved v1", { exact: false }).first()).toBeVisible();
    expect(draftOf(support.saveRequests[0]).inputs.map((input) => input.key)).toEqual([
      "reporting-period",
      "input-2nd-owners-e-mail-cafe",
    ]);
  });

  test("long and non-Latin input labels retain distinct valid internal keys", async ({ page }) => {
    const workflows = new WorkflowsPage(page);
    await workflows.goto();
    await workflows.create("Prepare a report");
    await workflows.buildExample();
    const labels = [`${"a".repeat(190)} first`, `${"a".repeat(190)} second`, "客户名称", "客户地区"];
    for (const [index, label] of labels.entries()) {
      if (index) await workflows.addInput();
      await workflows.editor().getByLabel(`Input ${index + 1} label`).fill(label);
      await workflows
        .editor()
        .getByLabel(`Input ${index + 1} description`)
        .fill(`Information for input ${index + 1}`);
    }
    await workflows.save();
    await expect(page.getByText("Saved v1", { exact: false }).first()).toBeVisible();
    const inputs = draftOf(support.saveRequests[0]).inputs;
    expect(inputs.map((input) => input.label)).toEqual(labels);
    expect(new Set(inputs.map((input) => input.key)).size).toBe(labels.length);
    for (const input of inputs) expect(input.key).toMatch(/^[a-z][a-z0-9_-]{0,63}$/);
  });

  test("fields explain problems once left, and save names every problem", async ({ page }) => {
    const workflows = new WorkflowsPage(page);
    await workflows.goto();
    await workflows.create();
    await workflows.name().focus();
    await workflows.purpose().focus();
    await expect(workflows.editor().getByText("Enter a name")).toBeVisible();
    expect(support.saveRequests).toHaveLength(0);
    await workflows.name().fill("Named plan");
    await workflows.save();
    await expect(workflows.error()).toContainText("Step 1 · Name: Enter a name");
    await expect(workflows.error()).toContainText(
      "Step 1 · What should the agent do?: Enter a description",
    );
    await expect(workflows.name()).toHaveValue("Named plan");
    expect(support.saveRequests).toHaveLength(0);
  });

  test("validation and save conflicts retain edits and recover explicitly", async ({ page }) => {
    await support.intercept(MOCK_AGENT_ID, { saved: true });
    const workflows = new WorkflowsPage(page);
    await workflows.goto(TEST_ORG_ID, WORKFLOW_ID);
    await workflows.edit();
    await workflows.name().fill("");
    await workflows.save();
    await expect(workflows.error()).toContainText("Enter a name");
    await workflows.name().fill("My edited report");
    support.conflictSave = true;
    support.conflictDescription = "Owner rewrote the outcome";
    await workflows.save();
    await expect(workflows.error()).toContainText("Workflow changed");
    await expect(workflows.name()).toHaveValue("My edited report");
    await workflows
      .editor()
      .getByRole("button", { name: "Load current revision and keep my edits" })
      .click();
    await expect(
      workflows.editor().getByRole("status").filter({ hasText: "Current revision loaded" }),
    ).toContainText("Owner rewrote the outcome");
    await expect(workflows.error()).toHaveCount(0);
    await workflows.save();
    await expect(page.getByRole("heading", { name: "My edited report" })).toBeVisible();
    expect(support.saveRequests.at(-1)?.expected_revision).toBe(2);
    await workflows.history();
    await page.getByRole("button", { name: "View v1" }).first().click();
    await expect(page.getByRole("heading", { name: NAME })).toBeVisible();
  });

  test("server validation errors use the form's labels and preserve the draft", async ({ page }) => {
    await support.intercept(MOCK_AGENT_ID, { saved: true });
    const workflows = new WorkflowsPage(page);
    await workflows.goto(TEST_ORG_ID, WORKFLOW_ID);
    await workflows.edit();
    await workflows.name().fill("Renamed report");
    support.validationSaveErrors = [
      { loc: ["body", "draft", "steps", 1, "goal"], msg: "Clarify the goal" },
    ];
    await workflows.save();
    await expect(workflows.error()).toContainText(
      "Step 2 · What should the agent do?: Clarify the goal",
    );
    await expect(workflows.stepInstructions(2)).toHaveValue(workflowDraft.steps[1].goal);
    await workflows.stepInstructions(2).fill("All changes and risks are clearly summarized");
    await workflows.save();
    expect(support.saveRequests).toHaveLength(2);
    expect(support.saveRequests[1]).toMatchObject({
      draft: { inputs: [{ key: "period", label: "Reporting period" }] },
    });
  });

  test("losing save authority disables the form after the first refusal", async ({ page }) => {
    await support.intercept(MOCK_AGENT_ID, { saved: true });
    const workflows = new WorkflowsPage(page);
    await workflows.goto(TEST_ORG_ID, WORKFLOW_ID);
    await workflows.edit();
    await workflows.name().fill("My edited report");
    support.forbidSave = true;
    support.saveAllowed = false;
    await workflows.save();
    await expect(workflows.error()).toBeVisible();
    await expect(workflows.saveButton()).toBeDisabled();
    await expect(workflows.name()).toHaveValue("My edited report");
    await expect(workflows.name()).toBeDisabled();
  });

  test("a failed capabilities refresh keeps the page and the draft", async ({ page }) => {
    await support.intercept(MOCK_AGENT_ID, { saved: true });
    const workflows = new WorkflowsPage(page);
    await workflows.goto(TEST_ORG_ID, WORKFLOW_ID);
    await workflows.edit();
    await workflows.name().fill("My edited report");
    support.failCapabilities = true;
    support.conflictSave = true;
    await workflows.save();
    await expect(workflows.error()).toContainText("Workflow changed");
    await expect(workflows.name()).toHaveValue("My edited report");
    await expect(workflows.railLink()).toBeVisible();
  });

  test("closing a changed draft asks first, on a phone too", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    const workflows = new WorkflowsPage(page);
    await workflows.goto();
    await workflows.create("A report");
    await workflows.name().focus();
    await page.keyboard.type("Keyboard plan");
    await workflows.editor().getByRole("button", { name: "Cancel", exact: true }).click();
    const confirm = workflows.confirmation(/^Discard unsaved changes\?$/);
    await expect(confirm).toBeVisible();
    await confirm.getByRole("button", { name: "Cancel", exact: true }).click();
    await expect(workflows.name()).toHaveValue("Keyboard plan");
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
    ).toBe(true);
    await workflows.editor().getByRole("button", { name: "Cancel", exact: true }).click();
    await confirm.getByRole("button", { name: "Discard changes" }).click();
    await expect(workflows.editor()).toHaveCount(0);
    expect(support.saveRequests).toHaveLength(0);
  });

  test("archived workflows are one toggle away and the choice survives reload", async ({ page }) => {
    await support.intercept(MOCK_AGENT_ID, { saved: true });
    const workflows = new WorkflowsPage(page);
    await workflows.goto();
    await expect(workflows.card(NAME)).toBeVisible();
    await expect(page.getByText("1 workflow", { exact: true })).toBeVisible();
    expect(support.listQueries.at(-1)).toContain("archived=false");
    expect(support.listQueries.at(-1)).not.toContain("created_by_me");
    await workflows.toggleArchived();
    await expect(page.getByRole("heading", { name: "Nothing here" })).toBeVisible();
    expect(support.listQueries.at(-1)).toContain("archived=true");
    await page.reload();
    await expect(page.getByRole("button", { name: "Back to workflows" })).toBeVisible();
    await workflows.toggleArchived();
    await expect(workflows.card(NAME)).toBeVisible();
  });

  test("archive from a card moves the workflow to Archived and keeps its history", async ({
    page,
  }) => {
    await support.intercept(MOCK_AGENT_ID, { saved: true });
    const workflows = new WorkflowsPage(page);
    await workflows.goto();
    await workflows.cardAction(NAME, "Archive");
    await workflows.confirmArchive();
    await expect(workflows.card(NAME)).toHaveCount(0);
    await workflows.toggleArchived();
    const card = workflows.card(NAME);
    await expect(card).toContainText("Archived");
    await expect(card.getByRole("button", { name: `Run ${NAME}` })).toBeDisabled();
    await workflows.open(NAME);
    await expect(page.getByText("Saved v1 · Archived", { exact: false })).toBeVisible();
    await expect(page.getByRole("button", { name: "Edit workflow" })).toHaveCount(0);
    await workflows.history();
    await expect(page.getByRole("button", { name: "View v1" })).toBeVisible();
  });

  test("archive from the workflow's own page removes authoring controls", async ({ page }) => {
    await support.intercept(MOCK_AGENT_ID, { saved: true });
    const workflows = new WorkflowsPage(page);
    await workflows.goto(TEST_ORG_ID, WORKFLOW_ID);
    await workflows.archive();
    await workflows.confirmArchive();
    await expect(page.getByText("Saved v1 · Archived", { exact: false })).toBeVisible();
    await expect(page.getByRole("button", { name: "Edit workflow" })).toHaveCount(0);
  });

  test("reads only visible views and reuses the save response instead of rereading", async ({
    page,
  }) => {
    await support.intercept(MOCK_AGENT_ID, { saved: true });
    const workflows = new WorkflowsPage(page);
    await workflows.goto(TEST_ORG_ID, WORKFLOW_ID);
    await expect(page.getByRole("heading", { name: NAME })).toBeVisible();
    expect(support.reads).toEqual({ list: 0, detail: 1, versions: 0 });
    await workflows.history();
    await expect(page.getByRole("button", { name: "View v1" })).toBeVisible();
    expect(support.reads.versions).toBe(1);
    await page.getByRole("tab", { name: "Overview" }).click();
    await workflows.edit();
    await workflows.name().fill("Renamed report");
    await workflows.save();
    await expect(page.getByRole("heading", { name: "Renamed report" })).toBeVisible();
    await expect(page.getByText("Saved v2", { exact: false }).first()).toBeVisible();
    expect(support.reads).toEqual({ list: 0, detail: 1, versions: 1 });
    await workflows.backToList();
    const card = workflows.card("Renamed report");
    await expect(card).toContainText("v2");
    expect(support.reads.list).toBe(1);
  });

  test("list pagination survives reload and returning from a workflow", async ({ page }) => {
    await support.intercept(MOCK_AGENT_ID, { saved: true, paginated: true });
    const workflows = new WorkflowsPage(page);
    await workflows.goto();
    await expect(workflows.card("Account briefs")).toBeVisible();
    await page.getByRole("button", { name: "Next", exact: true }).click();
    await expect(page).toHaveURL(/workflowPage=2/);
    await expect(workflows.card(NAME)).toBeVisible();
    await page.reload();
    await expect(page.getByText("Page 2", { exact: true })).toBeVisible();
    expect(support.readPages.list.at(-1)).toBe(2);
    await workflows.open(NAME);
    await expect(page.getByRole("heading", { name: NAME })).toBeVisible();
    await workflows.backToList();
    await expect(page.getByText("Page 2", { exact: true })).toBeVisible();
    await page.getByRole("button", { name: "Previous", exact: true }).click();
    await expect(workflows.card("Account briefs")).toBeVisible();
    await expect(page).not.toHaveURL(/workflowPage=/);
  });

  test("history pagination survives reload and invalid page parameters use page one", async ({
    page,
  }) => {
    await support.intercept(MOCK_AGENT_ID, { saved: true, paginated: true });
    const workflows = new WorkflowsPage(page);
    await workflows.goto(TEST_ORG_ID, WORKFLOW_ID);
    await workflows.history();
    await page.getByRole("button", { name: "Next versions" }).click();
    await expect(page).toHaveURL(/workflowVersionPage=2/);
    await expect(page.getByRole("button", { name: "View v1" })).toBeVisible();
    await page.reload();
    await expect(page.getByText("Page 2", { exact: true })).toBeVisible();
    expect(support.readPages.versions.at(-1)).toBe(2);
    await page.goto(
      `/dashboard/${TEST_ORG_ID}/workflows?workflowPage=-2&workflowVersionPage=9007199254740992&workflow=${WORKFLOW_ID}`,
    );
    await workflows.history();
    await expect(page.getByText("Page 1", { exact: true })).toBeVisible();
    expect(support.readPages.versions.at(-1)).toBe(1);
  });

  test("lost access replaces protected workflow detail", async ({ page }) => {
    await support.intercept(MOCK_AGENT_ID, { saved: true });
    const workflows = new WorkflowsPage(page);
    await workflows.goto(TEST_ORG_ID, WORKFLOW_ID);
    await expect(page.getByRole("heading", { name: NAME })).toBeVisible();
    support.denyAccess = true;
    await page.reload();
    await expect(page.getByText("We couldn’t load this workflow", { exact: true })).toBeVisible();
    await expect(page.getByRole("heading", { name: NAME })).toHaveCount(0);
  });

  test("in-app Organization switching drops drafts and cannot reuse cached definitions", async ({
    page,
  }) => {
    const otherId = "99999999-9999-4999-8999-999999999999";
    await support.enableOrganizationSwitch(otherId);
    await support.intercept(MOCK_AGENT_ID, { saved: true, organizationId: TEST_ORG_ID });
    await new WorkflowDataSupport(page).intercept(MOCK_AGENT_ID, {
      saved: false,
      organizationId: otherId,
    });
    const workflows = new WorkflowsPage(page);
    await workflows.goto();
    await expect(workflows.card(NAME)).toBeVisible();
    await workflows.switchOrganization("Globex");
    await expect(page).toHaveURL(new RegExp(`/dashboard/${otherId}`));
    // In-app, so the query cache stays: the other Organization must not see these.
    await workflows.railLink().click();
    await page.getByRole("tab", { name: "Workflows", exact: true }).click();
    await expect(page.getByRole("heading", { name: "No workflows yet" })).toBeVisible();
    await expect(workflows.card(NAME)).toHaveCount(0);
  });
});
