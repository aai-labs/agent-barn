import { type Page } from "@playwright/test";

import {
  workflowFixture,
  workflowSummary,
  workflowPaginationFixtures,
  workflowHistoryFixtures,
} from "../../fixtures/workflows";

import UserContext from "../../fixtures/user-context.json";
import { DataSupport } from "./data-support.po";

export class WorkflowDataSupport {
  saveRequests: Record<string, unknown>[] = [];
  savePaths: string[] = [];
  conflictSave = false;
  /** Description another user saved before the conflicting save. */
  conflictDescription: string | null = null;
  failCapabilities = false;
  forbidSave = false;
  saveAllowed = true;
  validationSaveErrors: { loc: (string | number)[]; msg: string }[] | null =
    null;
  denyAccess = false;
  /** GET counts per read family, to assert which views fetch. */
  reads = { list: 0, detail: 0, versions: 0 };
  readPages = { list: [] as number[], versions: [] as number[] };
  constructor(private page: Page) {}

  async enableOrganizationSwitch(otherId: string) {
    const original = UserContext.organization_users[0].organization;
    const other = { ...original, id: otherId, name: "Globex" };
    const data = new DataSupport(this.page);
    await data.users.interceptGetUserContextRequest({
      userContext: {
        ...UserContext,
        organization_users: [
          ...UserContext.organization_users,
          {
            ...UserContext.organization_users[0],
            id: "ffffffff-ffff-4fff-8fff-ffffffffffff",
            organization_id: otherId,
            organization: other,
          },
        ],
      },
    });
    await data.organizations.interceptListOrganizations({
      items: [original, other],
    });
    await data.organizations.interceptGetOrganization();
  }

  async intercept(
    agentId: string,
    {
      saved = false,
      viewer = false,
      authoring = true,
      organizationId = "*",
      stepId,
      paginated = false,
      description,
    }: {
      saved?: boolean;
      viewer?: boolean;
      authoring?: boolean;
      organizationId?: string;
      stepId?: string;
      paginated?: boolean;
      description?: string;
    } = {},
  ) {
    const data = new DataSupport(this.page);
    await data.agents.interceptGetAgentHealthRequest();
    await data.agents.interceptGetConversationChannelsRequest();
    await data.communicationConnections.interceptChannelsRequests({ agentId });
    let workflow = workflowFixture(agentId, viewer);
    if (stepId) workflow.version.draft.steps[0].id = stepId;
    if (description) workflow.version.draft.description = description;
    let present = saved;
    if (paginated) {
      workflow.revision = 3;
      workflow.version.number = 3;
    }
    const siblings = paginated ? workflowPaginationFixtures(agentId) : [];
    const versions = workflowHistoryFixtures(workflow);
    const pageSize = paginated ? 2 : 20;
    const base = `**/api/v1/organizations/${organizationId}/agents/${agentId}`;
    await this.page.route(`${base}/workflow-capabilities`, (route) =>
      this.failCapabilities
        ? route.abort()
        : route.fulfill({
        json: {
          authoring,
          execution: false,
          review_destinations: ["web"],
        },
      }),
    );
    await this.page.route(`${base}/workflows**`, async (route) => {
      const url = new URL(route.request().url());
      const path = url.pathname;
      const page = Number(url.searchParams.get("page") ?? 1);
      const offset = (page - 1) * pageSize;
      if (this.denyAccess) {
        await route.fulfill({
          status: 404,
          json: { detail: "Workflow not found" },
        });
        return;
      }
      if (route.request().method() === "POST") {
        if (path.endsWith("/archive")) {
          workflow.archived_at = "2026-10-14T11:00:00Z";
          workflow.allowed_actions = [];
          await route.fulfill({ status: 204 });
          return;
        }
        const body = route.request().postDataJSON();
        this.saveRequests.push(body);
        this.savePaths.push(path);
        if (this.validationSaveErrors) {
          const detail = this.validationSaveErrors;
          this.validationSaveErrors = null;
          await route.fulfill({ status: 422, json: { detail } });
          return;
        }
        if (this.forbidSave) {
          await route.fulfill({
            status: 403,
            json: { detail: "Permission denied" },
          });
          return;
        }
        if (this.conflictSave) {
          this.conflictSave = false;
          workflow.revision++;
          if (this.conflictDescription)
            workflow.version.draft.description = this.conflictDescription;
          await route.fulfill({
            status: 409,
            json: {
              detail:
                "Workflow changed; reload its current revision before saving. Your draft can be kept.",
            },
          });
          return;
        }
        workflow = {
          ...workflow,
          revision: present ? workflow.revision + 1 : 1,
          version: {
            ...workflow.version,
            id: crypto.randomUUID(),
            number: present ? workflow.version.number + 1 : 1,
            draft: body.draft ?? body,
          },
        };
        versions.unshift(structuredClone(workflow.version));
        present = true;
        await route.fulfill({ status: 201, json: workflow });
        return;
      }
      if (path.endsWith("/versions")) {
        this.reads.versions++;
        this.readPages.versions.push(page);
        await route.fulfill({
          json: {
            items: versions.slice(offset, offset + pageSize),
            total: versions.length,
            page,
            page_size: pageSize,
          },
        });
        return;
      }
      if (path.endsWith("/workflows")) {
        this.reads.list++;
        this.readPages.list.push(page);
        const items = present
          ? [...siblings, workflow].map(workflowSummary)
          : [];
        await route.fulfill({
          json: {
            items: items.slice(offset, offset + pageSize),
            total: items.length,
            page,
            page_size: pageSize,
          },
        });
        return;
      }
      this.reads.detail++;
      await route.fulfill({
        json: {
          ...workflow,
          allowed_actions: this.saveAllowed ? workflow.allowed_actions : [],
        },
      });
    });
  }
}
